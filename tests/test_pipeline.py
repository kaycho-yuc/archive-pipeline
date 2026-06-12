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
