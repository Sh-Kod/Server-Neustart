' Startet den Cinema-Watchdog versteckt im Hintergrund
Dim objShell, objFSO, scriptDir
Set objShell = WScript.CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.Run """" & scriptDir & "\venv\Scripts\pythonw.exe"" """ & scriptDir & "\watchdog_cinema.py""", 0, False
Set objShell = Nothing
Set objFSO = Nothing
