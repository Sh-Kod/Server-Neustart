' Startet das Programm versteckt im Hintergrund (kein Konsolenfenster)
' Nützlich für den Autostart via Windows Task Scheduler
Dim objShell
Set objShell = WScript.CreateObject("WScript.Shell")
objShell.Run "cmd /c cd /d """ & WScript.ScriptFullName & _
    """ & venv\Scripts\activate.bat & python main.py", 0, False
Set objShell = Nothing
