@echo off
REM ============================================================
REM  Cinema Server Reboot – Starten
REM ============================================================

cd /d "%~dp0"
call venv\Scripts\activate.bat 2>nul
python main.py %*
pause
