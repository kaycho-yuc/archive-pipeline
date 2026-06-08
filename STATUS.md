# 현재 상태 (Windows 세션 인수인계)

맥에서 파이프라인 전체를 작성·테스트했고, iCloud로 이 프로젝트가 윈도우 PC에 동기화되어 있습니다.
이 문서는 윈도우 Claude Code 새 세션이 곧바로 스모크 테스트를 이어가도록 돕기 위한 것입니다.

## 빌드 완료 (1~6단계)

| 모듈 | 파일 | 검증 |
|---|---|---|
| 추출 (PDF/이미지 OCR/텍스트) | `extractors/extract.py` | 맥에서 PDF·텍스트 검증, OCR은 코드만 |
| 분류·요약 (Ollama) | `classifier/classify.py` | 파싱·검증 검증 (LLM 모킹) |
| 노트 저장 | `notes/write_note.py` | frontmatter·충돌·특수문자 검증 |
| 파이프라인 (파일 1개) | `pipeline.py` | end-to-end 검증 |
| 자동 감시 (상시 실행) | `watch.py` | 미실행 |
| 일괄 처리 (수동 실행) | `run_once.py` | 미실행 |

`python -m pytest tests/` 기준 맥에서 11/11 통과.

## 핵심 설계
- `classify`는 Ollama를 `format="json"`, `temperature=0`으로 호출하고 `domain`이 반드시 `개인`/`업무`인지 검증한다. 아니면 `ValueError`.
- 처리 실패 시 `_inbox` 원본을 이동하지 않고 보존한다 (재시도 가능, 데이터 유실 없음).
- 볼트 경로는 OS별로 자동 선택한다 (`pipeline.py:_resolve_vault_path`). `.env`에 맥·윈도우 경로가 둘 다 있고, iCloud로 `.env`가 공유되므로 한 파일로 양쪽 동작한다.

## 윈도우에서 할 일: 스모크 테스트

```powershell
cd <이 프로젝트 폴더>           # 예: C:\Users\OWNER\iCloudDrive\...\Projects\archive-pipeline

# 맥 venv\ 는 동기화됐지만 윈도우에서 동작 안 함 — 새로 만든다
python -m venv venv-win
.\venv-win\Scripts\Activate.ps1
pip install -r requirements.txt

# Ollama 확인 (별도 창)
ollama serve
ollama pull llama3.1

# 테스트 파일 투입
echo 다음주 화요일 오후 2시 강남 현장 점검 회의. 참석자 3명. > _inbox\test.txt

# 일괄 처리 실행
python run_once.py
```

### 성공 기준
- 로그에 `노트 저장: ...KC_second_brain\업무\...md`, `아카이브 이동 완료` 출력
- Obsidian 볼트 `KC_second_brain\업무\<카테고리>\` 아래에 새 `.md` 노트 생성
- `_inbox\test.txt` → `_archive\` 로 이동

### 윈도우 주의점
- Tesseract OCR은 **이미지** 파일일 때만 필요. PDF·텍스트는 불필요. 핸드오프상 PATH 등록 완료이나, `pytesseract`가 "tesseract not found"면 PATH 누락.
- 동기화된 `venv\`, `__pycache__\` 는 맥 잔재이므로 무시. `venv-win` 사용.

## 환경 차이
- 맥에는 Ollama·Tesseract 없음 → 맥에서는 LLM·OCR 실호출 테스트 불가. 윈도우가 실호출 검증의 본 무대.
- 맥은 핸드오프상 Claude API 백엔드 사용 예정 (`classifier/classify.py`의 `_call_ollama`만 교체). 아직 미구현.

## 남은 단계
- 7단계: 윈도우 Task Scheduler 등록 (스모크 테스트 통과 후)
