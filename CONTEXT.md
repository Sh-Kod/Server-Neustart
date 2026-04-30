# CONTEXT.md

## Erledigt

- **Bug 1 behoben**: `reset_for_new_day()` in `state_manager.py` — hat bisher `in_progress`-Kinos aus abgestürzten Vorläufen (andere Tage) niemals zurückgesetzt → 12 von 13 Kinos seit 16. April nicht rebootet. Fix: nur laufende Prozesse desselben Tages schützen (`last_attempt_at[:10] == today`).
- **Bug 2 behoben**: `_run_loop()` in `telegram_controller.py` — Exception-Handler umschloss den gesamten Update-Batch; ein Fehler ließ alle verbleibenden Updates fallen → Bot reagierte nicht mehr. Fix: Exception-Handler per-Update in die for-Schleife verschoben.
- **Bug 3 (defensiv) behoben**: Cancel-Handler in `lamp_controller.py` — rief nur `_ld_reset()` auf, nicht `_dm.reset()`. Fix: `self._dm.reset()` ergänzt.
- **State zurückgesetzt**: Alle 13 Kinos für Donnerstag 30.04.2026 manuell auf `idle` zurückgesetzt (state.json).
- **Alle 13 Kinos erfolgreich neu gestartet** am 30.04.2026 nach Programm-Neustart.
- **Kino 05 `in_progress` erklärt**: Reboot-Befehl wurde um 06:53 gesendet, aber das Programm wurde während Schritt 4 (Warte auf Wiederherstellung) durch ein Auto-Update neugestartet → `set_success()` nie aufgerufen. Physisch läuft der Server korrekt. Wird nächsten Donnerstag (07.05.2026) automatisch zurückgesetzt.

## Geänderte Dateien

- `cinema_reboot/state_manager.py` — `reset_for_new_day()`: `IN_PROGRESS`-Schutz nur für heutigen Tag (Zeilen 185–189)
- `cinema_reboot/telegram_controller.py` — `_run_loop()`: per-Update Exception-Handling statt per-Batch
- `cinema_projector/lamp_controller.py` — Cancel-Handler: `self._dm.reset()` ergänzt
- `CLAUDE.md` — neu erstellt (Projektdokumentation für zukünftige Sessions)
- `CONTEXT.md` — neu erstellt (diese Datei)

## Offene Probleme

- **Kino 05 zeigt `in_progress`**: Kein funktionales Problem — wird am 07.05.2026 (nächster Donnerstag) automatisch auf `idle` zurückgesetzt. Optional: manueller Reboot via Bot → startet Kino 05 ein zweites Mal neu und setzt Status auf `success`.
- **Kein automatisches Test-Framework**: Alle Tests erfolgen manuell via `--dry-run` und `--status`. Fehler in der Reboot-Logik können erst beim echten Lauf erkannt werden.

## Nächster Schritt

- **Donnerstag 07.05.2026 ab 05:00 Uhr** beobachten: Starten alle 13 Kinos automatisch neu?
- Besonders prüfen: Kino 05 (wird aus `in_progress` von 30.04 korrekt auf `idle` zurückgesetzt und dann neu gestartet)
- Falls Telegram wieder nicht reagiert: Logs in `logs/` prüfen, auf Exception-Muster im `_run_loop` achten
- Bei erneutem Absturz während Reboot: `in_progress` aus state.json löschen oder manuellen Reboot via Bot auslösen
