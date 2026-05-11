# Cinema Server Reboot – CLAUDE.md

## Projektbeschreibung

Automatisches Reboot-Tool für Kinoprojektions-Server (Doremi/GDC). Startet jeden Donnerstag zwischen 05:00–12:00 Uhr alle konfigurierten Kino-Server neu, sofern keine Vorstellung läuft. Steuerung und Statusüberwachung per Telegram-Bot.

## Wichtige Dateien und Ordner

```
main.py                            # Einstiegspunkt, Hauptschleife, Argument-Parsing
config.yaml.example                # Konfigurationsvorlage (niemals config.yaml committen!)
cinema_reboot/
  state_manager.py                 # Persistenter JSON-Zustand aller Kinos (thread-safe)
  reboot_engine.py                 # Kernlogik: Login, Pre-Check, Reboot-Flow
  scheduler.py                     # Zeitplanung (Wartungsfenster, Retry-Logik)
  telegram_controller.py           # Telegram-Bot Long-Polling, Befehls-Verarbeitung
  telegram_sender.py               # Telegram-Nachrichten senden
  app_state.py                     # Gemeinsamer Laufzeit-Zustand (Pause, Shutdown, Pending-Runs)
  config.py                        # Konfiguration laden aus config.yaml
  updater.py                       # Auto-Update via git pull, background thread
  dialog_manager.py                # DialogManager für Telegram-Menüs (Reboot-Untermenü)
cinema_projector/
  lamp_controller.py               # LampTelegramController (Lampe/Health/Programm-Menüs)
  lamp_monitor.py                  # SNMP-Abfrage Projektor-Lampenstunden
  health_monitor.py                # TCP-Health-Check alle Projektoren
  lamp_config.py                   # Lampen-Konfiguration laden
```

## Build- und Test-Befehle

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Programm starten
python main.py

# Status aller Kinos anzeigen (kein Reboot)
python main.py --status

# Einzelnes Kino sofort neu starten
python main.py --run kino01

# Dry-Run (navigiert, sendet aber keinen echten Reboot-Befehl)
python main.py --dry-run

# Projektor-Lampenstatus testen
python main.py --test-projector kino01
python main.py --test-lamps
```

Kein automatisches Test-Framework vorhanden. Tests erfolgen manuell via `--dry-run` und `--status`.

## Architektur- und Design-Entscheidungen

- **Zwei Telegram-Dialog-Systeme**: `_lamp_dlg` (dict pro Chat, Lampe/Health/Programm) und `_dm` (DialogManager global, Reboot-Untermenüs). Beide müssen beim Cancel/Reset zurückgesetzt werden.
- **State-Persistenz**: `state_manager.py` schreibt nach jeder Änderung in `state.json`. Alle Methoden sind Lock-geschützt (nur innerhalb eines Prozesses — kein Cross-Process-Lock).
- **Status-Lifecycle**: `idle` → `in_progress` → `success` / `error` / `blocked_*` / `offline` / `ui_unclear`. `reset_for_new_day()` setzt täglich zurück — schützt aber laufende Prozesse desselben Tages via `last_attempt_at[:10] == today`.
- **Auto-Updater**: Background-Thread prüft alle 30s auf neue Git-Commits. Bei Update → `app_state.signal_update()` → `shutdown_requested=True` → `_release_single_instance_lock()` → `os.execv()` Neustart. Startup prüft ebenfalls mit `check_and_update()`.
- **Einzelinstanz-Lock**: TCP-Socket-Bindung auf `127.0.0.1:47392` in `_acquire_single_instance_lock()`. Muss vor `os.execv()` explizit freigegeben werden (`_release_single_instance_lock()`), damit der Neustart-Prozess die Sperre übernehmen kann.
- **Bekanntes Problem – Doppelinstanz**: 1 VBS-Klick erzeugt trotz Lock 2 Python-Instanzen. Root Cause ungeklärt. **WICHTIG: Nicht nochmal dieselben Ansätze probieren** — alle drei wurden bereits versucht und scheiterten:
  - `msvcrt.locking()`: Handle wird bei `os.execv()` vererbt → neuer Prozess kann dieselbe Byte-Region erneut sperren
  - Named Mutex via `ctypes.windll.kernel32.CreateMutexW`: `GetLastError()` nach dem ctypes-Aufruf ist unzuverlässig — Python-interne Aufrufe zwischen `CreateMutexW` und `GetLastError` können den Fehlerwert 183 (ERROR_ALREADY_EXISTS) überschreiben → zweite Instanz denkt irrtümlich sie ist erste
  - TCP-Socket `socket.bind(("127.0.0.1", 47392))`: ebenfalls implementiert + `_release_single_instance_lock()` vor `os.execv()` — verhindert manuelle Doppelklicks korrekt, aber nicht die 2. Instanz beim allerersten Start
  - Ausgeschlossen: Windows Autostart-Ordner (leer), Task Scheduler (kein Eintrag), VBS-Inhalt (nur ein Run-Aufruf)
  - Risiken: Race-Condition beim Reboot (~1s Fenster), Telegram-Antworten auf zufällige Instanz, state.json-Schreibkonflikte
  - **Nächster Schritt**: `wmic process where "name='python.exe'" get ProcessId,ParentProcessId,CommandLine` — zeigt welcher Elternprozess die 2. Instanz startet. Oder Sysinternals Process Monitor.
- **Adaptives Retry-Intervall**: `scheduler.smart_next_retry_time()` — normales Intervall (60 Min) außerhalb der letzten Stunde, kurzes Intervall (15 Min) in der letzten Stunde des Wartungsfensters. Konfigurierbar via `short_retry_interval_minutes` / `short_retry_threshold_minutes`.
- **Pending-Runs (manuelle Sofortläufe)**: `app_state.request_run(cinema_id)` → nächster Loop-Zyklus verarbeitet via `engine.run()` ohne weitere Checks.
- **Parallelisierung**: Optional via `parallel_reboot: true` in config; nutzt `engine.run_parallel()`.

## Code-Style-Regeln und Dinge, die zu vermeiden sind

- Alle state-mutierenden Methoden in `StateManager` immer mit `self._lock` absichern.
- `_save()` in `StateManager` nur mit bereits gehaltenem Lock aufrufen.
- `_get_cinema()` niemals außerhalb des Locks aufrufen.
- Keine Kommentare schreiben, die das WAS erklären — nur das WARUM wenn nicht offensichtlich.
- `config.yaml` niemals committen (enthält Passwörter/IPs).
- Exception-Handler in `_run_loop` immer per-Update (nicht per-Batch) — sonst fallen ganze Batches aus.
- Beim Cancel im Telegram-Handler immer BEIDE Dialog-Systeme zurücksetzen: `_ld_reset(chat_id)` UND `_dm.reset()`.
- `_release_single_instance_lock()` immer vor `os.execv()` aufrufen — sonst kann der neue Prozess die Sperre nicht übernehmen.

## Typische Workflows

### Bug fixen
1. `python main.py --status` → aktuellen Zustand verstehen
2. Logs in `logs/` prüfen (rotating, täglich)
3. Fix in der betroffenen Datei
4. Mit `--dry-run` testen
5. Commit auf Feature-Branch, Push zu origin

### Kino-Status manuell zurücksetzen
State-JSON direkt editieren (`state.json`, Pfad in config.yaml unter `state_file`) oder den Eintrag löschen → beim nächsten Start wird er als `idle` neu angelegt.

### Neues Kino hinzufügen
`config.yaml` → Abschnitt `cinemas` → neue Einträge mit `id`, `name`, `ip`, optional `projector_ip`, `projector_type`, `enabled`.

### Telegram-Bot reagiert nicht
1. Programm neu starten (`Ctrl+C` + `python main.py`)
2. Logs auf Exception-Muster prüfen
3. Sicherstellen dass `_run_loop`-Exception-Handler per-Update greift (nicht per-Batch)

### Git pull schlägt fehl (Permission denied auf .git/FETCH_HEAD)
Tritt auf wenn git-Operationen von unterschiedlichen Windows-Nutzern gestartet wurden:
```
takeown /f ".git" /r /d j
icacls ".git" /grant "Projektion:(OI)(CI)F" /T
```

## Sprach- und Kommunikationsregeln

- Antworte immer auf Deutsch, unabhängig von der Sprache der Eingabe.
- Alle Erklärungen, Kommentare, Fehlermeldungen und Rückmeldungen auf Deutsch verfassen.
- Codekommentare ebenfalls auf Deutsch schreiben.
