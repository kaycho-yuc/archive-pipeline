# Archive Pipeline

`_inbox`에 넣은 파일(PDF·이미지·텍스트)을 추출 → 로컬 LLM(Ollama) 분류·요약 → Obsidian 볼트에 마크다운 노트로 저장하는 파이프라인.

자세한 배경은 [archive-pipeline-handoff.md](archive-pipeline-handoff.md) 참고.

## 구조

```
extractors/extract.py   # PDF/이미지(OCR)/텍스트 추출
classifier/classify.py  # Ollama로 개인·업무 분류 + 세부 카테고리 + 요약
notes/write_note.py     # 볼트 내 {domain}/{category}/ 에 노트 저장
pipeline.py             # 추출→분류→저장→아카이브 이동 (파일 1개)
watch.py                # _inbox 자동 감시 (윈도우 상시 실행용)
run_once.py             # _inbox 일괄 처리 (맥북 수동 실행용)
```

## 설정

`.env.example`를 `.env`로 복사해 경로를 채운다.

```
INBOX_DIR=_inbox
ARCHIVE_DIR=_archive
OBSIDIAN_VAULT_PATH=/Users/kwangyeoncho/Library/Mobile Documents/iCloud~md~obsidian/Documents/KC_second_brain
OLLAMA_MODEL=llama3.1
```

## 실행

```bash
# 의존성
pip install -r requirements.txt

# Ollama 백그라운드 실행 (모델 미리 받아두기)
ollama serve
ollama pull llama3.1

# 맥북: _inbox 일괄 처리
python run_once.py

# 윈도우: 폴더 상시 감시
python watch.py
```

## 테스트

```bash
python -m pytest tests/ -v
```

LLM·OCR 호출은 외부 의존성이므로 테스트에서는 모킹한다. 이미지 OCR을 로컬에서 쓰려면 Tesseract 설치 필요:

```bash
brew install tesseract tesseract-lang   # macOS
```
