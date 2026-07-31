' 작업 스케줄러용 무창(無窓) 런처.
'
' 왜 필요한가: uv 가 만든 .venv\Scripts\pythonw.exe 는 44KB짜리 '징검다리'라서 실제
' 인터프리터를 다시 띄우는데, 콘솔용인 python.exe 를 띄운다. 그래서 창 없는 실행 파일로
' 시작해도 검은 콘솔 창이 남는다(작업 스케줄러의 Hidden 설정은 작업 목록에서 작업을 숨길
' 뿐 창과 무관하다). WScript.Shell.Run 의 두 번째 인자 0 이 창을 숨긴 채로 실행한다.
'
' 경로는 이 파일 위치에서 구하므로 저장소를 옮겨도 그대로 동작한다.

Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

' 세 번째 인자 True = 감시기가 끝날 때까지 기다린다. 기다리지 않으면 wscript 가 즉시
' 끝나 작업 상태가 Ready 로 돌아가고, Stop-ScheduledTask 로 감시기를 멈출 수 없게 된다.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Run """" & root & "\.venv\Scripts\pythonw.exe"" run_watch.py", 0, True
