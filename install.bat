@echo off
setlocal EnableDelayedExpansion
title Cinema Server Reboot - Installation
cd /d "%~dp0"

echo.
echo ===========================================================
echo   Cinema Server Reboot - Einmalige Installation
echo ===========================================================
echo.

:: ----------------------------------------------------------------
:: 1. Python prüfen
:: ----------------------------------------------------------------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Python ist nicht installiert!
    echo.
    echo Bitte Python 3.11 oder neuer installieren:
    echo   https://www.python.org/downloads/
    echo.
    echo Wichtig: Beim Installieren unbedingt
    echo   "Add Python to PATH" aktivieren!
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v gefunden.

:: ----------------------------------------------------------------
:: 2. Git prüfen (wird fuer Auto-Updates benoetigt)
:: ----------------------------------------------------------------
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Git nicht gefunden.
    echo        Auto-Updates funktionieren nur mit Git.
    echo        Optional installieren: https://git-scm.com/download/win
) else (
    for /f "tokens=*" %%v in ('git --version') do echo [OK] %%v gefunden.
)
echo.

:: ----------------------------------------------------------------
:: 3. Virtuelle Umgebung erstellen
:: ----------------------------------------------------------------
if exist venv (
    echo [1/4] Virtuelle Umgebung bereits vorhanden.
) else (
    echo [1/4] Erstelle virtuelle Umgebung...
    python -m venv venv
    if !errorlevel! neq 0 (
        echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden!
        pause
        exit /b 1
    )
    echo [OK] Virtuelle Umgebung erstellt.
)

:: ----------------------------------------------------------------
:: 4. Abhaengigkeiten installieren / aktualisieren
:: ----------------------------------------------------------------
echo [2/4] Installiere Abhaengigkeiten...
venv\Scripts\pip install --quiet --upgrade -r requirements.txt
if %errorlevel% neq 0 (
    echo [FEHLER] Pakete konnten nicht installiert werden!
    pause
    exit /b 1
)
echo [OK] Abhaengigkeiten installiert.

:: ----------------------------------------------------------------
:: 5. Playwright Chromium installieren
:: ----------------------------------------------------------------
echo [3/4] Installiere Playwright Chromium (einmalig, ~150 MB)...
venv\Scripts\playwright install chromium
if %errorlevel% neq 0 (
    echo [FEHLER] Playwright Chromium konnte nicht installiert werden!
    pause
    exit /b 1
)
echo [OK] Playwright Chromium installiert.

:: ----------------------------------------------------------------
:: 6. Windows-Autostart via Task Scheduler
:: ----------------------------------------------------------------
echo.
echo [4/4] Windows-Autostart einrichten?
echo       Das Programm startet dann automatisch beim naechsten Windows-Start.
echo.
set /p AUTOSTART="Autostart einrichten? [J/N]: "
if /i "!AUTOSTART!"=="J" (
    schtasks /create ^
        /tn "CinemaServerReboot" ^
        /tr "wscript.exe \"%~dp0start_hidden.vbs\"" ^
        /sc onstart ^
        /rl highest ^
        /f >nul 2>&1
    if !errorlevel! neq 0 (
        echo [WARNUNG] Task Scheduler Eintrag konnte nicht erstellt werden.
        echo           Skript bitte als Administrator ausfuehren.
    ) else (
        echo [OK] Autostart eingerichtet - startet ab naechstem Windows-Start.
    )
) else (
    echo [INFO] Autostart uebersprungen.
)

:: ----------------------------------------------------------------
:: 7. config.yaml pruefen
:: ----------------------------------------------------------------
echo.
if not exist config.yaml (
    echo [WARNUNG] config.yaml nicht gefunden!
    echo           Bitte config.yaml.example kopieren, umbenennen
    echo           und Telegram-Token sowie Kino-IPs eintragen.
) else (
    echo [OK] config.yaml gefunden.
)

echo.
echo ===========================================================
echo   Installation abgeschlossen!
echo.
echo   Naechste Schritte:
echo     1. config.yaml pruefen (Telegram-Token, Kino-IPs)
echo     2. Programm starten mit: start.bat
echo.
echo   Updates: Das Programm aktualisiert sich beim Start
echo            automatisch, wenn Git installiert ist.
echo ===========================================================
echo.
pause
