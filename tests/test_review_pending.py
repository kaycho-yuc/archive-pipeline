"""review_pending 스모크 테스트. 실제 볼트를 건드리지 않고 tmp_path 로만 검증한다."""

import pytest

import review_pending


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    """review_pending 의 VAULT/WORK_DIR 를 tmp_path 로 돌려, 실제 볼트를 절대 건드리지 않는다."""
    monkeypatch.setattr(review_pending, "VAULT", tmp_path)
    wd = tmp_path / "10_Professional"
    wd.mkdir()
    monkeypatch.setattr(review_pending, "WORK_DIR", wd)
    return wd


def test_find_pending_notes_returns_only_unknown_project(work_dir):
    """미정(未定) 노트만 걸러야 한다 — 프로젝트가 이미 확정된 업무 노트는 대상이 아니다."""
    (work_dir / "미정노트.md").write_text(
        "---\ntitle: 계약서\ndomain: 업무\nproject: 미정\n"
        "site: 종로 306-1\nsource: 계약서.pdf\n---\n\n## 원문\n\n내용.\n",
        encoding="utf-8",
    )
    (work_dir / "확정노트.md").write_text(
        "---\ntitle: 계약서2\ndomain: 업무\nproject: 성수동 리모델링\n"
        "source: 계약서2.pdf\n---\n\n## 원문\n\n내용.\n",
        encoding="utf-8",
    )

    pending = review_pending.find_pending_notes()

    names = {p.path.name for p in pending}
    assert names == {"미정노트.md"}


def test_find_pending_notes_ignores_notes_without_frontmatter(work_dir):
    """frontmatter 없는 손글씨 노트가 섞여 있어도 예외 없이 건너뛰어야 한다."""
    (work_dir / "손글씨.md").write_text("그냥 본문만 있는 노트.\n", encoding="utf-8")
    (work_dir / "미정노트.md").write_text(
        "---\ndomain: 업무\nproject: 미정\nsource: a.pdf\n---\n\n내용.\n", encoding="utf-8"
    )

    pending = review_pending.find_pending_notes()  # 예외 없이 끝나야 함

    assert [p.path.name for p in pending] == ["미정노트.md"]


def test_find_pending_notes_reports_site(work_dir):
    """site 가 있으면 값을 그대로 담고, 없어도 예외 없이 빈 값으로 처리해야 한다."""
    (work_dir / "site있음.md").write_text(
        "---\ndomain: 업무\nproject: 미정\nsite: 강남 123-4\nsource: b.pdf\n---\n\n내용.\n",
        encoding="utf-8",
    )
    (work_dir / "site없음.md").write_text(
        "---\ndomain: 업무\nproject: 미정\nsource: c.pdf\n---\n\n내용.\n", encoding="utf-8"
    )

    pending = review_pending.find_pending_notes()

    by_name = {p.path.name: p for p in pending}
    assert by_name["site있음.md"].site == "강남 123-4"
    assert by_name["site없음.md"].site == ""


def test_strip_site_line_removes_only_frontmatter_line():
    """frontmatter 의 site: 줄만 지우고 나머지는 그대로 남아야 한다."""
    text = (
        "---\ntitle: 계약서\ndomain: 업무\nproject: 미정\n"
        "site: 종로 306-1\nsource: a.pdf\n---\n\n## 원문\n\n내용.\n"
    )
    expected = (
        "---\ntitle: 계약서\ndomain: 업무\nproject: 미정\n"
        "source: a.pdf\n---\n\n## 원문\n\n내용.\n"
    )

    assert review_pending.strip_site_line(text) == expected


def test_strip_site_line_noop_without_site():
    """site: 줄이 애초에 없는 노트는 완전히 손대지 않아야 한다(byte-identical)."""
    text = "---\ntitle: 계약서\ndomain: 업무\nproject: 미정\nsource: a.pdf\n---\n\n내용.\n"

    assert review_pending.strip_site_line(text) == text


def test_strip_site_line_keeps_body_site_line():
    """본문(닫는 --- 아래)에 'site:' 로 시작하는 줄이 있어도 지우면 안 된다.

    frontmatter 를 단순 문자열 치환으로 다루면 이 경우를 깨뜨리기 쉽다 — 반드시
    frontmatter 경계(_frontmatter_bounds) 안에서만 지워야 한다."""
    text = (
        "---\ntitle: 계약서\ndomain: 업무\nproject: 미정\nsource: a.pdf\n---\n\n"
        "## 원문\n\nsite: 이 줄은 본문에 그대로 남아야 한다.\n"
    )

    assert review_pending.strip_site_line(text) == text
