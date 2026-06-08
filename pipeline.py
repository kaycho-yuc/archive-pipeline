"""추출 → 분류 → 노트 저장 → 아카이브 이동까지 단일 파일 처리 파이프라인."""

import logging
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

from classifier.classify import classify
from extractors.extract import extract_text
from notes.write_note import write_note

load_dotenv()

logger = logging.getLogger("archive_pipeline")


def _resolve_vault_path() -> Path:
    """프로젝트 폴더가 맥·윈도우 간 iCloud로 공유되므로 OS별 볼트 경로를 고른다."""
    key = "OBSIDIAN_VAULT_PATH_WIN" if os.name == "nt" else "OBSIDIAN_VAULT_PATH_MAC"
    path = os.getenv(key) or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
    return Path(path)


INBOX_DIR = Path(os.getenv("INBOX_DIR", "_inbox"))
ARCHIVE_DIR = Path(os.getenv("ARCHIVE_DIR", "_archive"))
VAULT_PATH = _resolve_vault_path()


def _move_to_archive(file_path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / file_path.name
    counter = 1
    while dest.exists():
        dest = archive_dir / f"{file_path.stem}-{counter}{file_path.suffix}"
        counter += 1
    shutil.move(str(file_path), str(dest))
    return dest


def process_file(
    file_path: Path,
    vault_path: Path = VAULT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> Path | None:
    """파일 하나를 처리해 생성된 노트 경로를 반환한다. 실패 시 None."""
    logger.info("처리 시작: %s", file_path.name)
    try:
        text = extract_text(file_path)
        if not text.strip():
            logger.warning("추출된 텍스트가 비어 있어 건너뜀: %s", file_path.name)
            return None

        result = classify(text)
        note_path = write_note(result, file_path.name, text, vault_path)
        logger.info("노트 저장: %s", note_path)

        _move_to_archive(file_path, archive_dir)
        logger.info("아카이브 이동 완료: %s", file_path.name)
        return note_path
    except Exception:
        logger.exception("처리 실패: %s", file_path.name)
        return None
