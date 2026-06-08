"""추출 → 분류 → 노트 저장 → 아카이브 이동까지 단일 파일 처리 파이프라인."""

import csv
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import notifier
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
FAILED_DIR = Path(os.getenv("FAILED_DIR", "_failed"))
PROCESSING_LOG = Path(os.getenv("PROCESSING_LOG", "processing_log.csv"))
VAULT_PATH = _resolve_vault_path()


def _log_result(filename: str, status: str, detail: str = "") -> None:
    """처리 결과를 CSV 로그에 한 줄 추가한다(엑셀에서 한글이 깨지지 않게 utf-8-sig)."""
    try:
        new_file = not PROCESSING_LOG.exists()
        PROCESSING_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PROCESSING_LOG.open("a", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(["시각", "상태", "파일명", "상세"])
            writer.writerow(
                [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status, filename, detail]
            )
    except Exception:
        logger.exception("처리 로그 기록 실패: %s", filename)


# 폴더가 비었는지 판단할 때 무시할 OS 잔재 파일(맥·윈도우 iCloud 동기화 잔여물).
_JUNK_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def prune_empty_dirs(root: Path) -> None:
    """root 하위의 빈(또는 잔재 파일만 남은) 폴더를 제거한다. root 자체는 보존한다."""
    if not root.exists():
        return
    # 깊은 폴더부터 처리해야 부모가 비는 것을 연쇄적으로 정리할 수 있다.
    subdirs = sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for dirpath in subdirs:
        entries = list(dirpath.iterdir())
        if all(e.is_file() and e.name in _JUNK_FILES for e in entries):
            for junk in entries:
                try:
                    junk.unlink()
                except OSError:
                    pass
            try:
                dirpath.rmdir()
            except OSError:
                logger.debug("빈 폴더 제거 실패(건너뜀): %s", dirpath)


def _move_to(file_path: Path, dest_dir: Path) -> Path:
    """파일을 dest_dir 로 옮긴다. 같은 이름이 있으면 -1, -2 … 를 붙인다."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_path.name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{file_path.stem}-{counter}{file_path.suffix}"
        counter += 1
    shutil.move(str(file_path), str(dest))
    return dest


def process_file(
    file_path: Path,
    vault_path: Path = VAULT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    failed_dir: Path = FAILED_DIR,
) -> Path | None:
    """파일 하나를 처리해 생성된 노트 경로를 반환한다. 실패 시 None.

    추출 불가(빈 텍스트)·분류 실패한 파일은 _failed 로 격리해, 매 로그인마다
    같은 파일을 무한 재시도(재OCR·재호출)하지 않도록 한다.
    """
    name = file_path.name
    logger.info("처리 시작: %s", name)
    try:
        text = extract_text(file_path)
        if not text.strip():
            logger.warning("추출된 텍스트가 비어 격리: %s", name)
            _move_to(file_path, failed_dir)
            _log_result(name, "격리(빈 텍스트)", "추출된 텍스트 없음")
            notifier.notify(f"⚠️ 처리 실패(텍스트 없음): {name}\n→ _failed 로 격리됨")
            return None

        result = classify(text)
        note_path = write_note(result, name, text, vault_path)
        logger.info("노트 저장: %s", note_path)

        _move_to(file_path, archive_dir)
        logger.info("아카이브 이동 완료: %s", name)
        _log_result(name, "저장", str(note_path))
        return note_path
    except Exception as error:
        logger.exception("처리 실패, 격리: %s", name)
        try:
            _move_to(file_path, failed_dir)
        except Exception:
            logger.exception("격리 이동 실패: %s", name)
        _log_result(name, "실패", str(error))
        notifier.notify(f"⚠️ 처리 실패: {name}\n사유: {error}\n→ _failed 로 격리됨")
        return None
