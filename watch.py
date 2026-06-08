"""_inbox 폴더를 감시해 새 파일이 들어오면 파이프라인을 실행한다."""

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from extractors.extract import IMAGE_EXTENSIONS, PDF_EXTENSIONS, TEXT_EXTENSIONS
from pipeline import (
    ARCHIVE_DIR,
    INBOX_DIR,
    VAULT_PATH,
    process_file,
    prune_empty_dirs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("archive_pipeline")

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | TEXT_EXTENSIONS

# 파일이 완전히 복사될 때까지 크기가 안정되길 기다리는 간격(초).
SETTLE_INTERVAL = 1.0
SETTLE_RETRIES = 5


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
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.info("지원하지 않는 형식, 건너뜀: %s", path.name)
            return
        if not _wait_until_stable(path):
            return
        process_file(path, vault_path=VAULT_PATH, archive_dir=ARCHIVE_DIR)
        prune_empty_dirs(INBOX_DIR)


def main():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("감시 시작: %s", INBOX_DIR.resolve())

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_DIR), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("감시 종료")
    observer.join()


if __name__ == "__main__":
    main()
