"""Ollama 로컬 LLM으로 문서를 분류하고 요약하는 모듈."""

import json
import os
from dataclasses import dataclass

import ollama

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# 이 PC의 시스템 OLLAMA_HOST 가 0.0.0.0 (접속 불가 주소)로 설정돼 있어
# 파이프라인 전용 접속 주소를 명시한다. 시스템 환경변수는 건드리지 않는다.
_host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
if _host.startswith(("0.0.0.0", "http://0.0.0.0", "https://0.0.0.0")):
    _host = _host.replace("0.0.0.0", "127.0.0.1")
_client = ollama.Client(host=_host)

# 추출 텍스트가 너무 길면 모델 컨텍스트를 넘기므로 앞부분만 사용한다.
MAX_INPUT_CHARS = 8000

SYSTEM_PROMPT = """\
당신은 문서를 분류하고 요약하는 한국어 비서입니다.
주어진 문서 내용을 읽고 아래 JSON 형식으로만 응답하세요. 다른 설명은 붙이지 마세요.

{
  "domain": "개인 또는 업무 중 하나",
  "category": "문서 내용에 맞는 구체적인 세부 카테고리 (한국어 단어 또는 짧은 구)",
  "title": "문서를 대표하는 짧은 제목",
  "summary": "문서 핵심 내용을 3~5문장으로 요약"
}

규칙:
- domain은 반드시 "개인" 또는 "업무" 중 하나여야 합니다.
- category는 폴더 이름으로 쓸 수 있도록 간결해야 합니다 (예: "계약서", "회의록", "영수증").
- 반드시 유효한 JSON 한 개만 출력하세요."""


@dataclass
class Classification:
    domain: str
    category: str
    title: str
    summary: str


def _build_messages(text: str) -> list[dict]:
    content = text[:MAX_INPUT_CHARS]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"다음 문서를 분류하고 요약하세요:\n\n{content}"},
    ]


def _call_ollama(messages: list[dict], model: str) -> str:
    response = _client.chat(
        model=model,
        messages=messages,
        format="json",
        options={"temperature": 0},
    )
    return response["message"]["content"]


def _parse_response(raw: str) -> Classification:
    data = json.loads(raw)

    domain = str(data["domain"]).strip()
    if domain not in ("개인", "업무"):
        raise ValueError(f"domain 값이 올바르지 않습니다: {domain!r}")

    return Classification(
        domain=domain,
        category=str(data["category"]).strip(),
        title=str(data["title"]).strip(),
        summary=str(data["summary"]).strip(),
    )


def classify(text: str, model: str = DEFAULT_MODEL) -> Classification:
    """문서 텍스트를 분류·요약해 Classification으로 반환한다."""
    if not text.strip():
        raise ValueError("빈 문서는 분류할 수 없습니다.")

    raw = _call_ollama(_build_messages(text), model)
    return _parse_response(raw)
