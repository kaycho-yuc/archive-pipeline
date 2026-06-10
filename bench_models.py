"""여러 모델을 같은 RAG 질문으로 비교한다(AEC/한국어 평가용).

각 모델 x 각 질문에 대해 Open WebUI RAG 로 답을 받아 _bench_result.md 에 저장한다.
사람이 읽고 어떤 모델이 가장 '근거 있고 똑똑한지' 고르기 위한 보조 자료.
"""

import json
import time
import urllib.request

import telegram_bot as tb

MODELS = [
    "mistral-nemo:latest",  # 현재 기본(기준선)
    "exaone3.5:7.8b",       # LG 한국어 특화
    "qwen2.5:14b",          # 12GB 이하 최강 추론
]

QUESTIONS = [
    "성수동 해체공사 계약 기준으로 대금 지급 조건과 내가 챙겨야 할 리스크를 분석해줘.",
    "내 노트들에서 성수동 프로젝트의 공사 금액 관련 숫자들을 모아 정리하고, 부가세 포함 여부를 따져줘.",
    "해체공사 계약서와 견적/내역 노트를 비교해서, 서로 어긋나거나 확인이 필요한 부분이 있으면 짚어줘.",
]


def ask(model: str, question: str) -> tuple[str, float]:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "files": [{"type": "collection", "id": tb.KB_ID}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{tb.OPENWEBUI_URL}/api/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {tb.API_KEY}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    m = json.loads(urllib.request.urlopen(req, timeout=600).read())["choices"][0]["message"]
    elapsed = time.time() - t0
    content = tb._strip_thinking(m.get("content") or "")
    if not content:
        content = f"(빈 답 — reasoning_content {len(m.get('reasoning_content') or '')}자)"
    return content, elapsed


def main() -> None:
    out = ["# 모델 비교 결과\n"]
    for qi, q in enumerate(QUESTIONS, 1):
        out.append(f"\n## 질문 {qi}: {q}\n")
        for model in MODELS:
            print(f"[{qi}] {model} ...", flush=True)
            try:
                ans, sec = ask(model, q)
            except Exception as e:
                ans, sec = f"(오류: {e})", 0.0
            out.append(f"\n### {model}  ·  {sec:.1f}s\n\n{ans}\n")
    open("_bench_result.md", "w", encoding="utf-8").write("\n".join(out))
    print("저장: _bench_result.md")


if __name__ == "__main__":
    main()
