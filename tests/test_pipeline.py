import sys

import pytest

import notifier
import pipeline
from classifier.classify import KIND_REFERENCE, Classification


@pytest.fixture(autouse=True)
def _isolate_side_effects(tmp_path, monkeypatch):
    """테스트가 실제 로그 파일을 쓰거나 텔레그램을 호출하지 않도록 격리한다."""
    monkeypatch.setattr(pipeline, "PROCESSING_LOG", tmp_path / "log.csv")
    monkeypatch.setattr(pipeline, "HASH_LOG", tmp_path / "hashes.json")
    monkeypatch.setattr(notifier, "notify", lambda message: False)


def test_process_file_end_to_end(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    vault = tmp_path / "vault"
    archive = tmp_path / "archive"

    source = inbox / "memo.txt"
    source.write_text("회의 내용입니다.", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification("업무", "회의록", "메모", "요약."),
    )

    note_path = pipeline.process_file(source, vault_path=vault, archive_dir=archive)

    assert note_path is not None and note_path.exists()
    assert not source.exists()  # _inbox 에서 사라짐
    assert (archive / "memo.txt").exists()  # _archive 로 이동


def test_process_file_notifies_when_project_unknown(tmp_path, monkeypatch):
    # 업무 문서인데 project 를 못 정했으면(빈 문자열) 사람이 나중에 확인하도록 알린다.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "memo.txt"
    source.write_text("회의 내용입니다.", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification(
            "업무", "회의록", "메모", "요약.", project="", site="아차산로 90"
        ),
    )
    notified = []
    monkeypatch.setattr(pipeline.notifier, "notify", lambda msg: notified.append(msg))

    pipeline.process_file(
        source, vault_path=tmp_path / "v", archive_dir=tmp_path / "a"
    )

    assert len(notified) == 1
    assert "아차산로 90" in notified[0]


def test_process_file_no_notify_when_project_detected(tmp_path, monkeypatch):
    # project 가 판별됐으면 알리지 않는다.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "memo.txt"
    source.write_text("회의 내용입니다.", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification(
            "업무", "회의록", "메모", "요약.", project="성수동 리모델링"
        ),
    )
    notified = []
    monkeypatch.setattr(pipeline.notifier, "notify", lambda msg: notified.append(msg))

    pipeline.process_file(
        source, vault_path=tmp_path / "v", archive_dir=tmp_path / "a"
    )

    assert notified == []


def test_process_file_explodes_msg_attachments(tmp_path, monkeypatch):
    # .msg 는 이메일 노트 1개 + 각 첨부가 독립 노트가 되고, 첨부 노트엔 출처 이메일이 남는다.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    vault = tmp_path / "vault"
    archive = tmp_path / "archive"

    mail = inbox / "mail.msg"
    mail.write_bytes(b"fake-msg-bytes")

    monkeypatch.setattr(pipeline, "INBOX_DIR", inbox)
    monkeypatch.setattr(
        pipeline,
        "msg_attachments",
        lambda path: [("계약서.pdf", b"PDF"), ("내역서.xlsx", b"XLSX")],
    )
    monkeypatch.setattr(pipeline, "extract_text", lambda path: f"내용 {path.name}")

    def _classify(text, source_name=""):
        if source_name.endswith(".msg"):
            return Classification("업무", "공문", "메일 - 김기봉", "요약.")
        return Classification("업무", "계약서", f"문서-{source_name}", "요약.")

    monkeypatch.setattr(pipeline, "classify", _classify)

    note_path = pipeline.process_file(mail, vault_path=vault, archive_dir=archive)

    assert note_path is not None and note_path.exists()  # 이메일 노트
    assert (archive / "mail.msg").exists()  # 이메일 원본 아카이브
    assert (archive / "계약서.pdf").exists()  # 첨부도 처리 후 아카이브
    assert (archive / "내역서.xlsx").exists()

    # 이메일 노트 자신엔 출처 링크가 없고, 첨부 노트엔 출처 이메일 위키링크가 있다.
    assert "source_email:" not in note_path.read_text(encoding="utf-8")
    attachment_notes = [p for p in vault.rglob("*.md") if p != note_path]
    assert len(attachment_notes) == 2
    for note in attachment_notes:
        assert f'source_email: "[[{note_path.stem}]]"' in note.read_text(
            encoding="utf-8"
        )


def test_move_to_times_out_when_move_hangs(tmp_path, monkeypatch):
    # iCloud 동기화로 파일 복사가 멈추는 상황을 흉내내 시간 제한이 동작하는지 본다.
    import time

    src = tmp_path / "stuck.txt"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(pipeline.shutil, "copy2", lambda s, d: time.sleep(5))

    with pytest.raises(TimeoutError):
        pipeline._move_to(src, tmp_path / "archive", timeout=0.5)


def test_move_to_leaves_no_partial_at_final_name(tmp_path, monkeypatch):
    """복사가 도중에 끊겨도 최종 이름엔 잘린 파일이 남으면 안 된다.

    남으면 다음 스윕이 원본을 '중복'으로 보고 -1 을 붙여 넣어, 잘린 파일이 정식 이름을
    차지하고 온전한 원본이 -1 로 밀린다(조용한 아카이브 손상)."""
    from pathlib import Path

    src = tmp_path / "doc.txt"
    src.write_text("온전한 원본", encoding="utf-8")
    archive = tmp_path / "archive"

    def _copy_then_die(source, destination):
        Path(destination).write_text("잘린", encoding="utf-8")
        raise OSError("복사 중 프로세스 중단")

    monkeypatch.setattr(pipeline.shutil, "copy2", _copy_then_die)
    with pytest.raises(OSError):
        pipeline._move_to(src, archive)

    assert not (archive / "doc.txt").exists()  # 최종 이름은 비어 있어야 한다
    assert list(archive.glob("*.part")) == []  # 실패한 조각도 남기지 않는다
    assert src.read_text(encoding="utf-8") == "온전한 원본"  # 원본은 그대로


def test_process_file_defers_on_move_timeout(tmp_path, monkeypatch):
    # 이동이 멈추면(타임아웃) 전체를 실패시키지 않고 '보류'로 넘어가고 알림도 보내지 않는다.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "memo.txt"
    source.write_text("내용 있음", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification(
            "업무", "회의록", "메모", "요약.", project="성수동 리모델링"
        ),
    )

    def _hang(file_path, dest_dir, timeout=pipeline.MOVE_TIMEOUT):
        raise TimeoutError("파일 이동 시간 초과")

    monkeypatch.setattr(pipeline, "_move_to", _hang)

    notified = []
    monkeypatch.setattr(pipeline.notifier, "notify", lambda msg: notified.append(msg))

    note_path = pipeline.process_file(
        source, vault_path=tmp_path / "v", archive_dir=tmp_path / "a", failed_dir=tmp_path / "f"
    )

    assert note_path is None
    assert source.exists()  # _inbox 에 남아 다음 스윕에서 재시도
    assert notified == []  # 보류는 실패 알림을 보내지 않음


def test_prune_empty_dirs_removes_empty_and_junk(tmp_path):
    root = tmp_path / "inbox"
    (root / "empty").mkdir(parents=True)
    (root / "junk_only").mkdir()
    (root / "junk_only" / ".DS_Store").write_text("x", encoding="utf-8")
    (root / "keep").mkdir()
    (root / "keep" / "real.txt").write_text("내용", encoding="utf-8")
    (root / "nested" / "deep").mkdir(parents=True)  # 둘 다 비어 연쇄 제거 대상

    pipeline.prune_empty_dirs(root)

    assert not (root / "empty").exists()
    assert not (root / "junk_only").exists()  # 잔재 파일만 있던 폴더도 제거
    assert not (root / "nested").exists()  # 빈 부모까지 연쇄 제거
    assert (root / "keep" / "real.txt").exists()  # 실제 파일 있는 폴더는 보존
    assert root.exists()  # root 자체는 보존


def test_process_file_quarantines_empty(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    failed = tmp_path / "failed"
    source = inbox / "empty.txt"
    source.write_text("   ", encoding="utf-8")

    note_path = pipeline.process_file(
        source,
        vault_path=tmp_path / "v",
        archive_dir=tmp_path / "a",
        failed_dir=failed,
    )

    assert note_path is None
    assert not source.exists()  # _inbox 에서 빠져 재시도 안 됨
    assert (failed / "empty.txt").exists()  # _failed 로 격리


def test_process_file_quarantines_reference(tmp_path, monkeypatch):
    # 참고자료로 분류되면 노트를 만들지 않고 참고자료 폴더로 격리한다.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    reference = tmp_path / "reference"
    vault = tmp_path / "vault"
    source = inbox / "표준양식.txt"
    source.write_text("빈 표준 도급계약서 양식", encoding="utf-8")

    monkeypatch.setattr(pipeline, "REFERENCE_DIR", reference)
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification(
            "업무", "계약서", "표준양식", "요약.", kind=KIND_REFERENCE
        ),
    )

    note_path = pipeline.process_file(
        source, vault_path=vault, archive_dir=tmp_path / "a", failed_dir=tmp_path / "f"
    )

    assert note_path is None
    assert not source.exists()  # _inbox 에서 빠짐
    assert (reference / "표준양식.txt").exists()  # 참고자료 폴더로 격리
    assert not vault.exists()  # 노트(볼트)는 생성되지 않음


def test_record_unsupported_creates_and_appends_note(tmp_path):
    # 미지원 파일을 노트에 기록하면 표가 생기고, 파일명·확장자·생성/수정일·위치가 들어간다.
    inbox = tmp_path / "inbox"
    (inbox / "sub").mkdir(parents=True)
    vault = tmp_path / "vault"
    drawing = inbox / "sub" / "도면.dwg"
    drawing.write_bytes(b"DWG")

    note = pipeline.record_unsupported(drawing, vault_path=vault, inbox_dir=inbox)

    assert note.name == "미지원_파일_목록.md"
    text = note.read_text(encoding="utf-8")
    assert "| 도면.dwg |" in text
    assert "| .dwg |" in text
    assert "| sub |" in text  # 인박스 내 원래 위치
    assert "_failed |" in text

    # 두 번째 파일은 같은 노트에 줄이 추가되고, 같은 파일은 중복 기록되지 않는다.
    archive = inbox / "묶음.zip"
    archive.write_bytes(b"ZIP")
    pipeline.record_unsupported(archive, vault_path=vault, inbox_dir=inbox)
    pipeline.record_unsupported(drawing, vault_path=vault, inbox_dir=inbox)  # 중복 시도
    text = note.read_text(encoding="utf-8")
    assert text.count("| 도면.dwg |") == 1
    assert "| 묶음.zip |" in text


def test_quarantine_unsupported_records_then_moves(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    vault = tmp_path / "vault"
    failed = tmp_path / "failed"
    archive = inbox / "계약서류.alz"
    archive.write_bytes(b"ALZ")

    ok = pipeline.quarantine_unsupported(
        archive, vault_path=vault, failed_dir=failed, inbox_dir=inbox
    )

    assert ok is True
    assert not archive.exists()  # _inbox 에서 빠짐
    assert (failed / "계약서류.alz").exists()  # _failed 로 격리
    assert "| 계약서류.alz |" in (vault / "미지원_파일_목록.md").read_text(
        encoding="utf-8"
    )


def test_sweep_inbox_processes_supported_and_quarantines_unsupported(
    tmp_path, monkeypatch
):
    # 한 번의 스윕으로 지원 파일은 노트가 되고(아카이브로 이동), 미지원 파일은 _failed 로 격리.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    vault = tmp_path / "vault"
    archive = tmp_path / "archive"
    failed = tmp_path / "failed"

    (inbox / "memo.txt").write_text("회의 내용", encoding="utf-8")
    (inbox / "도면.dwg").write_bytes(b"DWG")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification("업무", "회의록", "메모", "요약."),
    )

    processed, supported, unsupported = pipeline.sweep_inbox(
        vault_path=vault, archive_dir=archive, failed_dir=failed, inbox_dir=inbox
    )

    assert (processed, supported, unsupported) == (1, 1, 1)
    assert (archive / "memo.txt").exists()  # 지원 파일 처리·아카이브
    assert (failed / "도면.dwg").exists()  # 미지원 파일 격리
    assert "| 도면.dwg |" in (vault / "미지원_파일_목록.md").read_text(encoding="utf-8")


def test_process_file_does_not_touch_real_rag_index(tmp_path, monkeypatch):
    """process_file 실행 후 rag_local 이 sys.modules 에 없어야 한다.

    실패하면(rag_local 이 임포트됐다면) conftest.py 의 격리 fixture가 뚫린 것이고,
    실제로는 owner 의 운영 볼트 RAG 인덱스에 이 테스트가 만든 가짜 노트가 쓰였다는 뜻이다."""
    monkeypatch.delitem(sys.modules, "rag_local", raising=False)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "memo.txt"
    source.write_text("회의 내용입니다.", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda text, source_name="": Classification(
            "업무", "회의록", "메모", "요약.", project="성수동 리모델링"
        ),
    )

    note_path = pipeline.process_file(
        source, vault_path=tmp_path / "v", archive_dir=tmp_path / "a"
    )

    assert note_path is not None
    assert "rag_local" not in sys.modules


def test_process_file_quarantines_on_classify_error(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    failed = tmp_path / "failed"
    source = inbox / "memo.txt"
    source.write_text("내용 있음", encoding="utf-8")

    def _boom(text, source_name=""):
        raise ValueError("분류 실패")

    monkeypatch.setattr(pipeline, "classify", _boom)

    note_path = pipeline.process_file(
        source,
        vault_path=tmp_path / "v",
        archive_dir=tmp_path / "a",
        failed_dir=failed,
    )

    assert note_path is None
    assert not source.exists()
    assert (failed / "memo.txt").exists()
