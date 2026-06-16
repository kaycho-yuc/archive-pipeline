from datetime import datetime

from classifier.classify import Classification
from notes.write_note import write_note

RESULT = Classification(
    domain="업무",
    category="회의록",
    title="주간 회의 정리",
    summary="이번 주 진행 상황 요약.",
    tags=["성수동", "공정"],
    counterparty="영진건설",
    doc_date="2026-03-12",
    status="초안",
)

_Q = f"{datetime.now().year}-Q{(datetime.now().month - 1) // 3 + 1}"


def test_write_note_uses_domain_and_quarter_folder(tmp_path):
    path = write_note(RESULT, "meeting.pdf", "원문 내용입니다.", tmp_path)

    assert path == tmp_path / "10_Professional" / _Q / "주간 회의 정리.md"
    text = path.read_text(encoding="utf-8")
    assert "title: 주간 회의 정리" in text
    assert "domain: 업무" in text
    assert "project: 성수동 리모델링" in text  # 업무 노트엔 프로젝트가 들어간다
    assert "doc_date: 2026-03-12" in text  # 구조화 필드(있을 때만)
    assert "counterparty: 영진건설" in text
    assert "status: 초안" in text
    assert "source: meeting.pdf" in text
    # category 가 첫 태그, 모델 태그가 뒤따른다.
    assert "tags:\n  - 회의록\n  - 성수동\n  - 공정" in text
    assert "이번 주 진행 상황 요약." in text
    assert "원문 내용입니다." in text


def test_write_note_records_origin_email_as_wikilink(tmp_path):
    # 이메일 첨부에서 나온 노트면 출처 이메일을 위키링크로 남긴다(옵시디언 백링크).
    path = write_note(
        RESULT, "계약서.pdf", "원문.", tmp_path, origin_email="2026-03-17 공문 - 김기봉"
    )
    assert 'source_email: "[[2026-03-17 공문 - 김기봉]]"' in path.read_text(
        encoding="utf-8"
    )


def test_write_note_omits_origin_email_when_absent(tmp_path):
    path = write_note(RESULT, "meeting.pdf", "원문.", tmp_path)
    assert "source_email:" not in path.read_text(encoding="utf-8")


def test_write_note_adds_note_tag_from_filename(tmp_path):
    # 파일명에 '노트'가 있으면 분류 category 와 무관하게 '노트' 태그가 붙는다.
    path = write_note(RESULT, "2026-06-17 노트 작업진행.txt", "원문.", tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "- 노트" in text


def test_write_note_no_note_tag_without_marker(tmp_path):
    # 파일명에 '노트'가 없으면 추가되지 않는다.
    path = write_note(RESULT, "meeting.pdf", "원문.", tmp_path)
    assert "- 노트" not in path.read_text(encoding="utf-8")


def test_write_note_personal_goes_to_20(tmp_path):
    result = Classification(domain="개인", category="메모", title="생각", summary="s")
    path = write_note(result, "x.txt", "c", tmp_path)
    assert path == tmp_path / "20_Personal" / _Q / "생각.md"
    # 개인 노트엔 project 필드를 넣지 않는다.
    assert "project:" not in path.read_text(encoding="utf-8")


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

    assert path.parent.name == _Q
    assert path.name == "3월 정산.md"
