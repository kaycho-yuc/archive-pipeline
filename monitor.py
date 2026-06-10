"""리소스 사용률(램·CPU·GPU·로드된 모델)을 주기적으로 CSV에 기록한다.

PC가 멈췄을 때 원인을 추적하기 위한 블랙박스 역할: 멈추기 직전의 마지막 줄이
당시 상태를 알려준다. run_watch.py 가 데몬 스레드로 시작하므로 감시기와 함께
켜지고 꺼진다(별도 자동 실행 등록 불필요).
"""

import csv
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

logger = logging.getLogger("archive_pipeline")

RESOURCE_LOG = Path(os.getenv("RESOURCE_LOG", "resource_log.csv"))
SAMPLE_INTERVAL = float(os.getenv("MONITOR_INTERVAL", "30"))  # 초
MAX_ROWS = 20000  # 약 1주일 분량. 넘으면 오래된 절반을 버린다.

_HEADER = [
    "time",
    "ram_used_gb",
    "ram_total_gb",
    "cpu_pct",
    "gpu_mem_used_mb",
    "gpu_mem_total_mb",
    "gpu_util_pct",
    "ollama_models",
]

# Windows에서 자식 프로세스 콘솔 창이 뜨지 않게 한다.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run_quiet(args: list[str], timeout: float = 10) -> str:
    """외부 명령을 조용히 실행해 stdout 을 돌려준다. 실패하면 빈 문자열."""
    try:
        out = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _gpu_stats() -> tuple[str, str, str]:
    """(사용 VRAM MB, 전체 VRAM MB, GPU 사용률 %). nvidia-smi 없으면 빈 값."""
    line = _run_quiet(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    parts = [p.strip() for p in line.split(",")]
    return tuple(parts) if len(parts) == 3 else ("", "", "")


def _ollama_models() -> str:
    """현재 Ollama 에 로드된 모델 목록("이름(크기); …"). 없으면 빈 문자열."""
    lines = _run_quiet(["ollama", "ps"]).splitlines()[1:]  # 헤더 제외
    models = []
    for line in lines:
        cols = [c for c in line.split("  ") if c.strip()]
        if len(cols) >= 3:
            models.append(f"{cols[0].strip()}({cols[2].strip()})")
    return "; ".join(models)


def sample_row() -> list[str]:
    """리소스 상태 한 줄을 측정해 돌려준다."""
    mem = psutil.virtual_memory()
    gpu_used, gpu_total, gpu_util = _gpu_stats()
    return [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"{mem.used / 2**30:.1f}",
        f"{mem.total / 2**30:.1f}",
        f"{psutil.cpu_percent(interval=1):.0f}",
        gpu_used,
        gpu_total,
        gpu_util,
        _ollama_models(),
    ]


def _append_row(row: list[str]) -> None:
    new_file = not RESOURCE_LOG.exists()
    with RESOURCE_LOG.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(_HEADER)
        writer.writerow(row)


def _trim_log() -> None:
    """로그가 MAX_ROWS 를 넘으면 헤더 + 최근 절반만 남긴다."""
    try:
        lines = RESOURCE_LOG.read_text(encoding="utf-8-sig").splitlines()
        if len(lines) > MAX_ROWS:
            kept = [lines[0]] + lines[-(MAX_ROWS // 2):]
            RESOURCE_LOG.write_text("\n".join(kept) + "\n", encoding="utf-8-sig")
    except Exception:
        logger.exception("리소스 로그 정리 실패")


def _monitor_loop() -> None:
    while True:
        try:
            _append_row(sample_row())
            _trim_log()
        except Exception:
            logger.exception("리소스 측정 실패(다음 주기에 재시도)")
        time.sleep(SAMPLE_INTERVAL)


def start_monitor() -> threading.Thread:
    """백그라운드 데몬 스레드로 모니터링을 시작한다(메인이 끝나면 같이 종료)."""
    thread = threading.Thread(target=_monitor_loop, name="resource-monitor", daemon=True)
    thread.start()
    logger.info("리소스 모니터 시작: %s (%.0fs 간격)", RESOURCE_LOG, SAMPLE_INTERVAL)
    return thread
