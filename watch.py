"""_inbox 폴더를 감시해 새 파일이 들어오면 파이프라인을 실행한다."""

import logging
import os
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from extractors.extract import SUPPORTED_EXTENSIONS
from pipeline import (
    ARCHIVE_DIR,
    FAILED_DIR,
    INBOX_DIR,
    VAULT_PATH,
    process_file,
    prune_empty_dirs,
    quarantine_unsupported,
    sweep_inbox,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("archive_pipeline")

# 파일이 완전히 복사될 때까지 크기가 안정되길 기다리는 간격(초).
SETTLE_INTERVAL = 1.0
SETTLE_RETRIES = 5

# 주기적 전체 스윕 간격(초). iCloud 동기화로 생긴 파일은 감시기의 on_created 이벤트가
# 안정적으로 발생하지 않아, 일정 간격으로 _inbox 전체를 다시 훑어 놓친 파일을 처리한다.
SWEEP_INTERVAL = float(os.getenv("SWEEP_INTERVAL", "600"))

# 로컬 RAG 전체 재색인 간격(초, 기본 1시간). 새 노트는 파이프라인이 저장 직후 바로
# 색인하지만, (a) pause_ai 로 Ollama 가 멈춘 동안 만들어진 노트, (b) 볼트에서 손으로
# 고치거나 이름을 바꾼 노트는 감시기가 못 본다. 증분 재색인(안 바뀐 노트는 건너뜀)으로
# 주기적으로 따라잡는 안전망이다. RAG_BACKEND=local 일 때만 동작.
RAG_REINGEST_INTERVAL = float(os.getenv("RAG_REINGEST_INTERVAL", "3600"))


def _wait_until_stable(file_path: Path) -> bool:
    """파일 크기가 더 이상 변하지 않을 때까지 기다린다. 사라지면 False."""
    last_size = -1
    for _ in range(SETTLE_RETRIES):
        if not file_path.exists():
            return False
        size = file_path.stat().st_size
        if size == last_size:
            return True
        last_size = size
        time.sleep(SETTLE_INTERVAL)
    return True


class InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not _wait_until_stable(path):
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            # 미지원 형식은 볼트 노트에 기록한 뒤 _failed 로 격리한다.
            quarantine_unsupported(path, vault_path=VAULT_PATH, failed_dir=FAILED_DIR)
            prune_empty_dirs(INBOX_DIR)
            return
        process_file(path, vault_path=VAULT_PATH, archive_dir=ARCHIVE_DIR)
        prune_empty_dirs(INBOX_DIR)


def _reingest_rag_backstop() -> None:
    """로컬 RAG 증분 전체 재색인(best-effort). Ollama 정지 등 실패는 다음 주기에 재시도."""
    if os.getenv("RAG_BACKEND", "local").lower() != "local":
        return
    try:
        import rag_local

        stats = rag_local.ingest(reset=False, verbose=False)
        if stats["added"] or stats["updated"]:
            logger.info("RAG 주기 재색인: 추가 %d, 갱신 %d", stats["added"], stats["updated"])
    except Exception:
        logger.warning("RAG 주기 재색인 실패(다음 주기에 재시도)")


def main():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("감시 시작: %s", INBOX_DIR.resolve())

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_DIR), recursive=True)
    observer.start()
    last_sweep = time.monotonic()
    last_reingest = time.monotonic()
    try:
        while True:
            time.sleep(1)
            if time.monotonic() - last_sweep >= SWEEP_INTERVAL:
                # iCloud 동기화로 on_created 이벤트가 누락된 파일까지 주기적으로 정리한다.
                try:
                    sweep_inbox()
                except Exception:
                    logger.exception("주기적 스윕 실패(다음 주기에 재시도)")
                last_sweep = time.monotonic()
            if time.monotonic() - last_reingest >= RAG_REINGEST_INTERVAL:
                # pause_ai 구간·수동 편집으로 놓친 노트를 증분 재색인으로 따라잡는 안전망.
                _reingest_rag_backstop()
                last_reingest = time.monotonic()
    except KeyboardInterrupt:
        observer.stop()
        logger.info("감시 종료")
    observer.join()


if __name__ == "__main__":
    main()
