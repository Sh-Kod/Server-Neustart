@echo off
REM ============================================================
REM  Cinema Server Reboot – Erstinstallation (Windows)
REM  Führe dieses Skript einmalig aus, um alles einzurichten.
REM ============================================================

echo.
echo ============================================================
echo   Cinema Server Reboot – Setup
echo ============================================================
echo.

REM Python prüfen
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo FEHLER: Python nicht gefunden!
    echo Bitte Python 3.11+ installieren: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Erstelle virtuelle Umgebung...
python -m venv venv
if %errorlevel% neq 0 (
    echo FEHLER beim Erstellen der virtuellen Umgebung!
    pause
    exit /b 1
)

echo [2/4] Aktiviere virtuelle Umgebung...
call venv\Scripts\activate.bat

echo [3/4] Installiere Abhängigkeiten...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo FEHLER beim Installieren der Pakete!
    pause
    exit /b 1
)

echo [4/4] Installiere Playwright-Browser...
playwright install chromium
if %errorlevel% neq 0 (
    echo FEHLER beim Installieren von Playwright Chromium!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup erfolgreich abgeschlossen!
echo.
echo   Nächste Schritte:
echo   1. Öffne config.yaml und trage deinen Telegram Bot-Token
echo      und Chat-ID ein.
echo   2. Setze dry_run: true (Standard) für erste Tests.
echo   3. Starte mit: start.bat
echo ============================================================
echo.
pause
