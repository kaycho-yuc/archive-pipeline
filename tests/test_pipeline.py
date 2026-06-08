import pytest

import notifier
import pipeline
from classifier.classify import Classification


@pytest.fixture(autouse=True)
def _isolate_side_effects(tmp_path, monkeypatch):
    """테스트가 실제 로그 파일을 쓰거나 텔레그램을 호출하지 않도록 격리한다."""
    monkeypatch.setattr(pipeline, "PROCESSING_LOG", tmp_path / "log.csv")
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
        lambda text: Classification("업무", "회의록", "메모", "요약."),
    )

    note_path = pipeline.process_file(source, vault_path=vault, archive_dir=archive)

    assert note_path is not None and note_path.exists()
    assert not source.exists()  # _inbox 에서 사라짐
    assert (archive / "memo.txt").exists()  # _archive 로 이동


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
