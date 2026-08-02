"""업무 노트(10_Professional)의 frontmatter `project` 를 파일명·본문 기준으로 채우거나 바로잡는다.

각 노트의 `source`(원본 파일명)와 `## 원문` 본문에서 프로젝트 식별자(지번 등)를 찾아
프로젝트를 판별한다(classify.detect_project) — 라이브 파이프라인(`detect_project(source, text)`)과
같은 근거로 판별해야, 파이프라인이라면 잡았을 노트를 마이그레이션이 놓치는 일이 없다.
식별자가 없으면 "미정"으로 남겨 review_pending.py 로 사람이 확정하게 한다
(예전처럼 기본 프로젝트로 조용히 채우지 않는다).

- project 가 없으면 판별값(또는 미정)을 추가한다.
- project 가 있는데 **식별자가 다른 프로젝트를 분명히 가리키면** 그 값으로 바로잡는다.
  (식별자로 확증되지 않으면 기존 값을 존중해 건드리지 않는다 → 손으로 정한 값 보호.)
- `--redetect`: 위 보호를 끄고 업무 노트의 project 를 처음부터 다시 판별한다.
  단, 재판별 대상은 파이프라인이 스스로 만들 수 있었던 값(PROJECT_REGISTRY 등록
  프로젝트, 또는 "미정")뿐이다. 그 밖의 값('기타' 등 사람이 직접 적은 값)은
  건드리지 않는다 — 판별되면 그 값, 안 되면 "미정".

손으로 쓴 노트도 frontmatter 만 보강하고 본문은 건드리지 않는다.

사용법:
  python migrate_add_project.py             # 미리보기(dry-run) — old→new 전수 출력
  python migrate_add_project.py --redetect   # 모든 업무 노트를 처음부터 재판별(미리보기)
  python migrate_add_project.py --execute            # 실제 적용(먼저 백업 zip 생성)
  python migrate_add_project.py --redetect --execute # 재판별 결과를 실제 적용
"""

import os
import re
import sys
import zipfile

# 윈도우에서 stdout 이 파일로 리다이렉트되면 cp949 로 인코딩돼 한글이 깨지므로 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from classifier.classify import PROJECT_REGISTRY, detect_project
from notes.write_note import UNKNOWN_PROJECT

load_dotenv()

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or os.getenv("OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
WORK_DIR = VAULT / "10_Professional"


def _backup(vault: Path = None) -> Path:
    """vault 를 zip 으로 백업한다. 안 주면 이 모듈의 전역 VAULT 를 쓴다.

    review_pending.py 는 자기 VAULT 를 넘겨야 한다 — 안 그러면 review_pending.VAULT 를
    테스트에서 tmp_path 로 monkeypatch 해도 여기선 이 모듈의 실제 VAULT 가 그대로
    쓰여, 테스트용 --fix 실행이 진짜 옵시디언 볼트를 zip 떠버린다."""
    vault = vault or VAULT
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"vault_backup_{stamp}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in vault.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(vault))
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


def _body(text: str) -> str:
    """프로젝트 판별에 쓸 본문만 추출한다(`## 원문` 아래만).

    CRITICAL: 노트 전체 텍스트를 detect_project 에 넘기면 안 된다. frontmatter 에는
    이미 `project: 성수동 리모델링` 이 적혀 있고, '성수동 리모델링' 은 그 자체로 등록된
    프로젝트 식별자이기도 하다. 전체 텍스트를 스캔하면 노트가 이미 달고 있는 라벨과
    스스로 매치되는 순환 논리가 되어 거짓 191/192 결과를 만든다. 그래서
    migrate_revise_notes.py:_body() 와 달리, `## 원문` 섹션이 없거나 너무 짧으면
    전체 텍스트로 폴백하지 않고 빈 문자열을 돌려준다(본문에서는 식별자를 못 찾은 것으로 취급)."""
    if "## 원문" in text:
        body = text.split("## 원문", 1)[1].strip()
        if len(body) >= 30:
            return body
    return ""


def _plan_change(note: Path, redetect: bool = False) -> tuple[str | None, str] | None:
    """이 노트에 필요한 (기존 project, 새 project) 를 돌려준다. 변경 없으면 None.

    redetect=True 면 기존 값 보호(확증 없으면 존중)를 끄고 처음부터 다시 판별한다."""
    text = note.read_text(encoding="utf-8")
    lines = text.splitlines()
    end = _frontmatter_bounds(lines)
    if end == -1:
        return None  # frontmatter 없는 파일은 건드리지 않는다
    if (_field(lines, end, "domain") or "") != "업무":
        return None  # 업무 노트만 대상
    source = _field(lines, end, "source") or ""
    current = _field(lines, end, "project")  # None = 필드 없음
    detected = detect_project(source, _body(text))  # 식별자 못 찾으면 ""

    if current is None:
        return (None, detected or UNKNOWN_PROJECT)  # 없으면 추가

    if redetect:
        # 재판별은 파이프라인이 스스로 만들어낼 수 있었던 값만 덮어쓴다
        # (PROJECT_REGISTRY 의 등록 프로젝트, 또는 미정). 그 밖의 값('기타' 등 사람이
        # 직접 적은 값)은 기계가 준 값이 아니므로 덮어쓸 근거가 없다 — 이걸 어기면
        # 이 변경 세트 전체가 없애려는 조용한 기본값 버그와 같은 종류의 정보 파괴가 된다.
        # 미정은 반드시 포함해야 한다: 나중에 레지스트리가 넓어지면 미정 노트가 다음
        # 실행에서 실제 프로젝트로 승격될 수 있어야 하기 때문(막는 건 강등뿐).
        if current not in PROJECT_REGISTRY and current != UNKNOWN_PROJECT:
            return None
        new = detected or UNKNOWN_PROJECT
        return (current, new) if new != current else None

    if detected and detected != current:
        return (current, detected)  # 식별자가 다른 프로젝트를 확증하면 바로잡음
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
    # --redetect 는 기본 꺼짐이어야 한다: review_pending.py 로 사람이 이미 확정한 노트는
    # 대개 자기 본문에 매칭되는 식별자가 없다 — 바로 그래서 애초에 미정으로 남아 사람이
    # 봐야 했던 것이다. 재판별을 기본으로 켜두면 그런 노트들이 실행할 때마다 다시 미정으로
    # 강등되어 사람의 확정 결정을 조용히 무효화하게 된다. 그래서 명시적 opt-in 으로만 켠다.
    redetect = "--redetect" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    notes = sorted(WORK_DIR.rglob("*.md"))
    changes: list[tuple[Path, str | None, str]] = []
    for note in notes:
        plan = _plan_change(note, redetect)
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
