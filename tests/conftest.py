"""전역 테스트 격리: 어떤 테스트도 실제 RAG 인덱스·임베딩 API에 닿지 못하게 한다.

배경: pipeline.process_file 은 내부에서 _index_note_best_effort 를 통해 rag_local 을
지연 임포트해 rag_local.index_note(path) 를 호출한다. 이 모듈을 모킹하지 않은 테스트가
있으면(과거 tests/test_pipeline.py 가 그랬다), rag_local.DB_PATH 가 owner 의 실제
LanceDB 인덱스(운영 볼트)를 가리키기 때문에 pytest 를 돌릴 때마다 가짜 노트("메모.md" 등
테스트 픽스처 이름)가 운영 인덱스에 그대로 기록된다. 그 유령 노트는 텔레그램 봇과 MCP
search_vault 가 실제 출처인 것처럼 인용할 수 있고, 색인 과정에서 실제 Gemini 임베딩
API 호출까지 발생한다(watch.py 의 시간별 재색인이 유령을 지워주긴 하지만, 그때까지 최대
1시간의 노출 창이 생긴다).

이 fixture 는 테스트를 작성하는 사람이 매번 rag_local 을 모킹하는 걸 잊어도 구조적으로
안전하도록, 모든 테스트에 autouse 로 적용된다:
- RAG_BACKEND 를 local 이 아닌 값으로 바꿔 _index_note_best_effort(pipeline.py)와
  watch.py 의 동일한 가드가 조기 반환하게 한다.
- RAG_DB_PATH 를 tmp_path 아래로 돌려, 가드를 우회해 rag_local 이 나중에 새로
  임포트되더라도 모듈 최상단에서 계산되는 DB_PATH 가 디스크 위 임시 경로를 가리키게 한다.
- rag_local 이 이미 sys.modules 에 있다면(다른 테스트가 먼저 임포트해둔 경우), DB_PATH 는
  임포트 시점에 이미 계산되어 있으므로 환경변수만으론 부족하다 — 로드된 모듈 객체의
  DB_PATH 속성도 함께 tmp_path 로 바꿔준다.

주의: 여기서 rag_local 을 직접 import 하지 않는다. lancedb 임포트 비용이 세션당 약 10초
들고, tests/test_mcp_server.py 의 test_browse_tools_do_not_import_lancedb 가 그 비용이
불필요하게 발생하지 않는지 감시하고 있다.

이 파일을 지우고 싶어질 수도 있는데, 지우면 다시 owner 의 운영 볼트에 테스트 노트가
쌓이기 시작한다는 뜻이다.
"""

import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_rag(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "test")
    monkeypatch.setenv("RAG_DB_PATH", str(tmp_path / "rag_db"))

    rag_local = sys.modules.get("rag_local")
    if rag_local is not None:
        monkeypatch.setattr(rag_local, "DB_PATH", tmp_path / "rag_db")
