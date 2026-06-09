# 아카이브 파이프라인 — 현재 개발 상태 핸드오프

> 이 문서는 **지금까지 실제로 구현되어 동작하는 시스템**을 다른 AI/개발자에게 인계하기 위한 것입니다.
> 작성일: 2026-06-09 · 플랫폼: Windows 11 Pro · Python 3.13 · 전부 로컬에서 동작(클라우드 LLM 미사용)

---

## 1. 한 줄 요약

사용자의 문서 파일을 `_inbox` 폴더에 떨어뜨리면 → **텍스트 추출 → 로컬 LLM 분류 → Obsidian 노트 자동 생성 → 원본 아카이브**까지 자동으로 처리하는 개인용 지식 관리 파이프라인. 모든 처리는 로컬에서 일어나며 외부로 데이터가 나가지 않습니다(Telegram 알림 제외).

사용자는 **비개발자(건축/BIM 실무자, 한국어 사용)** 이며, "이 PC의 기본 상태를 가능한 한 건드리지 않고, 호환성을 최우선으로" 라는 제약을 지켜야 합니다.

---

## 2. 데이터 흐름 (파이프라인)

```
_inbox/ (iCloud)  ──감시/스윕──►  process_file()
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        ▼                            ▼                              ▼
  ① 중복 검사(SHA-256)        ② 텍스트 추출            ③ 분류(로컬 LLM)
   processed_hashes.json      extractors/extract.py     classifier/classify.py
        │                            │                              │
   중복이면 아카이브로            추출 실패/빈 문서면          domain(업무/개인) +
   바로 이동                     _failed 격리 + 알림          tags[] + 제목 산출
                                                                    │
                                                                    ▼
                                                         ④ Obsidian 노트 작성
                                                          notes/write_note.py
                                                          vault/{도메인}/{분기}/제목.md
                                                                    │
                                                                    ▼
                                                         ⑤ 원본 _archive 이동
                                                          + 해시 기록 + CSV 로그
```

핵심 진입점은 `pipeline.py`의 `process_file(file_path, vault_path, archive_dir, failed_dir)`.

---

## 3. 디렉터리 / 경로 설정

모든 경로는 `.env`(git 제외)에서 읽습니다. `.env.example`에 템플릿이 있습니다.

| 변수 | 현재 값 | 용도 |
|---|---|---|
| `INBOX_DIR` | `C:\Users\OWNER\iCloudDrive\_inbox` | 감시 대상(하위 폴더 재귀 처리) |
| `ARCHIVE_DIR` | 로컬 `_archive` (iCloud 밖) | 처리 끝난 원본 보관 — iCloud 용량 절약 목적 |
| `FAILED_DIR` | 로컬 `_failed` | 추출 실패/빈 문서 격리 |
| `OBSIDIAN_VAULT_PATH_WIN` | `C:\Users\OWNER\iCloudDrive\iCloud~md~obsidian\KC_second_brain` | Obsidian 볼트 |
| `OLLAMA_HOST` | `127.0.0.1:11434` | 로컬 LLM |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | (설정됨) | 실패 알림 |

`processing_log.csv`, `processed_hashes.json`, `vault_backup_*.zip`, `*.log`, `_failed/`는 모두 gitignore.

---

## 4. 모듈별 상세

### `extractors/extract.py` — 텍스트 추출
- 진입점 `extract_text(path)` 가 확장자로 분기.
- 지원 형식:
  - **PDF** (`.pdf`): pdfplumber로 임베드 텍스트 우선 → 50자 미만이면 **스캔본으로 보고 OCR 폴백**(PyMuPDF로 300dpi 렌더링 → 전처리 → Tesseract).
  - **이미지** (`.jpg/.png/.bmp/.tiff` 등): Tesseract OCR.
  - **텍스트** (`.txt/.md`).
  - **HWP** (`.hwp`, 한글 v5 바이너리/OLE): `pyhwp`의 `TextTransform`을 BytesIO로 받아 디코딩.
  - **HWPX** (`.hwpx`, 한글 OWPML zip+xml): zipfile로 `Contents/section*.xml`을 열어 네임스페이스 무시하고 `t`(텍스트 런) 요소만 수집.
- **한국어 스캔 OCR 핵심**: `kor+eng` + 그레이스케일 + autocontrast + **이진화(임계값 150)** + `--psm 6`. 이진화 없이는 한국어 인식률이 매우 낮음.

### `classifier/classify.py` — 로컬 LLM 분류
- Ollama `llama3.1:8b` 사용. **클라이언트 host를 코드에서 `127.0.0.1:11434`로 고정**(머신 환경변수 `OLLAMA_HOST=0.0.0.0`이 Windows에서 연결 불가라서 — 머신 설정은 건드리지 않고 코드에서 강제).
- 산출물 `Classification` dataclass: `domain`(업무/개인), `category`, `title`, `tags: list[str]`.
- **견고성 처리(긴 문서에서 LLM이 스키마를 무시하는 문제 해결)**:
  - 입력을 `MAX_INPUT_CHARS=4000`자로 자름.
  - 문서를 `=== 문서 시작/끝 ===` 구분자로 감싸고, **본문 뒤에 스키마를 다시 명시**.
  - 온도를 바꿔가며 재시도 `RETRY_TEMPERATURES=(0.0, 0.4, 0.8)`, `num_predict=1024`.
  - 파싱은 domain만 엄격 검증(개인/업무), 나머지는 기본값 허용.

### `notes/write_note.py` — Obsidian 노트 작성 (볼트 스키마 v2)
- 폴더 매핑: `업무→10_Professional`, `개인→20_Personal`, 그 외 `90_System`.
- 분기 폴더: `_quarter(dt)` → `YYYY-QN`. 최종 경로 `vault/{top}/{quarter}/{title}.md`.
- **분류는 깊은 폴더가 아니라 태그로**: YAML frontmatter에 `tags`(카테고리 + 모델 태그 병합), `source`, 날짜 등 기록. (Obsidian 네이티브 방식 — 이전 핸드오프의 `<METADATA>` 블록 방식은 거부함.)

### `pipeline.py` — 오케스트레이션
- `process_file()`: ①SHA-256 중복검사(중복이면 추출 없이 아카이브) → ②추출 → 빈/실패 시 `_failed` 격리 + `notifier.notify` + CSV 로그 → ③분류 → ④노트 작성 → ⑤해시 기록 + 아카이브 이동.
- `prune_empty_dirs()`: 처리 후 빈 하위폴더 정리(`.DS_Store/Thumbs.db/desktop.ini`는 무시).

### `notifier.py` — Telegram 알림
- `notify(message)`: 표준 라이브러리 urllib로 Telegram Bot API POST. 토큰/챗ID 미설정이면 no-op. 주로 실패 격리 시 호출.

### 실행 진입점
- `run_once.py`: `_inbox` 전체를 한 번 스윕(수동 실행). 재귀 처리.
- `watch.py`: watchdog `Observer`로 `_inbox` 실시간 감시(`recursive=True`). 파일 크기 안정화 대기 후 처리.
- `run_watch.py`: **Windows 작업 스케줄러용 진입점**. 작업 폴더 고정 + `watch.log` 파일 로깅 + `run_once` 후 `watch` 실행.

### 마이그레이션 스크립트(1회성)
- `migrate_vault.py`: 기존 볼트를 v2 구조로 이전. **백업(zip) → dry-run → `--execute`**. `source` 필드가 있고 도메인이 유효한 노트만 이전(손으로 쓴 노트는 보존).
- `migrate_workout.py`: 손으로 쓴 운동일지 9개에 frontmatter 부여, 인라인 `#해시태그`를 수집해 태그로, 본문 유지, `20_Personal`로 이동.

---

## 5. 자동 실행(무인 운영)

- **Windows 작업 스케줄러**에 `ArchivePipelineWatch` 작업 등록 → 부팅 시 항상 켜진 watcher로 동작(사용자 요청: "컴퓨터 켠 뒤엔 아무것도 안 건드리고 싶다").
- Ollama는 자동 시작.
- 주의: 이 PowerShell에는 `Restart-ScheduledTask`가 없음 → **Stop + Start로 재시작**.

---

## 6. 테스트

- pytest 스위트: `test_classify.py`, `test_write_note.py`, `test_pipeline.py`(autouse fixture가 로그/해시/알림을 패치), `test_notifier.py`, `test_extract.py`(합성 zip으로 HWPX 검증). 전부 통과 상태.

---

## 7. 알려진 제약 / 함정

1. **지원하지 않는 형식이 많음**: 현재 실제 `_inbox`에는 `.xlsx .msg .dwg .pptx .zip .alz`가 대다수인데 파이프라인은 PDF/이미지/txt/md/hwp/hwpx만 처리. 나머지는 그냥 건너뜀.
2. **iCloud 온라인 전용 placeholder 지연**: 다운로드되지 않은 파일을 만지면 watcher가 I/O에서 멈춘 것처럼 보일 수 있음(가짜 행). 격리 테스트로 추출/복사 자체는 빠름을 확인.
3. **pyhwp 한계**: 일부 `.hwp`가 `OleStream ... propertySetStream` AttributeError → 우아하게 `_failed` 격리.
4. **머신 환경변수 `OLLAMA_HOST=0.0.0.0`** 은 그대로 두되 코드에서 무력화함(머신 설정 보존 원칙).

---

## 8. 아직 안 만든 것(로드맵 — `archive-pipeline-handoff.md` 참고)

- Open WebUI(Docker) 기반 RAG 레이어: 볼트를 지식베이스로 등록, ChromaDB 임베딩. 현재 **localhost(127.0.0.1:3000)로만 기동**, 관리자 계정/지식베이스 설정 미완. Tailscale 공개 시 포트 3000을 본인 기기로만 제한하는 ACL 필요(타 사용자 jisoo.park@ 제외).
- 로컬 Whisper(음성), 비전 모델(스케치 인식), 정규식 민감정보 사전 플래그.

---

## 9. 이 시스템을 인계받는 AI에게

- 먼저 `STATUS.md`, `README.md`, 그리고 미래 설계는 `archive-pipeline-handoff.md`를 읽으세요.
- 경로/비밀값은 `.env`에 있습니다(git 제외). 동작 확인은 `python run_once.py`.
- 사용자는 비개발자입니다. **머신 기본 상태를 바꾸는 변경은 피하고, 변경 전 이유를 쉬운 말로 설명**하세요.
```
