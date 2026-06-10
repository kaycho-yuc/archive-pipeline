"""볼트의 모든 .md 노트를 Open WebUI 지식베이스(KC_second_brain)에 올린다.

Open WebUI REST API 사용:
  1) 지식베이스 생성(없으면)        POST /api/v1/knowledge/create
  2) 파일 업로드                    POST /api/v1/files/   (multipart)
  3) 파일을 지식베이스에 연결        POST /api/v1/knowledge/{id}/file/add

이미 같은 이름의 지식베이스가 있으면 재사용하고, 이미 올라간 파일명은 건너뛴다
(중복 임베딩 방지). 임베딩은 서버가 nomic-embed-text 로 자동 수행한다.
"""

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("OPENWEBUI_URL", "http://127.0.0.1:3000")
API_KEY = os.getenv("OPENWEBUI_API_KEY", "")
if not API_KEY:
    sys.exit("OPENWEBUI_API_KEY 가 .env 에 없습니다. Open WebUI → 설정 → 계정 → API 키 발급 후 추가하세요.")
KB_NAME = "KC_second_brain"
KB_DESC = "Obsidian 볼트 자동 동기화 지식베이스 (아카이브 파이프라인)"
VAULT = Path(r"C:\Users\OWNER\iCloudDrive\iCloud~md~obsidian\KC_second_brain")

# 노트가 들어 있는 구조화 폴더만 올린다(템플릿·첨부 등은 제외).
INCLUDE_DIRS = ("10_Professional", "20_Personal", "90_System")

H = {"Authorization": f"Bearer {API_KEY}"}


def get_or_create_kb() -> str:
    r = requests.get(f"{BASE}/api/v1/knowledge/", headers=H, timeout=15)
    r.raise_for_status()
    payload = r.json()
    existing = payload["items"] if isinstance(payload, dict) else payload
    for kb in existing:
        if kb.get("name") == KB_NAME:
            print(f"기존 지식베이스 재사용: {kb['id']}")
            return kb["id"]
    r = requests.post(
        f"{BASE}/api/v1/knowledge/create",
        headers=H,
        json={"name": KB_NAME, "description": KB_DESC},
        timeout=120,
    )
    r.raise_for_status()
    kb_id = r.json()["id"]
    print(f"지식베이스 생성: {kb_id}")
    return kb_id


def already_ingested(kb_id: str) -> set[str]:
    """지식베이스에 이미 연결된 파일명 집합."""
    r = requests.get(f"{BASE}/api/v1/knowledge/{kb_id}", headers=H, timeout=15)
    r.raise_for_status()
    files = r.json().get("files", []) or []
    return {f.get("meta", {}).get("name") or f.get("filename") for f in files}


def upload_file(path: Path) -> str:
    with path.open("rb") as fh:
        r = requests.post(
            f"{BASE}/api/v1/files/",
            headers=H,
            files={"file": (path.name, fh, "text/markdown")},
            timeout=120,
        )
    r.raise_for_status()
    return r.json()["id"]


# 임베딩 중 Ollama 가 잠깐 끊기면(모델 재로딩 등) 이 문구가 담긴 400 이 온다.
_TRANSIENT = "Cannot connect to host"


def link_to_kb(kb_id: str, file_id: str, retries: int = 4) -> None:
    """파일을 지식베이스에 연결(임베딩)한다. Ollama 일시 단절은 백오프 후 재시도한다."""
    for attempt in range(retries):
        r = requests.post(
            f"{BASE}/api/v1/knowledge/{kb_id}/file/add",
            headers=H,
            json={"file_id": file_id},
            timeout=300,  # 임베딩까지 동기적으로 일어나므로 넉넉히
        )
        if r.status_code == 400 and _TRANSIENT in r.text and attempt < retries - 1:
            time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s … Ollama 회복 대기
            continue
        r.raise_for_status()
        return


def main() -> None:
    notes = sorted(
        p
        for d in INCLUDE_DIRS
        for p in (VAULT / d).rglob("*.md")
        if p.is_file()
    )
    print(f"대상 노트: {len(notes)}개")
    if not notes:
        sys.exit("볼트에서 .md 노트를 찾지 못했습니다.")

    kb_id = get_or_create_kb()
    done = already_ingested(kb_id)
    if done:
        print(f"이미 올라간 파일 {len(done)}개는 건너뜁니다.")

    ok = skipped = failed = 0
    for i, note in enumerate(notes, 1):
        if note.name in done:
            skipped += 1
            continue
        try:
            fid = upload_file(note)
            link_to_kb(kb_id, fid)
            ok += 1
            print(f"[{i}/{len(notes)}] OK  {note.name}")
        except Exception as e:
            failed += 1
            detail = getattr(e, "response", None)
            msg = detail.text[:200] if detail is not None else str(e)
            print(f"[{i}/{len(notes)}] 실패 {note.name} -> {msg}")
        time.sleep(0.2)  # 서버 부담 완화

    print(f"\n완료: 성공 {ok}, 건너뜀 {skipped}, 실패 {failed}, 전체 {len(notes)}")


if __name__ == "__main__":
    main()
