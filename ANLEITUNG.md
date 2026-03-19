# Cinema Server Reboot – Anleitung

## Was macht dieses Programm?

Dieses Programm startet automatisch 13 Kino-Server (Dolby/Doremi) in der Nacht neu.
**Es ist so gebaut, dass es NIEMALS rebooted, wenn ein Film läuft.**

### Sicherheitsprinzipien

1. **DRY-RUN-Modus**: Standardmäßig aktiv. Das Programm navigiert und prüft, klickt aber NICHT auf Reboot.
2. **Mehrfach-Barrieren**: Pre-Check → Power-Menü-Check → Popup-Check → Post-Check
3. **Rote Grenze**: Wenn Playback läuft → sofort Abbrechen, Alarm, Telegram
4. **Nur erlaubte Klicks**: Nur "Restart" (Doremi) bzw. "Reboot" (IMS3000) darf geklickt werden

---

## Erstinstallation

### Voraussetzungen

- Windows 10/11
- Python 3.11 oder neuer → [Download](https://www.python.org/downloads/)
  - Bei der Installation: **"Add Python to PATH"** aktivieren!

### Setup

1. Diesen Ordner auf den PC kopieren
2. `setup.bat` als Administrator ausführen
3. Warten bis Meldung "Setup erfolgreich abgeschlossen!" erscheint

---

## Konfiguration

Öffne `config.yaml` mit einem Texteditor (z.B. Notepad).

### Wichtigste Einstellungen

```yaml
settings:
  dry_run: true   # ← IMMER erst mit true testen!
  headless: true  # false = Browser sichtbar (zum Debuggen)
```

### Telegram einrichten

1. Schreibe `@BotFather` auf Telegram
2. Tippe `/newbot` und folge den Anweisungen
3. Du erhältst einen **Bot-Token** (z.B. `1234567890:ABCdef...`)
4. Schreibe deinen neuen Bot an und tippe `/start`
5. Finde deine **Chat-ID**: Schreibe `@userinfobot` auf Telegram
6. Trage beides in `config.yaml` ein:

```yaml
telegram:
  bot_token: "1234567890:ABCdef..."
  chat_id: "987654321"
  enabled: true
  # Optional: weitere autorisierte Chat-IDs (z.B. Kollegen)
  admin_chat_ids: []
```

---

## Telegram-Steuerung

Sobald der Bot läuft, kannst du folgende Befehle senden:

| Befehl | Funktion |
|--------|----------|
| `1` | Status aller Kinos anzeigen |
| `2` oder `/start` | Hauptmenü öffnen |
| `3` | Automatisierung **pausieren** |
| `4` | Automatisierung **fortsetzen** |
| `5` | Wartungsfenster ändern (Start, Ende, Wochentage) |
| `6` | Server konfigurieren (bearbeiten / hinzufügen / deaktivieren) |
| `7` | Zugangsdaten ändern |
| `8` | Sofort-Reboot für ein bestimmtes Kino auslösen |
| `9` | Scheduler neu starten (neuer Tagesplan) |
| `10` | Programm beenden |

**Abbrechen:** Schreibe `0` oder `/abbrechen` während eines laufenden Dialogs.

> **Hinweis:** Alle Konfigurationsänderungen (Befehl 5, 6, 7) werden sofort in
> `config.yaml` gespeichert und sind nach einem Neustart weiterhin aktiv.

---

## Programm starten

### Normal starten
Doppelklick auf `start.bat`

### Status anzeigen
```
start.bat --status
```

### Ein einzelnes Kino sofort rebooten (Dry-Run)
```
start.bat --run kino01 --dry-run
```

### Im Hintergrund starten (ohne Konsolenfenster)
Doppelklick auf `start_hidden.vbs`

---

## Autostart einrichten (Windows Task Scheduler)

1. Windows-Taste → "Aufgabenplanung" öffnen
2. "Einfache Aufgabe erstellen..."
3. Name: `Cinema Server Reboot`
4. Trigger: `Beim Starten des Computers`
5. Aktion: `Programm starten`
6. Programm: `wscript.exe`
7. Argumente: `"C:\Pfad\zum\Ordner\start_hidden.vbs"`
8. Optionen: `Unabhängig von der Benutzeranmeldung ausführen` aktivieren

---

## Testprozedur (WICHTIG – vor dem Live-Betrieb)

### Phase 1: Dry-Run-Test

1. `config.yaml`: `dry_run: true`, `headless: false` (Browser sichtbar)
2. Starte: `start.bat --run kino01`
3. Beobachte: Browser öffnet sich, navigiert, aber klickt **nicht** auf Restart
4. Log-Datei in `logs/` prüfen
5. Wiederhole für `kino08` (IMS3000)

### Phase 2: Live-Test mit einem Kino

1. Abends nach Kinobetrieb (Wartungsfenster 03:00–06:00)
2. `config.yaml`: `dry_run: false`, `headless: false`
3. Nur **kino01** aktiviert lassen (`enabled: true`), alle anderen `enabled: false`
4. Telegram-Benachrichtigungen prüfen
5. Server muss nach ca. 10-15 Minuten wieder online sein

### Phase 3: Alle Kinos aktivieren

1. Alle Kinos auf `enabled: true` setzen
2. `headless: true` (läuft im Hintergrund)
3. Mehrere Nächte beobachten

---

## Log-Dateien

Log-Dateien befinden sich im Ordner `logs/`:
- `cinema_reboot.log` – Hauptlog
- `screenshot_kinoXX_*.png` – Screenshots bei Fehlern

---

## Fehlerbehebung

### Server wird nicht gefunden
- IP-Adresse in `config.yaml` prüfen
- Ping testen: `ping 172.20.21.11`
- Firewall prüfen

### Login schlägt fehl
- `headless: false` setzen und manuell zuschauen
- Benutzername/Passwort in `config.yaml` prüfen

### Selektoren passen nicht (UI sieht anders aus)
- Screenshots in `logs/` prüfen
- Die Selektoren in `cinema_reboot/handlers/doremi.py` oder `ims3000.py` anpassen
- Melde dich beim Entwickler mit einem Screenshot

### Playback-Alarm trotz freiem Server
- Log prüfen: Was hat das Programm erkannt?
- `headless: false` und `--run kinoXX` für manuellen Test

---

## Projektstruktur

```
cinema-reboot/
├── config.yaml              ← Konfiguration (anpassen!)
├── state.json               ← Wird automatisch erstellt (Zustand pro Kino)
├── schedule_today.json      ← Tagesplan (wird täglich neu erstellt)
├── main.py                  ← Hauptprogramm
├── requirements.txt         ← Python-Abhängigkeiten
├── setup.bat                ← Erstinstallation
├── start.bat                ← Starten
├── start_hidden.vbs         ← Starten ohne Konsolenfenster
├── logs/                    ← Log-Dateien und Fehler-Screenshots
└── cinema_reboot/
    ├── config.py            ← Konfigurationsmodul
    ├── state_manager.py     ← Zustandsverwaltung
    ├── scheduler.py         ← Planung & Timing (inkl. Wochentag-Filter)
    ├── app_state.py         ← Gemeinsamer Laufzeit-Zustand (pause/resume)
    ├── telegram_sender.py   ← Automatische Telegram-Benachrichtigungen
    ├── telegram_controller.py ← Telegram-Bot für Fernsteuerung
    ├── dialog_manager.py    ← Zustandsmaschine für mehrstufige Dialoge
    ├── config_writer.py     ← Live-Änderungen an config.yaml
    ├── notifier.py          ← Lokale Alarme (Windows)
    ├── reboot_engine.py     ← Orchestrierung
    ├── logger_setup.py      ← Logging
    └── handlers/
        ├── base.py          ← Basis-Klasse
        ├── doremi.py        ← Doremi/DCP2000 (Kinos 01-07, 09-13)
        └── ims3000.py       ← IMS3000 (Kino 08)
```
