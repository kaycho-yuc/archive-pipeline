"""Classification 결과를 Obsidian 마크다운 노트로 저장하는 모듈."""

import re
from datetime import datetime
from pathlib import Path

from classifier.classify import Classification

# 파일/폴더 이름에 쓸 수 없는 문자.
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')

# domain 별 최상위 폴더. 세부 분류는 폴더가 아니라 태그로 한다(얕은 시간 기반 구조).
_DOMAIN_FOLDERS = {"업무": "10_Professional", "개인": "20_Personal"}
_FALLBACK_FOLDER = "90_System"


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
    result: Classification, source_name: str, content: str, created: datetime
) -> str:
    tags = _merge_tags(result)
    return f"""---
title: {result.title}
domain: {result.domain}
category: {result.category}
{_format_tags(tags)}
source: {source_name}
created: {created.strftime("%Y-%m-%d %H:%M")}
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
) -> Path:
    """볼트 내 {10_/20_ 도메인}/{YYYY-QN}/ 아래에 노트를 저장하고 경로를 반환한다.

    세부 분류는 폴더가 아니라 frontmatter tags 로 한다(검색·RAG 친화적인 얕은 구조).
    """
    created = datetime.now()
    top = _DOMAIN_FOLDERS.get(result.domain, _FALLBACK_FOLDER)
    folder = vault_path / top / _quarter(created)
    folder.mkdir(parents=True, exist_ok=True)

    note_path = _unique_path(folder / f"{_sanitize(result.title)}.md")
    note_path.write_text(
        _build_markdown(result, source_name, content, created), encoding="utf-8"
    )
    return note_path
