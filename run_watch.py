"""Task Scheduler 진입점: 기존 _inbox 파일을 먼저 처리한 뒤 폴더 감시를 시작한다.

윈도우 작업 스케줄러는 작업 디렉터리를 보장하지 않으므로 먼저 이 파일 위치로
이동한다(상대 경로 _inbox/_archive/.env 가 올바르게 잡히도록). 로그는 watch.log 에 남긴다.
"""

import logging
import os
import socket
from logging.handlers import RotatingFileHandler
from pathlib import Path

os.chdir(Path(__file__).parent)

# 같은 _inbox 를 두 프로세스가 감시하면 같은 파일이 두 번 처리돼 노트가 중복된다.
# 포트를 하나 잡아 단일 실행을 보장한다. 파일 잠금과 달리 프로세스가 죽으면 OS 가 즉시
# 회수하므로, 비정상 종료 뒤 잠금이 남아 다음 기동을 막는 문제가 없다.
LOCK_PORT = int(os.getenv("WATCH_LOCK_PORT", "47823"))

# 회전 로그: 파일 하나가 커져도 5MB 에서 잘리고 백업 3개까지만 보관한다
# (최대 약 20MB). 과거처럼 장애 루프가 로그로 디스크를 채우는 일을 막는다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        RotatingFileHandler(
            "watch.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    ],
)

import monitor  # noqa: E402  (로깅 설정 후 임포트)
import run_once  # noqa: E402
import telegram_bot  # noqa: E402
import watch  # noqa: E402

def acquire_single_instance() -> socket.socket:
    """이미 감시기가 돌고 있으면 조용히 물러난다. 잡은 소켓은 프로세스가 살아 있는 동안 쥔다."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
        lock.listen(1)
    except OSError:
        logging.getLogger("archive_pipeline").warning(
            "감시기가 이미 실행 중입니다(포트 %d 사용 중). 이번 인스턴스는 종료합니다.", LOCK_PORT
        )
        raise SystemExit(0) from None
    return lock


if __name__ == "__main__":
    _lock = acquire_single_instance()  # 중복 감시기 방지(포트를 계속 쥐고 있어야 하므로 변수로 보관)
    monitor.start_monitor()  # 리소스 블랙박스(데몬 스레드, 감시기와 함께 종료)
    telegram_bot.start_bot()  # 텔레그램 RAG 봇(데몬 스레드, 설정 없으면 건너뜀)
    run_once.main()  # 감시 시작 전, 이미 쌓여 있던 파일을 먼저 처리
    watch.main()  # 이후 새로 들어오는 파일을 상시 감시
