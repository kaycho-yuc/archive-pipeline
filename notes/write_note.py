"""Classification 결과를 Obsidian 마크다운 노트로 저장하는 모듈."""

import os
import re
from datetime import date as _Date, datetime
from pathlib import Path

from classifier.classify import Classification

# 파일/폴더 이름에 쓸 수 없는 문자.
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')

# domain 별 최상위 폴더. 세부 분류는 폴더가 아니라 태그로 한다(얕은 시간 기반 구조).
_DOMAIN_FOLDERS = {"업무": "10_Professional", "개인": "20_Personal"}
_FALLBACK_FOLDER = "90_System"

# 업무 노트에는 어떤 프로젝트인지 frontmatter 에 기록한다. 현재는 단일 프로젝트라
# 기본값을 쓰고, 프로젝트가 늘면 분류기에서 추론하도록 확장한다(.env 로 변경 가능).
_WORK_DOMAIN = "업무"
DEFAULT_WORK_PROJECT = os.getenv("DEFAULT_WORK_PROJECT", "성수동 리모델링")


def _sanitize(name: str) -> str:
    """경로 구성요소로 안전한 문자열로 변환한다."""
    cleaned = _INVALID_CHARS.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "무제"


def _quarter(dt: datetime) -> str:
    """날짜를 'YYYY-QN' 분기 문자열로 변환한다."""
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


# 파일명에 이 단어가 들어 있으면 분류 결과와 무관하게 '노트' 태그를 보장한다.
# (진행 노트처럼 직접 만든 파일을 _inbox 에 넣을 때 파일명에 '노트'만 넣으면 됨.)
NOTE_FILENAME_MARKER = "노트"


def _merge_tags(result: Classification, source_name: str | None = None) -> list[str]:
    """category 를 첫 태그로 두고 모델이 준 태그를 합친다(공백 제거·중복 제거).

    source_name(원본 파일명)에 '노트'가 들어 있으면 '노트' 태그를 항상 추가한다."""
    merged: list[str] = []
    raw_tags = [result.category, *result.tags]
    if source_name and NOTE_FILENAME_MARKER in source_name:
        raw_tags.append(NOTE_FILENAME_MARKER)
    for raw in raw_tags:
        tag = re.sub(r"\s+", "-", str(raw).strip()).strip("-#")
        if tag and tag not in merged:
            merged.append(tag)
    return merged


def _format_tags(tags: list[str]) -> str:
    if not tags:
        return "tags: []"
    return "tags:\n" + "\n".join(f"  - {tag}" for tag in tags)


def _unique_path(path: Path) -> Path:
    """같은 이름이 있으면 -1, -2 ... 를 붙여 충돌을 피한다."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _build_markdown(
    result: Classification,
    source_name: str,
    content: str,
    created: datetime,
    origin_email: str | None = None,
) -> str:
    tags = _merge_tags(result, source_name)
    # 업무 노트에만 project 필드를 넣는다(개인 노트엔 의미 없음).
    project_line = (
        f"project: {DEFAULT_WORK_PROJECT}\n" if result.domain == _WORK_DOMAIN else ""
    )
    # 값이 있을 때만 넣는 구조화 필드(기계 파싱용). 비면 생략해 frontmatter 를 깔끔히.
    extra = "".join(
        f"{key}: {value}\n"
        for key, value in (
            ("doc_date", result.doc_date),
            ("counterparty", result.counterparty),
            ("status", result.status),
        )
        if value
    )
    # 이메일 첨부에서 나온 노트면 출처 이메일을 위키링크로 남긴다(옵시디언 백링크 생성).
    email_line = f'source_email: "[[{origin_email}]]"\n' if origin_email else ""
    return f"""---
title: {result.title}
domain: {result.domain}
{project_line}category: {result.category}
{extra}{_format_tags(tags)}
source: {source_name}
{email_line}created: {created.strftime("%Y-%m-%d %H:%M")}
---

## 요약

{result.summary}

## 원문

{content}
"""


_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_DAILY_KEYWORDS = ("운동 일지", "운동일지")


def _stem_date(stem: str) -> _Date | None:
    m = _DATE_PREFIX.match(stem)
    if m:
        try:
            return _Date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _link_daily_sessions(note_path: Path, doc_date: str, vault_path: Path) -> None:
    """주간 운동리뷰 노트 하단에 해당 기간의 회차별 일지 위키링크를 추가한다.

    이전 리뷰 날짜 < 세션 날짜 < 현재 리뷰 날짜 범위의 일지만 연결한다.
    같은 날 세션은 다음 리뷰로 미뤄 이중 링크를 방지한다."""
    try:
        review_date = _Date.fromisoformat(doc_date) if doc_date else None
    except ValueError:
        review_date = None
    if review_date is None:
        review_date = _stem_date(note_path.stem)
    if review_date is None:
        return

    # 이전 운동리뷰 날짜들을 수집한다.
    prev_dates: list[_Date] = []
    for md in vault_path.rglob("*.md"):
        if md == note_path:
            continue
        d = _stem_date(md.stem)
        if d is None or d >= review_date:
            continue
        try:
            if "category: 운동리뷰" in md.read_text(encoding="utf-8", errors="ignore"):
                prev_dates.append(d)
        except Exception:
            pass
    prev_date = max(prev_dates) if prev_dates else _Date(2000, 1, 1)

    # 범위 안의 일별 운동 일지를 찾는다.
    sessions: list[tuple[_Date, str]] = []
    for md in vault_path.rglob("*.md"):
        if md == note_path:
            continue
        stem = md.stem
        if not any(kw in stem for kw in _DAILY_KEYWORDS):
            continue
        d = _stem_date(stem)
        if d is None or not (prev_date <= d < review_date):
            continue
        try:
            if "category: 운동리뷰" in md.read_text(encoding="utf-8", errors="ignore"):
                continue  # 주간 리뷰 노트는 제외
        except Exception:
            pass
        sessions.append((d, stem))

    if not sessions:
        return

    sessions.sort()
    links = "\n".join(f"- [[{stem}]]" for _, stem in sessions)
    section = f"\n## 관련 일지\n\n{links}\n"

    content = note_path.read_text(encoding="utf-8")
    if "## 관련 일지" not in content:
        note_path.write_text(content.rstrip() + section, encoding="utf-8")


def write_note(
    result: Classification,
    source_name: str,
    content: str,
    vault_path: Path,
    origin_email: str | None = None,
) -> Path:
    """볼트 내 {10_/20_ 도메인}/{YYYY-QN}/ 아래에 노트를 저장하고 경로를 반환한다.

    세부 분류는 폴더가 아니라 frontmatter tags 로 한다(검색·RAG 친화적인 얕은 구조).
    origin_email 이 있으면(이메일 첨부에서 나온 노트) 출처 이메일 위키링크를 기록한다.
    """
    created = datetime.now()
    top = _DOMAIN_FOLDERS.get(result.domain, _FALLBACK_FOLDER)
    folder = vault_path / top / _quarter(created)
    folder.mkdir(parents=True, exist_ok=True)

    note_path = _unique_path(folder / f"{_sanitize(result.title)}.md")
    note_path.write_text(
        _build_markdown(result, source_name, content, created, origin_email),
        encoding="utf-8",
    )
    if result.category == "운동리뷰":
        _link_daily_sessions(note_path, result.doc_date, vault_path)
    return note_path
