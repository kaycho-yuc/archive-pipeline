import pipeline
from classifier.classify import Classification


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
        lambda text: Classification("업무", "회의록", "메모", "요약."),
    )

    note_path = pipeline.process_file(source, vault_path=vault, archive_dir=archive)

    assert note_path is not None and note_path.exists()
    assert not source.exists()  # _inbox 에서 사라짐
    assert (archive / "memo.txt").exists()  # _archive 로 이동


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


def test_process_file_quarantines_on_classify_error(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    failed = tmp_path / "failed"
    source = inbox / "memo.txt"
    source.write_text("내용 있음", encoding="utf-8")

    def _boom(text):
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
