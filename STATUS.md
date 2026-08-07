# 현재 상태 (스냅샷)

> 작성 기준: 2026-08-08 · 브랜치 `main` (origin 과 동기화, HEAD `e2f3a9f`)
> 이 문서는 짧은 현황 스냅샷이다. 상세 구현 인계는 [SYSTEM-HANDOFF.md](SYSTEM-HANDOFF.md),
> 개념·로드맵은 [ROADMAP.md](ROADMAP.md), 5분 요약은 [OVERVIEW.md](OVERVIEW.md),
> 시행착오 기록은 [learnings/](learnings/), 운영은 `/my-vault` 스킬.

## 한 줄 요약

`_inbox` 에 떨어진 문서를 **추출 → 로컬 LLM 분류·구조화 → Obsidian 노트 생성 → 원본 아카이브**하고,
볼트 전체를 **로컬 RAG**(LanceDB + bge-m3)로 만들어 **텔레그램으로 한국어 질의**까지 하는 개인용 지식관리 파이프라인.
상시 운영 환경은 **Windows 11 + RTX 4080**, 의존성은 **uv**, 처리는 전부 로컬(분류 백엔드로 Gemini 선택 시 예외).

## 구현 완료 · 동작 중

| 영역 | 파일 | 상태 |
|---|---|---|
| 추출 (PDF·이미지 OCR·txt·hwp·hwpx·xlsx·docx·msg·xml) | `extractors/extract.py` | 동작. 스캔 PDF 는 OCR 폴백(이진화 + `--psm 6`) |
| 분류·구조화 (도메인·kind·category·상대방·날짜·태그·제목) | `classifier/classify.py` | 동작. 백엔드 `LLM_PROVIDER`=ollama(기본)/gemini |
| 노트 작성 (10_/20_/90_ + YYYY-QN, frontmatter 태그) | `notes/write_note.py` | 동작 |
| 파이프라인 (중복 SHA-256 · iCloud 하이드레이션 가드 · 참고자료 격리) | `pipeline.py` | 동작 |
| 사람 검토 대기열 (프로젝트 미정·참고자료 판정 확인) | `review_pending.py` · `_review/` | 동작. `/my-vault` 로 확정 |
| 감시 / 일괄 / 스케줄러 진입점 (창 없는 실행·중복 인스턴스 차단) | `watch.py` · `run_once.py` · `run_watch.py` · `run_watch_hidden.vbs` | 동작 |
| 로컬 RAG (적재·검색·답변) | `rag_local.py` · `ingest_vault.py` | 동작 (LanceDB + bge-m3) |
| 볼트를 로컬 에이전트에 노출하는 MCP 서버 | `mcp_server.py` | 동작 |
| 텔레그램 봇 · 실패 알림 · 리소스 모니터 | `telegram_bot.py` · `notifier.py` · `monitor.py` | 동작 |
| 볼트 마이그레이션 (구조 변경·중복 제거) | `migrate_*.py` (`migrate_dedupe_notes.py` 등) | 백업 → dry-run → `--execute` |
| Revit/Enscape 전후 AI 스택 정지·복구 | `pause_ai.ps1` · `resume_ai.ps1` | 동작 |

**테스트: `uv run pytest -q` 기준 109 passed** (이 Mac에서 확인). LLM·OCR·텔레그램은 모킹, RAG 인덱스는 격리(`tests/conftest.py`).

## 핵심 설계

- 분류 백엔드는 `.env` 의 `LLM_PROVIDER` 로 머신별 선택(ollama / gemini). `.env` 는 git 제외.
- 파일명 최우선(filename-first) 분류: 원본 파일명이 유형·상대방·날짜의 최고 권위 근거, 본문 OCR 은 보조.
- 제목은 `compose_title()` 로 결정적 조립(LLM 이 제목 문자열을 직접 만들지 않음).
- **프로젝트는 식별자로 못 찾으면 추측하지 않고 `미정`으로 남긴다**(가짜 채움 금지). 사람이 `_review` 에서 확정한다.
- 참고자료(빈 양식·샘플·정부지침·다른 현장)는 노트로 만들지 않고 격리 → 봇 지식베이스 정확도 보호.
- 중복 판정은 요약이 아니라 **문서 본문**으로 비교한다(요약 노이즈 방지). 처리 실패·빈 텍스트는 `_failed` 격리.
- 볼트 경로는 OS별 자동 선택(`pipeline.py:_resolve_vault_path`), iCloud 온라인 전용 파일은 다운로드 대기 가드.

## 환경 메모

- 상시 운영: Windows 작업 스케줄러가 부팅 시 `run_watch.py`(창 없이) 실행, 중복 인스턴스는 스스로 거부.
- 이 Mac 은 개발·테스트용(uv 로 테스트 통과 확인 가능). Ollama·Tesseract 실호출은 Windows 가 본 무대.
- 로컬 폴백 `vault/`, `.agents/`, `rag_db/`, `.env`, 로그·해시 파일은 gitignore.

## 열린 항목 / 다음

- ROADMAP 참조. 진행 중 조정은 분류 정확도(참고자료·프로젝트 오분류)와 RAG 답변 품질 튜닝, `_review` 대기열 운영.
