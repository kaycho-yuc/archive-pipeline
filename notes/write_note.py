"""Classification 결과를 Obsidian 마크다운 노트로 저장하는 모듈."""

import re
from datetime import datetime
from pathlib import Path

from classifier.classify import Classification

# 파일/폴더 이름에 쓸 수 없는 문자.
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str) -> str:
    """경로 구성요소로 안전한 문자열로 변환한다."""
    cleaned = _INVALID_CHARS.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "무제"


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


def _build_markdown(result: Classification, source_name: str, content: str) -> str:
    created = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""---
title: {result.title}
domain: {result.domain}
category: {result.category}
source: {source_name}
created: {created}
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
    """볼트 내 {domain}/{category}/ 아래에 노트를 저장하고 경로를 반환한다."""
    folder = vault_path / _sanitize(result.domain) / _sanitize(result.category)
    folder.mkdir(parents=True, exist_ok=True)

    note_path = _unique_path(folder / f"{_sanitize(result.title)}.md")
    note_path.write_text(
        _build_markdown(result, source_name, content), encoding="utf-8"
    )
    return note_path
