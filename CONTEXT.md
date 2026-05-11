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
- **Einzelinstanz-Lock versucht** (Commits 510dfb3, 7ce4bc5): Named Mutex via ctypes, dann TCP-Socket auf Port 47392 — beide Ansätze greifen technisch, lösen aber das Doppelinstanz-Problem nicht vollständig (Root Cause ungeklärt). Siehe ausführliche Analyse unten.

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

## Doppelinstanz-Problem – vollständige Analyse (ungeklärt)

### Symptom
Ein einziger Klick auf `start_hidden.vbs` erzeugt stets **2 Python-Instanzen** (`python main.py`). Mehrere weitere Klicks auf die VBS erzeugen keine weiteren Instanzen — der Lock funktioniert also für manuelle Doppelklicks, aber nicht beim allerersten Start.

### Beobachtungen (wmic-Ausgaben in dieser Session)
- Vor Start: nur DCP Automatisierung (PID 5944) — kein Server-Neustart
- Nach 1× VBS-Klick: immer 2× `python main.py` (wechselnde PIDs)
- Nach 4–5 weiteren Klicks: keine neuen Instanzen hinzugekommen → Lock verhindert extra Starts korrekt
- `taskkill` auf die alten PIDs: mehrfach "nicht gefunden" → Prozesse hatten sich selbst neu gestartet (via Auto-Updater `os.execv()`) bevor der Benutzer killen konnte

### Was überprüft und ausgeschlossen wurde
- **Windows Autostart-Ordner** (`C:\Users\Projektion\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`): kein Eintrag für Server-Neustart (nur OneNote, VirtualBox, Signiant App)
- **Task Scheduler** (`schtasks /query /fo LIST | findstr /i "neustart"`): kein Ergebnis — kein geplanter Task
- **`start_hidden.vbs` Inhalt geprüft**: enthält nur einen einzigen `objShell.Run`-Aufruf mit `0, False` → startet genau einen cmd-Prozess, kein Doppelstart durch VBS selbst
- **VBS startet nicht doppelt**: Inhalt ist eindeutig — `cmd /c cd /d "..." && venv\Scripts\activate.bat && python main.py`

### Alle drei Lock-Ansätze und warum sie scheiterten

**Versuch 1 — `msvcrt.locking()` (Datei-Byte-Lock, Windows)**
- Lock-Datei `cinema_reboot.lock`, Byte-Range-Lock auf Byte 0
- Problem: `msvcrt.locking()` sperrt nur eine Byte-Region innerhalb einer Datei. Bei `os.execv()` erbt der neue Prozess den Datei-Handle → neuer Prozess kann dieselbe Byte-Region erneut sperren (selber Prozess-Stammbaum, kein echtes Cross-Process-Lock)
- Ergebnis: scheitert bei os.execv()-Neustarts

**Versuch 2 — Windows Named Mutex via ctypes (Commit 510dfb3)**
- `ctypes.windll.kernel32.CreateMutexW(None, True, "Global\\CinemaRebootSingleInstance")`
- Lock-Check auf frühestmöglichen Zeitpunkt verschoben (direkt nach `parser.parse_args()`)
- Problem: `ctypes.windll.kernel32.GetLastError()` ist unzuverlässig — Python-interne Aufrufe zwischen `CreateMutexW` und `GetLastError` können den Windows-Fehlerwert (183 = ERROR_ALREADY_EXISTS) überschreiben. Folge: zweite Instanz sieht fälschlicherweise `last_err = 0` statt `183` → denkt sie ist die erste Instanz → läuft weiter
- Ergebnis: beide Instanzen denken sie halten den Mutex → beide laufen

**Versuch 3 — TCP-Socket auf 127.0.0.1:47392 (Commit 7ce4bc5)**
- `socket.bind(("127.0.0.1", 47392))` — atomar, kein ctypes, kein GetLastError-Problem
- `_release_single_instance_lock()` explizit vor jedem `os.execv()`-Aufruf → neuer Prozess kann Port sofort übernehmen
- Ergebnis: noch immer 2 Instanzen — Root Cause liegt tiefer (vor oder außerhalb des Lock-Checks)

### Wahrscheinlichster Root Cause (Theorie, nicht bewiesen)
Wenn bereits 2 Instanzen laufen (aus einem früheren Start) und beide den Auto-Updater aktiv haben:
1. Beide Instanzen erkennen einen neuen Git-Commit
2. Beide rufen `_release_single_instance_lock()` auf (geben Port frei) und dann `os.execv()` auf
3. Beide starten jeweils einen neuen Prozess — fast gleichzeitig
4. Beide neuen Prozesse versuchen `socket.bind(47392)` — weil sie so dicht beieinander starten, könnte es sein, dass Prozess A noch nicht vollständig beendet ist wenn Prozess B' den Port prüft und dann beide die Bindung schaffen (unwahrscheinlich, aber möglich bei sehr schneller CPU)

**Warum aber entstehen die ersten 2 aus 1 VBS-Klick?** — Das ist die eigentliche unbeantwortete Frage. Ohne direkten Windows-Zugriff und Process Monitor nicht lösbar.

### Was für die nächste Session gebraucht wird
- **Sysinternals Process Monitor** (<https://learn.microsoft.com/sysinternals/downloads/procmon>) auf dem Windows-PC ausführen, Filter auf `python.exe`, dann VBS klicken → zeigt genau welcher Eltern-Prozess `python main.py` ein zweites Mal startet und zu welcher Zeit
- Alternativ: `wmic process where "name='python.exe'" get ProcessId,ParentProcessId,CommandLine` — zeigt den Eltern-Prozess (ParentProcessId) beider Instanzen → klärt ob VBS, cmd, oder Auto-Updater der Auslöser ist

### Gefahr bei 2 gleichzeitigen Instanzen
- **Doppel-Reboot**: Race-Condition-Fenster ~1s — beide Instanzen prüfen `is_due()` bevor eine `in_progress` setzt → beide starten Reboot desselben Kinos
- **Telegram-Split**: Nachrichten gehen zufällig an Instanz A oder B → Menüs und Antworten inkonsistent
- **`state.json`-Konflikte**: Kein Cross-Process-Lock → simultane Schreibvorgänge möglich

## Versuch 4 – os.execv() → sys.exit(0) (09.05.2026)

**Theorie**: Wenn `os.execv()` auf Windows einen neuen Prozess startet UND gleichzeitig NSSM den sterbenden Prozess neu startet, entstehen 2 Instanzen aus dem Update-Zyklus. Mit `sys.exit(0)` startet NSSM genau einmal — kein zweiter Prozess durch `os.execv()` möglich.

**Ergebnis**: Fehlgeschlagen — kein NSSM vorhanden, VBS startet das Programm nicht neu. Nach `sys.exit(0)` läuft kein Programm mehr.

## Versuch 5 – subprocess.Popen (DETACHED + NEWGRP) + os._exit(0) (09.05.2026)

**Theorie**: `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` + `DEVNULL`-Redirects + `os._exit(0)` statt `os.execv()`. VBS direkt auf `venv\Scripts\python.exe` (kein cmd.exe).

**Ergebnis**: Noch immer 2 Instanzen sichtbar (wmic). Fehlendes `CREATE_BREAKAWAY_FROM_JOB` und falscher Platz des Restart-Codes im `finally`-Block.

## Versuch 6 – CREATE_BREAKAWAY_FROM_JOB + finally-Block-Timing (09.05.2026)

**Root Causes (aus Online-Recherche bestätigt)**:

1. **`CREATE_BREAKAWAY_FROM_JOB` fehlte**: Windows setzt Prozesse automatisch in Job-Objekte (WScript.Shell oder Windows-Session-Management). Ohne dieses Flag wird der Kindprozess in dasselbe Job-Objekt eingetragen — er ist nicht wirklich unabhängig. Hinzugefügt in beiden Popen-Aufrufen.

2. **`finally`-Block verzögert den Kill**: Das `if app_state.update_available:` stand NACH dem `finally:`-Block. Der `finally:`-Block rief `controller.stop()` auf (Telegram-Thread mit `join(timeout=5)`) → bis zu 5 Sekunden Verzögerung. Während dieser Zeit liefen BEIDE Instanzen gleichzeitig. Fix: Update-Restart-Block an den ANFANG des `finally:`-Blocks verschoben; `os._exit(0)` im Update-Fall vor Cleanup.

3. **`time.sleep(1)` unnötig**: Ein Listening-Socket gibt seinen Port bei `close()` sofort frei (kein TCP TIME_WAIT). Entfernt.

**Änderungen in `main.py`**:
- Startup-Update-Check (ca. Zeile 542–557): `time.sleep(1)` entfernt, `CREATE_BREAKAWAY_FROM_JOB` ergänzt
- `try/finally`-Block (ca. Zeile 590–617): `if app_state.update_available:` an Anfang des `finally:`-Blocks verschoben (BEVOR cleanup), `time.sleep(1)` entfernt, `CREATE_BREAKAWAY_FROM_JOB` ergänzt

## Offene Probleme

- **Doppelinstanz-Problem (Versuch 6 aktiv)**: Ob alle 3 Root Causes gemeinsam das Problem lösen, muss beim nächsten Auto-Update beobachtet werden.
- **`.git/FETCH_HEAD`: Permission denied** — tritt auf wenn git-Operationen von unterschiedlichen Windows-Nutzern/Prozessen gestartet werden. Behelfslösung: `takeown /f ".git" /r /d j` + `icacls ".git" /grant "Projektion:(OI)(CI)F" /T`.
- **Kein automatisches Test-Framework**: Alle Tests erfolgen manuell via `--dry-run` und `--status`.

## Nächster Schritt

- Nach nächstem Auto-Update: `wmic process where "name='python.exe'" get ProcessId,ParentProcessId,CommandLine /format:list` ausführen → prüfen ob noch 2 Instanzen sichtbar sind
- Falls noch immer 2: Sysinternals Process Monitor auf Windows-PC ausführen, Filter `python.exe`, VBS klicken → zeigt welcher Eltern-Prozess die zweite Instanz startet
- Falls Telegram wieder nicht reagiert: Logs in `logs/` prüfen, auf Exception-Muster im `_run_loop` achten
