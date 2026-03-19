@echo off
REM ============================================================
REM  Cinema Server Reboot – Starten
REM ============================================================

cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py %*
pause
