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

:: NSSM suchen – zuerst im Programmordner, dann im PATH
set NSSM_EXE=
if exist "%NSSM_EXE%" (
    set NSSM_EXE=%PROGRAM_DIR%nssm.exe
    echo [OK] NSSM gefunden: %PROGRAM_DIR%nssm.exe
    goto :nssm_ok
)
for /f "tokens=*" %%i in ('where nssm 2^>nul') do (
    set NSSM_EXE=%%i
    echo [OK] NSSM gefunden: %%i
    goto :nssm_ok
)
echo.
echo [FEHLER] nssm.exe nicht gefunden!
echo Bitte herunterladen von: https://nssm.cc/download
echo Die nssm.exe in diesen Ordner legen: %PROGRAM_DIR%
echo.
pause
exit /b 1
:nssm_ok

:: Dienst entfernen falls schon vorhanden
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorlevel% == 0 (
    echo [INFO] Bestehender Dienst wird entfernt...
    "%NSSM_EXE%" stop "%SERVICE_NAME%" confirm >nul 2>&1
    "%NSSM_EXE%" remove "%SERVICE_NAME%" confirm
)

echo.
echo [INFO] Installiere Dienst "%SERVICE_NAME%"...

:: Dienst installieren
"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_EXE%" main.py

:: Dienst konfigurieren
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%PROGRAM_DIR%"
"%NSSM_EXE%" set "%SERVICE_NAME%" DisplayName "Cinema Server Auto Reboot"
"%NSSM_EXE%" set "%SERVICE_NAME%" Description "Automatischer Kino-Server Neustart mit Telegram-Steuerung"
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%PROGRAM_DIR%logs\service_stdout.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%PROGRAM_DIR%logs\service_stderr.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateBytes 10485760

:: Bei Absturz automatisch neu starten (nach 5 Sekunden)
"%NSSM_EXE%" set "%SERVICE_NAME%" AppExit Default Restart
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRestartDelay 5000

:: logs Ordner erstellen falls nicht vorhanden
if not exist "%PROGRAM_DIR%logs" mkdir "%PROGRAM_DIR%logs"

echo.
echo [INFO] Starte Dienst...
"%NSSM_EXE%" start "%SERVICE_NAME%"

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
