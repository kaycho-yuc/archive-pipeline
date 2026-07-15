@echo off
REM 더블클릭으로 AI 스택 다시 켜기 — pause_ai 로 멈춘 뒤 작업이 끝나면 실행.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0resume_ai.ps1"
echo.
echo 완료. 봇이 다시 질문에 답합니다. 창을 닫아도 됩니다.
pause
