# pause_ai.ps1 로 멈춘 AI 스택을 다시 켠다 (수동 작업이 끝난 뒤 실행).

Write-Host "AI 스택을 다시 시작합니다..." -ForegroundColor Cyan

# 1) Docker 가 떠 있는지 확인하고, Open WebUI 컨테이너 시작.
# Docker 가 아예 없는 머신(클라우드 백엔드로 도는 N100 등)에서는 통째로 건너뛴다.
# 안 그러면 Docker Desktop 을 띄우려다 실패한 뒤 3초 x 40회, 2분을 기다린다.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "  [-] Docker 없음 — 건너뜀(RAG 는 클라우드 백엔드 사용)" -ForegroundColor DarkGray
} else {
    $dockerUp = $false
    try { docker info 2>$null | Out-Null; $dockerUp = $? } catch {}
    if (-not $dockerUp) {
        Write-Host "  [..] Docker Desktop 기동 중..." -ForegroundColor DarkGray
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        for ($i=0; $i -lt 40; $i++) { Start-Sleep 3; try { docker info 2>$null | Out-Null; if ($?) { break } } catch {} }
    }
    try {
        docker start open-webui 2>$null | Out-Null
        Write-Host "  [O] Open WebUI 컨테이너 시작" -ForegroundColor Green
    } catch { Write-Host "  [-] 컨테이너 시작 실패 — Docker 상태 확인 필요" -ForegroundColor Yellow }
}

# 2) 파일 감시기(+리소스 모니터) 다시 시작.
try {
    Start-ScheduledTask -TaskName "ArchivePipelineWatch" -ErrorAction Stop
    Write-Host "  [O] 파일 감시기 시작" -ForegroundColor Green
} catch { Write-Host "  [-] 감시기 작업을 찾지 못함" -ForegroundColor Yellow }

Write-Host "완료. _inbox 감시와 RAG 가 다시 동작합니다." -ForegroundColor Cyan
Write-Host "(모델은 첫 질문 때 자동으로 다시 로드됩니다.)" -ForegroundColor DarkGray
