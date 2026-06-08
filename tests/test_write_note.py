from classifier.classify import Classification
from notes.write_note import write_note

RESULT = Classification(
    domain="업무",
    category="회의록",
    title="주간 회의 정리",
    summary="이번 주 진행 상황 요약.",
)


def test_write_note_creates_file_in_domain_category(tmp_path):
    path = write_note(RESULT, "meeting.pdf", "원문 내용입니다.", tmp_path)

    assert path == tmp_path / "업무" / "회의록" / "주간 회의 정리.md"
    text = path.read_text(encoding="utf-8")
    assert "title: 주간 회의 정리" in text
    assert "domain: 업무" in text
    assert "source: meeting.pdf" in text
    assert "이번 주 진행 상황 요약." in text
    assert "원문 내용입니다." in text


def test_write_note_avoids_collision(tmp_path):
    first = write_note(RESULT, "a.pdf", "A", tmp_path)
    second = write_note(RESULT, "b.pdf", "B", tmp_path)

    assert first != second
    assert second.name == "주간 회의 정리-1.md"


def test_write_note_sanitizes_invalid_chars(tmp_path):
    result = Classification(
        domain="개인", category="영수증/카드", title="3월: 정산?", summary="s"
    )
    path = write_note(result, "x.txt", "c", tmp_path)

    assert path.parent.name == "영수증카드"
    assert path.name == "3월 정산.md"
