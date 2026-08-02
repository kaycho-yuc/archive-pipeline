"""MCP 도구 테스트. rag_local 은 모킹해 오프라인·저비용으로 돈다."""

import sys
import types

import pytest

import mcp_server


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "VAULT", tmp_path)
    monkeypatch.setattr(mcp_server, "INCLUDE_DIRS", ("10_Professional", "20_Personal"))
    work = tmp_path / "10_Professional" / "2026-Q1"
    work.mkdir(parents=True)
    (work / "2026-03-01 도급계약서 - 영진건설.md").write_text(
        "---\ntitle: 도급계약서\ndomain: 업무\ncategory: 도급계약서\nproject: 성수동 리모델링\n"
        "doc_date: 2026-03-01\n---\n\n## 요약\n\n해체 및 보강공사 계약.\n",
        encoding="utf-8",
    )
    personal = tmp_path / "20_Personal" / "2026-Q3"
    personal.mkdir(parents=True)
    (personal / "2026-07-28 보고서 (운동일지).md").write_text(
        "---\ntitle: 운동일지\ndomain: 개인\ncategory: 보고서\ndoc_date: 2026-07-28\n---\n\n본문.\n",
        encoding="utf-8",
    )
    (tmp_path / "95_Templates").mkdir()
    (tmp_path / "95_Templates" / "템플릿.md").write_text("---\n---\n템플릿", encoding="utf-8")
    return tmp_path


def test_list_notes_excludes_non_note_folders(vault):
    out = mcp_server.list_notes()
    assert "도급계약서" in out
    assert "운동일지" in out
    assert "템플릿" not in out  # 95_Templates 는 INCLUDE_DIRS 밖


def test_list_notes_filters(vault):
    assert "운동일지" not in mcp_server.list_notes(project="성수동")
    assert "도급계약서" not in mcp_server.list_notes(category="보고서")
    assert "도급계약서" not in mcp_server.list_notes(since="2026-07-01")


def test_list_notes_domain_personal_excludes_work(vault):
    out = mcp_server.list_notes(domain="개인")
    assert "운동일지" in out
    assert "도급계약서" not in out


def test_list_notes_domain_work_excludes_personal(vault):
    out = mcp_server.list_notes(domain="업무")
    assert "도급계약서" in out
    assert "운동일지" not in out


def test_get_note_returns_full_text(vault):
    out = mcp_server.get_note("2026-07-28 보고서 (운동일지)")
    assert "본문." in out


def test_get_note_suggests_candidates_on_partial_name(vault):
    out = mcp_server.get_note("도급계약서")
    assert "후보" in out
    assert "2026-03-01 도급계약서 - 영진건설" in out


def test_get_note_missing(vault):
    assert "찾지 못했습니다" in mcp_server.get_note("없는노트")


def test_search_vault_formats_hits(monkeypatch):
    """search_vault 는 rag_local 을 지연 임포트하므로, 가짜 모듈을 심어 검증한다."""
    fake = types.ModuleType("rag_local")
    fake.search = lambda query, k=5, domain="", project="", category="", since="": [
        {"note_name": "도급계약서", "summary": "해체 공사", "text": "상대 영진건설"}
    ]
    monkeypatch.setitem(sys.modules, "rag_local", fake)
    out = mcp_server.search_vault("685-317 상대 회사")
    assert "도급계약서" in out
    assert "영진건설" in out
    assert "해체 공사" in out


def test_search_vault_forwards_filters(monkeypatch):
    """모든 필터 인자가 rag_local.search 로 그대로 전달돼야 한다(재구현 금지)."""
    received = {}

    def fake_search(query, k=5, domain="", project="", category="", since=""):
        received.update(
            query=query, k=k, domain=domain, project=project, category=category, since=since
        )
        return []

    fake = types.ModuleType("rag_local")
    fake.search = fake_search
    monkeypatch.setitem(sys.modules, "rag_local", fake)
    mcp_server.search_vault(
        "계약", k=3, domain="개인", project="성수동 리모델링", category="도급계약서", since="2026-01-01"
    )
    assert received == {
        "query": "계약",
        "k": 3,
        "domain": "개인",
        "project": "성수동 리모델링",
        "category": "도급계약서",
        "since": "2026-01-01",
    }


def test_search_vault_no_filters_passes_empty_strings(monkeypatch):
    received = {}

    def fake_search(query, k=5, domain="", project="", category="", since=""):
        received.update(domain=domain, project=project, category=category, since=since)
        return []

    fake = types.ModuleType("rag_local")
    fake.search = fake_search
    monkeypatch.setitem(sys.modules, "rag_local", fake)
    mcp_server.search_vault("계약")
    assert received == {"domain": "", "project": "", "category": "", "since": ""}


def test_ask_vault_appends_sources(monkeypatch):
    fake = types.ModuleType("rag_local")
    fake.answer = lambda q: ("영진건설입니다.", ["도급계약서.md"])
    monkeypatch.setitem(sys.modules, "rag_local", fake)
    out = mcp_server.ask_vault("상대 회사는?")
    assert "영진건설입니다." in out
    assert "출처: 도급계약서.md" in out


def test_browse_tools_do_not_import_lancedb(vault, monkeypatch):
    """목록·조회 도구가 rag_local 을 건드리면 세션마다 10초를 낸다 — 그러면 안 된다."""
    monkeypatch.delitem(sys.modules, "rag_local", raising=False)
    mcp_server.list_notes()
    mcp_server.get_note("2026-07-28 보고서 (운동일지)")
    mcp_server.vault_status()
    assert "rag_local" not in sys.modules
