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


def test_process_file_skips_empty(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "empty.txt"
    source.write_text("   ", encoding="utf-8")

    note_path = pipeline.process_file(
        source, vault_path=tmp_path / "v", archive_dir=tmp_path / "a"
    )

    assert note_path is None
    assert source.exists()  # 실패 시 원본 보존
