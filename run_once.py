"""_inbox 안의 모든 파일을 한 번에 처리한다 (맥북 수동 실행용)."""

import logging

from extractors.extract import SUPPORTED_EXTENSIONS
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


def main():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        p
        for p in sorted(INBOX_DIR.rglob("*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        logger.info("처리할 파일이 없습니다: %s", INBOX_DIR.resolve())
        return

    logger.info("%d개 파일 처리 시작", len(files))
    processed = 0
    for path in files:
        if process_file(path, vault_path=VAULT_PATH, archive_dir=ARCHIVE_DIR):
            processed += 1
    prune_empty_dirs(INBOX_DIR)
    logger.info("완료: %d/%d 성공", processed, len(files))


if __name__ == "__main__":
    main()
