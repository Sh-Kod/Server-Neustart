' Startet das Programm versteckt im Hintergrund (kein Konsolenfenster)
' Nützlich für den Autostart via Windows Task Scheduler
Dim objShell, objFSO, scriptDir
Set objShell = WScript.CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.Run "cmd /c cd /d """ & scriptDir & """ && venv\Scripts\activate.bat && python main.py", 0, False
Set objShell = Nothing
Set objFSO = Nothing
