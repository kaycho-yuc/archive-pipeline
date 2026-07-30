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
- **OCR 백엔드 선택(`OCR_PROVIDER`, 2026-07-29 추가)**: 기본 `tesseract`(로컬, 위 이진화 경로).
  `gemini`로 설정하면 Tesseract가 없는 머신(예: N100 미니PC)에서도 동작 — PyMuPDF로 페이지를
  렌더링해 비전 모델에 그대로 전달(비전 모델엔 이진화가 오히려 해로워 **전처리 생략**).
  `GEMINI_OCR_MODEL`(기본 `gemini-3.5-flash-lite`), `GEMINI_OCR_MAX_PAGES`(기본 30, 비용 상한),
  `GEMINI_OCR_MAX_OUTPUT_TOKENS`(기본 8192). 응답이 잘리면(`finish_reason=MAX_TOKENS`) 조용히
  받지 않고 예외 — 페이지 중간에서 끊긴 주소·금액이 '전부'로 둔갑하는 걸 막는다.
- **글꼴 서브셋 깨짐 감지(`MIN_DISTINCT_PUA=5`)**: 서브셋 글꼴이 ToUnicode 표 없이 글리프를
  사설영역(PUA)에 매핑하면 추출기가 글자 대신 글리프 코드를 돌려준다(레시피 PDF 의 영양정보·
  조리순서 숫자가 통째로 사라진 실제 사례). **서로 다른** PUA 코드가 5종 이상이면 임베드
  텍스트를 버리고 OCR 로 다시 읽는다. 장식용 구분선처럼 같은 글리프만 반복되는 경우(견적서의
  U+F000 x98)는 distinct 가 1이라 걸리지 않아, 멀쩡한 문서를 괜히 OCR 돌리지 않는다.
- **OCR 실패는 폴백하지 않는다**: 이 분기까지 왔다는 건 임베드 텍스트가 이미 50자 미만이라,
  폴백하면 페이지번호·워터마크 몇 글자를 문서 전체로 분류하게 된다. 예외를 그대로 올려
  `_failed` 격리 + 알림에 걸리게 한다. (OCR 이 '빈 결과'를 준 경우는 예외가 아니라 기존 동작 유지.)

### `classifier/classify.py` — 로컬 LLM 분류 + 추출
- Ollama 사용(분류 모델 `OLLAMA_MODEL`, 현재 **`exaone3.5:7.8b`** — 한국어 우수 + 봇과 모델 공유). **클라이언트 host를 코드에서 `127.0.0.1:11434`로 고정**.
- **파일명 최우선(filename-first):** `classify(text, source_name)` — 원본 파일명이 유형·상대방·날짜·상태의 최고 권위 근거. 본문 OCR 은 보조(노이즈 많음).
- 산출물 `Classification`: `domain`(업무/개인), `kind`(프로젝트자료/참고자료), `category`(통제 어휘 문서유형), `counterparty`(상대방), `doc_date`(ISO, 실재 날짜 검증), `status`(초안/최종), `tags`, `summary`, `title`.
- **제목은 `compose_title()`로 결정적 조립**: `YYYY-MM-DD <유형> - <상대방> (<부가, 상태>)`. LLM 이 제목 문자열을 직접 만들지 않음.
- **kind**: 참고자료(빈 양식·샘플·정부지침/매뉴얼/사례집·다른 현장)는 봇에서 제외하기 위한 판정. 확실할 때만 참고자료, 애매하면 프로젝트자료(실데이터 보호).
- 견고성: `MAX_INPUT_CHARS=4000`, 스키마 본문 뒤 재명시, `RETRY_TEMPERATURES=(0.0,0.4,0.8)`, domain 만 엄격 검증.
- **분류 백엔드 선택(`LLM_PROVIDER`, 2026-07-29 추가)**: 기본 `ollama`(위 경로). `gemini`로 설정하면
  Ollama가 없는 머신에서도 동작(`GEMINI_MODEL`, 기본 `gemini-3.1-flash-lite`). 3.5 Flash Lite는
  10회 A/B에서 통제 어휘 밖 카테고리를 2회 출력해 **탈락**시켰다(제목은 3.1이 10/10, 3.5가 9/10
  일치) — 근거는 `ROADMAP.md` 결정 기록 참고. `.env`는 머신별 로컬이라 이 설정은 머신마다 독립.

### `notes/write_note.py` — Obsidian 노트 작성 (볼트 스키마 v2 + 명명규칙)
- 폴더 매핑: `업무→10_Professional`, `개인→20_Personal`, 그 외 `90_System`. 분기 폴더 `YYYY-QN`.
- **Frontmatter(기계 파싱 가능, Dublin Core: 제목=사람용 라벨, frontmatter=구조화 데이터):**
  `title, domain, project(업무만), category, doc_date, counterparty, status, tags, source, created`.
  `doc_date/counterparty/status`는 값이 있을 때만 기록. (이전 핸드오프의 `<METADATA>` 블록 방식은 거부.)
- 명명규칙 근거: ISO 8601(날짜), RDM 파일명 모범사례, ISO 15489/Dublin Core. `migrate_revise_notes.py`로 기존 노트 일괄 재정리(백업 → dry-run 캐시 → `--execute`).

### `pipeline.py` — 오케스트레이션
- `process_file()`: ①SHA-256 중복검사(중복이면 추출 없이 아카이브) → ②추출 → 빈/실패 시 `_failed` 격리 + `notifier.notify` + CSV 로그 → ③분류(`source_name` 전달) → ③.5 **참고자료면 `_failed/참고자료`로 격리(노트 미생성, 봇 임베딩 제외)** → ④노트 작성 → ⑤해시 기록 + 아카이브 이동.
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
- `migrate_add_project.py`: 업무 노트 frontmatter 에 `project` 채움.
- `migrate_classify_reference.py`: 기존 업무 노트를 다시 분류해 참고자료를 검토 폴더로 이동(자동 분류 보조; 사람이 최종 확정).
- `migrate_revise_notes.py`: 기존 업무 노트를 명명규칙으로 재정리(제목·구조화 frontmatter). dry-run 이 `_revise_plan.json` 캐시를 만들고 `--execute` 가 그 결과를 그대로 적용(재분류 없음). source/created/project·원문 보존.

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

1. **일부 형식 미지원**: 이제 PDF/이미지/txt/md/hwp/hwpx **+ xlsx/docx/msg/xml**까지 처리한다. 남은 미지원(`.dwg .pptx .zip .alz`)은 볼트 노트 `미지원_파일_목록.md`에 기록한 뒤 `_failed`로 격리한다(그냥 건너뛰지 않음).
2. **iCloud 온라인 전용 placeholder 지연**: 다운로드되지 않은 파일을 만지면 watcher가 I/O에서 멈춘 것처럼 보일 수 있음(가짜 행). 격리 테스트로 추출/복사 자체는 빠름을 확인.
3. **pyhwp 한계**: 일부 `.hwp`가 `OleStream ... propertySetStream` AttributeError → 우아하게 `_failed` 격리.
4. **머신 환경변수 `OLLAMA_HOST=0.0.0.0`** 은 그대로 두되 코드에서 무력화함(머신 설정 보존 원칙).
5. **iCloud 폴더 간 `os.rename` → `WinError 426`(2026-07-29 발견/수정)**: iCloud 동기화 폴더에서
   동기화 범위 밖 폴더로 `os.rename` 하면 Windows 클라우드 필터 드라이버가 가로채 60초 멎었다가
   `ERROR_CLOUD_FILE_REQUEST_TIMEOUT`로 실패한다. `shutil.move`의 복사 폴백은 그 60초 뒤에야
   실행되는데 `_move_to`의 20초 워치독이 먼저 워커를 죽여, 아카이브가 매 스윕마다 무한 재시도되며
   조용히 실패하고 있었다. `pipeline._move_to`를 `shutil.copy2` + `os.unlink`로 고쳐(rename 자체를
   시도하지 않음) 해결 — 같은 동작이 0.02초. 전체 기록: `learnings/2026-07-29-icloud-rename-winerror-426.md`.

---

## 8. RAG 레이어(구축 완료, 2026-07)

- **로컬 인프로세스 RAG** — `rag_local.py`: 볼트 노트를 bge-m3(Ollama, 1024차원)로 임베딩해
  파일 기반 **LanceDB**(`rag_db/`, git 제외)에 저장·검색. **Docker/Open WebUI 불필요.**
  - 하이브리드 검색(키워드 FTS + 벡터, RRF 결합)으로 지번·'연면적' 같은 정확 용어를 잡음.
  - 각 청크에 노트 frontmatter(제목·날짜·분류)를 각인, 답변 시 노트별 깨끗한 `요약`을 함께
    제공 → 스캔 OCR이 깨져도 값 추출. 답변 생성 temperature 0.3.
  - 새 노트는 `pipeline.process_file` 이후 `index_note()`로 즉시 색인(best-effort), 감시기가
    1시간마다 증분 전체 재색인으로 보완(pause_ai 구간·수동 편집 포함).
  - `RAG_BACKEND` 로 `local`(기본)/`openwebui`(구 경로, 폴백) 전환. 임베딩 주의: 구 Open
    WebUI 기본 임베더는 영어 전용 all-MiniLM-L6-v2라 한국어 검색이 약했음(이전 이유).
- **아직 안 만든 것**: 리랭커·프로젝트별 RAG 필터(선택), 로컬 Whisper(음성), 비전 모델
  (스케치), 정규식 민감정보 사전 플래그, 네이티브 PDF 표 추출(Docling, 안정 환경에서). 상세는
  `ROADMAP.md`.

---

## 9. 이 시스템을 인계받는 AI에게

- 먼저 `STATUS.md`, `README.md`, 그리고 미래 설계는 `archive-pipeline-handoff.md`를 읽으세요.
- 경로/비밀값은 `.env`에 있습니다(git 제외). 동작 확인은 `python run_once.py`.
- 사용자는 비개발자입니다. **머신 기본 상태를 바꾸는 변경은 피하고, 변경 전 이유를 쉬운 말로 설명**하세요.
```
