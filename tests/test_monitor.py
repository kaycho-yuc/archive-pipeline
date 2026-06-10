import csv

import monitor


def test_sample_row_shape():
    row = monitor.sample_row()
    assert len(row) == len(monitor._HEADER)
    # 램 사용량/전체는 항상 숫자여야 한다 (GPU·ollama 는 환경에 따라 빈 값 허용)
    assert float(row[1]) > 0
    assert float(row[2]) > 0
    assert 0 <= float(row[3]) <= 100


def test_append_and_trim(tmp_path, monkeypatch):
    log = tmp_path / "resource_log.csv"
    monkeypatch.setattr(monitor, "RESOURCE_LOG", log)

    monitor._append_row(["t", "1", "2", "3", "", "", "", ""])
    monitor._append_row(["t", "1", "2", "3", "", "", "", ""])
    with log.open(encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == monitor._HEADER
    assert len(rows) == 3

    # MAX_ROWS 를 작게 줄여 절반만 남기는 동작 확인
    monkeypatch.setattr(monitor, "MAX_ROWS", 3)
    monitor._trim_log()
    lines = log.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("time")  # 헤더 보존
    assert len(lines) <= 3
