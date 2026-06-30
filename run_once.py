"""_inbox 안의 모든 파일을 한 번에 처리한다 (맥북 수동 실행·시작 backlog용).

지원 형식은 처리하고, 미지원 형식(dwg·pptx·zip·alz 등)은 볼트 노트에 기록한 뒤
_failed 로 격리한다 — 실제 동작은 pipeline.sweep_inbox 에 모여 있다."""

import logging

from pipeline import INBOX_DIR, sweep_inbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("archive_pipeline")


def main():
    processed, supported, unsupported = sweep_inbox()
    if supported == 0 and unsupported == 0:
        logger.info("처리할 파일이 없습니다: %s", INBOX_DIR.resolve())
        return
    logger.info(
        "완료: 지원 %d/%d 성공, 미지원 %d개 기록·격리",
        processed,
        supported,
        unsupported,
    )


if __name__ == "__main__":
    main()
