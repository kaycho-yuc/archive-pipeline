"""기존 업무 노트(10_Professional)를 다시 분류해, '참고자료'로 판정된 노트를
참고자료 검토 폴더로 옮긴다(봇 지식베이스에서 빠지도록).

참고자료 = 빈 양식·표준서식·템플릿, 샘플/예시, 정부·기관 지침/매뉴얼/사례집,
또는 우리 프로젝트가 아닌 다른 현장 문서. 봇이 이런 자료를 실데이터처럼 인용하는
것을 막기 위해 프로젝트 폴더 밖으로 옮긴다.

안전장치: 삭제하지 않고 '이동'만 한다. dry-run 으로 먼저 목록을 확인하고, 사람이
검토한 뒤에만 --execute. 애매한 문서는 분류기가 '프로젝트자료'로 두므로 남는다.

사용법:
  uv run python migrate_classify_reference.py            # 미리보기(dry-run)
  uv run python migrate_classify_reference.py --execute  # 실제 이동(먼저 백업)
"""

import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from classifier.classify import KIND_REFERENCE, classify
from pipeline import REFERENCE_DIR

load_dotenv()

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or os.getenv("OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
WORK_DIR = VAULT / "10_Professional"


def _backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"vault_backup_{stamp}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in VAULT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(VAULT))
    return dest


def _classify_text(note: Path) -> str:
    """노트에서 분류에 쓸 텍스트(원문 우선, 없으면 제목+요약)를 뽑는다."""
    text = note.read_text(encoding="utf-8")
    if "## 원문" in text:
        body = text.split("## 원문", 1)[1].strip()
        if len(body) >= 30:
            return body
    return text  # frontmatter+요약이라도 통째로 넘긴다


def main() -> None:
    execute = "--execute" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    notes = sorted(WORK_DIR.rglob("*.md"))
    print(f"업무 노트 {len(notes)}개를 다시 분류합니다 (시간이 걸립니다)...\n")

    flagged: list[Path] = []
    for i, note in enumerate(notes, 1):
        try:
            kind = classify(_classify_text(note)).kind
        except Exception as e:
            print(f"  [{i}/{len(notes)}] 분류 실패(건너뜀): {note.name} -> {e}")
            continue
        mark = "참고자료 ←격리대상" if kind == KIND_REFERENCE else "프로젝트자료"
        print(f"  [{i}/{len(notes)}] {mark}: {note.name}")
        if kind == KIND_REFERENCE:
            flagged.append(note)

    print(f"\n참고자료로 판정: {len(flagged)}/{len(notes)}개")
    if not flagged:
        print("옮길 노트가 없습니다.")
        return
    if not execute:
        print("\n위 '←격리대상' 목록을 검토하세요. 실제로 옮기려면 --execute 를 붙이세요.")
        print(f"(이동 위치: {REFERENCE_DIR})")
        return

    backup = _backup()
    print(f"\n백업 생성: {backup}")
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    for note in flagged:
        dest = REFERENCE_DIR / note.name
        counter = 1
        while dest.exists():
            dest = REFERENCE_DIR / f"{note.stem}-{counter}{note.suffix}"
            counter += 1
        note.rename(dest)
    print(f"완료: {len(flagged)}개 노트를 참고자료 폴더로 이동")
    print("이제 봇 지식베이스를 다시 적재하세요: uv run python ingest_vault.py (먼저 KB 리셋)")


if __name__ == "__main__":
    main()
