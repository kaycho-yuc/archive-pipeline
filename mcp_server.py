"""볼트 RAG를 MCP 도구로 노출한다(Claude Code 등 로컬 에이전트용).

설계 원칙 두 가지:

1. **에이전트가 볼트 파일을 직접 읽지 않게 한다.** 볼트 전체는 약 467,000토큰이고 검색 한 번은
   약 530토큰이다. 파일을 뒤지는 것보다 이 도구가 편해야 그 900배 차이를 얻는다.
2. **안 쓰는 세션엔 비용을 물리지 않는다.** `rag_local` 임포트(lancedb+pyarrow)는 이 머신에서
   10초, 89MB다. 그래서 모듈 최상단에서 부르지 않고 실제로 검색하는 도구 안에서만 부른다.
   목록·조회 도구는 파일시스템만 쓰므로 그 10초를 영영 내지 않는다.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv(Path(__file__).parent / ".env")

mcp = MCPServer("vault")

VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH_WIN" if os.name == "nt" else "OBSIDIAN_VAULT_PATH_MAC")
    or os.getenv("OBSIDIAN_VAULT_PATH", "vault")
)
# 노트가 든 폴더만 본다(템플릿·첨부 제외). rag_local.INCLUDE_DIRS 와 같은 값이지만, 이걸
# 읽자고 lancedb 를 끌어오면 위 10초를 내야 해서 여기서 따로 둔다.
INCLUDE_DIRS = ("10_Professional", "20_Personal", "90_System")


def _notes() -> list[Path]:
    return [
        p
        for p in sorted(VAULT.rglob("*.md"))
        if p.relative_to(VAULT).parts[0] in INCLUDE_DIRS
    ]


def _frontmatter(path: Path) -> dict[str, str]:
    """노트 머리말에서 필요한 키만 얕게 읽는다(전체 파싱도, YAML 의존도 불필요)."""
    fields: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            if fh.readline().strip() != "---":
                return fields
            for line in fh:
                line = line.rstrip("\n")
                if line.strip() == "---":
                    break
                if ":" in line and not line.startswith((" ", "-", "\t")):
                    key, _, value = line.partition(":")
                    fields[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return fields


@mcp.tool()
def search_vault(query: str, k: int = 5) -> str:
    """볼트에서 질문과 관련된 노트 조각을 찾는다. 볼트를 볼 일이 있으면 항상 여기서 시작할 것.

    노트 파일을 직접 열거나 폴더를 뒤지지 말 것 — 볼트 전체는 약 467,000토큰이고 이 검색은
    약 530토큰이다. 전문이 꼭 필요할 때만 결과의 노트 이름으로 get_note 를 부른다.
    지번(685-317)·회사명 같은 고유명사에 강한 하이브리드 검색이다.
    """
    import rag_local  # 지연 임포트: 이 도구를 실제로 쓸 때만 lancedb 비용을 낸다

    hits = rag_local.search(query, k=k)
    if not hits:
        return "관련 내용을 찾지 못했습니다."
    out = []
    for h in hits:
        block = f"## {h['note_name']}"
        if h.get("summary"):
            block += f"\n요약: {h['summary']}"
        out.append(f"{block}\n{h['text'].strip()}")
    return "\n\n---\n\n".join(out)


@mcp.tool()
def ask_vault(question: str) -> str:
    """볼트 내용을 근거로 질문에 한국어로 답한다(출처 노트 이름 포함).

    조각을 직접 읽고 판단하고 싶으면 search_vault 를, 답만 필요하면 이걸 쓴다.
    """
    import rag_local  # 지연 임포트

    answer, names = rag_local.answer(question)
    if names:
        answer += "\n\n출처: " + ", ".join(names)
    return answer


@mcp.tool()
def list_notes(
    category: str = "", project: str = "", since: str = "", limit: int = 50
) -> str:
    """조건에 맞는 노트 '제목만' 나열한다(전문 아님). 볼트에 뭐가 있는지 훑을 때.

    category/project 는 부분 일치, since 는 YYYY-MM-DD 이후 문서만. 무엇을 찾을지 모를 땐
    이걸로 범위를 좁힌 뒤 search_vault 를 쓰는 편이 싸다.
    """
    rows = []
    for path in _notes():
        fm = _frontmatter(path)
        if category and category not in fm.get("category", ""):
            continue
        if project and project not in fm.get("project", ""):
            continue
        if since and fm.get("doc_date", "") < since:
            continue
        rows.append((fm.get("doc_date", ""), path.stem, fm.get("category", "")))
    if not rows:
        return "조건에 맞는 노트가 없습니다."
    rows.sort(reverse=True)
    shown = rows[:limit]
    lines = [f"{d or '날짜없음'} | {c or '미분류'} | {n}" for d, n, c in shown]
    tail = f"\n... 외 {len(rows) - len(shown)}개" if len(rows) > len(shown) else ""
    return f"{len(rows)}개 중 {len(shown)}개:\n" + "\n".join(lines) + tail


@mcp.tool()
def get_note(name: str) -> str:
    """노트 하나의 전문을 읽는다(약 1,900토큰). search_vault 조각으로 부족할 때만 쓸 것.

    name 은 search_vault/list_notes 가 돌려준 노트 이름(확장자 없이)이다.
    """
    matches = [p for p in _notes() if p.stem == name]
    if not matches:  # 정확히 안 맞으면 부분 일치로 후보를 알려준다
        near = [p.stem for p in _notes() if name in p.stem][:10]
        if not near:
            return f"'{name}' 노트를 찾지 못했습니다."
        return "정확히 일치하는 노트가 없습니다. 후보:\n" + "\n".join(near)
    return matches[0].read_text(encoding="utf-8", errors="ignore")


@mcp.tool()
def vault_status() -> str:
    """볼트 규모와 색인 시각을 알려준다(문제 진단용)."""
    notes = _notes()
    newest = max((p.stat().st_mtime for p in notes), default=0)
    from datetime import datetime

    return (
        f"볼트: {VAULT}\n노트 {len(notes)}개\n"
        f"최근 수정: {datetime.fromtimestamp(newest):%Y-%m-%d %H:%M}\n"
        f"오늘: {date.today()}"
    )


if __name__ == "__main__":
    mcp.run()
