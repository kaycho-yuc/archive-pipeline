"""수기 운동일지 노트를 우리 frontmatter 스키마에 맞춰 20_Personal 로 이관한다.

운동일지는 frontmatter 가 없는 손으로 쓴 노트라, 본문은 그대로 두고 위에
title/domain/category/tags/source/created 블록만 덧붙인 뒤 새 구조로 옮긴다.
본문 안의 인라인 해시태그(#육아스트렝스 등)를 tags 로 수집한다.

기본은 dry-run. --execute 로만 실제 이동(템플릿 파일은 건드리지 않는다).
"""

import argparse
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_INVALID = re.compile(r'[\\/:*?"<>|]')
_HASHTAG = re.compile(r"#(\w[\w가-힣]*)")


def _resolve_vault() -> Path:
    key = "OBSIDIAN_VAULT_PATH_WIN" if os.name == "nt" else "OBSIDIAN_VAULT_PATH_MAC"
    return Path(os.getenv(key) or os.getenv("OBSIDIAN_VAULT_PATH", "vault"))


def _sanitize(name: str) -> str:
    cleaned = _INVALID.sub("", name).strip()
    return re.sub(r"\s+", " ", cleaned) or "무제"


def _date_from(name: str, fallback: Path) -> datetime:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return datetime.fromtimestamp(fallback.stat().st_mtime)


def _title_from(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            return re.sub(r"^#+\s*", "", line).replace("📅", "").strip() or fallback
    return fallback


def _collect_tags(category: str, body: str) -> list[str]:
    tags: list[str] = []
    for raw in [category, *_HASHTAG.findall(body)]:
        tag = re.sub(r"\s+", "-", str(raw).strip()).strip("-#")
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:8]


def _frontmatter(title, category, tags, source, created) -> str:
    tag_lines = "\n".join(f"  - {t}" for t in tags) if tags else ""
    tags_block = f"tags:\n{tag_lines}" if tags else "tags: []"
    return (
        "---\n"
        f"title: {title}\n"
        "domain: 개인\n"
        f"category: {category}\n"
        f"{tags_block}\n"
        f"source: {source}\n"
        f"created: {created.strftime('%Y-%m-%d %H:%M')}\n"
        "---\n\n"
    )


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while (path.parent / f"{path.stem}-{i}{path.suffix}").exists():
        i += 1
    return path.parent / f"{path.stem}-{i}{path.suffix}"


def migrate(execute: bool) -> None:
    vault = _resolve_vault()
    src_dir = vault / "개인" / "운동일지"
    notes = sorted(src_dir.glob("*.md")) if src_dir.exists() else []
    print(f"볼트: {vault}")
    print(f"운동일지 이관 대상: {len(notes)}개  ({'실행' if execute else 'DRY-RUN'})")
    print("템플릿(운동일지_템플릿.md)은 templates/ 에 그대로 둡니다.\n")

    for src in notes:
        body = src.read_text(encoding="utf-8")
        if body.startswith("---"):
            print(f"  건너뜀(이미 frontmatter 있음): {src.name}")
            continue
        created = _date_from(src.name, src)
        quarter = f"{created.year}-Q{(created.month - 1) // 3 + 1}"
        category = "운동리뷰" if "리뷰" in src.name else "운동일지"
        title = _title_from(body, src.stem)
        tags = _collect_tags(category, body)
        dest = _unique(vault / "20_Personal" / quarter / f"{_sanitize(title)}.md")
        print(f"  {src.relative_to(vault)}")
        print(f"   → {dest.relative_to(vault)}")
        print(f"     tags: {', '.join(tags)}")
        if execute:
            dest.parent.mkdir(parents=True, exist_ok=True)
            new_text = _frontmatter(title, category, tags, src.name, created) + body
            dest.write_text(new_text, encoding="utf-8")
            src.unlink()

    print(f"\n{'이관 완료' if execute else '이관 예정'}: {len(notes)}개")
    if not execute:
        print("실제로 옮기려면 --execute 를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="운동일지 이관")
    parser.add_argument("--execute", action="store_true")
    migrate(execute=parser.parse_args().execute)
