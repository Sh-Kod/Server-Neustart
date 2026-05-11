' Startet das Programm versteckt im Hintergrund (kein Konsolenfenster)
' Nützlich für den Autostart via Windows Task Scheduler
Dim objShell, objFSO, scriptDir
Set objShell = WScript.CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.Run """" & scriptDir & "\venv\Scripts\python.exe"" """ & scriptDir & "\main.py""", 0, False
Set objShell = Nothing
Set objFSO = Nothing
