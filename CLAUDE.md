# Cinema Server Reboot

Automatisches Reboot-Tool für Kinoprojektions-Server (Doremi/GDC). Startet jeden Donnerstag zwischen 05:00–12:00 Uhr alle konfigurierten Kino-Server neu, sofern keine Vorstellung läuft. Steuerung und Statusüberwachung per Telegram-Bot.

**Tech Stack:** Python 3, YAML, Telegram Bot API, SNMP, NSSM (Windows-Dienst)

## WHAT — Dateien & Ordner

```
main.py
config.yaml.example          ← niemals config.yaml committen!
cinema_reboot/
  state_manager.py
  reboot_engine.py
  scheduler.py
  telegram_controller.py
  telegram_sender.py
  app_state.py
  config.py
  updater.py
  dialog_manager.py
cinema_projector/
  lamp_controller.py
  lamp_monitor.py
  health_monitor.py
  lamp_config.py
```

## WHY — Architekturentscheidungen

- **Zwei Telegram-Dialog-Systeme**: `_lamp_dlg` (dict pro Chat, Lampe/Health/Programm) und `_dm` (DialogManager global, Reboot-Untermenüs). Beide müssen beim Cancel/Reset zurückgesetzt werden.
- **State-Persistenz**: `state_manager.py` schreibt nach jeder Änderung in `state.json`. Alle Methoden sind Lock-geschützt (nur innerhalb eines Prozesses — kein Cross-Process-Lock).
- **Status-Lifecycle**: `idle` → `in_progress` → `success` / `error` / `blocked_*` / `offline` / `ui_unclear`. `reset_for_new_day()` setzt täglich zurück — schützt laufende Prozesse desselben Tages via `last_attempt_at[:10] == today`.
- **Auto-Updater**: Background-Thread prüft alle 30s auf neue Git-Commits. Bei Update → `app_state.signal_update()` → `shutdown_requested=True` → `_release_single_instance_lock()` → `os.execv()` Neustart.
- **Einzelinstanz-Lock**: TCP-Socket-Bindung auf `127.0.0.1:47392`. Muss vor `os.execv()` explizit freigegeben werden, damit der Neustart-Prozess die Sperre übernehmen kann.
- **Adaptives Retry-Intervall**: `scheduler.smart_next_retry_time()` — 60 Min normal, 15 Min in der letzten Stunde des Wartungsfensters. Konfigurierbar via `short_retry_interval_minutes` / `short_retry_threshold_minutes`.
- **Pending-Runs**: `app_state.request_run(cinema_id)` → nächster Loop-Zyklus verarbeitet via `engine.run()` ohne weitere Checks.
- **Parallelisierung**: Optional via `parallel_reboot: true` in config; nutzt `engine.run_parallel()`.

### Bekanntes Problem — Doppelinstanz

1 VBS-Klick erzeugt trotz Lock 2 Python-Instanzen. Root Cause ungeklärt. **Nicht nochmal dieselben Ansätze probieren** — alle drei sind gescheitert:
- `msvcrt.locking()`: Handle wird bei `os.execv()` vererbt → neuer Prozess kann dieselbe Byte-Region erneut sperren
- Named Mutex via `ctypes.windll.kernel32.CreateMutexW`: `GetLastError()` nach dem ctypes-Aufruf ist unzuverlässig — Python-interne Aufrufe können Fehlerwert 183 überschreiben
- TCP-Socket `socket.bind(("127.0.0.1", 47392))`: verhindert manuelle Doppelklicks, aber nicht die 2. Instanz beim allerersten Start

Ausgeschlossen: Windows Autostart-Ordner (leer), Task Scheduler (kein Eintrag), VBS-Inhalt (nur ein Run-Aufruf).
Risiken: Race-Condition beim Reboot (~1s), Telegram-Antworten auf zufällige Instanz, `state.json`-Schreibkonflikte.
**Nächster Schritt**: `wmic process where "name='python.exe'" get ProcessId,ParentProcessId,CommandLine`

## HOW — Befehle & Workflows

```bash
pip install -r requirements.txt

python main.py                        # normaler Start
python main.py --status               # Status aller Kinos (kein Reboot)
python main.py --run kino01           # Einzelnes Kino sofort neu starten
python main.py --dry-run              # navigiert, sendet keinen echten Reboot-Befehl
python main.py --test-projector kino01
python main.py --test-lamps
```

Kein automatisches Test-Framework — Tests manuell via `--dry-run` und `--status`.

**Bug fixen:** `--status` → Logs in `logs/` prüfen → Fix → `--dry-run` → Commit auf Feature-Branch

**Kino-Status zurücksetzen:** `state.json` direkt editieren (Pfad in config.yaml unter `state_file`) oder Eintrag löschen → nächster Start legt ihn als `idle` an.

**Neues Kino:** `config.yaml` → `cinemas` → neue Einträge mit `id`, `name`, `ip`, optional `projector_ip`, `projector_type`, `enabled`.

**Telegram-Bot reagiert nicht:** Neustart → Logs prüfen → sicherstellen dass `_run_loop`-Exception-Handler per-Update greift.

**Git pull schlägt fehl (Permission denied auf `.git/FETCH_HEAD`):**
```
takeown /f ".git" /r /d j
icacls ".git" /grant "Projektion:(OI)(CI)F" /T
```

## Regeln

- Alle state-mutierenden Methoden in `StateManager` immer mit `self._lock` absichern.
- `_save()` nur mit bereits gehaltenem Lock aufrufen; `_get_cinema()` niemals außerhalb des Locks.
- Exception-Handler in `_run_loop` immer per-Update (nicht per-Batch) — sonst fallen ganze Batches aus.
- Beim Cancel im Telegram-Handler immer BEIDE Dialog-Systeme zurücksetzen: `_ld_reset(chat_id)` UND `_dm.reset()`.
- `_release_single_instance_lock()` immer vor `os.execv()` aufrufen.
- Keine Kommentare die das WAS erklären — nur das WARUM wenn nicht offensichtlich.
- `config.yaml` niemals committen (enthält Passwörter/IPs).
