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
import os
import re
from pathlib import Path

import lancedb
import ollama
import pyarrow as pa
from dotenv import load_dotenv

load_dotenv()

EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")
EMBED_DIM = 1024  # bge-m3 출력 차원
GEN_MODEL = os.getenv("TELEGRAM_RAG_MODEL", "exaone3.5:7.8b")
DB_PATH = Path(os.getenv("RAG_DB_PATH", "rag_db"))
TABLE_NAME = "vault"

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or r"C:\Users\OWNER\iCloudDrive\iCloud~md~obsidian\KC_second_brain"
)
# 노트가 들어 있는 구조화 폴더만 색인(템플릿·첨부 제외). ingest_vault.py 와 동일.
INCLUDE_DIRS = ("10_Professional", "20_Personal", "90_System")

CHUNK_CHARS = 1000  # 청크 목표 길이(문단 경계로 자름)

# 시스템 OLLAMA_HOST 가 0.0.0.0(접속 불가)인 경우를 대비해 접속 주소를 명시한다.
_host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
if _host.startswith(("0.0.0.0", "http://0.0.0.0", "https://0.0.0.0")):
    _host = _host.replace("0.0.0.0", "127.0.0.1")
_client = ollama.Client(host=_host)


def embed(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 bge-m3 로 임베딩한다(한 번의 배치 호출)."""
    if not texts:
        return []
    return _client.embed(model=EMBED_MODEL, input=texts)["embeddings"]


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


def chunk_text(body: str, header: str) -> list[str]:
    """본문을 문단 경계로 CHUNK_CHARS 근처에서 자르고, 각 청크에 헤더(제목+메타)를 붙인다.

    헤더를 붙이면 '원문' 문단만으로는 어떤 문서인지·언제 문서인지 알 수 없는 청크도
    검색에 잘 걸리고, 날짜·분류 질문에 깨끗한 메타데이터로 답할 수 있다.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
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
                    "vector": vectors[j],
                }
                for j in range(len(chunks))
            ]
        )
        if verbose:
            print(f"[{i}/{len(notes)}] {'갱신' if note.name in existing else '추가'} {note.name} ({len(chunks)}청크)")

    stats = {"added": added, "updated": updated, "skipped": skipped, "total": len(notes), "rows": tbl.count_rows()}
    if verbose:
        print(f"\n색인 완료: 추가 {added}, 갱신 {updated}, 건너뜀 {skipped}, 노트 {len(notes)}, 청크행 {stats['rows']}")
    return stats


def search(query: str, k: int = 5) -> list[dict]:
    """질의를 임베딩해 상위 k 청크를 돌려준다(note_name, text, _distance 포함)."""
    tbl = connect()
    qv = embed([query])[0]
    return tbl.search(qv).limit(k).to_list()


# 검색 청크 수. 제목이 겹치는 노트(같은 지번의 여러 문서)가 상위를 차지해 정작 답이 든
# 노트가 밀려나는 일을 막기 위해 넉넉히 가져온다. 그만큼 문맥이 길어지므로 num_ctx 로
# 컨텍스트 창을 넓혀 잘리지 않게 한다.
DEFAULT_K = 8
GEN_NUM_CTX = 8192


def answer(question: str, k: int = DEFAULT_K, model: str | None = None) -> tuple[str, list[str]]:
    """검색 문맥으로 로컬 LLM 답변을 만들고 (답, 참고노트명) 을 돌려준다."""
    hits = search(question, k=k)
    if not hits:
        return "관련 노트를 찾지 못했습니다. 질문을 바꿔 다시 시도해 주세요.", []
    context = "\n\n---\n\n".join(f"[{h['note_name']}]\n{h['text']}" for h in hits)
    prompt = (
        "아래는 내 개인 노트(볼트)에서 질문과 관련해 검색한 내용이다. "
        "이 내용만 근거로 한국어로 정확히 답하라. 근거가 부족하면 모른다고 답하라.\n\n"
        f"# 검색된 노트\n{context}\n\n# 질문\n{question}\n"
    )
    resp = _client.chat(
        model=model or GEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"num_ctx": GEN_NUM_CTX},
    )
    ans = (resp.get("message") or {}).get("content", "").strip()
    names: list[str] = []
    for h in hits:
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
            print(f"· {h['note_name']}  (거리 {h['_distance']:.3f})")
        return
    ingest(reset=args.reset)


if __name__ == "__main__":
    main()
