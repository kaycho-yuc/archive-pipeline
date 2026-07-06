"""로컬 RAG(rag_local) 스모크 테스트. Ollama 임베딩/생성은 모킹해 오프라인에서 돈다."""

import pytest

import rag_local

KEYWORDS = ["허가", "운동", "회의"]


def _fake_embed(model, input):
    """키워드 존재 여부를 원-핫 벡터로 인코딩(결정적 최근접 검색용)."""
    vecs = []
    for t in input:
        v = [0.0] * rag_local.EMBED_DIM
        for i, kw in enumerate(KEYWORDS):
            if kw in t:
                v[i] = 1.0
        vecs.append(v)
    return {"embeddings": vecs}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_local, "DB_PATH", tmp_path / "db")
    monkeypatch.setattr(rag_local, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(rag_local, "INCLUDE_DIRS", ("notes",))
    monkeypatch.setattr(rag_local._client, "embed", _fake_embed)
    notes = tmp_path / "vault" / "notes"
    notes.mkdir(parents=True)
    (notes / "허가서.md").write_text(
        "---\ntitle: 성수동 증축 허가 필증\n---\n\n## 원문\n\n건축 허가 관련 내용.\n",
        encoding="utf-8",
    )
    (notes / "운동일지.md").write_text(
        "---\ntitle: 16회차 운동 일지\n---\n\n## 원문\n\n운동 기록.\n", encoding="utf-8"
    )
    (notes / "회의록.md").write_text(
        "---\ntitle: 현장 회의록\n---\n\n## 원문\n\n회의 내용.\n", encoding="utf-8"
    )
    return notes


def test_ingest_and_search(vault):
    stats = rag_local.ingest(reset=True, verbose=False)
    assert stats["added"] == 3
    assert stats["rows"] >= 3

    hits = rag_local.search("허가", k=1)
    assert hits
    assert hits[0]["note_name"] == "허가서.md"


def test_incremental_skips_unchanged(vault):
    rag_local.ingest(reset=True, verbose=False)
    stats = rag_local.ingest(reset=False, verbose=False)
    assert stats["skipped"] == 3
    assert stats["added"] == 0


def test_changed_note_reindexed(vault):
    rag_local.ingest(reset=True, verbose=False)
    (vault / "회의록.md").write_text(
        "---\ntitle: 현장 회의록\n---\n\n## 원문\n\n운동 이야기로 바뀜.\n", encoding="utf-8"
    )
    stats = rag_local.ingest(reset=False, verbose=False)
    assert stats["updated"] == 1
    assert stats["added"] == 0


def test_index_note_adds_and_updates(vault):
    rag_local.ingest(reset=True, verbose=False)
    new = vault / "새노트.md"
    new.write_text("---\ntitle: 새 허가 노트\n---\n\n## 원문\n\n허가 관련.\n", encoding="utf-8")
    assert rag_local.index_note(new) is True
    hits = rag_local.search("허가", k=3)
    assert any(h["note_name"] == "새노트.md" for h in hits)

    # 같은 이름으로 다시 색인하면 중복 없이 갱신된다(청크가 쌓이지 않음).
    tbl = rag_local.connect()
    before = tbl.count_rows()
    rag_local.index_note(new)
    assert tbl.count_rows() == before


def test_index_note_embed_failure_preserves_index(vault, monkeypatch):
    rag_local.ingest(reset=True, verbose=False)
    tbl = rag_local.connect()
    before = tbl.count_rows()
    new = vault / "실패노트.md"
    new.write_text("---\ntitle: 실패\n---\n\n내용.\n", encoding="utf-8")

    def boom(model, input):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(rag_local._client, "embed", boom)
    assert rag_local.index_note(new) is False  # 실패해도 예외 안 던짐
    assert rag_local.connect().count_rows() == before  # 기존 인덱스 보존


def test_chunk_text_prepends_header():
    chunks = rag_local.chunk_text("본문 문단.", "# 제목")
    assert chunks[0].startswith("# 제목")


def test_split_note_exposes_metadata():
    text = "---\ntitle: 허가서\ndoc_date: 2026-05-08\ncategory: 허가서\n---\n\n본문."
    header, body = rag_local._split_note(text, "fallback")
    assert "# 허가서" in header
    assert "날짜 2026-05-08" in header  # 깨끗한 메타데이터가 청크 헤더에 노출됨
    assert body == "본문."


def test_answer_uses_context(vault, monkeypatch):
    rag_local.ingest(reset=True, verbose=False)
    captured = {}

    def fake_chat(model, messages, stream, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return {"message": {"content": "허가는 2026년에 나왔습니다."}}

    monkeypatch.setattr(rag_local._client, "chat", fake_chat)
    ans, names = rag_local.answer("허가 언제 나왔어?", k=1)
    assert "2026" in ans
    assert "허가서.md" in names
    assert "성수동 증축 허가 필증" in captured["prompt"]  # 제목 문맥이 프롬프트에 포함
