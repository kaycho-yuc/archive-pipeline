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


def test_weekly_review_links_daily_sessions(tmp_path):
    # 운동리뷰 노트를 쓰면 기간 내 일별 운동 일지 위키링크가 자동 추가된다.
    vault = tmp_path / "vault"
    vault.mkdir()
    personal = vault / "20_Personal" / "2026-Q2"
    personal.mkdir(parents=True)

    # 이전 리뷰 (2026-06-01)와 일별 일지 2개를 미리 만든다.
    prev_review = personal / "2026-06-01 운동일지 (주간 운동 리뷰).md"
    prev_review.write_text("---\ncategory: 운동리뷰\n---\n", encoding="utf-8")
    session_a = personal / "2026-06-02 (화) 7회차 운동 일지.md"
    session_a.write_text("---\ncategory: 운동일지\n---\n내용", encoding="utf-8")
    session_b = personal / "2026-06-04 (목) 8회차 운동 일지.md"
    session_b.write_text("---\ncategory: 운동일지\n---\n내용", encoding="utf-8")
    # 범위 밖(이전 리뷰 이전)은 포함되지 않아야 한다.
    old = personal / "2026-05-07 (목) 1회차 운동 일지.md"
    old.write_text("---\ncategory: 운동일지\n---\n내용", encoding="utf-8")

    review = Classification(
        domain="개인", category="운동리뷰",
        title="2026-06-08 운동리뷰", summary="이번 주 요약.", doc_date="2026-06-08",
    )
    note = write_note(review, "2026-06-08_주간운동리뷰.md", "원문", vault)

    text = note.read_text(encoding="utf-8")
    assert "## 관련 일지" in text
    assert "[[2026-06-02 (화) 7회차 운동 일지]]" in text
    assert "[[2026-06-04 (목) 8회차 운동 일지]]" in text
    assert "[[2026-05-07 (목) 1회차 운동 일지]]" not in text  # 범위 밖


def test_weekly_review_no_links_when_no_sessions(tmp_path):
    # 기간 내 일지가 없으면 관련 일지 섹션을 추가하지 않는다.
    vault = tmp_path / "vault"
    vault.mkdir()
    review = Classification(
        domain="개인", category="운동리뷰",
        title="2026-07-06 운동리뷰", summary="이번 주 요약.", doc_date="2026-07-06",
    )
    note = write_note(review, "2026-07-06_주간운동리뷰.md", "원문", vault)
    assert "## 관련 일지" not in note.read_text(encoding="utf-8")


def test_non_review_note_gets_no_session_links(tmp_path):
    # 운동리뷰가 아닌 노트에는 관련 일지 섹션을 추가하지 않는다.
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "20_Personal" / "2026-Q2").mkdir(parents=True)
    session = vault / "20_Personal" / "2026-Q2" / "2026-06-02 (화) 7회차 운동 일지.md"
    session.write_text("내용", encoding="utf-8")
    note = write_note(RESULT, "meeting.pdf", "원문", vault)
    assert "## 관련 일지" not in note.read_text(encoding="utf-8")


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
