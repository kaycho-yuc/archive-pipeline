"""project 가 미정(未定)으로 남은 업무 노트를 사람이 한 건씩 확정하는 검토 도구.

분류기가 파일명·본문에서 등록된 프로젝트 식별자를 못 찾으면 노트는 project: 미정 로
저장되고, 대신 문서에서 읽은 현장 표기를 site: 줄에 남긴다(classifier.classify.detect_project,
notes.write_note 참고). 이 스크립트는 그렇게 쌓인 미정 노트를 모아 보여주고,
--fix 모드에서는 하나씩 프로젝트를 확정받아 frontmatter 를 고친 뒤 obsolete 해진
site: 줄을 지우고 로컬 RAG 색인을 갱신한다.

frontmatter 조작(_frontmatter_bounds·_field·_apply)과 백업(_backup)은
migrate_add_project.py 것을 그대로 재사용한다.

사용법:
  python review_pending.py         # 미정 노트 목록만 출력(변경 없음)
  python review_pending.py --fix   # 하나씩 확정 → 백업 → 일괄 적용 → 재색인
"""

import sys

# 윈도우에서 stdout 이 파일로 리다이렉트되면 cp949 로 인코딩돼 한글이 깨지므로 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dataclasses import dataclass
from pathlib import Path

from classifier.classify import PROJECT_REGISTRY
from migrate_add_project import VAULT, WORK_DIR, _apply, _backup, _field, _frontmatter_bounds
from notes.write_note import UNKNOWN_PROJECT

_NO_SITE = "(없음)"  # site 필드가 없을 때 표시용 마커


@dataclass
class PendingNote:
    """미정 노트 한 건 — 경로·원본 파일명(source)·문서에서 읽은 현장 표기(site)."""

    path: Path
    source: str
    site: str


def find_pending_notes() -> list[PendingNote]:
    """WORK_DIR 아래에서 project 가 미정(UNKNOWN_PROJECT)인 노트를 모두 찾는다.

    frontmatter 가 없는 파일은 조용히 건너뛴다(예외 없음). project 필드가 있는데
    값이 미정이 아니면(이미 확정된 노트) 대상에서 제외한다."""
    pending: list[PendingNote] = []
    for note in sorted(WORK_DIR.rglob("*.md")):
        lines = note.read_text(encoding="utf-8").splitlines()
        end = _frontmatter_bounds(lines)
        if end == -1:
            continue  # frontmatter 없는 파일은 대상 아님
        if _field(lines, end, "project") != UNKNOWN_PROJECT:
            continue  # 이미 확정됐거나 업무 노트가 아님
        source = _field(lines, end, "source") or ""
        site = _field(lines, end, "site") or ""
        pending.append(PendingNote(note, source, site))
    return pending


def strip_site_line(text: str) -> str:
    """frontmatter 안의 site: 줄만 제거한다. 본문(닫는 --- 아래)의 동일 문구는 건드리지 않는다.

    site: 줄이 없으면(이미 없거나 애초에 없던 노트) 입력을 그대로 돌려준다.
    trailing newline 유지 방식은 migrate_add_project._apply 와 동일하다."""
    lines = text.splitlines()
    end = _frontmatter_bounds(lines)
    if end == -1:
        return text  # frontmatter 없으면 손대지 않는다
    for i in range(1, end):
        if lines[i].startswith("site:"):
            del lines[i]
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text  # site: 줄이 없으면 그대로


def _reindex_best_effort(path: Path) -> bool:
    """노트를 로컬 RAG 인덱스에 반영한다(best-effort, pipeline._index_note_best_effort 와 동일 관례).

    rag_local 은 다른 세션이 한창 고치고 있어 임포트·임베딩 차원이 언제든 어긋날 수
    있으므로 여기서 지연 임포트하고, 무엇이 실패하든 경고만 찍고 계속 진행한다.
    frontmatter 수정은 이미 끝난 뒤라 색인 실패로 그 결과를 잃지 않는다."""
    try:
        import rag_local

        return rag_local.index_note(path)
    except Exception as error:
        print(f"  ! 재색인 건너뜀({path.name}): {error}")
        return False


def _collect_decisions(pending: list[PendingNote]) -> list[tuple[PendingNote, str]]:
    """미정 노트를 하나씩 보여주고 확정할 프로젝트를 물어 결정 목록을 만든다.

    이 단계에서는 아무 파일도 건드리지 않는다(결정만 모은다). 'q' 를 입력하면
    그때까지 모은 결정만 가지고 즉시 멈춘다."""
    options = sorted(PROJECT_REGISTRY)
    decisions: list[tuple[PendingNote, str]] = []
    for i, note in enumerate(pending, 1):
        print(f"\n[{i}/{len(pending)}] {note.path.relative_to(VAULT)}")
        print(f"  source: {note.source}")
        print(f"  site: {note.site or _NO_SITE}")
        for n, name in enumerate(options, 1):
            print(f"  {n}) {name}")
        print("  s) 건너뛰기")
        print("  q) 종료")
        print("  (목록에 없는 프로젝트면 .env WORK_PROJECTS 에 등록하고 다시 실행하세요)")
        choice = input("선택 > ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            decisions.append((note, options[int(choice) - 1]))
        else:
            print("  알 수 없는 선택, 건너뜁니다.")
    return decisions


def main() -> None:
    fix = "--fix" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    pending = find_pending_notes()

    if not fix:
        print(f"프로젝트 미정 노트 {len(pending)}개")
        for note in pending:
            print(f"  · {note.path.relative_to(VAULT)}")
            print(f"      source: {note.source}")
            print(f"      site: {note.site or _NO_SITE}")
        if not pending:
            print("미정 노트가 없습니다.")
        return

    if not pending:
        print("미정 노트가 없습니다.")
        return

    decisions = _collect_decisions(pending)
    if not decisions:
        print("\n확정한 노트가 없습니다.")
        return

    print(f"\n다음 {len(decisions)}개 노트에 project 를 적용합니다:")
    for note, project in decisions:
        print(f"  · {note.path.relative_to(VAULT)}: '{project}'")
    answer = input("계속할까요? (y/N): ").strip().lower()
    if answer != "y":
        print("취소했습니다.")
        return

    # migrate_add_project._backup 은 인자가 없으면 그 모듈의 전역 VAULT 를 쓴다.
    # 여기 VAULT(이 파일의 것)를 명시적으로 넘겨야 테스트에서 monkeypatch 한 값이
    # 실제로 반영된다(안 그러면 테스트 --fix 가 진짜 볼트를 zip 뜬다).
    backup = _backup(VAULT)
    print(f"\n백업 생성: {backup}")

    updated = 0
    indexed = 0
    for note, project in decisions:
        _apply(note.path, project)
        text = note.path.read_text(encoding="utf-8")
        note.path.write_text(strip_site_line(text), encoding="utf-8")
        updated += 1
        if _reindex_best_effort(note.path):
            indexed += 1

    print(f"완료: {updated}개 노트 갱신, {indexed}개 재색인")


if __name__ == "__main__":
    main()
