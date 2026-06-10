"""Task Scheduler 진입점: 기존 _inbox 파일을 먼저 처리한 뒤 폴더 감시를 시작한다.

윈도우 작업 스케줄러는 작업 디렉터리를 보장하지 않으므로 먼저 이 파일 위치로
이동한다(상대 경로 _inbox/_archive/.env 가 올바르게 잡히도록). 로그는 watch.log 에 남긴다.
"""

import logging
import os
from pathlib import Path

os.chdir(Path(__file__).parent)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("watch.log", encoding="utf-8")],
)

import monitor  # noqa: E402  (로깅 설정 후 임포트)
import run_once  # noqa: E402
import watch  # noqa: E402

if __name__ == "__main__":
    monitor.start_monitor()  # 리소스 블랙박스(데몬 스레드, 감시기와 함께 종료)
    run_once.main()  # 감시 시작 전, 이미 쌓여 있던 파일을 먼저 처리
    watch.main()  # 이후 새로 들어오는 파일을 상시 감시
