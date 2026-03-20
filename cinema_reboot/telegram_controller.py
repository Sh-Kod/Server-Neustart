"""
Telegram Controller – verarbeitet eingehende Nachrichten und führt Befehle aus.

Läuft in einem eigenen Thread neben der Hauptschleife und kommuniziert über
AppState (pause/resume/shutdown/pending_runs).
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional

import pytz
import requests

from .app_state import AppState
from .config import Config
from .config_writer import (
    add_cinema_to_config,
    update_cinema_in_config,
    update_config_value,
    update_credentials_in_config,
)
from .dialog_manager import DS, DialogManager
from .scheduler import Scheduler
from .state_manager import StateManager

logger = logging.getLogger(__name__)

# Mapping: Nutzereingabe → Kurzname
_DAYS_MAP = {
    "1": "Mo", "mo": "Mo", "montag": "Mo",
    "2": "Di", "di": "Di", "dienstag": "Di",
    "3": "Mi", "mi": "Mi", "mittwoch": "Mi",
    "4": "Do", "do": "Do", "donnerstag": "Do",
    "5": "Fr", "fr": "Fr", "freitag": "Fr",
    "6": "Sa", "sa": "Sa", "samstag": "Sa",
    "7": "So", "so": "So", "sonntag": "So",
}


class TelegramController:
    """Empfängt und verarbeitet Telegram-Nachrichten in einem eigenen Thread."""

    def __init__(
        self,
        config: Config,
        app_state: AppState,
        state_manager: StateManager,
        scheduler: Scheduler,
        config_path: str,
    ):
        self._config = config
        self._app_state = app_state
        self._state = state_manager
        self._scheduler = scheduler
        self._config_path = config_path
        self._dm = DialogManager()
        self._tz = pytz.timezone(config.timezone)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._offset = 0
        self._session = requests.Session()
        self._base_url = f"https://api.telegram.org/bot{config.telegram_token}"

    # ── Thread-Steuerung ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Startet den Controller in einem Hintergrund-Thread."""
        self._skip_pending_updates()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="TelegramController",
            daemon=True,
        )
        self._thread.start()
        logger.info("Telegram-Controller gestartet.")

    def _skip_pending_updates(self) -> None:
        """Überspringt alle ausstehenden Telegram-Nachrichten beim Start.
        Verhindert, dass alte Nachrichten nach einem Neustart erneut verarbeitet werden."""
        try:
            resp = self._session.get(
                f"{self._base_url}/getUpdates",
                params={"offset": -1, "timeout": 0},
                timeout=10,
            )
            if resp.ok:
                updates = resp.json().get("result", [])
                if updates:
                    self._offset = updates[-1]["update_id"] + 1
                    logger.info(f"Alte Telegram-Nachrichten übersprungen (Offset: {self._offset}).")
                else:
                    logger.info("Keine ausstehenden Telegram-Nachrichten.")
        except Exception as e:
            logger.warning(f"Fehler beim Überspringen alter Nachrichten: {e}")

    def stop(self) -> None:
        """Beendet den Controller-Thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Telegram-Controller beendet.")

    # ── Polling-Schleife ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Telegram Verbindungsfehler: {e}")
                time.sleep(10)
            except Exception as e:
                logger.error(f"Fehler im Telegram-Controller: {e}", exc_info=True)
                time.sleep(5)

    def _get_updates(self) -> list:
        resp = self._session.get(
            f"{self._base_url}/getUpdates",
            params={"offset": self._offset, "timeout": 30},
            timeout=40,
        )
        if not resp.ok:
            return []
        updates = resp.json().get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    # ── Nachrichten-Routing ───────────────────────────────────────────────────

    def _is_authorized(self, chat_id: str) -> bool:
        allowed = self._config.telegram_admin_chat_ids
        if allowed:
            return chat_id in allowed
        return chat_id == self._config.telegram_chat_id

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        if not text:
            return
        if not self._is_authorized(chat_id):
            logger.warning(f"Nicht autorisierte Nachricht von chat_id={chat_id}")
            return
        logger.info(f"Telegram [{chat_id}]: {text!r}")

        if self._dm.is_cancel(text):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.\n\n" + self._main_menu())
            return

        if not self._dm.is_idle:
            self._handle_dialog(chat_id, text)
            return

        self._handle_command(chat_id, text)

    # ── Befehle (IDLE) ────────────────────────────────────────────────────────

    def _handle_command(self, chat_id: str, text: str) -> None:
        cmd = text.lower().lstrip("/")

        if cmd in ("start", "hilfe", "menu", "2", "help"):
            self._send(chat_id, self._main_menu())

        elif cmd in ("1", "status"):
            self._send(chat_id, self._build_status())

        elif cmd in ("3", "pausieren", "pause"):
            self._app_state.pause()
            self._send(chat_id, "⏸️ Automatisierung *pausiert*.\n\nMit Befehl *4* wieder fortsetzen.")

        elif cmd in ("4", "fortsetzen", "resume"):
            self._app_state.resume()
            self._send(chat_id, "▶️ Automatisierung *fortgesetzt*.")

        elif cmd in ("5", "zeitplan"):
            self._dm.start(DS.SCHEDULE_MENU)
            self._send(chat_id, self._schedule_menu_text())

        elif cmd in ("6", "server"):
            self._dm.start(DS.SERVER_MENU)
            self._send(chat_id, self._server_menu_text())

        elif cmd in ("7", "zugangsdaten", "login"):
            self._dm.start(DS.CREDS_USERNAME)
            self._send(chat_id, "🔑 *Zugangsdaten ändern*\n\nNeuen Benutzernamen eingeben:\n_(0 = Abbrechen)_")

        elif cmd in ("8", "sofort"):
            self._cmd_immediate(chat_id)

        elif cmd in ("9", "neustart", "restart"):
            self._app_state.mark_scheduler_restart()
            self._send(chat_id, "🔄 Scheduler neu gestartet – Tagesplan wird neu erstellt.")

        elif cmd in ("10", "shutdown", "beenden"):
            self._dm.start(DS.SHUTDOWN_CONFIRM)
            self._send(chat_id, "⚠️ *Programm wirklich beenden?*\n\n*ja* bestätigen, *0* abbrechen.")

        else:
            self._send(chat_id, f"Unbekannter Befehl: `{text}`\n\n" + self._main_menu())

    # ── Dialog-Routing ────────────────────────────────────────────────────────

    def _handle_dialog(self, chat_id: str, text: str) -> None:
        s = self._dm.state
        dispatch = {
            DS.SCHEDULE_MENU:          self._dialog_schedule_menu,
            DS.SCHEDULE_START:         self._dialog_schedule_start,
            DS.SCHEDULE_END:           self._dialog_schedule_end,
            DS.SCHEDULE_DAYS:          self._dialog_schedule_days,
            DS.SCHEDULE_CONFIRM:       self._dialog_schedule_confirm,
            DS.SERVER_MENU:            self._dialog_server_menu,
            DS.SERVER_SELECT_EDIT:     self._dialog_server_select_edit,
            DS.SERVER_EDIT_FIELD:      self._dialog_server_edit_field,
            DS.SERVER_EDIT_VALUE:      self._dialog_server_edit_value,
            DS.SERVER_EDIT_CONFIRM:    self._dialog_server_edit_confirm,
            DS.SERVER_ADD_ID:          self._dialog_server_add_id,
            DS.SERVER_ADD_NAME:        self._dialog_server_add_name,
            DS.SERVER_ADD_IP:          self._dialog_server_add_ip,
            DS.SERVER_ADD_TYPE:        self._dialog_server_add_type,
            DS.SERVER_ADD_CONFIRM:     self._dialog_server_add_confirm,
            DS.SERVER_DISABLE_SELECT:  self._dialog_server_disable_select,
            DS.SERVER_DISABLE_CONFIRM: self._dialog_server_disable_confirm,
            DS.CREDS_USERNAME:         self._dialog_creds_username,
            DS.CREDS_PASSWORD:         self._dialog_creds_password,
            DS.CREDS_CONFIRM:          self._dialog_creds_confirm,
            DS.SHUTDOWN_CONFIRM:       self._dialog_shutdown_confirm,
        }
        handler = dispatch.get(s)
        if handler:
            handler(chat_id, text)
        else:
            self._dm.reset()
            self._send(chat_id, "Unbekannter Dialog-Zustand – zurückgesetzt.")

    # ══════════════════════════════════════════════════════════════════════════
    # ZEITPLAN-DIALOG (Befehl 5)
    # ══════════════════════════════════════════════════════════════════════════

    def _dialog_schedule_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            self._dm.next(DS.SCHEDULE_START)
            self._send(chat_id,
                f"🕐 Neue *Startzeit* (aktuell: `{self._config.mw_start}`):\n"
                f"Format: `HH:MM`  _(0 = Abbrechen)_")
        elif t == "2":
            self._dm.next(DS.SCHEDULE_END)
            self._send(chat_id,
                f"🕕 Neue *Endzeit* (aktuell: `{self._config.mw_end}`):\n"
                f"Format: `HH:MM`  _(0 = Abbrechen)_")
        elif t == "3":
            self._dm.next(DS.SCHEDULE_DAYS)
            self._send(chat_id,
                f"📅 Aktive *Wochentage* (aktuell: `{self._config.allowed_days_str}`):\n"
                f"Beispiel: `Mo,Di,Mi,Do,Fr` oder `1,2,3,4,5`\n"
                f"_(0 = Abbrechen)_")
        else:
            self._send(chat_id, "Bitte *1*, *2* oder *3* eingeben.")

    def _dialog_schedule_start(self, chat_id: str, text: str) -> None:
        t = self._parse_time_input(text)
        if t is None:
            self._send(chat_id, "❌ Ungültiges Format. Beispiel: `03:00`")
            return
        self._dm.set("new_start", t)
        self._dm.next(DS.SCHEDULE_CONFIRM)
        self._send(chat_id, f"Startzeit auf `{t}` setzen?\n*ja* bestätigen, *0* abbrechen.")

    def _dialog_schedule_end(self, chat_id: str, text: str) -> None:
        t = self._parse_time_input(text)
        if t is None:
            self._send(chat_id, "❌ Ungültiges Format. Beispiel: `06:00`")
            return
        self._dm.set("new_end", t)
        self._dm.next(DS.SCHEDULE_CONFIRM)
        self._send(chat_id, f"Endzeit auf `{t}` setzen?\n*ja* bestätigen, *0* abbrechen.")

    def _dialog_schedule_days(self, chat_id: str, text: str) -> None:
        days = self._parse_days_input(text)
        if days is None:
            self._send(chat_id, "❌ Ungültige Eingabe. Beispiel: `Mo,Di,Mi,Do,Fr`")
            return
        self._dm.set("new_days", days)
        self._dm.next(DS.SCHEDULE_CONFIRM)
        self._send(chat_id,
            f"Wochentage auf `{', '.join(days)}` setzen?\n*ja* bestätigen, *0* abbrechen.")

    def _dialog_schedule_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return

        changes = []
        data = self._dm.all_data()

        if "new_start" in data:
            v = data["new_start"]
            update_config_value(self._config_path, ["maintenance_window", "start"], v)
            self._config._raw["maintenance_window"]["start"] = v
            changes.append(f"Start: `{v}`")

        if "new_end" in data:
            v = data["new_end"]
            update_config_value(self._config_path, ["maintenance_window", "end"], v)
            self._config._raw["maintenance_window"]["end"] = v
            changes.append(f"Ende: `{v}`")

        if "new_days" in data:
            v = data["new_days"]
            update_config_value(self._config_path, ["maintenance_window", "allowed_days"], v)
            self._config._raw["maintenance_window"]["allowed_days"] = v
            changes.append(f"Tage: `{', '.join(v)}`")

        self._dm.reset()
        if changes:
            self._send(chat_id, "✅ Zeitplan gespeichert:\n" + "\n".join(f"  • {c}" for c in changes))
        else:
            self._send(chat_id, "Keine Änderungen.")

    # ══════════════════════════════════════════════════════════════════════════
    # SERVER-DIALOG (Befehl 6)
    # ══════════════════════════════════════════════════════════════════════════

    def _dialog_server_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            cinemas = self._config.cinemas
            lines = ["🖥️ *Server bearbeiten* – Nummer eingeben:\n"]
            for i, c in enumerate(cinemas, 1):
                icon = "✅" if c.get("enabled", True) else "🔴"
                lines.append(f"{i}. {icon} {c['name']} ({c['id']}) – {c['ip']}")
            lines.append("\n_(0 = Abbrechen)_")
            self._dm.set("for_immediate", False)
            self._dm.next(DS.SERVER_SELECT_EDIT)
            self._send(chat_id, "\n".join(lines))
        elif t == "2":
            self._dm.next(DS.SERVER_ADD_ID)
            self._send(chat_id,
                "🆕 *Neuen Server hinzufügen*\n\n"
                "Kino-ID eingeben (z.B. `kino14`):\n_(0 = Abbrechen)_")
        elif t == "3":
            cinemas = self._config.cinemas
            lines = ["🔴 *Server deaktivieren* – Nummer eingeben:\n"]
            for i, c in enumerate(cinemas, 1):
                state_lbl = "✅" if c.get("enabled", True) else "🔴 (bereits aus)"
                lines.append(f"{i}. {state_lbl} {c['name']} ({c['id']})")
            lines.append("\n_(0 = Abbrechen)_")
            self._dm.next(DS.SERVER_DISABLE_SELECT)
            self._send(chat_id, "\n".join(lines))
        else:
            self._send(chat_id, "Bitte *1*, *2* oder *3* eingeben.")

    def _dialog_server_select_edit(self, chat_id: str, text: str) -> None:
        try:
            idx = int(text.strip()) - 1
            cinemas = self._config.cinemas
            if idx < 0 or idx >= len(cinemas):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return

        cinema = cinemas[idx]

        # Sofort-Reboot?
        if self._dm.get("for_immediate"):
            self._dm.reset()
            self._app_state.request_run(cinema["id"])
            self._send(chat_id,
                f"⚡ Sofort-Reboot für *{cinema['name']}* angefordert.\n"
                f"_Wird im nächsten Prüfzyklus ausgeführt._")
            return

        # Normales Bearbeiten
        self._dm.set("cinema_id", cinema["id"])
        self._dm.set("cinema_name", cinema["name"])
        self._dm.next(DS.SERVER_EDIT_FIELD)
        self._send(chat_id,
            f"*{cinema['name']}* bearbeiten:\n\n"
            f"1 – Name        (aktuell: `{cinema['name']}`)\n"
            f"2 – IP-Adresse  (aktuell: `{cinema['ip']}`)\n"
            f"3 – Typ         (aktuell: `{cinema['type']}`)\n"
            f"4 – Aktiviert   (aktuell: `{cinema.get('enabled', True)}`)\n\n"
            f"_(0 = Abbrechen)_")

    def _dialog_server_edit_field(self, chat_id: str, text: str) -> None:
        field_map = {"1": "name", "2": "ip", "3": "type", "4": "enabled"}
        field = field_map.get(text.strip())
        if not field:
            self._send(chat_id, "❌ Bitte 1–4 eingeben.")
            return
        self._dm.set("edit_field", field)
        self._dm.next(DS.SERVER_EDIT_VALUE)
        prompts = {
            "name":    "Neuen *Namen* eingeben:",
            "ip":      "Neue *IP-Adresse* eingeben (z.B. `172.20.21.11`):",
            "type":    "Neuen *Typ* eingeben (`doremi` oder `ims3000`):",
            "enabled": "*Aktiviert?* `ja` oder `nein`:",
        }
        self._send(chat_id, prompts[field] + "\n_(0 = Abbrechen)_")

    def _dialog_server_edit_value(self, chat_id: str, text: str) -> None:
        field = self._dm.get("edit_field")
        value: object = text.strip()

        if field == "type" and value not in ("doremi", "ims3000"):
            self._send(chat_id, "❌ Ungültiger Typ. Bitte `doremi` oder `ims3000` eingeben.")
            return
        if field == "enabled":
            if str(value).lower() in ("ja", "yes", "true", "1"):
                value = True
            elif str(value).lower() in ("nein", "no", "false", "0"):
                value = False
            else:
                self._send(chat_id, "❌ Bitte `ja` oder `nein` eingeben.")
                return

        self._dm.set("edit_value", value)
        self._dm.next(DS.SERVER_EDIT_CONFIRM)
        cinema_id = self._dm.get("cinema_id")
        self._send(chat_id,
            f"*{cinema_id}*: Feld `{field}` auf `{value}` setzen?\n"
            f"*ja* bestätigen, *0* abbrechen.")

    def _dialog_server_edit_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return
        cinema_id = self._dm.get("cinema_id")
        field = self._dm.get("edit_field")
        value = self._dm.get("edit_value")
        try:
            update_cinema_in_config(self._config_path, cinema_id, field, value)
            for c in self._config._raw["cinemas"]:
                if c["id"] == cinema_id:
                    c[field] = value
                    break
            self._dm.reset()
            self._send(chat_id, f"✅ {cinema_id}: `{field}` → `{value}` gespeichert.")
        except Exception as e:
            self._dm.reset()
            self._send(chat_id, f"❌ Fehler: {e}")

    def _dialog_server_add_id(self, chat_id: str, text: str) -> None:
        new_id = text.strip().lower()
        existing_ids = [c["id"] for c in self._config._raw["cinemas"]]
        if new_id in existing_ids:
            self._send(chat_id, f"❌ ID `{new_id}` existiert bereits.")
            return
        if not new_id.replace("-", "").replace("_", "").isalnum():
            self._send(chat_id, "❌ ID darf nur Buchstaben, Zahlen, `-` und `_` enthalten.")
            return
        self._dm.set("new_id", new_id)
        self._dm.next(DS.SERVER_ADD_NAME)
        self._send(chat_id, f"ID: `{new_id}`\n\nAnzeige-*Name* eingeben (z.B. `Kino 14`):\n_(0 = Abbrechen)_")

    def _dialog_server_add_name(self, chat_id: str, text: str) -> None:
        self._dm.set("new_name", text.strip())
        self._dm.next(DS.SERVER_ADD_IP)
        self._send(chat_id, f"Name: `{text.strip()}`\n\n*IP-Adresse* eingeben:\n_(0 = Abbrechen)_")

    def _dialog_server_add_ip(self, chat_id: str, text: str) -> None:
        ip = text.strip()
        parts = ip.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            self._send(chat_id, "❌ Ungültige IP-Adresse.")
            return
        self._dm.set("new_ip", ip)
        self._dm.next(DS.SERVER_ADD_TYPE)
        self._send(chat_id, f"IP: `{ip}`\n\n*Typ* eingeben (`doremi` oder `ims3000`):\n_(0 = Abbrechen)_")

    def _dialog_server_add_type(self, chat_id: str, text: str) -> None:
        t = text.strip().lower()
        if t not in ("doremi", "ims3000"):
            self._send(chat_id, "❌ Bitte `doremi` oder `ims3000` eingeben.")
            return
        self._dm.set("new_type", t)
        self._dm.next(DS.SERVER_ADD_CONFIRM)
        d = self._dm.all_data()
        self._send(chat_id,
            f"*Neuer Server:*\n"
            f"  ID:   `{d['new_id']}`\n"
            f"  Name: `{d['new_name']}`\n"
            f"  IP:   `{d['new_ip']}`\n"
            f"  Typ:  `{d['new_type']}`\n\n"
            f"*ja* zum Speichern, *0* abbrechen.")

    def _dialog_server_add_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return
        d = self._dm.all_data()
        new_cinema = {
            "id": d["new_id"], "name": d["new_name"],
            "ip": d["new_ip"], "type": d["new_type"], "enabled": True,
        }
        try:
            add_cinema_to_config(self._config_path, new_cinema)
            self._config._raw["cinemas"].append(new_cinema)
            self._dm.reset()
            self._send(chat_id, f"✅ *{d['new_name']}* (`{d['new_id']}`) hinzugefügt.")
        except Exception as e:
            self._dm.reset()
            self._send(chat_id, f"❌ Fehler: {e}")

    def _dialog_server_disable_select(self, chat_id: str, text: str) -> None:
        try:
            idx = int(text.strip()) - 1
            cinemas = self._config.cinemas
            if idx < 0 or idx >= len(cinemas):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        cinema = cinemas[idx]
        self._dm.set("disable_id", cinema["id"])
        self._dm.set("disable_name", cinema["name"])
        self._dm.next(DS.SERVER_DISABLE_CONFIRM)
        self._send(chat_id,
            f"🔴 *{cinema['name']}* ({cinema['id']}) deaktivieren?\n"
            f"*ja* bestätigen, *0* abbrechen.")

    def _dialog_server_disable_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return
        cinema_id = self._dm.get("disable_id")
        cinema_name = self._dm.get("disable_name")
        try:
            update_cinema_in_config(self._config_path, cinema_id, "enabled", False)
            for c in self._config._raw["cinemas"]:
                if c["id"] == cinema_id:
                    c["enabled"] = False
                    break
            self._dm.reset()
            self._send(chat_id, f"✅ *{cinema_name}* deaktiviert.")
        except Exception as e:
            self._dm.reset()
            self._send(chat_id, f"❌ Fehler: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # ZUGANGSDATEN-DIALOG (Befehl 7)
    # ══════════════════════════════════════════════════════════════════════════

    def _dialog_creds_username(self, chat_id: str, text: str) -> None:
        self._dm.set("new_username", text.strip())
        self._dm.next(DS.CREDS_PASSWORD)
        self._send(chat_id,
            f"Benutzername: `{text.strip()}`\n\n*Passwort* eingeben:\n_(0 = Abbrechen)_")

    def _dialog_creds_password(self, chat_id: str, text: str) -> None:
        self._dm.set("new_password", text.strip())
        self._dm.next(DS.CREDS_CONFIRM)
        username = self._dm.get("new_username")
        stars = "*" * min(len(text.strip()), 8)
        self._send(chat_id,
            f"Zugangsdaten setzen?\n"
            f"  Benutzer: `{username}`\n"
            f"  Passwort: `{stars}`\n\n"
            f"*ja* bestätigen, *0* abbrechen.\n"
            f"⚠️ _Diese Nachricht danach bitte löschen!_")

    def _dialog_creds_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return
        username = self._dm.get("new_username")
        password = self._dm.get("new_password")
        try:
            update_credentials_in_config(self._config_path, username, password)
            self._config._raw["credentials"]["username"] = username
            self._config._raw["credentials"]["password"] = password
            self._dm.reset()
            self._send(chat_id, f"✅ Zugangsdaten für `{username}` gespeichert.")
        except Exception as e:
            self._dm.reset()
            self._send(chat_id, f"❌ Fehler: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # SOFORT-REBOOT (Befehl 8)
    # ══════════════════════════════════════════════════════════════════════════

    def _cmd_immediate(self, chat_id: str) -> None:
        cinemas = self._config.cinemas
        lines = ["⚡ *Sofort-Reboot* – Kino wählen:\n"]
        for i, c in enumerate(cinemas, 1):
            lines.append(f"{i}. {c['name']} ({c['id']}) – {c['ip']}")
        lines.append("\n_(0 = Abbrechen)_")
        self._dm.start(DS.SERVER_SELECT_EDIT, for_immediate=True)
        self._send(chat_id, "\n".join(lines))

    # ══════════════════════════════════════════════════════════════════════════
    # SHUTDOWN (Befehl 10)
    # ══════════════════════════════════════════════════════════════════════════

    def _dialog_shutdown_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._dm.reset()
            self._send(chat_id, "❌ Abgebrochen.")
            return
        self._dm.reset()
        self._send(chat_id, "🛑 Programm wird beendet...")
        self._app_state.request_shutdown()

    # ══════════════════════════════════════════════════════════════════════════
    # HILFSFUNKTIONEN
    # ══════════════════════════════════════════════════════════════════════════

    def _send(self, chat_id: str, text: str) -> None:
        """Sendet eine Markdown-Nachricht an den angegebenen Chat."""
        try:
            self._session.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Fehler beim Senden an {chat_id}: {e}")

    def _main_menu(self) -> str:
        paused = "⏸️ PAUSIERT" if self._app_state.paused else "▶️ AKTIV"
        mode = "⚠️ DRY-RUN" if self._config.dry_run else "✅ LIVE"
        return (
            f"🎬 *Cinema Server Reboot* v{self._app_state.version}\n"
            f"Status: {paused} | Modus: {mode}\n\n"
            f"*Befehle:*\n"
            f"1 – Status aller Kinos\n"
            f"2 – Diese Hilfe\n"
            f"3 – Automatisierung pausieren\n"
            f"4 – Automatisierung fortsetzen\n"
            f"5 – Wartungsfenster ändern\n"
            f"6 – Server konfigurieren\n"
            f"7 – Zugangsdaten ändern\n"
            f"8 – Sofort-Reboot auslösen\n"
            f"9 – Scheduler neu starten\n"
            f"10 – Programm beenden\n\n"
            f"_0 oder /abbrechen = Dialog abbrechen_"
        )

    def _build_status(self) -> str:
        now = datetime.now(self._tz)
        today = now.strftime("%Y-%m-%d")
        in_window = self._scheduler.in_maintenance_window()
        paused = self._app_state.paused
        lines = [
            f"📊 *Status* – {now.strftime('%d.%m.%Y %H:%M')}",
            f"Fenster: `{self._config.mw_start}–{self._config.mw_end}` "
            f"({'🟢 aktiv' if in_window else '⚪ inaktiv'})",
            f"Automatisierung: {'⏸️ pausiert' if paused else '▶️ läuft'}",
            f"Modus: {'⚠️ DRY-RUN' if self._config.dry_run else '✅ LIVE'}",
            "",
        ]
        icons = {
            "idle": "⏳", "success": "✅", "blocked_by_playback": "🔴",
            "blocked_by_transfer": "🟡", "error": "❌", "offline": "📴",
            "ui_unclear": "❓", "in_progress": "🔄",
        }
        for cinema in self._config.cinemas:
            cid = cinema["id"]
            status = self._state.get_status(cid)
            sched = self._scheduler.get_scheduled_time(cid)
            done = self._state.was_successful_today(cid, today)
            icon = icons.get(status, "?")
            sched_str = sched.strftime("%H:%M") if sched else "?"
            done_mark = " ✓" if done else ""
            lines.append(
                f"{icon} *{cinema['name']}* – {status}{done_mark} (Plan: {sched_str})"
            )
        return "\n".join(lines)

    def _schedule_menu_text(self) -> str:
        return (
            f"📅 *Wartungsfenster ändern*\n\n"
            f"Aktuell: `{self._config.mw_start}–{self._config.mw_end}` "
            f"an `{self._config.allowed_days_str}`\n\n"
            f"1 – Startzeit ändern\n"
            f"2 – Endzeit ändern\n"
            f"3 – Wochentage ändern\n\n"
            f"_(0 = Abbrechen)_"
        )

    def _server_menu_text(self) -> str:
        count = len(self._config.cinemas)
        return (
            f"🖥️ *Server konfigurieren*\n\n"
            f"Aktuell {count} aktive Kinos\n\n"
            f"1 – Server bearbeiten\n"
            f"2 – Server hinzufügen\n"
            f"3 – Server deaktivieren\n\n"
            f"_(0 = Abbrechen)_"
        )

    @staticmethod
    def _parse_time_input(text: str) -> Optional[str]:
        """Parst HH:MM-Eingabe → normalisierten String oder None."""
        text = text.strip().replace(".", ":")
        parts = text.split(":")
        if len(parts) != 2:
            return None
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return None
            return f"{h:02d}:{m:02d}"
        except ValueError:
            return None

    @staticmethod
    def _parse_days_input(text: str) -> Optional[list]:
        """Parst Tages-Eingabe → sortierte Kurzliste oder None."""
        raw = [p.strip().lower() for p in text.replace(";", ",").split(",")]
        order = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        result = []
        for part in raw:
            found = _DAYS_MAP.get(part)
            if found is None:
                return None
            if found not in result:
                result.append(found)
        # In Wochentag-Reihenfolge sortieren
        result.sort(key=lambda d: order.index(d))
        return result if result else None
