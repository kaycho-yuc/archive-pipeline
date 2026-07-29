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
from extractors.extract import (
    MSG_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    extract_text,
    msg_attachments,
)
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


# iCloud 가 동기화 중인 파일은 이동(복사 후 원본 unlink)이 무한정 멈출 수 있다.
# 한 파일의 멈춤이 전체 파이프라인을 얼리지 않도록 이동에 시간 제한을 둔다.
MOVE_TIMEOUT = float(os.getenv("MOVE_TIMEOUT", "20"))


def _move_to(file_path: Path, dest_dir: Path, timeout: float = MOVE_TIMEOUT) -> Path:
    """파일을 dest_dir 로 옮긴다. 같은 이름이 있으면 -1, -2 … 를 붙인다.

    iCloud 동기화로 이동이 멈추는 경우를 대비해 별도 스레드에서 수행하고 timeout
    안에 못 끝내면 TimeoutError 를 던진다(호출부가 격리/보류로 처리)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_path.name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{file_path.stem}-{counter}{file_path.suffix}"
        counter += 1

    outcome: dict = {}

    # 복사 도중 프로세스가 죽으면 '잘린 파일'이 최종 이름을 차지하고, 다음 스윕은 원본을
    # 중복으로 보고 -1 을 붙여 넣는다 — 온전한 원본이 -1 로 밀리고 잘린 파일이 정식 이름을
    # 갖는 최악의 결과. 임시 이름으로 복사한 뒤 제자리에 놓아 최종 이름엔 완전한 파일만 남긴다.
    partial = dest.with_name(dest.name + ".part")

    def _do() -> None:
        try:
            # shutil.move 를 쓰지 않는다: 같은 볼륨으로 보이면 os.rename 을 먼저 시도하는데,
            # iCloud 동기화 루트 '밖'으로의 rename 은 Windows 클라우드 필터 드라이버가
            # 가로채 60초를 멈춘 뒤 WinError 426 으로 실패한다(shutil 의 복사 폴백은 그
            # 뒤에야 실행돼 아래 timeout 에 먼저 걸린다). 복사 후 삭제는 같은 경계에서
            # 0.02초로 끝나므로 rename 을 아예 거치지 않는다.
            shutil.copy2(str(file_path), str(partial))
            # 같은 폴더 안(=클라우드 경계를 넘지 않음)이라 이 rename 은 원자적이고 안전하다.
            os.replace(str(partial), str(dest))
            os.unlink(str(file_path))
            outcome["ok"] = True
        except Exception as exc:  # noqa: BLE001 — 스레드 내 예외를 호출부로 전달
            try:
                partial.unlink(missing_ok=True)  # 실패한 조각을 아카이브에 남기지 않는다
            except OSError:
                pass
            outcome["err"] = exc

    worker = threading.Thread(target=_do, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"파일 이동 시간 초과({timeout:.0f}s): {file_path.name}")
    if "err" in outcome:
        raise outcome["err"]
    return dest


# 미지원 형식(추출기 없는 dwg·pptx·zip·alz 등) 파일을 누적 기록하는 볼트 노트.
# 새 미지원 파일이 들어올 때마다 표에 한 줄씩 추가되고, 파일은 _failed 로 격리된다.
UNSUPPORTED_NOTE_NAME = os.getenv("UNSUPPORTED_NOTE_NAME", "미지원_파일_목록.md")

_UNSUPPORTED_NOTE_HEADER = """\
---
title: 미지원 파일 목록 (자동 처리 불가 파일)
category: 시스템
status: 유지관리
tags:
  - 시스템/미지원파일
  - 유지관리
created: {today}
updated: {today}
---

# 미지원 파일 목록

아카이브 파이프라인이 **자동 처리하지 못하는 형식**의 파일을 기록하는 목록입니다.
지원 형식(pdf · docx · xlsx/xls · hwp/hwpx · md · msg · xml · txt · 이미지)에 없는 파일은
인박스(`_inbox`)에서 처리되지 않으므로, 여기에 기록한 뒤 `_failed` 폴더로 옮깁니다.

- **압축파일(zip·alz)**: 풀어서 안의 pdf·docx 등을 인박스에 넣으면 처리됩니다.
- **도면(dwg)·파워포인트(pptx)**: 현재 추출기가 없습니다.
- 이 노트는 미지원 파일이 새로 나올 때마다 **자동으로 누적**됩니다.

| 기록일 | 파일명 | 확장자 | 생성일 | 최근 수정일 | 크기(MB) | 인박스 내 원래 위치 | 이동 위치 |
|--------|--------|--------|--------|-------------|----------|---------------------|-----------|
"""


def _unsupported_note_row(file_path: Path, inbox_dir: Path) -> str:
    """미지원 파일 한 줄을 노트 표 형식(생성일·수정일 포함)으로 만든다."""
    st = file_path.stat()
    created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    size_mb = round(st.st_size / (1024 * 1024), 1)
    try:
        rel = file_path.parent.relative_to(inbox_dir)
        location = str(rel) if str(rel) != "." else "(루트)"
    except ValueError:
        location = str(file_path.parent)
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"| {today} | {file_path.name} | {file_path.suffix.lower()} | {created} | "
        f"{modified} | {size_mb} | {location} | _failed |"
    )


def record_unsupported(
    file_path: Path, vault_path: Path = VAULT_PATH, inbox_dir: Path = INBOX_DIR
) -> Path:
    """미지원 파일을 볼트 노트(누적 표)에 한 줄 추가한다. 노트가 없으면 만든다.

    같은 파일명이 이미 표에 있으면 다시 적지 않는다(이동 실패로 재시도될 때 중복 방지)."""
    note = vault_path / UNSUPPORTED_NOTE_NAME
    note.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    content = (
        note.read_text(encoding="utf-8")
        if note.exists()
        else _UNSUPPORTED_NOTE_HEADER.format(today=today)
    )
    if f"| {file_path.name} |" in content:
        return note  # 이미 기록됨
    if not content.endswith("\n"):
        content += "\n"
    content += _unsupported_note_row(file_path, inbox_dir) + "\n"
    note.write_text(content, encoding="utf-8")
    return note


def quarantine_unsupported(
    file_path: Path,
    vault_path: Path = VAULT_PATH,
    failed_dir: Path = FAILED_DIR,
    inbox_dir: Path = INBOX_DIR,
) -> bool:
    """미지원 형식 파일을 노트에 기록한 뒤 _failed 로 격리한다. 이동 성공 시 True.

    이동이 iCloud 동기화로 멈추면(타임아웃) 이번엔 보류하고 다음 스윕에서 재시도한다."""
    name = file_path.name
    if not file_path.exists():
        return False  # 다른 경로(감시기/이전 스윕)에서 이미 처리됨
    try:
        record_unsupported(file_path, vault_path, inbox_dir)
        _move_to(file_path, failed_dir)
        logger.info("미지원 형식 기록·격리: %s", name)
        _log_result(name, "미지원(격리)", "미지원 형식 — 목록 기록 후 _failed 이동")
        return True
    except TimeoutError as error:
        logger.warning("미지원 격리 이동 지연으로 보류(다음 스윕 재시도): %s — %s", name, error)
        _log_result(name, "보류(이동지연)", str(error))
        return False
    except Exception as error:  # noqa: BLE001 — 한 파일 실패가 스윕 전체를 막지 않게 한다
        logger.exception("미지원 격리 실패: %s", name)
        _log_result(name, "미지원 격리 실패", str(error))
        return False


def _explode_msg_attachments(
    msg_path: Path,
    origin_email: str,
    vault_path: Path,
    archive_dir: Path,
    failed_dir: Path,
) -> None:
    """이메일(.msg)의 첨부를 _inbox 에 풀어 각각 독립 파일로 다시 처리한다.

    각 첨부는 자체 파일명으로 분류돼 별도 노트가 되고(계약서·내역서 등),
    origin_email(출처 이메일 노트 제목)을 받아 노트에 출처 위키링크를 남긴다.
    한 첨부의 실패가 전체를 막지 않도록 개별로 감싼다."""
    try:
        attachments = msg_attachments(msg_path)
    except Exception:
        logger.exception("이메일 첨부 목록 추출 실패(건너뜀): %s", msg_path.name)
        return
    for name, data in attachments:
        try:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            dest = INBOX_DIR / name
            counter = 1
            while dest.exists():
                dest = INBOX_DIR / f"{Path(name).stem}-{counter}{Path(name).suffix}"
                counter += 1
            dest.write_bytes(data)
            logger.info("이메일 첨부 처리: %s ← %s", dest.name, msg_path.name)
            process_file(dest, vault_path, archive_dir, failed_dir, origin_email)
        except Exception:
            logger.exception("이메일 첨부 처리 실패(건너뜀): %s ← %s", name, msg_path.name)


def _index_note_best_effort(note_path: Path) -> None:
    """새 노트를 로컬 RAG 인덱스에 반영한다(best-effort).

    실패해도 파일 처리를 막지 않는다. Ollama 가 멈춰 있으면(pause_ai) 조용히 건너뛰고,
    감시기의 주기적 전체 재색인(watch.py)이 나중에 따라잡는다. RAG_BACKEND=local 일 때만 동작."""
    if os.getenv("RAG_BACKEND", "local").lower() != "local":
        return
    try:
        import rag_local

        rag_local.index_note(note_path)
    except Exception:
        logger.warning("로컬 RAG 색인 건너뜀(다음 전체 재색인에서 반영): %s", note_path.name)


def process_file(
    file_path: Path,
    vault_path: Path = VAULT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    failed_dir: Path = FAILED_DIR,
    origin_email: str | None = None,
) -> Path | None:
    """파일 하나를 처리해 생성된 노트 경로를 반환한다. 실패 시 None.

    추출 불가(빈 텍스트)·분류 실패한 파일은 _failed 로 격리해, 매 로그인마다
    같은 파일을 무한 재시도(재OCR·재호출)하지 않도록 한다.

    origin_email 이 있으면 이메일 첨부에서 나온 파일이라는 뜻으로, 생성 노트에
    출처 이메일 위키링크를 남긴다.
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

        note_path = write_note(result, name, text, vault_path, origin_email=origin_email)
        logger.info("노트 저장: %s", note_path)
        _index_note_best_effort(note_path)  # 새 노트를 로컬 RAG 에 즉시 반영(best-effort)

        _record_hash(file_hash, name, str(note_path))
        archived = _move_to(file_path, archive_dir)
        logger.info("아카이브 이동 완료: %s", name)
        _log_result(name, "저장", str(note_path))

        # 이메일이면 첨부를 풀어 각각 독립 노트로 만든다(출처 이메일 = 방금 만든 이 노트).
        if archived.suffix.lower() in MSG_EXTENSIONS:
            _explode_msg_attachments(
                archived, note_path.stem, vault_path, archive_dir, failed_dir
            )
        return note_path
    except TimeoutError as error:
        # iCloud 동기화 등으로 파일 이동이 멈춤. 전체를 얼리지 않도록 이번엔 보류하고
        # 다음 파일로 넘어간다(파일은 _inbox 에 남아 다음 스윕에서 재시도). 노트가 이미
        # 만들어졌다면 해시로 중복 처리되므로 노트가 중복 생성되지는 않는다.
        logger.warning("이동 지연으로 보류(다음 스윕 재시도): %s — %s", name, error)
        _log_result(name, "보류(이동지연)", str(error))
        return None
    except Exception as error:
        logger.exception("처리 실패, 격리: %s", name)
        try:
            _move_to(file_path, failed_dir)
        except Exception:
            logger.exception("격리 이동 실패: %s", name)
        _log_result(name, "실패", str(error))
        notifier.notify(f"⚠️ 처리 실패: {name}\n사유: {error}\n→ _failed 로 격리됨")
        return None


def sweep_inbox(
    vault_path: Path = VAULT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    failed_dir: Path = FAILED_DIR,
    inbox_dir: Path = INBOX_DIR,
) -> tuple[int, int, int]:
    """_inbox 전체를 한 번 훑는다: 지원 형식은 처리, 미지원 형식은 기록·격리.

    시작 시(backlog)와 감시 중 주기적으로 호출돼, iCloud 동기화로 감시기가 놓친
    파일까지 빠짐없이 처리하고 미지원 파일을 쌓이지 않게 정리한다.
    (처리 성공 수, 지원 형식 수, 미지원 형식 수)를 돌려준다."""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        p
        for p in sorted(inbox_dir.rglob("*"))
        if p.is_file() and p.name not in _JUNK_FILES
    ]
    supported = [p for p in entries if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    unsupported = [p for p in entries if p.suffix.lower() not in SUPPORTED_EXTENSIONS]

    processed = 0
    for path in supported:
        if process_file(
            path, vault_path=vault_path, archive_dir=archive_dir, failed_dir=failed_dir
        ):
            processed += 1
    for path in unsupported:
        quarantine_unsupported(
            path, vault_path=vault_path, failed_dir=failed_dir, inbox_dir=inbox_dir
        )

    prune_empty_dirs(inbox_dir)
    return processed, len(supported), len(unsupported)
