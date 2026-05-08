# CONTEXT.md

## Erledigt

- **Bug 1 behoben**: `reset_for_new_day()` in `state_manager.py` — hat bisher `in_progress`-Kinos aus abgestürzten Vorläufen (andere Tage) niemals zurückgesetzt → 12 von 13 Kinos seit 16. April nicht rebootet. Fix: nur laufende Prozesse desselben Tages schützen (`last_attempt_at[:10] == today`).
- **Bug 2 behoben**: `_run_loop()` in `telegram_controller.py` — Exception-Handler umschloss den gesamten Update-Batch; ein Fehler ließ alle verbleibenden Updates fallen → Bot reagierte nicht mehr. Fix: Exception-Handler per-Update in die for-Schleife verschoben.
- **Bug 3 (defensiv) behoben**: Cancel-Handler in `lamp_controller.py` — rief nur `_ld_reset()` auf, nicht `_dm.reset()`. Fix: `self._dm.reset()` ergänzt.
- **State zurückgesetzt**: Alle 13 Kinos für Donnerstag 30.04.2026 manuell auf `idle` zurückgesetzt (state.json).
- **Alle 13 Kinos erfolgreich neu gestartet** am 30.04.2026 nach Programm-Neustart.
- **Kino 05 `in_progress` erklärt**: Reboot-Befehl wurde um 06:53 gesendet, aber das Programm wurde während Schritt 4 (Warte auf Wiederherstellung) durch ein Auto-Update neugestartet → `set_success()` nie aufgerufen. Physisch läuft der Server korrekt.
- **Bug 4 behoben**: Retry-jede-Minute-Bug in `scheduler.py` — wenn ein Kino durch Playback/Transfer blockiert war und die Retry-Zeit außerhalb des Wartungsfensters lag (`next_retry=None`), fiel `is_due()` in den Planungs-Modus und gab jeden Loop-Zyklus (60s) `True` zurück → versuchte jede Minute zu rebooten. Fix: explizite Prüfung auf `BLOCKED_BY_PLAYBACK`/`BLOCKED_BY_TRANSFER` ohne Retry → sofort `False`.
- **Feature**: Adaptives Retry-Intervall in der letzten Stunde des Wartungsfensters (commit 1abf4b2) — in den letzten 60 Minuten wird alle 15 Minuten statt alle 60 Minuten versucht. Konfigurierbar via `short_retry_interval_minutes` (Standard 15) und `short_retry_threshold_minutes` (Standard 60) in config.yaml.
- **Einzelinstanz-Lock versucht** (Commits 510dfb3, 7ce4bc5): Named Mutex via ctypes, dann TCP-Socket auf Port 47392 — beide Ansätze greifen technisch, lösen aber das Doppelinstanz-Problem nicht vollständig (Root Cause ungeklärt).

## Geänderte Dateien (gesamt)

- `cinema_reboot/state_manager.py` — `reset_for_new_day()`: `IN_PROGRESS`-Schutz nur für heutigen Tag
- `cinema_reboot/telegram_controller.py` — `_run_loop()`: per-Update Exception-Handling statt per-Batch
- `cinema_projector/lamp_controller.py` — Cancel-Handler: `self._dm.reset()` ergänzt
- `cinema_reboot/scheduler.py` — `is_due()`: BLOCKED-ohne-Retry → False; `smart_next_retry_time()` neu
- `cinema_reboot/config.py` — `short_retry_interval_minutes`, `short_retry_threshold_minutes` neu
- `cinema_reboot/reboot_engine.py` — `_process_outcome()` + `run()`: nutzen `smart_next_retry_time()`
- `main.py` — Einzelinstanz-Lock (TCP-Socket Port 47392), `_release_single_instance_lock()` vor `os.execv()`
- `CLAUDE.md` — aktualisiert
- `CONTEXT.md` — diese Datei

## Offene Probleme

- **Doppelinstanz-Problem (ungeklärt)**: Ein einziger VBS-Klick startet stets 2 Python-Instanzen. Alle bisherigen Sperr-Ansätze (msvcrt, Named Mutex, TCP-Socket) verhindern zusätzliche manuelle Starts korrekt, aber nicht die 2. Instanz beim ersten Start. Vermutlicher Root Cause: Auto-Updater in beiden alten Instanzen löst gleichzeitig `os.execv()` aus → beide starten neue Instanzen, bevor die Sperre greifen kann.
  - **Gefahr**: Doppel-Reboot möglich (Race-Condition-Fenster ~1s), Telegram-Antworten auf zufällige Instanz verteilt, `state.json`-Schreibkonflikte ohne Cross-Process-Lock.
  - **Status**: Wird akzeptiert bis zur nächsten Session mit direktem Windows-Zugriff für Root-Cause-Analyse.
- **`.git/FETCH_HEAD`: Permission denied** — tritt auf wenn git-Operationen von unterschiedlichen Windows-Nutzern/Prozessen gestartet werden. Behelfslösung: `takeown /f ".git" /r /d j` + `icacls ".git" /grant "Projektion:(OI)(CI)F" /T`.
- **Kein automatisches Test-Framework**: Alle Tests erfolgen manuell via `--dry-run` und `--status`.

## Nächster Schritt

- **Donnerstag 07.05.2026 ab 05:00 Uhr** beobachten: Starten alle 13 Kinos automatisch neu?
- Prüfen ob das adaptive Retry-Intervall (15 Min in letzter Stunde) korrekt funktioniert
- Doppelinstanz-Problem: Root Cause muss via Windows-Prozessmonitor (z.B. Process Monitor von Sysinternals) ermittelt werden — zeigt genau, welcher Prozess `python main.py` ein zweites Mal startet
- Falls Telegram wieder nicht reagiert: Logs in `logs/` prüfen, auf Exception-Muster im `_run_loop` achten
