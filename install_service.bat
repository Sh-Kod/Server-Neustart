@echo off
:: ============================================================
:: Cinema Server Auto Reboot – Windows-Dienst Installation
:: ============================================================
:: Dieses Script installiert das Programm als Windows-Dienst
:: mit NSSM (Non-Sucking Service Manager).
::
:: VORAUSSETZUNGEN:
::   - NSSM muss heruntergeladen sein: https://nssm.cc/download
::   - nssm.exe in diesen Ordner legen (neben install_service.bat)
::   - Python muss installiert sein und im PATH
::
:: AUSFÜHREN: Als Administrator ausführen (Rechtsklick → Als Admin)
:: ============================================================

setlocal EnableDelayedExpansion

set SERVICE_NAME=CinemaServerReboot
set PROGRAM_DIR=%~dp0
set MAIN_SCRIPT=%PROGRAM_DIR%main.py

:: Python-Pfad automatisch ermitteln
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    set PYTHON_EXE=%%i
    goto :found_python
)
echo [FEHLER] Python wurde nicht gefunden!
echo Bitte Python installieren und sicherstellen dass es im PATH ist.
pause
exit /b 1

:found_python
echo [OK] Python gefunden: %PYTHON_EXE%

:: NSSM prüfen
if not exist "%PROGRAM_DIR%nssm.exe" (
    echo.
    echo [FEHLER] nssm.exe nicht gefunden!
    echo.
    echo Bitte herunterladen von: https://nssm.cc/download
    echo Die nssm.exe ^(aus dem win64 Ordner^) in diesen Ordner legen:
    echo   %PROGRAM_DIR%
    echo.
    pause
    exit /b 1
)
echo [OK] NSSM gefunden

:: Dienst entfernen falls schon vorhanden
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% == 0 (
    echo [INFO] Bestehender Dienst wird entfernt...
    "%PROGRAM_DIR%nssm.exe" stop "%SERVICE_NAME%" confirm >nul 2>&1
    "%PROGRAM_DIR%nssm.exe" remove "%SERVICE_NAME%" confirm
)

echo.
echo [INFO] Installiere Dienst "%SERVICE_NAME%"...

:: Dienst installieren
"%PROGRAM_DIR%nssm.exe" install "%SERVICE_NAME%" "%PYTHON_EXE%" main.py

:: Dienst konfigurieren
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppDirectory "%PROGRAM_DIR%"
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" DisplayName "Cinema Server Auto Reboot"
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" Description "Automatischer Kino-Server Neustart mit Telegram-Steuerung"
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppStdout "%PROGRAM_DIR%logs\service_stdout.log"
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppStderr "%PROGRAM_DIR%logs\service_stderr.log"
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppRotateFiles 1
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppRotateBytes 10485760

:: Bei Absturz automatisch neu starten (nach 5 Sekunden)
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppExit Default Restart
"%PROGRAM_DIR%nssm.exe" set "%SERVICE_NAME%" AppRestartDelay 5000

:: logs Ordner erstellen falls nicht vorhanden
if not exist "%PROGRAM_DIR%logs" mkdir "%PROGRAM_DIR%logs"

echo.
echo [INFO] Starte Dienst...
"%PROGRAM_DIR%nssm.exe" start "%SERVICE_NAME%"

echo.
echo ============================================================
echo  FERTIG! Dienst "%SERVICE_NAME%" wurde installiert.
echo ============================================================
echo.
echo  - Startet automatisch beim Windows-Start
echo  - Startet automatisch neu bei Absturz (nach 5 Sek.)
echo  - Logs: %PROGRAM_DIR%logs\
echo.
echo  Verwaltung:
echo    Dienst stoppen:    nssm stop %SERVICE_NAME%
echo    Dienst starten:    nssm start %SERVICE_NAME%
echo    Dienst entfernen:  nssm remove %SERVICE_NAME%
echo    Status prüfen:     sc query %SERVICE_NAME%
echo.
pause
