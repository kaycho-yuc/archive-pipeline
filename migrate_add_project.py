"""업무 노트(10_Professional)의 frontmatter `project` 를 파일명 기준으로 채우거나 바로잡는다.

각 노트의 `source`(원본 파일명)에서 프로젝트 식별자(지번 등)를 찾아 프로젝트를 판별한다
(classify.detect_project). 식별자가 없으면 기본 프로젝트로 둔다.

- project 가 없으면 판별값(또는 기본값)을 추가한다.
- project 가 있는데 **파일명이 다른 프로젝트를 분명히 가리키면** 그 값으로 바로잡는다.
  (식별자로 확증되지 않으면 기존 값을 존중해 건드리지 않는다 → 손으로 정한 값 보호.)

손으로 쓴 노트도 frontmatter 만 보강하고 본문은 건드리지 않는다.

사용법:
  python migrate_add_project.py            # 미리보기(dry-run) — old→new 전수 출력
  python migrate_add_project.py --execute  # 실제 적용(먼저 백업 zip 생성)
"""

import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from classifier.classify import detect_project

load_dotenv()

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or os.getenv("OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
WORK_DIR = VAULT / "10_Professional"
DEFAULT_PROJECT = os.getenv("DEFAULT_WORK_PROJECT", "성수동 리모델링")


def _backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"vault_backup_{stamp}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in VAULT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(VAULT))
    return dest


def _frontmatter_bounds(lines: list[str]) -> int:
    """여는 --- 다음부터 닫는 --- 의 인덱스를 돌려준다. frontmatter 가 없으면 -1."""
    if not lines or lines[0].strip() != "---":
        return -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return i
    return -1


def _field(lines: list[str], end: int, key: str) -> str | None:
    """frontmatter(1..end) 에서 `key: value` 를 찾아 값을 돌려준다. 없으면 None."""
    for line in lines[1:end]:
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if m:
            return m.group(1).strip()
    return None


def _plan_change(note: Path) -> tuple[str | None, str] | None:
    """이 노트에 필요한 (기존 project, 새 project) 를 돌려준다. 변경 없으면 None."""
    lines = note.read_text(encoding="utf-8").splitlines()
    end = _frontmatter_bounds(lines)
    if end == -1:
        return None  # frontmatter 없는 파일은 건드리지 않는다
    if (_field(lines, end, "domain") or "") != "업무":
        return None  # 업무 노트만 대상
    source = _field(lines, end, "source") or ""
    current = _field(lines, end, "project")  # None = 필드 없음
    detected = detect_project(source)  # 식별자 못 찾으면 ""

    if current is None:
        return (None, detected or DEFAULT_PROJECT)  # 없으면 추가
    if detected and detected != current:
        return (current, detected)  # 파일명이 다른 프로젝트를 확증하면 바로잡음
    return None  # 확증 없으면 기존 값 존중


def _apply(note: Path, new_project: str) -> None:
    """frontmatter 의 project 줄을 교체하거나(있으면) domain 뒤에 삽입한다(없으면)."""
    lines = note.read_text(encoding="utf-8").splitlines()
    end = _frontmatter_bounds(lines)
    for i in range(1, end):
        if lines[i].startswith("project:"):
            lines[i] = f"project: {new_project}"
            break
    else:  # project 줄이 없으면 domain 뒤(없으면 여는 --- 뒤)에 삽입
        insert_at = 1
        for i in range(1, end):
            if lines[i].startswith("domain:"):
                insert_at = i + 1
                break
        lines.insert(insert_at, f"project: {new_project}")
    text = note.read_text(encoding="utf-8")
    note.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")


def main() -> None:
    execute = "--execute" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    notes = sorted(WORK_DIR.rglob("*.md"))
    changes: list[tuple[Path, str | None, str]] = []
    for note in notes:
        plan = _plan_change(note)
        if plan:
            changes.append((note, plan[0], plan[1]))

    print(f"업무 노트 {len(notes)}개 · project 변경 대상 {len(changes)}개")
    for note, old, new in changes:
        label = f"'{old}' → '{new}'" if old is not None else f"(없음) → '{new}'"
        print(f"  · {note.relative_to(VAULT)}: {label}")

    if not changes:
        print("변경할 노트가 없습니다.")
        return
    if not execute:
        print("\n미리보기입니다. 실제 적용하려면 --execute 를 붙이세요.")
        return

    backup = _backup()
    print(f"\n백업 생성: {backup}")
    for note, _old, new in changes:
        _apply(note, new)
    print(f"완료: {len(changes)}개 노트 project 갱신")


if __name__ == "__main__":
    main()
