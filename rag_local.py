"""로컬 RAG: 볼트 .md 노트를 bge-m3(Ollama)로 임베딩해 LanceDB 에 저장하고 검색한다.

Open WebUI(Docker) 없이 파이프라인 안에서 직접 RAG 를 처리하기 위한 모듈.
- 임베딩: bge-m3(다국어, 1024차원). 영어 전용 all-MiniLM 대비 한국어 검색이 크게 향상.
- 저장: 파일 기반 LanceDB(rag_db/). 별도 서비스·Docker 불필요, 도커 업그레이드로 KB 가
  날아가는 사고에서 자유롭다.
- 생성(답변): 기존과 동일하게 Ollama 로컬 모델(exaone3.5 등).
- 증분: 노트 내용의 SHA-256 을 저장해 두고, 바뀌지 않은 노트는 재임베딩을 건너뛴다.

CLI:
  uv run python rag_local.py            # 볼트 증분 색인
  uv run python rag_local.py --reset    # 전체 재색인(기존 인덱스 비우고 다시)
  uv run python rag_local.py --query "성수동 증축 허가"   # 검색 상위 결과 출력
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import time
from pathlib import Path

import lancedb
import ollama
import pyarrow as pa
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("archive_pipeline")

# 임베딩·답변 백엔드: ollama(로컬, GPU 있는 머신) 또는 gemini(클라우드, Ollama 없는 머신).
# 분류기(classify.py)와 같은 방식으로 .env 에서 머신별로 고른다.
EMBED_PROVIDER = os.getenv("RAG_EMBED_PROVIDER", "ollama").lower()
GEN_PROVIDER = os.getenv("RAG_GEN_PROVIDER", "ollama").lower()

if EMBED_PROVIDER == "gemini":
    EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "gemini-embedding-001")
    EMBED_DIM = int(os.getenv("RAG_EMBED_DIM", "3072"))  # gemini-embedding-001/2 출력 차원
else:
    EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")
    EMBED_DIM = int(os.getenv("RAG_EMBED_DIM", "1024"))  # bge-m3 출력 차원

GEN_MODEL = (
    os.getenv("RAG_GEN_MODEL", "gemini-3.1-flash-lite")
    if GEN_PROVIDER == "gemini"
    else os.getenv("TELEGRAM_RAG_MODEL", "exaone3.5:7.8b")
)
GEN_THINKING_LEVEL = os.getenv("RAG_GEN_THINKING", "minimal")
GEN_RETRIES = 3  # 일시적 503(모델 혼잡)에 대비. 대화형이라 실패가 곧 무응답이다.
DB_PATH = Path(os.getenv("RAG_DB_PATH", "rag_db"))
TABLE_NAME = "vault"

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or r"C:\Users\OWNER\iCloudDrive\iCloud~md~obsidian\KC_second_brain"
)
# 노트가 들어 있는 구조화 폴더만 색인(템플릿·첨부 제외). ingest_vault.py 와 동일.
INCLUDE_DIRS = ("10_Professional", "20_Personal", "90_System")

CHUNK_CHARS = 700  # 청크 목표 길이(문단 경계로 자르되, 긴 문단은 하드 분할)

# 시스템 OLLAMA_HOST 가 0.0.0.0(접속 불가)인 경우를 대비해 접속 주소를 명시한다.
_host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
if _host.startswith(("0.0.0.0", "http://0.0.0.0", "https://0.0.0.0")):
    _host = _host.replace("0.0.0.0", "127.0.0.1")
_client = ollama.Client(host=_host)


_gemini = None


def _gemini_client():
    """google-genai 클라이언트를 최초 1회만 생성해 캐시한다(모듈 import 시엔 안 만든다)."""
    global _gemini
    if _gemini is None:
        from google import genai  # ollama 전용 머신엔 없을 수 있어 지연 import

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY 가 비어 있습니다(.env 에 발급 키를 넣으세요).")
        _gemini = genai.Client(api_key=api_key)
    return _gemini


# API 제한: 한 요청에 최대 100건. 볼트 전체 색인은 수천 청크라 반드시 나눠 보내야 한다.
GEMINI_EMBED_BATCH = 100


def _embed_gemini(texts: list[str]) -> list[list[float]]:
    """Gemini 임베딩. 100건씩 나눠 보내고, 개수가 어긋나면 그 묶음만 1건씩 재시도한다."""
    from google.genai import types

    config = types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
    client = _gemini_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), GEMINI_EMBED_BATCH):
        batch = texts[start : start + GEMINI_EMBED_BATCH]
        response = client.models.embed_content(
            model=EMBED_MODEL, contents=batch, config=config
        )
        got = [e.values for e in response.embeddings]
        if len(got) != len(batch):
            # gemini-embedding-2 는 입력 여러 개를 줘도 오류 없이 벡터 1개만 돌려준다.
            # 그대로 쓰면 청크와 벡터가 어긋나 검색이 조용히 망가지므로 1건씩 다시 부른다.
            got = [
                client.models.embed_content(model=EMBED_MODEL, contents=t, config=config)
                .embeddings[0]
                .values
                for t in batch
            ]
        vectors.extend(got)
    return vectors


def embed(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 임베딩한다. RAG_EMBED_PROVIDER 로 백엔드를 고른다."""
    if not texts:
        return []
    if EMBED_PROVIDER == "gemini":
        vectors = _embed_gemini(texts)
    else:
        vectors = _client.embed(model=EMBED_MODEL, input=texts)["embeddings"]

    # 개수·차원이 어긋나면 인덱스가 조용히 망가진다. 여기서 크게 실패시킨다.
    if len(vectors) != len(texts):
        raise ValueError(f"임베딩 개수 불일치: 입력 {len(texts)}개, 결과 {len(vectors)}개")
    if vectors and len(vectors[0]) != EMBED_DIM:
        raise ValueError(
            f"임베딩 차원 불일치: 스키마 {EMBED_DIM}, 모델 {EMBED_MODEL} 출력 {len(vectors[0])}. "
            "모델을 바꿨다면 RAG_EMBED_DIM 을 맞추고 인덱스를 재생성하세요(--reset)."
        )
    return vectors


def _generate(prompt: str, model: str) -> str:
    """RAG 답변 생성. RAG_GEN_PROVIDER 로 백엔드를 고른다.

    낮은 temperature: 사실 질의라 창의성보다 일관·정확한 값 추출이 중요하다."""
    if GEN_PROVIDER == "gemini":
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0.3,
            # 근거가 이미 검색돼 프롬프트에 들어 있어 추론을 길게 돌릴 이유가 없다. 안 막으면
            # 모델에 따라 답 하나에 30~120초가 걸려 대화형 봇으로 못 쓴다(실측).
            thinking_config=types.ThinkingConfig(thinking_level=GEN_THINKING_LEVEL),
        )
        last: Exception | None = None
        for attempt in range(GEN_RETRIES):
            try:
                response = _gemini_client().models.generate_content(
                    model=model, contents=prompt, config=config
                )
                return (response.text or "").strip()
            except Exception as error:  # noqa: BLE001 — 재시도 후 호출부로 전달
                last = error
                # 봇은 대화형이라 한 번의 일시적 503 이 곧 '답이 안 옴'이다(수집 경로와 달리
                # 나중에 자동 재시도되지 않는다). 짧게 물러났다 다시 시도한다.
                if attempt < GEN_RETRIES - 1:
                    time.sleep(2 * (attempt + 1))
        raise last

    resp = _client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"num_ctx": GEN_NUM_CTX, "temperature": 0.3},
    )
    return (resp.get("message") or {}).get("content", "").strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sql_quote(s: str) -> str:
    """LanceDB where 절용 문자열 리터럴(작은따옴표 이스케이프)."""
    return "'" + s.replace("'", "''") + "'"


_FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
# 헤더로 노출할 frontmatter 필드(질의에 자주 쓰이는 권위 있는 값). 스캔 원문이 OCR 로
# 지저분해도 이 깨끗한 메타데이터를 모든 청크에 붙이면 날짜·분류 질문에 정확히 답한다.
_META_FIELDS = (("doc_date", "날짜"), ("category", "분류"), ("project", "프로젝트"),
                ("counterparty", "상대"), ("status", "상태"))


def _frontmatter(text: str) -> dict[str, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^(\w+):\s*(.+)$", line)
        if mm:
            fields[mm.group(1)] = mm.group(2).strip().strip("\"'")
    return fields


def _split_note(text: str, fallback_title: str) -> tuple[str, str]:
    """노트를 (헤더, 본문)으로 나눈다. 헤더 = 제목 + 핵심 메타데이터."""
    fm = _frontmatter(text)
    body = _FM_RE.sub("", text, count=1).strip() or text
    header = f"# {fm.get('title') or fallback_title}"
    meta = [f"{label} {fm[key]}" for key, label in _META_FIELDS if fm.get(key)]
    if meta:
        header += "\n(" + " · ".join(meta) + ")"
    return header, body


# 노트 본문의 '## 요약' 섹션(분류 시 LLM 이 쓴 깨끗한 핵심 요약)을 뽑는다. 스캔 OCR 원문은
# 글자가 깨져 작은 모델이 값을 못 읽을 때가 있는데, 이 깨끗한 요약을 답변 문맥에 함께 넣으면
# 날짜·면적·금액 같은 값을 안정적으로 찾아낸다.
_SUMMARY_RE = re.compile(r"##\s*요약\s*\n+(.+?)(?:\n##\s|\Z)", re.DOTALL)


def _extract_summary(text: str) -> str:
    m = _SUMMARY_RE.search(text)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:400] if m else ""


def chunk_text(body: str, header: str) -> list[str]:
    """본문을 문단 경계로 CHUNK_CHARS 근처에서 자르고, 각 청크에 헤더(제목+메타)를 붙인다.

    헤더를 붙이면 '원문' 문단만으로는 어떤 문서인지·언제 문서인지 알 수 없는 청크도
    검색에 잘 걸리고, 날짜·분류 질문에 깨끗한 메타데이터로 답할 수 있다.
    """
    # 문단 경계로 나누되, CHUNK_CHARS 보다 긴 문단은 하드 분할한다. 스캔 OCR 원문은 빈 줄이
    # 없어 문단 하나가 수천 자로 거대해지곤 하는데, 그대로 두면 청크가 너무 커져 검색 임베딩이
    # 흐려지고 생성 시 컨텍스트를 넘겨 잘린다.
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= CHUNK_CHARS:
            pieces.append(para)
        else:
            for i in range(0, len(para), CHUNK_CHARS):
                pieces.append(para[i : i + CHUNK_CHARS])
    chunks: list[str] = []
    buf = ""
    for p in pieces:
        if buf and len(buf) + len(p) + 2 > CHUNK_CHARS:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    if not chunks:
        chunks = [""]
    return [f"{header}\n\n{c}".strip() for c in chunks]


def _schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("note_name", pa.string()),
            pa.field("note_path", pa.string()),
            pa.field("note_sha", pa.string()),
            pa.field("chunk_idx", pa.int32()),
            pa.field("text", pa.string()),
            pa.field("summary", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
        ]
    )


def connect():
    """LanceDB 테이블을 열거나(없으면) 생성해 돌려준다."""
    DB_PATH.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(DB_PATH))
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=_schema())


def list_notes() -> list[Path]:
    return sorted(
        p for d in INCLUDE_DIRS for p in (VAULT / d).rglob("*.md") if p.is_file()
    )


def ingest(reset: bool = False, verbose: bool = True) -> dict:
    """볼트 노트를 증분 색인한다. reset=True 면 인덱스를 비우고 전체 재색인."""
    tbl = connect()
    if reset:
        tbl.delete("true")  # 전체 삭제

    existing: dict[str, str] = {}
    if not reset and tbl.count_rows() > 0:
        arrow = tbl.to_arrow().select(["note_name", "note_sha"])
        existing = dict(zip(arrow.column("note_name").to_pylist(),
                            arrow.column("note_sha").to_pylist()))

    notes = list_notes()
    added = skipped = updated = 0
    for i, note in enumerate(notes, 1):
        text = note.read_text(encoding="utf-8")
        sha = _sha256(text)
        if existing.get(note.name) == sha:
            skipped += 1
            continue
        if note.name in existing:
            tbl.delete(f"note_name = {_sql_quote(note.name)}")  # 바뀐 노트: 옛 청크 제거
            updated += 1
        else:
            added += 1
        header, body = _split_note(text, note.stem)
        summary = _extract_summary(text)
        chunks = chunk_text(body, header)
        vectors = embed(chunks)
        tbl.add(
            [
                {
                    "id": f"{note.name}::{j}",
                    "note_name": note.name,
                    "note_path": str(note),
                    "note_sha": sha,
                    "chunk_idx": j,
                    "text": chunks[j],
                    "summary": summary,
                    "vector": vectors[j],
                }
                for j in range(len(chunks))
            ]
        )
        if verbose:
            print(f"[{i}/{len(notes)}] {'갱신' if note.name in existing else '추가'} {note.name} ({len(chunks)}청크)")

    # 전문(FTS) 인덱스를 (재)생성한다. 하이브리드 검색(키워드+벡터)이 지번·'연면적' 같은
    # 정확한 용어를 잘 잡는다. FTS 는 정적이라 add 후 재생성이 필요한데, 여기(전체/주기 색인)
    # 에서 다시 만들어 index_note 로 들어온 새 노트도 다음 주기에 FTS 검색에 포함된다.
    try:
        tbl.create_fts_index("text", replace=True)
    except Exception:
        logger.warning("FTS 인덱스 생성 실패(벡터 검색으로 폴백)")

    stats = {"added": added, "updated": updated, "skipped": skipped, "total": len(notes), "rows": tbl.count_rows()}
    if verbose:
        print(f"\n색인 완료: 추가 {added}, 갱신 {updated}, 건너뜀 {skipped}, 노트 {len(notes)}, 청크행 {stats['rows']}")
    return stats


def index_note(path) -> bool:
    """노트 한 개를 색인한다(추가/갱신). 파이프라인이 새 노트를 쓴 직후 호출용.

    임베딩을 먼저 끝낸 뒤에야 테이블을 건드리므로, Ollama 정지(pause_ai) 등으로 임베딩이
    실패하면 기존 인덱스를 그대로 보존하고 False 를 돌려준다(파일 처리는 막지 않는다).
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("색인용 노트 읽기 실패: %s", path)
        return False
    header, body = _split_note(text, path.stem)
    summary = _extract_summary(text)
    chunks = chunk_text(body, header)
    try:
        vectors = embed(chunks)
    except Exception:
        logger.warning("임베딩 실패로 색인 건너뜀(다음 전체 재색인에서 반영): %s", path.name)
        return False
    sha = _sha256(text)
    tbl = connect()
    tbl.delete(f"note_name = {_sql_quote(path.name)}")  # 갱신이면 옛 청크 제거(없으면 무해)
    tbl.add(
        [
            {
                "id": f"{path.name}::{j}",
                "note_name": path.name,
                "note_path": str(path),
                "note_sha": sha,
                "chunk_idx": j,
                "text": chunks[j],
                "summary": summary,
                "vector": vectors[j],
            }
            for j in range(len(chunks))
        ]
    )
    return True


def search(query: str, k: int = 5) -> list[dict]:
    """질의로 상위 k 청크를 돌려준다. 하이브리드(키워드+벡터), FTS 없으면 벡터로 폴백.

    하이브리드는 지번(685-317)·'연면적' 같은 정확한 용어를 키워드로 잡아, 임베딩만으로는
    흐려지는 고유명사·같은 프로젝트 내 유사 문서 구분에 강하다.
    """
    tbl = connect()
    qv = embed([query])[0]
    try:
        from lancedb.rerankers import RRFReranker

        return (
            tbl.search(query_type="hybrid")
            .vector(qv)
            .text(query)
            .rerank(RRFReranker())
            .limit(k)
            .to_list()
        )
    except Exception:
        # FTS 인덱스가 아직 없거나(최초 색인 전) 하이브리드 실패 시 벡터 검색으로 폴백.
        return tbl.search(qv).limit(k).to_list()


# 검색 후보 청크 수. 제목이 겹치는 노트(같은 지번의 여러 문서)가 상위를 차지해 정작 답이
# 든 청크가 밀려나는 일을 막기 위해 넉넉히 가져온 뒤, 아래 문맥 예산 안에서만 실제로 넣는다.
DEFAULT_K = 12
# exaone3.5:7.8b 의 기본 컨텍스트(4096). 이보다 크게(예: 8192) 요청하면 이 Ollama 빌드에서
# 생성이 깨져 답이 한 글자로 잘리는 버그가 있어 기본값에 맞춘다.
GEN_NUM_CTX = 4096
# 모델에 넣을 문맥의 최대 글자 수. num_ctx(4096 토큰) 안에 답 생성 여유까지 남기도록
# 넉넉히 잡되(한국어 ~1.5자/토큰), 상위 청크만 골라 넣어 컨텍스트 초과 truncation 을 막는다.
CONTEXT_CHAR_BUDGET = 3500
# 한 노트가 상위 청크를 독식해 다른 노트(정작 답이 든)가 밀려나는 것을 막는 노트당 청크 상한.
MAX_CHUNKS_PER_NOTE = 2


def answer(question: str, k: int = DEFAULT_K, model: str | None = None) -> tuple[str, list[str]]:
    """검색 문맥으로 로컬 LLM 답변을 만들고 (답, 참고노트명) 을 돌려준다."""
    hits = search(question, k=k)
    if not hits:
        return "관련 노트를 찾지 못했습니다. 질문을 바꿔 다시 시도해 주세요.", []
    # 관련도 순으로 담되, (1) 노트당 청크 상한으로 다양성을 확보하고 (2) 문맥 예산을 지킨다.
    picked: list[dict] = []
    total = 0
    per_note: dict[str, int] = {}
    for h in hits:
        if per_note.get(h["note_name"], 0) >= MAX_CHUNKS_PER_NOTE:
            continue
        block = f"[{h['note_name']}]\n{h['text']}"
        if picked and total + len(block) > CONTEXT_CHAR_BUDGET:
            continue
        picked.append(h)
        total += len(block)
        per_note[h["note_name"]] = per_note.get(h["note_name"], 0) + 1
    # 노트별로 묶어, 각 노트의 깨끗한 요약을 먼저 주고 그 다음 검색된 청크(원문 조각)를 준다.
    # 요약엔 날짜·면적·금액 등 값이 정제돼 있어, 원문이 OCR 로 깨져도 모델이 값을 찾는다.
    groups: dict[str, dict] = {}
    for h in picked:
        g = groups.setdefault(h["note_name"], {"summary": h.get("summary") or "", "chunks": []})
        g["chunks"].append(h["text"])
    blocks = []
    for name, g in groups.items():
        summary_line = f"요약: {g['summary']}\n" if g["summary"] else ""
        blocks.append(f"[{name}]\n{summary_line}" + "\n".join(g["chunks"]))
    context = "\n\n---\n\n".join(blocks)
    prompt = (
        "아래는 내 노트(볼트)에서 질문과 관련해 검색한 내용이다(스캔 OCR로 글자가 일부 "
        "깨졌을 수 있다). 이 내용을 근거로 한국어로 구체적으로 답하라. 숫자·날짜·금액·면적 "
        "등 값이 노트에 있으면 반드시 찾아 제시하라. 정말 관련 근거가 없을 때만 모른다고 답하라.\n\n"
        f"# 검색된 노트\n{context}\n\n# 질문\n{question}\n"
    )
    ans = _generate(prompt, model or GEN_MODEL)
    names: list[str] = []
    for h in picked:  # 실제로 문맥에 넣은 노트만 출처로 표기(정직한 인용)
        if h["note_name"] not in names:
            names.append(h["note_name"])
    return ans, names


def main() -> None:
    ap = argparse.ArgumentParser(description="로컬 RAG 색인/검색")
    ap.add_argument("--reset", action="store_true", help="인덱스를 비우고 전체 재색인")
    ap.add_argument("--query", help="검색만 수행(색인 안 함)")
    ap.add_argument("-k", type=int, default=5, help="검색 결과 개수")
    args = ap.parse_args()

    if args.query:
        for h in search(args.query, k=args.k):
            score = h.get("_relevance_score", h.get("_distance", 0.0))
            print(f"· {h['note_name']}  ({score:.3f})")
        return
    ingest(reset=args.reset)


if __name__ == "__main__":
    main()
