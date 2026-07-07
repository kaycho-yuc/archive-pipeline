"""텔레그램으로 내 지식베이스(볼트)에 질문하는 봇.

동작 방식:
  핸드폰(텔레그램) ─질문→ 텔레그램 서버 ─→ (집 PC에서 폴링하는) 이 봇
      → Open WebUI RAG(bge-m3 로 볼트 검색) + llama3.1(답 작성) → 답+출처 회신

봇은 텔레그램 서버로 '바깥으로' 연결하므로, 집 PC를 인터넷에 열 필요가 없다
(포트 포워딩·Tailscale 불필요). 볼트는 집 밖으로 나가지 않고 질문/답 텍스트만 오간다.

보안: 허가된 한 사람(TELEGRAM_CHAT_ID)에게만 응답하고 그 외에는 무시한다.
keep-warm 없음: 모델은 Ollama 기본값대로 유휴 시 알아서 내려간다(첫 질문은 5~10초 지연).
"""

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("telegram_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENWEBUI_URL = os.getenv("OPENWEBUI_URL", "http://127.0.0.1:3000")
API_KEY = os.getenv("OPENWEBUI_API_KEY", "")
KB_ID = os.getenv("OPENWEBUI_KB_ID", "")
MODEL = os.getenv("TELEGRAM_RAG_MODEL", "llama3.1:8b")

# RAG 백엔드: "local"(LanceDB+bge-m3, 기본) 또는 "openwebui"(구 Docker 경로).
# 로컬은 한국어 임베더(bge-m3)를 써서 검색 품질이 높고 Docker 가 필요 없다.
RAG_BACKEND = os.getenv("RAG_BACKEND", "local").lower()

_TG = f"https://api.telegram.org/bot{TOKEN}"

# 추론형 모델(qwen 등)이 답 앞에 붙이는 <think>…</think> 사고 과정을 제거한다.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()

WELCOME = (
    "📚 KC 지식베이스 봇입니다. 내 노트(볼트)에 한국어로 물어보세요.\n\n"
    "이렇게 물어보면 잘 답합니다 👇\n"
    "· 685-317 도급계약 상대 회사는?\n"
    "· 성수동 증축 허가 필증 교부일은?\n"
    "· 대수선 허가 필증 연면적은?\n"
    "· 16회차 운동 리뷰 요약해줘\n\n"
    "💡 팁: 지번(685-317 / 685-383)이나 문서 종류(대수선/증축)를 구체적으로 넣을수록 정확합니다. "
    "답 아래엔 📎 참고한 노트가 함께 표시됩니다.\n"
    "첫 질문은 모델 로딩으로 5~10초 걸릴 수 있습니다."
)


def _tg_call(method: str, params: dict, timeout: int = 65) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    with urllib.request.urlopen(f"{_TG}/{method}", data=data, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send_message(chat_id: str, text: str) -> None:
    # 텔레그램 메시지 길이 제한(4096자) 대비 잘라서 보낸다.
    for i in range(0, len(text), 4000):
        try:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4000],
                                     "disable_web_page_preview": "true"})
        except Exception:
            logger.exception("메시지 전송 실패")


def send_typing(chat_id: str) -> None:
    try:
        _tg_call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
    except Exception:
        pass


def ask_knowledge_base(question: str) -> str:
    """설정된 RAG 백엔드로 질문에 답(+출처)을 만들어 돌려준다."""
    if RAG_BACKEND == "local":
        return _ask_local(question)
    return _ask_openwebui(question)


def _ask_local(question: str) -> str:
    """로컬 RAG(LanceDB+bge-m3)로 검색·생성한다."""
    import rag_local  # 지연 임포트: openwebui 백엔드만 쓸 때 lancedb 로딩 회피

    answer, names = rag_local.answer(question, model=MODEL)
    answer = _strip_thinking(answer)
    if not answer:
        return "답을 만들지 못했습니다. 질문을 바꿔 다시 시도해 주세요."
    if names:
        answer += "\n\n📎 참고한 노트:\n" + "\n".join(f"· {n}" for n in names[:10])
    return answer


def _ask_openwebui(question: str) -> str:
    """Open WebUI RAG 에 질문해 답(+출처)을 만들어 돌려준다(구 경로)."""
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": question}],
        "files": [{"type": "collection", "id": KB_ID}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OPENWEBUI_URL}/api/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        result = json.loads(r.read().decode("utf-8"))

    answer = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
    answer = _strip_thinking(answer)
    if not answer:
        return "답을 만들지 못했습니다. 질문을 바꿔 다시 시도해 주세요."

    # 출처(참고한 노트) 목록을 덧붙인다.
    titles = []
    for src in result.get("sources") or []:
        for meta in src.get("metadata") or []:
            name = (meta or {}).get("name") or (meta or {}).get("source")
            if name and name not in titles:
                titles.append(name)
    if titles:
        answer += "\n\n📎 참고한 노트:\n" + "\n".join(f"· {t}" for t in titles[:10])
    return answer


def handle_message(chat_id: str, text: str) -> None:
    text = text.strip()
    if text in ("/start", "/help"):
        send_message(chat_id, WELCOME)
        return
    send_typing(chat_id)
    try:
        send_message(chat_id, ask_knowledge_base(text))
    except Exception as e:
        logger.exception("질문 처리 실패")
        send_message(chat_id, f"⚠️ 처리 중 오류가 났습니다: {e}")


def _required_config() -> list[tuple[str, str]]:
    """RAG 백엔드에 따라 필요한 설정 목록. 로컬은 Open WebUI 키가 필요 없다."""
    req = [("TELEGRAM_BOT_TOKEN", TOKEN), ("TELEGRAM_CHAT_ID", ALLOWED_CHAT_ID)]
    if RAG_BACKEND != "local":
        req += [("OPENWEBUI_API_KEY", API_KEY), ("OPENWEBUI_KB_ID", KB_ID)]
    return req


def main() -> None:
    missing = [n for n, v in _required_config() if not v]
    if missing:
        raise SystemExit(f".env 에 다음 값이 필요합니다: {', '.join(missing)}")

    logger.info("텔레그램 봇 시작 (허가 chat_id=%s, 모델=%s)", ALLOWED_CHAT_ID, MODEL)
    offset = 0
    backoff = 0.0
    while True:
        try:
            updates = _tg_call("getUpdates", {"offset": offset, "timeout": 50}, timeout=60)
        except Exception as e:
            # 네트워크·DNS 장애 시 urlopen 이 즉시 예외를 던져 루프가 폭주할 수 있으므로
            # 지수 백오프로 재시도한다(최대 60초). 트레이스백 대신 한 줄만 남긴다.
            backoff = min(backoff * 2 or 5.0, 60.0)
            logger.warning("getUpdates 실패(%s), %.0f초 후 재시도", e, backoff)
            time.sleep(backoff)
            continue
        backoff = 0.0

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg or "text" not in msg:
                continue
            chat_id = str(msg["chat"]["id"])
            if chat_id != str(ALLOWED_CHAT_ID):
                logger.warning("허가되지 않은 chat_id 무시: %s", chat_id)
                continue
            logger.info("질문: %s", msg["text"][:80])
            handle_message(chat_id, msg["text"])


def start_bot() -> threading.Thread | None:
    """봇을 백그라운드 데몬 스레드로 시작한다(감시기와 함께 살고 죽음).

    토큰·KB 등 설정이 없으면 조용히 건너뛴다(봇은 부가 기능이라 감시기를 막지 않는다).
    """
    if any(not v for _, v in _required_config()):
        logger.warning("텔레그램 봇 설정이 부족해 시작하지 않습니다(.env 확인).")
        return None

    def _run() -> None:
        try:
            main()
        except Exception:
            logger.exception("텔레그램 봇 루프 종료")

    thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    thread.start()
    logger.info("텔레그램 봇 데몬 시작")
    return thread


if __name__ == "__main__":
    main()
