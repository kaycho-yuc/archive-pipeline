# AI 스택을 잠시 멈춰 RAM/VRAM 을 비운다 (Revit·Enscape 같은 수동 작업 전에 실행).
# 되돌리려면 resume_ai.ps1 을 실행한다. 볼트·노트·로그는 전혀 건드리지 않는다.

Write-Host "AI 스택을 멈추고 메모리를 비웁니다..." -ForegroundColor Cyan

# 1) 감시기(+리소스 모니터) 정지 — 새 파일이 들어와도 Ollama 를 깨우지 않게 한다.
try {
    Stop-ScheduledTask -TaskName "ArchivePipelineWatch" -ErrorAction Stop
    Write-Host "  [O] 파일 감시기 정지" -ForegroundColor Green
} catch { Write-Host "  [-] 감시기는 이미 멈춰 있음" -ForegroundColor DarkGray }

# 2) 감시기가 띄운 python 프로세스 종료(혹시 남아 있으면).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -match "run_watch|watch.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 3) Ollama 에 올라온 모델을 모두 내려 VRAM/RAM 즉시 회수 (가장 큰 효과).
$loaded = (& ollama ps) | Select-Object -Skip 1
if ($loaded) {
    foreach ($line in $loaded) {
        $name = ($line -split '\s{2,}')[0].Trim()
        if ($name) { & ollama stop $name 2>$null; Write-Host "  [O] 모델 내림: $name" -ForegroundColor Green }
    }
} else { Write-Host "  [-] 로드된 모델 없음" -ForegroundColor DarkGray }

# 4) Open WebUI 컨테이너 정지 (RAG 임베딩 호출도 멈춤). 데이터 볼륨은 보존된다.
try {
    docker stop open-webui 2>$null | Out-Null
    Write-Host "  [O] Open WebUI 컨테이너 정지" -ForegroundColor Green
} catch { Write-Host "  [-] Docker 미실행 또는 컨테이너 없음" -ForegroundColor DarkGray }

Start-Sleep -Seconds 2
$os = Get-CimInstance Win32_OperatingSystem
$gpu = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null)
Write-Host ("완료. RAM 사용 {0:N1} GB / {1:N1} GB,  VRAM {2} MB" -f `
    (($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB), ($os.TotalVisibleMemorySize/1MB), $gpu) -ForegroundColor Cyan
Write-Host "Revit/Enscape 작업이 끝나면 resume_ai.ps1 로 다시 켜세요." -ForegroundColor Yellow
