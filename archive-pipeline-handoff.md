# Archive Pipeline 핸드오프 문서

## 프로젝트 개요

iCloud Drive의 `_inbox` 폴더에 파일을 넣으면 자동으로 처리해서 Obsidian 볼트에 마크다운 노트로 저장하는 파이프라인.

---

## 아키텍처

```
iCloud Drive/_inbox/ 에 파일 투입
        ↓
[1단계: 파일 감지]
윈도우 watchdog이 폴더 변화 감지
        ↓
[2단계: 추출]
- PDF       → pdfplumber로 텍스트 추출
- 이미지     → pytesseract로 OCR (한국어 포함)
- 음성       → (추후 추가 예정, 현재 스코프 외)
- 텍스트 파일 → 그대로 사용
        ↓
[3단계: 로컬 LLM 처리 (Ollama)]
- 개인 / 업무 분류
- 세부 카테고리 AI 판단 및 자동 생성
- 요약 생성
- Obsidian 마크다운 노트 구조화
        ↓
[4단계: Obsidian 저장]
iCloud Drive 내 Obsidian 볼트에 .md 파일로 저장
폴더 구조는 AI가 분류 기준으로 자동 생성
        ↓
[5단계: 완료 처리]
처리된 파일을 _inbox에서 _archive로 이동
```

---

## 실행 환경

### 윈도우 PC (자동 실행, 메인)
- OS: Windows
- CPU/GPU: RTX 4080 (VRAM 16GB)
- RAM: 64GB
- Python: 3.13.3
- 경로: `C:\Users\OWNER\Desktop\_WORK\archive-pipeline\` (생성 예정)

### 맥북에어 (수동 실행, 윈도우 불가시 대체)
- 동일 스크립트를 수동으로 실행하는 구조
- 프로젝트 경로: `~/Documents/Projects/archive-pipeline/`

---

## 설치 완료된 것들 (윈도우)

### Python 패키지
```
pdfplumber
pytesseract
watchdog
ollama
python-dotenv
Pillow
```

### Ollama
- 버전: 0.30.5
- 설치 모델: llama3.1 (8B)

### Tesseract OCR
- 경로: `C:\Program Files\Tesseract-OCR\`
- 언어팩: 영어 + 한국어 (kor) 확인 완료
- PATH 등록 완료

---

## iCloud 폴더 구조

```
iCloud Drive/
  _inbox/      ← 파일 투입 위치
  _archive/    ← 처리 완료 파일 이동 위치
```

Obsidian 볼트도 iCloud Drive 내에 위치. 볼트 경로는 세션 시작 전 광연님께 확인 필요.

---

## LLM 설정

- 윈도우 자동 처리: Ollama (llama3.1, 로컬, 무료)
- 맥북 수동 처리: Claude API (추후 API 키 발급 예정)
- RTX 4080 VRAM 16GB 기준 13B Q4 모델까지 여유 있게 실행 가능

---

## 분류 체계

- 최상위: 개인 / 업무 (2분류)
- 세부 카테고리: AI가 문서 내용 기반으로 자동 판단 및 생성
- 볼트 내 폴더 구조 없음 (파이프라인이 생성)

---

## 처리 대상 파일 타입

| 타입 | 처리 방식 |
|------|----------|
| PDF | pdfplumber 텍스트 추출 |
| 이미지 (jpg, png 등) | pytesseract OCR |
| 텍스트 (txt, md 등) | 직접 읽기 |
| 음성 | 추후 추가 예정 |

---

## 보안 정책

- 시방서, 현장 보고서 등 일반 업무 문서: API 전송 허용
- 계약서, 견적서, 내역서: 현재는 마스킹 없이 처리 (사내 보안 정책 미수립 상태)
- 사내 정보보안 정책 수립 시 마스킹 레이어 추가 예정

---

## 코드 작업 순서 (Claude Code에서 진행)

1. 프로젝트 폴더 생성 및 `.env` 설정
2. 파일 추출 모듈 작성 (PDF, 이미지, 텍스트)
3. Ollama 연동 분류 및 요약 모듈 작성
4. Obsidian 마크다운 노트 생성 모듈 작성
5. watchdog 폴더 감시 및 자동 실행 모듈 작성
6. 전체 파이프라인 통합 및 테스트
7. 윈도우 Task Scheduler 등록 (AURIC 스크립트와 동일 방식)

---

## Claude Code 세션 시작 전 확인사항

- [ ] Obsidian 볼트 경로 확인 (iCloud Drive 내 정확한 경로)
- [ ] 윈도우 작업 폴더 경로 확정 (`C:\Users\OWNER\Desktop\_WORK\archive-pipeline\`)
- [ ] Ollama가 백그라운드에서 실행 중인지 확인 (`ollama serve`)
