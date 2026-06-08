"""실패 알림 전송 모듈 (텔레그램).

환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 가 설정돼 있어야 동작한다.
설정이 없으면 조용히 건너뛴다(알림은 부가 기능이라 파이프라인을 막지 않는다).
"""

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger("archive_pipeline")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def notify(message: str) -> bool:
    """텔레그램으로 메시지를 보낸다. 성공하면 True, 미설정·실패면 False."""
    # .env 로드 이후 호출되도록 토큰을 호출 시점에 읽는다.
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False

    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}
    ).encode("utf-8")
    try:
        with urllib.request.urlopen(
            _API_URL.format(token=token), data=data, timeout=10
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not payload.get("ok"):
                logger.warning("텔레그램 응답 오류: %s", payload)
                return False
            return True
    except Exception:
        logger.exception("텔레그램 알림 전송 실패")
        return False
