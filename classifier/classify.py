"""Ollama 로컬 LLM으로 문서를 분류하고 요약하는 모듈."""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date

import ollama

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# 이 프로젝트가 무엇인지(이름 + 식별자)를 분류기에 알려줘, 문서가 '프로젝트 실데이터'인지
# '참고자료'(템플릿·샘플·정부지침·다른 현장 예시)인지 판단하게 한다.
PROJECT_NAME = os.getenv("DEFAULT_WORK_PROJECT", "성수동 리모델링")
PROJECT_IDENTIFIERS = [
    s.strip()
    for s in os.getenv("PROJECT_IDENTIFIERS", "685-317,685-383,성수동1가").split(",")
    if s.strip()
]

KIND_PROJECT = "프로젝트자료"
KIND_REFERENCE = "참고자료"

# 문서유형(category) 통제 어휘 — 일관된 제목/분류를 위해 가급적 이 중에서 고른다.
DOC_TYPES = (
    "계약서, 도급계약서, 용역계약서, 견적서, 내역서, 공정표, 세금계산서, 청구서, "
    "위임장, 회의록, 계획서, 보고서, 공문, 안내문, 체크리스트, 명세서, 영수증"
)

# 이 PC의 시스템 OLLAMA_HOST 가 0.0.0.0 (접속 불가 주소)로 설정돼 있어
# 파이프라인 전용 접속 주소를 명시한다. 시스템 환경변수는 건드리지 않는다.
_host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
if _host.startswith(("0.0.0.0", "http://0.0.0.0", "https://0.0.0.0")):
    _host = _host.replace("0.0.0.0", "127.0.0.1")
_client = ollama.Client(host=_host)

# 추출 텍스트가 너무 길면 모델이 지시를 무시하고 엉뚱한 JSON 을 내므로 앞부분만 쓴다.
# (긴 스캔 문서에서 지시문이 묻혀 스키마를 무시하는 현상을 줄이기 위해 짧게 자른다.)
MAX_INPUT_CHARS = 4000

# 모델이 JSON 을 끝없이 토해내 파싱이 실패하는 경우를 막기 위해 출력 토큰을 제한한다.
MAX_OUTPUT_TOKENS = 1024

# temperature=0 으로 재시도하면 동일 결과가 나오므로, 실패 시 점점 다양화한다.
# (긴 문서에서 모델이 domain 키를 누락하거나 잘못된 JSON 을 내는 경우 대비)
RETRY_TEMPERATURES = (0.0, 0.4, 0.8)

SYSTEM_PROMPT = f"""\
당신은 문서를 분류·정리하는 한국어 비서입니다. 아래 JSON 형식으로만 응답하세요. 다른 설명 금지.

{{
  "domain": "개인 또는 업무 중 하나",
  "kind": "프로젝트자료 또는 참고자료 중 하나",
  "category": "문서유형 하나",
  "counterparty": "상대방(회사/기관) 이름 또는 빈 문자열",
  "doc_date": "문서 자체의 날짜 YYYY-MM-DD (모르면 YYYY-MM, 없으면 빈 문자열)",
  "status": "초안/최종 등 상태 또는 빈 문자열",
  "detail": "제목 괄호에 넣을 짧은 부가설명(범위/대상) 또는 빈 문자열",
  "tags": ["핵심 키워드 3~6개"],
  "summary": "문서 핵심 내용을 3~5문장으로 요약"
}}

가장 중요한 규칙 — **원본 파일명이 최우선·최고 권위의 근거입니다.** 사용자는 파일명에 날짜·문서유형·
상대방·범위를 이미 담아둡니다(예: "260204 협력사 용역계약서_설비전기통신소방_영진D&EC_초안" →
유형=용역계약서, 상대방=영진D&EC, 날짜=2026-02-04, 상태=초안). **파일명에서 읽을 수 있는 값은
본문 OCR 로 절대 뒤집지 마세요.** 본문은 파일명에 없는 정보를 보완할 때만 쓰세요. 본문 OCR 은
스캔 오류로 깨진 글자가 많으니 신뢰하지 마세요.

- domain: 반드시 "개인" 또는 "업무".
- category: 가급적 다음 중 하나(통제 어휘): {DOC_TYPES}. **파일명·기존 제목의 문서유형을 그대로
  따르세요**(파일명/제목에 '계약서/견적서/세금계산서/위임장/내역서/보고서/계획서' 등이 있으면 그것).
  **'공정표'는 공정·일정을 날짜축으로 나열한 일정표(간트/예정표)일 때만** 쓰세요. 계약서·내역서·견적서·
  보고서·결과서·계획서·입찰안내서·세금계산서를 표나 숫자가 있다는 이유로 '공정표'로 바꾸지 마세요.
- counterparty: '상대 회사/기관' 이름. **반드시 파일명에서 우선 추출**(예: "_누리구조" → 누리구조,
  "한성건축견적서" → 한성건축). 파일명에 회사명이 없고 본문 OCR 이 깨져 이름이 불명확하거나 이상한
  글자 조합이면 **빈 문자열**로 두세요(추측·창작 절대 금지). 내부 문서(회의록 등)도 빈 문자열.
- doc_date: 문서·파일명에 **실제로 적힌** 날짜(작성·발행·계약일)만 ISO 로. 파일명의 6자리(YYMMDD)
  활용. **명확한 날짜가 없으면 빈 문자열.** 월·일을 추측해 지어내지 마라(예: 1월 1일로 채우지 말 것).
- status: "초안"/"최종"/"수정" 등 명시돼 있을 때만. 없으면 빈 문자열.
- detail: 범위나 대상을 한두 단어로(예: "근생 리모델링", "설비전기통신소방", "685-317 해체"). 없으면 빈 문자열.
- kind: '{PROJECT_NAME}'({", ".join(PROJECT_IDENTIFIERS)}) 프로젝트의 실제 자료면 "프로젝트자료";
  빈 양식·표준서식·샘플·정부지침/매뉴얼/사례집·다른 현장 문서면 "참고자료". 애매하면 "프로젝트자료".
- tags: 검색용 키워드 3~6개(공백 없는 짧은 단어).
- 반드시 유효한 JSON 한 개만 출력."""


@dataclass
class Classification:
    domain: str
    category: str
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    kind: str = KIND_PROJECT
    counterparty: str = ""
    doc_date: str = ""
    status: str = ""


def compose_title(category: str, counterparty: str, doc_date: str,
                  detail: str = "", status: str = "") -> str:
    """명명규칙 'YYYY-MM-DD <유형> - <상대방> (<부가, 상태>)' 로 제목을 일관되게 조립한다."""
    base = category or "문서"
    if counterparty:
        base += f" - {counterparty}"
    paren = ", ".join(x for x in (detail, status) if x)
    if paren:
        base += f" ({paren})"
    return f"{doc_date} {base}" if doc_date else base


def _build_messages(text: str, source_name: str = "") -> list[dict]:
    content = text[:MAX_INPUT_CHARS]
    name_line = f"원본 파일명: {source_name}\n\n" if source_name else ""
    # 파일명 + 문서를 구분자로 감싸고, 스키마를 본문 "뒤"에 다시 명시한다(최신 지시 우선).
    user = (
        "다음 문서를 분류·정리하세요. 원본 파일명을 최우선 근거로 쓰세요.\n\n"
        f"{name_line}=== 문서 시작 ===\n{content}\n=== 문서 끝 ===\n\n"
        "반드시 아래 키를 가진 JSON 하나만 출력: "
        '{"domain":"개인|업무","kind":"프로젝트자료|참고자료","category":"문서유형",'
        '"counterparty":"상대방 또는 \\"\\"","doc_date":"YYYY-MM-DD 또는 \\"\\"",'
        '"status":"초안/최종 또는 \\"\\"","detail":"부가설명 또는 \\"\\"",'
        '"tags":[...],"summary":"..."}. '
        f"category 는 가급적 [{DOC_TYPES}] 중에서. doc_date 는 파일명/본문의 날짜를 ISO 로."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _call_ollama(messages: list[dict], model: str, temperature: float = 0.0) -> str:
    response = _client.chat(
        model=model,
        messages=messages,
        format="json",
        options={"temperature": temperature, "num_predict": MAX_OUTPUT_TOKENS},
    )
    return response["message"]["content"]


def _normalize_tags(raw_tags) -> list[str]:
    """tags 를 공백 없는 문자열 리스트로 정규화한다(배열·쉼표문자열 모두 허용)."""
    if isinstance(raw_tags, str):
        raw_tags = re.split(r"[,\n]", raw_tags)
    if not isinstance(raw_tags, list):
        return []
    tags = []
    for tag in raw_tags:
        text = re.sub(r"\s+", "-", str(tag).strip()).strip("-#")
        if text and text not in tags:
            tags.append(text)
    return tags


def _valid_doc_date(value: str) -> str:
    """YYYY-MM 또는 실재하는 YYYY-MM-DD 만 통과시킨다. 그 외(형식오류·없는 날짜)는 빈 문자열."""
    if re.fullmatch(r"\d{4}-\d{2}", value):
        y, m = (int(x) for x in value.split("-"))
        return value if 1 <= m <= 12 else ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            date.fromisoformat(value)  # 2026-02-32 같은 값에서 ValueError
            return value
        except ValueError:
            return ""
    return ""


def _parse_response(raw: str) -> Classification:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("응답이 JSON 객체가 아닙니다.")

    # domain 은 폴더(개인/업무)를 결정하는 필수 값이라 엄격히 검증한다.
    domain = str(data.get("domain", "")).strip()
    if domain not in ("개인", "업무"):
        raise ValueError(f"domain 값이 올바르지 않습니다: {domain!r}")

    # kind 는 참고자료로 '확실히' 판정될 때만 격리한다. 그 외(누락·오타·애매)는
    # 안전하게 프로젝트자료로 둬, 실데이터가 봇에서 누락되지 않게 한다.
    kind = KIND_REFERENCE if str(data.get("kind", "")).strip() == KIND_REFERENCE else KIND_PROJECT

    category = str(data.get("category") or "미분류").strip() or "미분류"
    counterparty = str(data.get("counterparty") or "").strip()
    status = str(data.get("status") or "").strip()
    detail = str(data.get("detail") or "").strip()
    # doc_date 는 형식뿐 아니라 '실제로 존재하는 날짜'인지까지 검증한다(2026-02-32 같은 값 차단).
    doc_date = _valid_doc_date(str(data.get("doc_date") or "").strip())

    return Classification(
        domain=domain,
        category=category,
        title=compose_title(category, counterparty, doc_date, detail, status),
        summary=str(data.get("summary") or "").strip(),
        tags=_normalize_tags(data.get("tags")),
        kind=kind,
        counterparty=counterparty,
        doc_date=doc_date,
        status=status,
    )


def classify(text: str, source_name: str = "", model: str = DEFAULT_MODEL) -> Classification:
    """문서 텍스트를 분류·정리해 Classification으로 반환한다.

    source_name(원본 파일명)을 함께 주면 제목/유형/상대방/날짜 추출의 최우선 근거로 쓴다.
    긴 스캔 문서에서 모델이 깨진 JSON 을 내는 일이 잦아 temperature 를 올려가며 재시도한다.
    """
    if not text.strip():
        raise ValueError("빈 문서는 분류할 수 없습니다.")

    messages = _build_messages(text, source_name)
    last_error: Exception | None = None
    for temperature in RETRY_TEMPERATURES:
        try:
            raw = _call_ollama(messages, model, temperature)
            return _parse_response(raw)
        except (json.JSONDecodeError, ValueError, KeyError) as error:
            last_error = error

    raise ValueError(
        f"분류 실패 (재시도 {len(RETRY_TEMPERATURES)}회): {last_error}"
    )
