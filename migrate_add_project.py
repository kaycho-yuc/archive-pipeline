"""기존 업무 노트(10_Professional)의 frontmatter 에 project 필드를 채운다.

현재 모든 업무 노트는 '성수동 리모델링' 프로젝트이므로 기본값을 넣는다.
이미 project 가 있는 노트는 건너뛴다. 손으로 쓴 노트도 frontmatter 만 보강하고
본문은 건드리지 않는다.

사용법:
  python migrate_add_project.py            # 미리보기(dry-run)
  python migrate_add_project.py --execute  # 실제 적용(먼저 백업 zip 생성)
"""

import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or os.getenv("OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
WORK_DIR = VAULT / "10_Professional"
PROJECT = os.getenv("DEFAULT_WORK_PROJECT", "성수동 리모델링")


def _backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"vault_backup_{stamp}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in VAULT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(VAULT))
    return dest


def _needs_project(lines: list[str]) -> bool:
    """frontmatter(--- ... ---) 안에 project 키가 없으면 True."""
    if not lines or lines[0].strip() != "---":
        return False  # frontmatter 가 없는 파일은 건드리지 않는다
    for line in lines[1:]:
        if line.strip() == "---":
            return True  # frontmatter 끝까지 project 가 없었음
        if line.startswith("project:"):
            return False
    return False  # 닫는 --- 가 없는 비정상 파일은 건너뜀


def _insert_project(text: str) -> str:
    """frontmatter 의 domain 줄 뒤(없으면 여는 --- 뒤)에 project 줄을 끼운다."""
    lines = text.splitlines()
    insert_at = 1  # 기본: 여는 --- 바로 다음
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
        if line.startswith("domain:"):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"project: {PROJECT}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def main() -> None:
    execute = "--execute" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    targets = []
    for note in sorted(WORK_DIR.rglob("*.md")):
        if _needs_project(note.read_text(encoding="utf-8").splitlines()):
            targets.append(note)

    total = len(list(WORK_DIR.rglob("*.md")))
    print(f"업무 노트 {total}개 중 project 추가 대상: {len(targets)}개 (프로젝트='{PROJECT}')")
    for note in targets:
        print(f"  + {note.relative_to(VAULT)}")

    if not targets:
        print("추가할 노트가 없습니다.")
        return
    if not execute:
        print("\n미리보기입니다. 실제 적용하려면 --execute 를 붙이세요.")
        return

    backup = _backup()
    print(f"\n백업 생성: {backup}")
    for note in targets:
        note.write_text(_insert_project(note.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"완료: {len(targets)}개 노트에 project 추가")


if __name__ == "__main__":
    main()
