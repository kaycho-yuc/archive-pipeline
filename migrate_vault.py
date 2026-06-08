"""기존 볼트 노트를 새 구조로 이관한다.

이전:  {업무|개인}/{category}/제목.md  (frontmatter 에 tags 없음)
이후:  {10_Professional|20_Personal}/{YYYY-QN}/제목.md  (frontmatter 에 tags 추가)

기본은 dry-run(미리보기만). 실제 이동은 --execute 를 줘야 하며, 그 전에 볼트
전체를 zip 으로 백업한다. category 는 첫 번째 tag 로 frontmatter 에 추가된다.
"""

import argparse
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline import prune_empty_dirs

load_dotenv()

DOMAIN_FOLDERS = {"업무": "10_Professional", "개인": "20_Personal"}
FALLBACK = "90_System"
TOP_LEVEL = set(DOMAIN_FOLDERS.values()) | {FALLBACK}


def _resolve_vault() -> Path:
    key = "OBSIDIAN_VAULT_PATH_WIN" if os.name == "nt" else "OBSIDIAN_VAULT_PATH_MAC"
    return Path(os.getenv(key) or os.getenv("OBSIDIAN_VAULT_PATH", "vault"))


def _frontmatter(text: str) -> dict:
    """첫 '---' 블록의 단순 key: value 들을 dict 로 읽는다."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    block = text[3 : end if end != -1 else len(text)]
    fm = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def _quarter(created: str, fallback: Path) -> str:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(created.strip(), fmt)
            return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        except (ValueError, AttributeError):
            continue
    dt = datetime.fromtimestamp(fallback.stat().st_mtime)
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def _sanitize_tag(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip()).strip("-#") or "미분류"


def _ensure_tags(text: str, category: str) -> str:
    """frontmatter 에 tags 가 없으면 category 를 첫 태그로 추가한다."""
    if re.search(r"^tags:", text, re.MULTILINE):
        return text
    tag = _sanitize_tag(category)
    lines = text.split("\n")
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith("category:"):
            out.extend(["tags:", f"  - {tag}"])
            inserted = True
    if not inserted:  # category 줄이 없으면 여는 --- 바로 뒤에 넣는다
        out = [lines[0], "tags:", f"  - {tag}"] + lines[1:]
    return "\n".join(out)


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while (parent / f"{stem}-{i}{suffix}").exists():
        i += 1
    return parent / f"{stem}-{i}{suffix}"


def _backup(vault: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path.cwd() / f"vault_backup_{stamp}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in vault.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(vault))
    return dest


def migrate(execute: bool) -> None:
    vault = _resolve_vault()
    if not vault.exists():
        print(f"볼트를 찾을 수 없습니다: {vault}")
        return

    # 파이프라인이 만든 노트만 이관한다(source + 유효 domain). 사용자가 직접 만든
    # 노트(템플릿·일지 등)는 frontmatter 시그니처가 없으므로 건드리지 않는다.
    notes = []
    skipped_handmade = 0
    for p in vault.rglob("*.md"):
        if p.relative_to(vault).parts[0] in TOP_LEVEL:
            continue  # 이미 이관됨
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        if "source" in fm and fm.get("domain") in DOMAIN_FOLDERS:
            notes.append(p)
        else:
            skipped_handmade += 1

    print(f"볼트: {vault}")
    print(f"이관 대상(파이프라인 노트): {len(notes)}개  ({'실행' if execute else 'DRY-RUN'})")
    print(f"보존(직접 만든 노트, 건드리지 않음): {skipped_handmade}개\n")

    if execute and notes:
        backup = _backup(vault)
        print(f"백업 완료: {backup}\n")

    planned = 0
    for src in sorted(notes):
        text = src.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        domain = fm.get("domain", "")
        category = fm.get("category", "미분류")
        top = DOMAIN_FOLDERS.get(domain, FALLBACK)
        quarter = _quarter(fm.get("created", ""), src)
        dest = _unique(vault / top / quarter / src.name)
        rel_src = src.relative_to(vault)
        rel_dest = dest.relative_to(vault)
        print(f"  {rel_src}\n   → {rel_dest}   (+tag: {_sanitize_tag(category)})")
        planned += 1
        if execute:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_ensure_tags(text, category), encoding="utf-8")
            src.unlink()

    print(f"\n총 {planned}개 {'이관 완료' if execute else '이관 예정'}.")
    if execute:
        prune_empty_dirs(vault)
        print("빈 폴더 정리 완료.")
    else:
        print("실제로 옮기려면 --execute 를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="볼트 구조 이관")
    parser.add_argument("--execute", action="store_true", help="실제 이동(기본은 dry-run)")
    args = parser.parse_args()
    migrate(execute=args.execute)
