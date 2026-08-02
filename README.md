# Archive Pipeline

`_inbox`에 넣은 파일을 **추출 → 로컬 LLM(Ollama) 분류·요약 → Obsidian 볼트에 노트로 저장 → 원본 아카이브**하고,
볼트 전체를 **로컬 RAG**로 만들어 **텔레그램으로 한국어 질문**까지 할 수 있는 개인용 지식관리 파이프라인.
모든 처리는 PC 안에서만 일어난다(클라우드 LLM 미사용).

> **🛠 운영은 한 단어로:** Claude Code에서 **`/my-vault`** 를 입력하면 상태 점검·봇 동기화·
> 프로젝트 추가·멈춤 진단 메뉴가 뜬다. 외워둘 필요 없이 `/` 만 쳐도 목록에 보인다.
>
> **문서 안내**
> - [OVERVIEW.md](OVERVIEW.md) — 5분 요약(개념·구조·기술스택). 남에게 보여줄 때.
> - [ROADMAP.md](ROADMAP.md) — 개념·의사결정 기록·앞으로 할 일(로드맵).
> - [SYSTEM-HANDOFF.md](SYSTEM-HANDOFF.md) — 현재 구현 상태 상세(기술 인계).
> - [archive-pipeline-handoff.md](archive-pipeline-handoff.md) — 최초 RAG 설계 구상.

## 데이터 흐름

```
_inbox(iCloud) ──감시──► 중복검사(SHA-256) → 텍스트 추출 → LLM 분류·요약
                         → Obsidian 노트 작성(태그 + 업무는 project) → 원본 _archive 이동
                                            │
                         볼트 ──► 로컬 RAG(LanceDB + bge-m3) ──► 텔레그램 봇(한국어 질의)
```

## 구조

```
extractors/extract.py   # PDF/이미지(OCR)/텍스트/HWP/HWPX 추출 (스캔본 OCR 폴백 포함)
classifier/classify.py  # Ollama로 개인·업무 분류 + 카테고리 + 태그 + 요약
notes/write_note.py     # 볼트 10_/20_/90_ + YYYY-QN 폴더에 태그 기반 노트 저장
pipeline.py             # 추출→분류→저장→아카이브 (파일 1개) + iCloud 하이드레이션 가드
monitor.py              # 리소스(RAM/CPU/GPU/로드모델) 블랙박스 로깅
rag_local.py            # 로컬 RAG: 볼트를 bge-m3로 임베딩→LanceDB 저장·검색(Docker 불필요)
telegram_bot.py         # 볼트 RAG에 텔레그램으로 질의(허가된 사용자만)
notifier.py             # 실패 시 텔레그램 알림
watch.py / run_once.py  # _inbox 상시 감시 / 일괄 처리
run_watch.py            # 작업 스케줄러 진입점(감시기+모니터+봇 동시 기동)
ingest_vault.py         # 볼트 .md 노트를 RAG 인덱스에 적재(기본 local, --backend openwebui 선택)
bench_models.py         # 여러 LLM을 같은 RAG 질문으로 비교(모델 선택용)
review_pending.py       # project 가 '미정'인 업무 노트를 사람이 확정(--fix) + 재색인
migrate_*.py            # 볼트 구조/필드 마이그레이션(백업 → dry-run → --execute)
pause_ai.ps1 / resume_ai.ps1  # Revit·Enscape 작업 전후로 RAM/VRAM 비우기/복구
```

## 설정

`.env.example`를 `.env`로 복사해 값을 채운다(`.env`는 git 제외). 주요 항목:

```
INBOX_DIR=C:\Users\OWNER\iCloudDrive\_inbox
ARCHIVE_DIR=_archive            # iCloud 밖(용량 절약)
OBSIDIAN_VAULT_PATH_WIN=C:\Users\OWNER\iCloudDrive\iCloud~md~obsidian\KC_second_brain
OLLAMA_HOST=127.0.0.1:11434     # 머신 환경변수(0.0.0.0)는 건드리지 않고 코드에서 강제
OLLAMA_MODEL=llama3.1           # 분류·요약용
LLM_PROVIDER=ollama             # 분류 백엔드. ollama(기본, 로컬) 또는 gemini(클라우드)
GEMINI_API_KEY=...              # LLM_PROVIDER 또는 OCR_PROVIDER 가 gemini일 때 필요
GEMINI_MODEL=gemini-3.1-flash-lite  # LLM_PROVIDER=gemini일 때 분류 모델
OCR_PROVIDER=tesseract          # 스캔 OCR 백엔드. tesseract(기본, 로컬) 또는 gemini(클라우드)
GEMINI_OCR_MODEL=gemini-3.5-flash-lite  # OCR_PROVIDER=gemini일 때 OCR 모델
GEMINI_OCR_MAX_PAGES=30         # 문서당 OCR 호출할 최대 페이지 수(비용 상한)
DEFAULT_WORK_PROJECT=성수동 리모델링  # 레지스트리의 기본 프로젝트 이름(폴백 아님)
PROJECT_IDENTIFIERS=685-317,685-383,성수동1가,성수동 리모델링  # 이 프로젝트를 가리키는 식별자
WORK_PROJECTS=                  # 2번째 이상 프로젝트. 예: {"판교 오피스":["521-3"]}
TELEGRAM_BOT_TOKEN=...          # 알림 + 봇
TELEGRAM_CHAT_ID=...            # 봇이 응답할 (본인) 채팅 ID
OPENWEBUI_URL=http://127.0.0.1:3000
OPENWEBUI_API_KEY=...           # Open WebUI → 설정 → 계정 → API 키
OPENWEBUI_KB_ID=...             # 지식베이스 ID
TELEGRAM_RAG_MODEL=exaone3.5:7.8b   # 봇 답변 모델(Ollama 백엔드일 때)
RAG_EMBED_PROVIDER=ollama       # 임베딩 백엔드. ollama(기본) 또는 gemini(클라우드)
RAG_GEN_PROVIDER=ollama         # 답변 백엔드. ollama(기본) 또는 gemini(클라우드)
RAG_EMBED_MODEL=bge-m3          # gemini 면 gemini-embedding-001
RAG_EMBED_DIM=1024              # bge-m3=1024, gemini-embedding-001=3072
RAG_GEN_MODEL=gemini-3.1-flash-lite  # RAG_GEN_PROVIDER=gemini 일 때 답변 모델
```

> **Ollama/Tesseract 없는 머신에서 돌리기:** `LLM_PROVIDER=gemini` + `OCR_PROVIDER=gemini`로
> 설정하면 Ollama도 Tesseract도 설치되지 않은 머신(예: 내장 그래픽 미니PC)에서도 **수집 경로**
> (추출 → 분류 → 노트 → 아카이브)가 그대로 동작한다. `.env`는 머신마다 로컬이라(git 제외) 이
> 설정을 바꿔도 다른 머신엔 영향 없다.
>
> **RAG·텔레그램 봇도 클라우드로 돌아간다:** `RAG_EMBED_PROVIDER=gemini` +
> `RAG_GEN_PROVIDER=gemini` 로 두면 Ollama 없이도 볼트 색인과 봇 답변이 동작한다. 임베딩 모델을
> 바꾸면 벡터 차원이 달라지므로 `RAG_EMBED_DIM` 을 맞추고 `--reset` 으로 재색인해야 한다
> (안 맞으면 색인 전에 오류로 잡힌다).

## 실행

의존성은 **uv**로 관리한다([astral.sh/uv](https://docs.astral.sh/uv/)). `uv.lock`에 정확한
버전이 고정돼 있어 어디서든 동일한 환경이 재현된다.

```powershell
# 의존성 설치 + 가상환경(.venv) 생성 (uv.lock 그대로 재현)
uv sync

# Ollama (모델 미리 받기)
ollama pull llama3.1        # 분류·요약
ollama pull bge-m3          # 다국어 임베딩(한국어). 아래 '임베딩 주의' 참고
ollama pull exaone3.5:7.8b  # 봇 답변(한국어 특화)

# _inbox 일괄 처리(수동)
uv run python run_once.py

# 상시 감시 + 모니터 + 텔레그램 봇(작업 스케줄러가 부팅 시 자동 실행)
uv run python run_watch.py

# 볼트를 RAG 인덱스로 적재(최초 1회/노트 추가 후). 기본 백엔드는 로컬(LanceDB+bge-m3)
uv run python ingest_vault.py            # 증분 색인
uv run python ingest_vault.py --reset    # 전체 재색인

# project 가 '미정'으로 남은 업무 노트를 확정
uv run python review_pending.py          # 목록만
uv run python review_pending.py --fix    # 하나씩 고르고 일괄 반영 + 재색인
```

### 업무 노트의 project 는 어떻게 정해지나

`classify.detect_project()` 가 원본 파일명과 본문에서 등록된 식별자(지번 등)를 찾아 정한다.
LLM 이 프로젝트 이름을 짓지 않는다 — 모델은 문서에서 읽은 현장 표기를 `site` 로 보고할 뿐이고,
그 문자열은 레지스트리 대조에만 쓰인다.

식별자를 못 찾으면 **`project: 미정`** 으로 저장하고 텔레그램으로 알린다. 예전에는 기본
프로젝트로 조용히 채웠는데, 그 탓에 다른 현장 문서까지 같은 프로젝트로 표시됐다
(2026-08-02 에 192건 중 60건이 그런 상태로 발견됨). 미정 노트는 `review_pending.py` 로 확정한다.

> **RAG 백엔드:** 기본은 **로컬(LanceDB + bge-m3)** 로 Docker 가 필요 없고 한국어 검색이
> 우수하다. 인덱스는 `rag_db/`(git 제외)에 저장된다. 구 **Open WebUI** 경로는
> `RAG_BACKEND=openwebui` 로 전환할 수 있다(폴백용).

> `requirements.txt`가 필요하면 `uv export -o requirements.txt`로 만들 수 있다.

상시 운영은 Windows **작업 스케줄러**의 `ArchivePipelineWatch` 작업이 `run_watch.py`를 부팅 시 실행한다.
(이 PowerShell엔 `Restart-ScheduledTask`가 없으니 재시작은 **Stop + Start**.)

Revit·Enscape 등 무거운 작업 전에는 AI 스택을 잠시 멈춰 메모리를 비운다:

가장 쉬운 방법은 파일 탐색기에서 **`pause_ai.bat` 를 더블클릭**(작업 후 `resume_ai.bat` 더블클릭).
명령으로 실행하려면:

```powershell
powershell -ExecutionPolicy Bypass -File pause_ai.ps1    # 멈추고 ~9GB RAM + VRAM 회수
powershell -ExecutionPolicy Bypass -File resume_ai.ps1   # 다시 켜기
```

## 에이전트에서 볼트 읽기 (MCP)

`mcp_server.py` 가 볼트를 Claude Code 같은 에이전트에 도구로 노출한다. 목적은 **에이전트가 볼트
파일을 직접 뒤지지 않게** 하는 것이다. 볼트 전체는 약 467,000토큰, 검색 한 번은 약 700토큰이다.

| 도구 | 용도 | 비용 |
|---|---|---|
| `search_vault` | 관련 조각 찾기(먼저 이걸 쓴다) | 약 700토큰 |
| `ask_vault` | 근거 기반 답변 + 출처 | 약 300토큰 |
| `list_notes` | 조건에 맞는 제목만 훑기 | 수십~수백 토큰 |
| `get_note` | 노트 전문(꼭 필요할 때만) | 약 1,900토큰 |
| `vault_status` | 볼트 규모·최근 수정 확인 | 미미 |

**등록은 저장소 단위로 한다.** 전역(user scope)으로 걸면 볼트와 무관한 세션에서도 서버가 뜬다.
이 저장소에는 `.mcp.json` 이 들어 있어 여기서 작업할 때 자동으로 잡힌다. 다른 저장소에 붙이려면
그 폴더에서:

```powershell
# 이 저장소 안에서만 쓰이는 등록(남과 공유 안 함)
claude mcp add vault --scope local -- uv run --directory C:\Users\Indion\repos\archive-pipeline python mcp_server.py

# 팀·다른 기기와 공유할 저장소면 .mcp.json 을 커밋(--scope project)
claude mcp add vault --scope project -- uv run --directory C:\Users\Indion\repos\archive-pipeline python mcp_server.py
```

맥 등 다른 기기에서는 n100 의 서버를 SSH stdio 로 부른다(포트를 열지 않는다):

```bash
claude mcp add vault --scope local -- ssh n100-win "cd /c/Users/Indion/repos/archive-pipeline && uv run python mcp_server.py"
```

등록 확인·해제는 `claude mcp list`, `claude mcp remove vault`.

> **왜 전역 등록을 피하나:** 도구 정의 자체는 약 210토큰으로 가볍지만, 서버가 뜰 때마다
> `rag_local`(lancedb+pyarrow) 임포트에 이 머신 기준 **10초·89MB** 가 든다. 그래서
> `list_notes`/`get_note`/`vault_status` 는 파일시스템만 써서 그 비용을 아예 내지 않고,
> 검색 계열 도구를 실제로 호출할 때만 지연 임포트한다. 그래도 무관한 프로젝트에 굳이
> 붙여둘 이유는 없다. 즉석 질문은 텔레그램 봇이 더 싸다(Claude 토큰 0).

## 테스트

```powershell
uv run pytest -q
```

LLM·OCR·텔레그램 호출은 외부 의존성이라 테스트에서 모킹/격리한다. 로컬 OCR엔 Tesseract(kor+eng) 설치 필요.
한국어 스캔본은 이진화 전처리(`--psm 6`)로 인식한다.

## 기술 스택

로컬 전용: Ollama(분류 llama3.1 / 임베딩 bge-m3 / 답변 EXAONE 3.5) · LanceDB(로컬 벡터 인덱스) ·
Tesseract + PyMuPDF(스캔 OCR) · pyhwp(한글) · watchdog · Telegram Bot API · Obsidian.
환경: Windows 11 / Python 3.13 / RTX 4080.

> **RAG 임베딩:** 기본 로컬 백엔드는 **bge-m3**(다국어, 1024차원)로 한국어 검색이 우수하다.
> 구 Open WebUI 백엔드(`RAG_BACKEND=openwebui`)는 기본 임베더가 **all-MiniLM-L6-v2(영어
> 전용)** 라 한국어 검색이 약하므로, 쓸 경우 관리자 설정에서 bge-m3 로 바꿔야 한다.
```
