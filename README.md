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
DEFAULT_WORK_PROJECT=성수동 리모델링  # 업무 노트 frontmatter의 project 기본값
TELEGRAM_BOT_TOKEN=...          # 알림 + 봇
TELEGRAM_CHAT_ID=...            # 봇이 응답할 (본인) 채팅 ID
OPENWEBUI_URL=http://127.0.0.1:3000
OPENWEBUI_API_KEY=...           # Open WebUI → 설정 → 계정 → API 키
OPENWEBUI_KB_ID=...             # 지식베이스 ID
TELEGRAM_RAG_MODEL=exaone3.5:7.8b   # 봇 답변 모델(벤치마크로 선정)
```

> **Ollama/Tesseract 없는 머신에서 돌리기:** `LLM_PROVIDER=gemini` + `OCR_PROVIDER=gemini`로
> 설정하면 Ollama도 Tesseract도 설치되지 않은 머신(예: 내장 그래픽 미니PC)에서도 **수집 경로**
> (추출 → 분류 → 노트 → 아카이브)가 그대로 동작한다. `.env`는 머신마다 로컬이라(git 제외) 이
> 설정을 바꿔도 다른 머신엔 영향 없다.
>
> 다만 **RAG·텔레그램 봇은 아직 안 된다** — 임베딩(bge-m3)·답변 모델이 Ollama 위에서 돌기
> 때문이다. 그런 머신에선 `RAG_BACKEND=off` 로 둔다. 임베딩·답변까지 클라우드로 돌리는 작업이
> 다음 순서로 예정돼 있다(`ROADMAP.md` 참고).

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
```

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
