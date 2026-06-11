"""추출 → 분류 → 노트 저장 → 아카이브 이동까지 단일 파일 처리 파이프라인."""

import csv
import hashlib
import json
import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import notifier
from classifier.classify import KIND_REFERENCE, classify
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
# 참고자료(템플릿·샘플·정부지침·다른 현장 문서)는 노트로 만들지 않고 여기 격리한다.
# _failed 안의 별도 폴더 — 사람이 가끔 검토하고 오분류는 _inbox 로 되돌리면 된다.
REFERENCE_DIR = Path(os.getenv("REFERENCE_DIR", str(FAILED_DIR / "참고자료")))
PROCESSING_LOG = Path(os.getenv("PROCESSING_LOG", "processing_log.csv"))
HASH_LOG = Path(os.getenv("HASH_LOG", "processed_hashes.json"))
VAULT_PATH = _resolve_vault_path()


# iCloud(및 OneDrive) "온라인 전용" 파일을 가리키는 Windows 파일 속성 비트.
# 이 비트가 있으면 파일 바이트가 아직 로컬에 없어, 읽으면 다운로드될 때까지 멈춘다.
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_DEHYDRATED_BITS = (
    _FILE_ATTRIBUTE_OFFLINE
    | _FILE_ATTRIBUTE_RECALL_ON_OPEN
    | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

# 온라인 전용 파일을 내려받기까지 기다릴 최대 시간(초). 못 받으면 이번엔 건너뛴다.
HYDRATE_TIMEOUT = float(os.getenv("HYDRATE_TIMEOUT", "30"))


def _is_dehydrated(file_path: Path) -> bool:
    """파일이 아직 다운로드되지 않은 iCloud '온라인 전용' placeholder인지 판단한다."""
    try:
        attrs = file_path.stat().st_file_attributes  # Windows 전용
    except (AttributeError, OSError):
        return False  # 비윈도우거나 속성을 못 읽으면 일반 파일로 취급
    return bool(attrs & _DEHYDRATED_BITS)


def _ensure_hydrated(file_path: Path, timeout: float = HYDRATE_TIMEOUT) -> bool:
    """온라인 전용 파일을 백그라운드 스레드로 내려받게 하고, timeout 안에 준비되면 True.

    파이프라인이 다운로드 I/O에서 무한정 멈추지 않도록, 첫 바이트 접근(다운로드
    트리거)을 별도 스레드에서 수행하고 메인은 timeout 까지만 기다린다. 시간 안에
    못 받으면 False — 이번 처리에선 건너뛰고(파일은 _inbox 에 그대로) 다음 스윕에서
    재시도한다. 백그라운드 다운로드는 계속 진행되므로 다음 번엔 보통 성공한다.
    """
    if not _is_dehydrated(file_path):
        return True

    logger.info("iCloud에서 내려받는 중(최대 %.0fs): %s", timeout, file_path.name)
    done = threading.Event()

    def _pull() -> None:
        try:
            with file_path.open("rb") as fh:
                fh.read(1)  # 첫 바이트 접근이 iCloud 다운로드를 트리거한다
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=_pull, daemon=True).start()
    return done.wait(timeout) and not _is_dehydrated(file_path)


def _file_hash(file_path: Path) -> str:
    """파일 내용의 SHA-256 해시(중복 처리 방지용)."""
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_hashes() -> dict:
    if not HASH_LOG.exists():
        return {}
    try:
        return json.loads(HASH_LOG.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("해시 로그 읽기 실패, 빈 로그로 시작: %s", HASH_LOG)
        return {}


def _record_hash(file_hash: str, filename: str, note_path: str) -> None:
    hashes = _load_hashes()
    hashes[file_hash] = {
        "filename": filename,
        "note": note_path,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        HASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        HASH_LOG.write_text(
            json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.exception("해시 로그 기록 실패: %s", filename)


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
        if not _ensure_hydrated(file_path):
            logger.warning("iCloud 다운로드 대기 시간 초과, 이번엔 건너뜀: %s", name)
            _log_result(name, "보류(미다운로드)", "iCloud 온라인 전용 — 다음 스윕에서 재시도")
            return None

        file_hash = _file_hash(file_path)
        if file_hash in _load_hashes():
            logger.info("이미 처리된 파일(중복), 아카이브로 이동: %s", name)
            _move_to(file_path, archive_dir)
            _log_result(name, "중복", "해시 일치 — 건너뜀")
            return None

        text = extract_text(file_path)
        if not text.strip():
            logger.warning("추출된 텍스트가 비어 격리: %s", name)
            _move_to(file_path, failed_dir)
            _log_result(name, "격리(빈 텍스트)", "추출된 텍스트 없음")
            notifier.notify(f"⚠️ 처리 실패(텍스트 없음): {name}\n→ _failed 로 격리됨")
            return None

        result = classify(text, source_name=name)

        # 참고자료(템플릿·샘플·정부지침·다른 현장)는 노트로 만들지 않고 격리한다.
        # 봇 지식베이스를 프로젝트 실데이터로만 유지해 답변 정확도를 지킨다.
        if result.domain == "업무" and result.kind == KIND_REFERENCE:
            logger.info("참고자료로 판정, 격리(노트 미생성): %s", name)
            _move_to(file_path, REFERENCE_DIR)
            _log_result(name, "참고자료(격리)", "프로젝트 실데이터 아님 — 검토 폴더로 이동")
            return None

        note_path = write_note(result, name, text, vault_path)
        logger.info("노트 저장: %s", note_path)

        _record_hash(file_hash, name, str(note_path))
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
