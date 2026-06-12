"""Classification 결과를 Obsidian 마크다운 노트로 저장하는 모듈."""

import os
import re
from datetime import datetime
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


def _merge_tags(result: Classification) -> list[str]:
    """category 를 첫 태그로 두고 모델이 준 태그를 합친다(공백 제거·중복 제거)."""
    merged: list[str] = []
    for raw in [result.category, *result.tags]:
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
    tags = _merge_tags(result)
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
    return note_path
