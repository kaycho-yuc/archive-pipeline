@echo off
REM 더블클릭으로 AI 스택 잠시 멈추기(RAM/VRAM 회수) — Revit/Enscape 등 무거운 작업 전에.
REM %~dp0 = 이 파일이 있는 폴더. 어디서 실행해도 옆의 pause_ai.ps1 을 찾는다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pause_ai.ps1"
echo.
echo 완료. 창을 닫아도 됩니다. (다시 켜려면 resume_ai.bat 더블클릭)
pause
