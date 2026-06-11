"""기존 업무 노트(10_Professional)를 새 명명규칙으로 다시 정리한다.

원본 파일명(source)을 최우선 근거로 다시 분류해, 제목을
'YYYY-MM-DD <유형> - <상대방> (<부가, 상태>)' 형식으로 바꾸고 구조화 frontmatter
(doc_date·counterparty·status)를 채운다. 원문(## 원문)·source·created·project 는 보존한다.

안전장치: 삭제 아님(파일명만 변경, 내용 재작성). source 가 남으므로 언제든 재생성 가능.
백업 → dry-run(old→new 제목 미리보기) → 사람이 검토 후에만 --execute.
참고자료로 판정되는 노트는 건드리지 않고 따로 표시만 한다(별도 격리 대상).

사용법:
  uv run python migrate_revise_notes.py            # 미리보기(dry-run)
  uv run python migrate_revise_notes.py --execute  # 실제 적용(먼저 백업)
"""

import json
import os
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# 윈도우에서 stdout 이 파일로 리다이렉트되면 cp949 로 인코딩돼 한글·특수문자에서 깨지므로 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

from classifier.classify import KIND_REFERENCE, Classification, classify
from notes.write_note import _build_markdown, _sanitize, _unique_path

load_dotenv()

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN")
    or os.getenv("OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
WORK_DIR = VAULT / "10_Professional"
# dry-run 이 만든 계획을 저장 → 사람이 검토 후 --execute 가 '같은 결과'를 그대로 적용한다.
_PLAN = Path("_revise_plan.json")


def _frontmatter(text: str) -> dict:
    """노트 상단 frontmatter 에서 key: value 들을 단순 추출한다(목록 제외)."""
    if not text.startswith("---"):
        return {}
    fm = text.split("---", 2)[1]
    out = {}
    for line in fm.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def _body(text: str) -> str:
    """분류에 쓸 본문(## 원문 우선, 없으면 전체)."""
    if "## 원문" in text:
        b = text.split("## 원문", 1)[1].strip()
        if len(b) >= 30:
            return b
    return text


def _created(fm: dict) -> datetime:
    try:
        return datetime.strptime(fm.get("created", ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.now()


def _backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(f"vault_backup_{stamp}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in VAULT.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(VAULT))
    return dest


def _save_plan(plans: list) -> None:
    data = [
        {"path": str(note), "created": created.isoformat(), "source": source,
         "result": asdict(result)}
        for note, result, created, source in plans
    ]
    _PLAN.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _load_plan() -> list:
    out = []
    for e in json.loads(_PLAN.read_text(encoding="utf-8")):
        note = Path(e["path"])
        if note.exists():  # 사이에 사라진 노트는 건너뜀
            out.append((note, Classification(**e["result"]),
                        datetime.fromisoformat(e["created"]), e["source"]))
    return out


def _apply(plans: list) -> None:
    backup = _backup()
    print(f"백업 생성: {backup}")
    changed = 0
    for note, result, created, source in plans:
        body = _body(note.read_text(encoding="utf-8"))
        new_md = _build_markdown(result, source, body, created)
        new_name = f"{_sanitize(result.title)}.md"
        if new_name == note.name:
            note.write_text(new_md, encoding="utf-8")  # 같은 파일명: 내용만 갱신
        else:
            dest = _unique_path(note.parent / new_name)
            dest.write_text(new_md, encoding="utf-8")
            note.unlink()
        changed += 1
    print(f"완료: {changed}개 노트 갱신")
    print("이제 봇 지식베이스를 다시 적재하세요(먼저 KB 리셋): uv run python ingest_vault.py")


def main() -> None:
    execute = "--execute" in sys.argv
    if not WORK_DIR.exists():
        sys.exit(f"업무 폴더가 없습니다: {WORK_DIR}")

    # --execute 인데 검토된 계획 캐시가 있으면, 재분류 없이 '그 결과'를 그대로 적용한다.
    if execute and _PLAN.exists():
        plans = _load_plan()
        print(f"검토된 계획({_PLAN})에서 {len(plans)}개 적용합니다...")
        _apply(plans)
        return

    notes = sorted(WORK_DIR.rglob("*.md"))
    print(f"업무 노트 {len(notes)}개를 다시 분류합니다 (시간이 걸립니다)...\n")

    plans = []  # (note, result, created, source)
    refs = []
    for i, note in enumerate(notes, 1):
        text = note.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        source = fm.get("source", note.stem)
        # 기존 노트 제목을 보조 힌트로 본문 앞에 덧붙인다(파일명이 일반적일 때 유형 보존에 도움).
        # 우선순위는 프롬프트가 정함: 파일명 > 기존 제목 > 본문 OCR.
        hinted = f"[기존 노트 제목: {note.stem}]\n\n{_body(text)}"
        try:
            result = classify(hinted, source_name=source)
        except Exception as e:
            print(f"  [{i}/{len(notes)}] 분류 실패(건너뜀): {note.name} -> {e}")
            continue
        if result.kind == KIND_REFERENCE:
            refs.append(note.name)
            print(f"  [{i}/{len(notes)}] (참고자료?, 변경안함) {note.name}")
            continue
        print(f"  [{i}/{len(notes)}] {note.stem}  →  {result.title}")
        plans.append((note, result, _created(fm), source))

    print(f"\n제목/필드 갱신 대상: {len(plans)}개, 참고자료 의심(미변경): {len(refs)}개")
    if refs:
        print("참고자료로 의심되는 노트(필요하면 따로 격리 검토):")
        for n in refs:
            print(f"  - {n}")

    # 검토할 계획을 캐시에 저장 → 승인 후 --execute 가 같은 결과를 그대로 적용한다.
    _save_plan(plans)
    if not execute:
        print(f"\n위 'old → new' 제목을 검토하세요. 승인하면 --execute 가 {_PLAN} 의 같은 결과를 적용합니다.")
        return
    _apply(plans)


if __name__ == "__main__":
    main()
