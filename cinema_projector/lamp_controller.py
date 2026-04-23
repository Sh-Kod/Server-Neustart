"""
LampTelegramController – Hauptmenü mit 3 Bereichen + Lampen-Befehle.

Erbt von cinema_reboot.TelegramController.
cinema_reboot/ wird dabei NICHT verändert.

Hauptmenü (3 Bereiche):
  1 – 🔄 Server-Neustart        → Untermenü mit allen Reboot-Befehlen
  2 – 🔦 Lampen-Monitor         → Untermenü mit Lampen-Befehlen
  3 – 💚 Projektor-Gesundheit   → Übersicht + Sofortcheck

Lampen-Untermenü:
  1 – Alle Projektoren sofort prüfen
  2 – Einzelner Kino-Check
  3 – Prüfzeit ändern
  4 – Projektor-IP bearbeiten
  5 – Status (letzter Check)

Gesundheits-Untermenü:
  1 – Übersicht (alle Projektoren)
  2 – Sofort alle prüfen
  3 – Einzelner Projektor-Check
"""
import logging
import threading
from typing import Optional

from cinema_reboot.config_writer import update_cinema_in_config, update_config_value
from cinema_reboot.telegram_controller import TelegramController

from .lamp_config import LampConfig
from .lamp_monitor import LampMonitor

logger = logging.getLogger(__name__)

# Dialog-Zustände (Lampe)
_LS_REBOOT_SUBMENU   = "reboot_submenu"
_LS_MENU             = "lamp_menu"
_LS_SINGLE_SELECT    = "single_select"
_LS_TIME_INPUT       = "time_input"
_LS_PROJ_MENU        = "proj_menu"
_LS_PROJ_SELECT      = "proj_select"
_LS_PROJ_IP_INPUT    = "proj_ip_input"
_LS_PROJ_IP_CONFIRM  = "proj_ip_confirm"
_LS_PROJ_DEL_SELECT  = "proj_del_select"
_LS_PROJ_DEL_CONFIRM = "proj_del_confirm"

# Dialog-Zustände (Gesundheit)
_HS_MENU            = "health_menu"
_HS_SINGLE_SELECT   = "health_single_select"

# Dialog-Zustände (Temperatur-Schwellwert)
_HS_TEMP_SELECT     = "health_temp_select"
_HS_TEMP_INPUT      = "health_temp_input"

# Dialog-Zustände (Projektor-Steuerung)
_HS_CTRL_SELECT     = "health_ctrl_select"
_HS_CTRL_ACTION     = "health_ctrl_action"
_HS_CTRL_CONFIRM    = "health_ctrl_confirm"

# Dialog-Zustände (Programm-Steuerung)
_PS_MENU            = "prog_menu"
_PS_RESTART_CONFIRM = "prog_restart_confirm"
_PS_STOP_CONFIRM    = "prog_stop_confirm"

CANCEL_WORDS = {"0", "/abbrechen", "/cancel", "/stop", "/exit"}


class LampTelegramController(TelegramController):
    """
    Unterklasse von TelegramController mit Lampen-Monitor-Befehlen.
    Überschreibt nur _handle_update, _handle_command und _main_menu.
    """

    def __init__(
        self,
        lamp_monitor: LampMonitor,
        lamp_config: LampConfig,
        health_monitor=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._lamp        = lamp_monitor
        self._lamp_cfg    = lamp_config
        self._health      = health_monitor  # HealthMonitor oder None
        self._lamp_dlg: dict = {}   # {chat_id: {"state": str, "data": dict}}

    # ── Dialog-Hilfsfunktionen ────────────────────────────────────────────────

    def _ld_state(self, chat_id: str) -> Optional[str]:
        return self._lamp_dlg.get(chat_id, {}).get("state")

    def _ld_set(self, chat_id: str, state: str, **data) -> None:
        self._lamp_dlg[chat_id] = {"state": state, "data": data}

    def _ld_update_data(self, chat_id: str, key: str, value) -> None:
        self._lamp_dlg.setdefault(chat_id, {"state": "", "data": {}})["data"][key] = value

    def _ld_get(self, chat_id: str, key: str, default=None):
        return self._lamp_dlg.get(chat_id, {}).get("data", {}).get(key, default)

    def _ld_next(self, chat_id: str, state: str) -> None:
        if chat_id in self._lamp_dlg:
            self._lamp_dlg[chat_id]["state"] = state

    def _ld_reset(self, chat_id: str) -> None:
        self._lamp_dlg.pop(chat_id, None)

    # ── Override: Update-Routing ──────────────────────────────────────────────

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id = str(msg["chat"]["id"])
        text    = msg.get("text", "").strip()
        if not text or not self._is_authorized(chat_id):
            return

        # Im Lampen-Dialog?
        if chat_id in self._lamp_dlg:
            if text.strip().lower() in CANCEL_WORDS:
                self._ld_reset(chat_id)
                self._send(chat_id, "❌ Abgebrochen.\n\n" + self._main_menu())
            else:
                self._handle_lamp_dialog(chat_id, text)
            return

        # Sonst: normales Reboot-Routing
        super()._handle_update(update)

    def _handle_command(self, chat_id: str, text: str) -> None:
        cmd = text.lower().lstrip("/")
        if cmd in ("1", "reboot", "server", "neustart"):
            self._ld_set(chat_id, _LS_REBOOT_SUBMENU)
            self._send(chat_id, self._reboot_submenu_text())
        elif cmd in ("2", "lampen", "lampe", "lamp", "13"):
            self._open_lamp_menu(chat_id)
        elif cmd in ("3", "gesundheit", "health"):
            self._open_health_menu(chat_id)
        elif cmd in ("4", "programm", "prog"):
            self._open_prog_menu(chat_id)
        else:
            # Direktzugriff auf alte Befehle weiterhin möglich (z.B. /status, /pause)
            super()._handle_command(chat_id, text)

    def _main_menu(self) -> str:
        paused = "⏸️ PAUSIERT" if self._app_state.paused else "▶️ AKTIV"
        mode   = "⚠️ DRY-RUN"  if self._config.dry_run   else "✅ LIVE"
        return (
            f"🎬 *Cinema Server Manager*\n"
            f"Status: {paused} | Modus: {mode}\n\n"
            f"*Bereich wählen:*\n"
            f"1 – 🔄 Server-Neustart\n"
            f"2 – 🔦 Lampen-Monitor\n"
            f"3 – 💚 Projektor-Gesundheit\n"
            f"4 – ⚙️ Programm\n\n"
            f"_0 oder /abbrechen = Abbrechen_"
        )

    def _reboot_submenu_text(self) -> str:
        paused = "⏸️ pausiert" if self._app_state.paused else "▶️ läuft"
        mode   = "⚠️ DRY-RUN"  if self._config.dry_run   else "✅ LIVE"
        return (
            f"🔄 *Server-Neustart*  ({paused} | {mode})\n\n"
            f"1 – Status aller Kinos\n"
            f"2 – Wartungsfenster ändern\n"
            f"3 – Server konfigurieren\n"
            f"4 – Zugangsdaten ändern\n"
            f"5 – Sofort-Reboot auslösen\n"
            f"6 – Scheduler neu starten\n"
            f"7 – Browser-Modus umschalten\n\n"
            f"_0 = ← Hauptmenü_"
        )

    # ── Lampen-Menü ───────────────────────────────────────────────────────────

    def _open_lamp_menu(self, chat_id: str) -> None:
        self._ld_set(chat_id, _LS_MENU)
        self._send(chat_id, self._lamp_menu_text())

    def _lamp_menu_text(self) -> str:
        return (
            "🔦 *Lampen-Monitor*\n\n"
            "1 – Alle Projektoren sofort prüfen\n"
            "2 – Einzelner Kino-Check\n"
            "3 – Prüfzeit ändern\n"
            "4 – Projektor-IP bearbeiten\n"
            "5 – Status (letzter Check)\n\n"
            "_0 = Zurück zum Hauptmenü_"
        )

    def _handle_lamp_dialog(self, chat_id: str, text: str) -> None:
        state = self._ld_state(chat_id)
        dispatch = {
            _LS_REBOOT_SUBMENU:  self._dlg_reboot_submenu,
            _LS_MENU:            self._dlg_lamp_menu,
            _LS_SINGLE_SELECT:   self._dlg_single_select,
            _LS_TIME_INPUT:      self._dlg_time_input,
            _LS_PROJ_MENU:       self._dlg_proj_menu,
            _LS_PROJ_SELECT:     self._dlg_proj_select,
            _LS_PROJ_IP_INPUT:   self._dlg_proj_ip_input,
            _LS_PROJ_IP_CONFIRM: self._dlg_proj_ip_confirm,
            _LS_PROJ_DEL_SELECT: self._dlg_proj_del_select,
            _LS_PROJ_DEL_CONFIRM:self._dlg_proj_del_confirm,
            _HS_MENU:            self._dlg_health_menu,
            _HS_SINGLE_SELECT:   self._dlg_health_single_select,
            _HS_TEMP_SELECT:     self._dlg_temp_select,
            _HS_TEMP_INPUT:      self._dlg_temp_input,
            _HS_CTRL_SELECT:     self._dlg_ctrl_select,
            _HS_CTRL_ACTION:     self._dlg_ctrl_action,
            _HS_CTRL_CONFIRM:    self._dlg_ctrl_confirm,
            _PS_MENU:            self._dlg_prog_menu,
            _PS_RESTART_CONFIRM: self._dlg_prog_restart_confirm,
            _PS_STOP_CONFIRM:    self._dlg_prog_stop_confirm,
        }
        handler = dispatch.get(state)
        if handler:
            handler(chat_id, text)
        else:
            self._ld_reset(chat_id)
            self._send(chat_id, "❓ Unbekannter Zustand – zurückgesetzt.")

    # ── Reboot-Untermenü ─────────────────────────────────────────────────────

    def _dlg_reboot_submenu(self, chat_id: str, text: str) -> None:
        """Leitet Auswahl im Reboot-Untermenü weiter."""
        self._ld_reset(chat_id)
        super()._handle_command(chat_id, text)

    def _build_last_reboot_status(self) -> str:
        """Zeigt für jedes Kino wann der letzte Reboot war und ob er erfolgreich war."""
        from datetime import datetime as _dt
        from cinema_reboot.state_manager import Status

        now  = _dt.now(self._tz)
        today = now.strftime("%Y-%m-%d")
        all_state = self._state.get_all()

        lines = [f"📋 *Letzter Reboot – alle Säle*\n_{now.strftime('%d.%m.%Y %H:%M')}_\n"]

        for cinema in self._config.cinemas:
            cid  = cinema["id"]
            name = cinema["name"]
            entry = all_state.get(cid, {})
            status      = entry.get("status", Status.IDLE)
            reboot_at   = entry.get("last_reboot_at")
            attempt_at  = entry.get("last_attempt_at")
            attempt_cnt = entry.get("attempt_count", 0)
            last_error  = entry.get("last_error", "")

            if reboot_at:
                try:
                    dt = _dt.fromisoformat(reboot_at)
                    if dt.tzinfo is None:
                        dt = self._tz.localize(dt)
                    time_str = dt.strftime("%a %d.%m. %H:%M")
                except Exception:
                    time_str = reboot_at[:16]

                if status == Status.SUCCESS:
                    lines.append(f"✅ *{name}* – {time_str}")
                else:
                    err = last_error or "unbekannt"
                    lines.append(f"❌ *{name}* – letzter Erfolg {time_str} | jetzt: {err}")
            elif attempt_at:
                # Versuche gemacht, aber noch kein Erfolg
                try:
                    dt = _dt.fromisoformat(attempt_at)
                    if dt.tzinfo is None:
                        dt = self._tz.localize(dt)
                    time_str = dt.strftime("%a %d.%m. %H:%M")
                except Exception:
                    time_str = attempt_at[:16]
                err = last_error or "unbekannt"
                tries = f"{attempt_cnt}× versucht" if attempt_cnt else ""
                lines.append(f"❌ *{name}* – {time_str} | {err}{' | ' + tries if tries else ''}")
            else:
                lines.append(f"⏳ *{name}* – noch nie gebootet")

        return "\n".join(lines)

    # ── Dialog 1: Alle sofort prüfen ─────────────────────────────────────────

    def _dlg_lamp_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            self._ld_reset(chat_id)
            self._send(chat_id, "🔄 Prüfe alle Projektoren... (kann einige Sekunden dauern)")
            threading.Thread(
                target=self._run_check_all, args=(chat_id,), daemon=True
            ).start()
        elif t == "2":
            projs = self._lamp_cfg.projectors
            if not projs:
                self._ld_reset(chat_id)
                self._send(chat_id, "❌ Keine Projektoren konfiguriert.")
                return
            lines = ["🎯 *Einzelcheck* – Kino wählen:\n"]
            for i, p in enumerate(projs, 1):
                lines.append(f"{i}. {p['name']} – {p['projector_ip']}")
            lines.append("\n_(0 = Abbrechen)_")
            self._ld_next(chat_id, _LS_SINGLE_SELECT)
            self._send(chat_id, "\n".join(lines))
        elif t == "3":
            self._ld_next(chat_id, _LS_TIME_INPUT)
            self._send(chat_id,
                f"🕐 *Prüfzeit ändern*\n\n"
                f"Aktuell: `{self._lamp_cfg.check_time}`\n"
                f"Neues Format: `HH:MM` (z.B. `20:00`)\n"
                f"_(0 = Abbrechen)_")
        elif t == "4":
            self._ld_next(chat_id, _LS_PROJ_MENU)
            self._send(chat_id,
                "⚙️ *Projektoren bearbeiten*\n\n"
                "1 – IP ändern / hinzufügen\n"
                "2 – IP entfernen\n\n"
                "_(0 = Abbrechen)_")
        elif t == "5":
            self._ld_reset(chat_id)
            self._send(chat_id, self._build_lamp_status())
        else:
            self._send(chat_id, "Bitte 1–5 eingeben.\n\n" + self._lamp_menu_text())

    def _run_check_all(self, chat_id: str) -> None:
        try:
            results = self._lamp.run_now()
            self._send(chat_id, self._format_results(results))
        except Exception as e:
            self._send(chat_id, f"❌ Fehler bei der Prüfung: {e}")

    def _format_results(self, results: list) -> str:
        lines = ["🔦 *Lampen-Prüfung*\n"]
        for r in results:
            if r.ok:
                if r.percent >= self._lamp_cfg.critical_percent:
                    icon = "⛔"
                elif r.percent >= self._lamp_cfg.warn_percent:
                    icon = "⚠️"
                else:
                    icon = "✅"
                lines.append(
                    f"{icon} {r.cinema_name}: "
                    f"`{r.runtime_hours}h / {r.max_hours}h = {r.percent:.1f}%`"
                )
            else:
                lines.append(f"❓ {r.cinema_name}: nicht erreichbar")
        return "\n".join(lines)

    # ── Dialog 2: Einzelner Kino-Check ───────────────────────────────────────

    def _dlg_single_select(self, chat_id: str, text: str) -> None:
        projs = self._lamp_cfg.projectors
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(projs):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        proj = projs[idx]
        self._ld_reset(chat_id)
        self._send(chat_id, f"🔄 Prüfe *{proj['name']}*...")
        threading.Thread(
            target=self._run_check_single,
            args=(chat_id, proj),
            daemon=True,
        ).start()

    def _run_check_single(self, chat_id: str, proj: dict) -> None:
        # Christie hat keinen SNMP-Lampenzähler → Hinweis statt Fehler
        if proj.get("projector_type", "barco").lower() != "barco":
            self._send(
                chat_id,
                f"ℹ️ *{proj['name']}* – kein Lampen-SNMP-Check\n"
                f"Typ: {proj.get('projector_type', '?').upper()} verwendet kein SNMP.\n"
                f"Lampenstatus → Gesundheits-Menü (Option 3 → Einzelcheck)",
            )
            return
        from .lamp_checker import check_lamp
        try:
            result = check_lamp(
                cinema_id=proj["id"],
                cinema_name=proj["name"],
                projector_ip=proj["projector_ip"],
                community=self._lamp_cfg.snmp_community,
                port=self._lamp_cfg.snmp_port,
                timeout=self._lamp_cfg.snmp_timeout,
            )
            self._send(chat_id, self._format_results([result]))
        except Exception as e:
            self._send(chat_id, f"❌ Fehler: {e}")

    # ── Dialog 3: Prüfzeit ändern ─────────────────────────────────────────────

    def _dlg_time_input(self, chat_id: str, text: str) -> None:
        import re
        t = text.strip()
        if not re.match(r"^\d{1,2}:\d{2}$", t):
            self._send(chat_id, "❌ Ungültiges Format. Beispiel: `20:00`")
            return
        h, m = map(int, t.split(":"))
        if h > 23 or m > 59:
            self._send(chat_id, "❌ Ungültige Uhrzeit.")
            return
        new_time = f"{h:02d}:{m:02d}"
        try:
            update_config_value(
                self._config_path,
                ["projector_monitor", "check_time"],
                new_time,
            )
            self._lamp_cfg.check_time = new_time
            self._ld_reset(chat_id)
            self._send(chat_id, f"✅ Prüfzeit auf `{new_time}` gesetzt.")
        except Exception as e:
            self._ld_reset(chat_id)
            self._send(chat_id, f"❌ Fehler beim Speichern: {e}")

    # ── Dialog 4a: Projektor-IP bearbeiten ───────────────────────────────────

    def _dlg_proj_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            # IP hinzufügen/ändern
            cinemas = self._get_all_cinemas_with_status()
            lines = ["📝 *IP ändern / hinzufügen*\n", "Kino wählen:\n"]
            for i, c in enumerate(cinemas, 1):
                ip = c.get("projector_ip", "–")
                lines.append(f"{i}. {c['name']} – IP: `{ip}`")
            lines.append("\n_(0 = Abbrechen)_")
            self._ld_update_data(chat_id, "proj_action", "set")
            self._ld_next(chat_id, _LS_PROJ_SELECT)
            self._send(chat_id, "\n".join(lines))
        elif t == "2":
            # IP entfernen
            projs = self._lamp_cfg.projectors
            if not projs:
                self._ld_reset(chat_id)
                self._send(chat_id, "❌ Keine Projektoren mit IP konfiguriert.")
                return
            lines = ["🗑️ *IP entfernen* – Kino wählen:\n"]
            for i, p in enumerate(projs, 1):
                lines.append(f"{i}. {p['name']} – `{p['projector_ip']}`")
            lines.append("\n_(0 = Abbrechen)_")
            self._ld_next(chat_id, _LS_PROJ_DEL_SELECT)
            self._send(chat_id, "\n".join(lines))
        else:
            self._send(chat_id, "Bitte *1* oder *2* eingeben.")

    def _get_all_cinemas_with_status(self) -> list:
        """Alle Kinos aus der config (nicht nur die mit projector_ip)."""
        import yaml
        try:
            with open(self._config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            return [c for c in raw.get("cinemas", []) if c.get("enabled", True)]
        except Exception:
            return self._lamp_cfg.projectors

    def _dlg_proj_select(self, chat_id: str, text: str) -> None:
        cinemas = self._get_all_cinemas_with_status()
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(cinemas):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        cinema = cinemas[idx]
        self._ld_update_data(chat_id, "cinema_id",   cinema["id"])
        self._ld_update_data(chat_id, "cinema_name", cinema["name"])
        self._ld_next(chat_id, _LS_PROJ_IP_INPUT)
        current_ip = cinema.get("projector_ip", "–")
        self._send(chat_id,
            f"📝 *{cinema['name']}*\n"
            f"Aktuelle IP: `{current_ip}`\n\n"
            f"Neue Projektor-IP eingeben (z.B. `172.20.23.21`):\n"
            f"_(0 = Abbrechen)_")

    def _dlg_proj_ip_input(self, chat_id: str, text: str) -> None:
        import re
        ip = text.strip()
        if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
            self._send(chat_id, "❌ Ungültige IP-Adresse. Beispiel: `172.20.23.21`")
            return
        self._ld_update_data(chat_id, "new_ip", ip)
        self._ld_next(chat_id, _LS_PROJ_IP_CONFIRM)
        name = self._ld_get(chat_id, "cinema_name")
        self._send(chat_id,
            f"*{name}* – Projektor-IP auf `{ip}` setzen?\n"
            f"*ja* bestätigen, *0* abbrechen.")

    def _dlg_proj_ip_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Abgebrochen.")
            return
        cinema_id   = self._ld_get(chat_id, "cinema_id")
        cinema_name = self._ld_get(chat_id, "cinema_name")
        new_ip      = self._ld_get(chat_id, "new_ip")
        try:
            update_cinema_in_config(self._config_path, cinema_id, "projector_ip", new_ip)
            # In-Memory aktualisieren
            for p in self._lamp_cfg.projectors:
                if p["id"] == cinema_id:
                    p["projector_ip"] = new_ip
                    break
            else:
                self._lamp_cfg.projectors.append(
                    {"id": cinema_id, "name": cinema_name, "projector_ip": new_ip}
                )
            self._ld_reset(chat_id)
            self._send(chat_id, f"✅ *{cinema_name}*: Projektor-IP auf `{new_ip}` gesetzt.")
        except Exception as e:
            self._ld_reset(chat_id)
            self._send(chat_id, f"❌ Fehler: {e}")

    # ── Dialog 4b: Projektor-IP entfernen ────────────────────────────────────

    def _dlg_proj_del_select(self, chat_id: str, text: str) -> None:
        projs = self._lamp_cfg.projectors
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(projs):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        proj = projs[idx]
        self._ld_update_data(chat_id, "cinema_id",   proj["id"])
        self._ld_update_data(chat_id, "cinema_name", proj["name"])
        self._ld_update_data(chat_id, "cinema_ip",   proj["projector_ip"])
        self._ld_next(chat_id, _LS_PROJ_DEL_CONFIRM)
        self._send(chat_id,
            f"🗑️ Projektor-IP von *{proj['name']}* (`{proj['projector_ip']}`) entfernen?\n"
            f"*ja* bestätigen, *0* abbrechen.")

    def _dlg_proj_del_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Abgebrochen.")
            return
        cinema_id   = self._ld_get(chat_id, "cinema_id")
        cinema_name = self._ld_get(chat_id, "cinema_name")
        try:
            update_cinema_in_config(self._config_path, cinema_id, "projector_ip", None)
            self._lamp_cfg.projectors = [
                p for p in self._lamp_cfg.projectors if p["id"] != cinema_id
            ]
            self._ld_reset(chat_id)
            self._send(chat_id, f"✅ *{cinema_name}*: Projektor-IP entfernt.")
        except Exception as e:
            self._ld_reset(chat_id)
            self._send(chat_id, f"❌ Fehler: {e}")

    # ── Gesundheits-Menü ─────────────────────────────────────────────────────

    def _open_health_menu(self, chat_id: str) -> None:
        if self._health is None:
            self._ld_reset(chat_id)
            self._send(chat_id,
                "💚 *Projektor-Gesundheit*\n\n"
                "⚠️ _Kein Projektor konfiguriert._\n"
                "Bitte `projector_ip` in config.yaml ergänzen.\n\n"
                "_(0 = Zurück)_")
            return
        self._ld_set(chat_id, _HS_MENU)
        self._send(chat_id, self._health_menu_text())

    def _health_menu_text(self) -> str:
        return (
            "💚 *Projektor-Gesundheit*\n\n"
            "1 – Übersicht (letzter bekannter Status)\n"
            "2 – Sofort alle prüfen\n"
            "3 – Einzelner Projektor-Check\n"
            "4 – 🌡️ Temperatur-Schwellwert ändern\n"
            "5 – 🎛️ Projektor steuern\n"
            "6 – 🌡️ Temperatur-Übersicht\n\n"
            "💚 OK  🔵 Meldung  🟡 Warnung  🔴 Fehler  ⬛ Offline\n\n"
            "_0 = Zurück zum Hauptmenü_"
        )

    def _dlg_health_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            self._ld_reset(chat_id)
            self._send(chat_id, self._build_health_overview())
        elif t == "2":
            self._ld_reset(chat_id)
            self._send(chat_id, "🔄 Prüfe alle Projektoren... (kann einige Sekunden dauern)")
            threading.Thread(
                target=self._run_health_check_all, args=(chat_id,), daemon=True
            ).start()
        elif t == "3":
            projs = self._lamp_cfg.projectors
            if not projs:
                self._ld_reset(chat_id)
                self._send(chat_id, "❌ Keine Projektoren konfiguriert.")
                return
            lines = ["💚 *Einzelcheck* – Projektor wählen:\n"]
            for i, p in enumerate(projs, 1):
                lines.append(f"{i}. {p['name']} – {p['projector_ip']}")
            lines.append("\n_(0 = Abbrechen)_")
            self._ld_next(chat_id, _HS_SINGLE_SELECT)
            self._send(chat_id, "\n".join(lines))
        elif t == "4":
            self._open_temp_menu(chat_id)
        elif t == "5":
            self._open_ctrl_menu(chat_id)
        elif t == "6":
            self._ld_reset(chat_id)
            self._send(chat_id, self._build_temp_overview())
        else:
            self._send(chat_id, "Bitte 1–6 eingeben.\n\n" + self._health_menu_text())

    def _build_health_overview(self) -> str:
        """Übersicht aller Projektor-Zustände aus dem letzten bekannten State."""
        from .health_checker import HealthColor
        state = self._health.get_state()
        all_data = state.get_all()

        lines = ["💚 *Projektor-Gesundheit – Übersicht*\n"]

        for proj in self._lamp_cfg.projectors:
            cid  = proj["id"]
            name = proj["name"]
            entry = all_data.get(cid)

            if not entry:
                lines.append(f"❓ *{name}* – noch nicht geprüft")
                continue

            color    = entry.get("color", "unknown")
            checked  = entry.get("last_checked", "—")
            notif    = entry.get("notifications", 0)
            warn     = entry.get("warnings", 0)
            err      = entry.get("errors", 0)
            temp     = entry.get("temperature_c", -1.0)
            lamp_on  = entry.get("lamp_on")
            details  = entry.get("error_details", [])

            icon = {
                HealthColor.GREEN:   "💚",
                HealthColor.BLUE:    "🔵",
                HealthColor.YELLOW:  "🟡",
                HealthColor.RED:     "🔴",
                HealthColor.OFFLINE: "⬛",
            }.get(color, "❓")

            # Lampenstatus-Icon
            if lamp_on is True:
                lamp_str = " 💡AN"
            elif lamp_on is False:
                lamp_str = " 🌑AUS"
            else:
                lamp_str = ""

            # Temperatur
            temp_str = f" 🌡️{temp:.0f}°C" if temp > 0 else ""

            checked_short = checked[11:16] if len(checked) > 11 else checked

            if color == HealthColor.OFFLINE:
                status_line = f"{icon} *{name}* – stromlos / offline"
            elif color == HealthColor.RED:
                n_issues = len(details) if details else err + warn
                status_line = (
                    f"{icon} *{name}*{lamp_str}{temp_str} – "
                    f"{n_issues} Problem{'e' if n_issues != 1 else ''}"
                )
            elif color == HealthColor.YELLOW:
                n_warn = sum(1 for d in details if d.startswith("🟡")) if details else warn
                status_line = (
                    f"{icon} *{name}*{lamp_str}{temp_str} – "
                    f"{n_warn} Warnung{'en' if n_warn != 1 else ''}"
                )
            elif color == HealthColor.BLUE:
                n_notif = len(details) if details else (bin(notif).count('1') if notif else 0)
                status_line = (
                    f"{icon} *{name}*{lamp_str}{temp_str}"
                    + (f" – {n_notif} Meldung{'en' if n_notif != 1 else ''}" if n_notif else "")
                )
            else:
                status_line = f"{icon} *{name}*{lamp_str}{temp_str}"

            lines.append(f"{status_line}\n   _geprüft {checked_short}_")

            # Top-Fehlerdetails bei ROT anzeigen (max. 3)
            if color == HealthColor.RED and details:
                for d in details[:3]:
                    lines.append(f"   • {d}")

        if not self._lamp_cfg.projectors:
            lines.append("_Keine Projektoren konfiguriert._")

        return "\n".join(lines)

    def _build_temp_overview(self) -> str:
        """Zeigt Temperaturen aller Projektoren aus dem letzten bekannten State."""
        state    = self._health.get_state()
        all_data = state.get_all()
        thresholds = self._health.get_thresholds() if hasattr(self._health, "get_thresholds") else None

        lines = ["🌡️ *Temperatur-Übersicht* (letzter bekannter Wert)\n"]
        any_temp = False
        for proj in self._lamp_cfg.projectors:
            cid   = proj["id"]
            name  = proj["name"]
            entry = all_data.get(cid)
            temp  = entry.get("temperature_c", -1.0) if entry else -1.0
            thr   = thresholds.get(cid) if thresholds else 70

            if temp and temp > 0:
                any_temp = True
                # Warnsymbol wenn nahe oder über Schwellwert
                if temp >= thr:
                    sym = "🔴"
                elif temp >= thr - 5:
                    sym = "🟡"
                else:
                    sym = "🟢"
                lines.append(f"{sym} *{name}*: {temp:.1f}°C  _(Schwellwert: {thr}°C)_")
            else:
                checked = (entry or {}).get("color", "?")
                if checked == "offline":
                    lines.append(f"⬛ *{name}*: offline")
                else:
                    lines.append(f"❓ *{name}*: keine Temp.-Daten")

        if not any_temp:
            lines.append(
                "\n_Hinweis: Für Barco-Projektoren muss `snmp_temp_oid` in config.yaml "
                "konfiguriert sein. Christie-Projektoren liefern Temperatur automatisch._"
            )

        checked_str = ""
        for proj in self._lamp_cfg.projectors:
            entry = all_data.get(proj["id"])
            if entry and entry.get("last_checked"):
                checked_str = entry["last_checked"][11:16]
                break
        if checked_str:
            lines.append(f"\n_Stand: {checked_str} – Option 2 für Sofortprüfung_")

        return "\n".join(lines)

    def _run_health_check_all(self, chat_id: str) -> None:
        try:
            results = self._health.check_all_now()
            self._send(chat_id, self._format_health_results(results))
        except Exception as e:
            self._send(chat_id, f"❌ Fehler bei der Prüfung: {e}")

    def _format_health_results(self, results: list) -> str:
        from .health_checker import HealthColor
        lines = ["💚 *Projektor-Gesundheit – Sofortprüfung*\n"]
        for r in results:
            icon = {
                HealthColor.GREEN:   "💚",
                HealthColor.BLUE:    "🔵",
                HealthColor.YELLOW:  "🟡",
                HealthColor.RED:     "🔴",
                HealthColor.OFFLINE: "⬛",
            }.get(r.color, "❓")

            lamp_str = ""
            if r.lamp_on is True:
                lamp_str = " 💡AN"
            elif r.lamp_on is False:
                lamp_str = " 🌑AUS"

            temp_str = f" 🌡️{r.temperature_c:.0f}°C" if r.temperature_c > 0 else ""

            if r.color == HealthColor.OFFLINE:
                lines.append(f"{icon} *{r.cinema_name}* – stromlos / offline")
            elif r.color == HealthColor.RED:
                n_issues = len(r.error_details) if r.error_details else r.errors + r.warnings
                lines.append(
                    f"{icon} *{r.cinema_name}*{lamp_str}{temp_str} – "
                    f"{n_issues} Problem{'e' if n_issues != 1 else ''}"
                )
                for d in r.error_details[:3]:
                    lines.append(f"   • {d}")
            elif r.color == HealthColor.YELLOW:
                n_warn = sum(1 for d in r.error_details if d.startswith("🟡")) if r.error_details else r.warnings
                lines.append(
                    f"{icon} *{r.cinema_name}*{lamp_str}{temp_str} – "
                    f"{n_warn} Warnung{'en' if n_warn != 1 else ''}"
                )
            elif r.color == HealthColor.BLUE:
                n_notif = len(r.error_details) if r.error_details else (bin(r.notifications).count('1') if r.notifications else 0)
                lines.append(
                    f"{icon} *{r.cinema_name}*{lamp_str}{temp_str}"
                    + (f" – {n_notif} Meldung{'en' if n_notif != 1 else ''}" if n_notif else "")
                )
            else:
                lines.append(f"{icon} *{r.cinema_name}*{lamp_str}{temp_str}")

        return "\n".join(lines)

    def _dlg_health_single_select(self, chat_id: str, text: str) -> None:
        projs = self._lamp_cfg.projectors
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(projs):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        proj = projs[idx]
        self._ld_reset(chat_id)
        self._send(chat_id, f"🔄 Prüfe *{proj['name']}*...")
        threading.Thread(
            target=self._run_health_check_single,
            args=(chat_id, proj),
            daemon=True,
        ).start()

    def _run_health_check_single(self, chat_id: str, proj: dict) -> None:
        try:
            result = self._health.check_one_now(proj)
            self._send(chat_id, self._format_health_results([result]))
        except Exception as e:
            self._send(chat_id, f"❌ Fehler: {e}")

    # ── Temperatur-Schwellwert (Gesundheit Option 4) ──────────────────────────

    def _open_temp_menu(self, chat_id: str) -> None:
        if self._health is None:
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Kein Gesundheits-Monitor aktiv.")
            return
        projs = self._lamp_cfg.projectors
        if not projs:
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Keine Projektoren konfiguriert.")
            return
        thresholds = self._health.get_thresholds()
        lines = ["🌡️ *Temperatur-Schwellwert ändern*\n", "Kino wählen:\n"]
        for i, p in enumerate(projs, 1):
            current = thresholds.get(p["id"])
            lines.append(f"{i}. {p['name']} – aktuell: {current:.0f}°C")
        lines.append("\n_(0 = Abbrechen)_")
        self._ld_set(chat_id, _HS_TEMP_SELECT)
        self._send(chat_id, "\n".join(lines))

    def _dlg_temp_select(self, chat_id: str, text: str) -> None:
        projs = self._lamp_cfg.projectors
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(projs):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        proj = projs[idx]
        current = self._health.get_thresholds().get(proj["id"])
        self._ld_update_data(chat_id, "cinema_id",   proj["id"])
        self._ld_update_data(chat_id, "cinema_name", proj["name"])
        self._ld_next(chat_id, _HS_TEMP_INPUT)
        self._send(chat_id,
            f"🌡️ *{proj['name']}*\n"
            f"Aktueller Schwellwert: `{current:.0f}°C`\n\n"
            f"Neuen Schwellwert eingeben (z.B. `70`):\n"
            f"_(Empfehlung: 65–75°C | 0 = Abbrechen)_")

    def _dlg_temp_input(self, chat_id: str, text: str) -> None:
        try:
            val = float(text.strip().replace(",", "."))
            if val < 20 or val > 120:
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültiger Wert. Bitte Zahl zwischen 20 und 120 eingeben.")
            return
        cinema_id   = self._ld_get(chat_id, "cinema_id")
        cinema_name = self._ld_get(chat_id, "cinema_name")
        self._health.get_thresholds().set(cinema_id, val)
        self._ld_reset(chat_id)
        self._send(chat_id, f"✅ *{cinema_name}*: Temperatur-Schwellwert auf `{val:.0f}°C` gesetzt.")

    # ── Projektor-Steuerung (Gesundheit Option 5) ─────────────────────────────

    def _open_ctrl_menu(self, chat_id: str) -> None:
        if self._health is None:
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Kein Gesundheits-Monitor aktiv.")
            return
        projs = self._lamp_cfg.projectors
        if not projs:
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Keine Projektoren konfiguriert.")
            return
        lines = ["🎛️ *Projektor steuern*\n", "Welchen Kinosaal steuern?\n"]
        for i, p in enumerate(projs, 1):
            ptype = p.get("projector_type", "barco").upper()
            lines.append(f"{i}. {p['name']} ({ptype})")
        lines.append("\n⚠️ _Jede Aktion erfordert Bestätigung!_")
        lines.append("_(0 = Abbrechen)_")
        self._ld_set(chat_id, _HS_CTRL_SELECT)
        self._send(chat_id, "\n".join(lines))

    def _dlg_ctrl_select(self, chat_id: str, text: str) -> None:
        projs = self._lamp_cfg.projectors
        try:
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(projs):
                raise ValueError
        except ValueError:
            self._send(chat_id, "❌ Ungültige Nummer.")
            return
        proj = projs[idx]
        ptype = proj.get("projector_type", "barco").lower()
        lamp_label = "Laser" if ptype == "christie" else "Lampe"
        self._ld_update_data(chat_id, "proj_id",   proj["id"])
        self._ld_update_data(chat_id, "proj_name", proj["name"])
        self._ld_update_data(chat_id, "proj_ip",   proj["projector_ip"])
        self._ld_update_data(chat_id, "proj_port", proj.get("projector_port", 43728))
        self._ld_update_data(chat_id, "proj_type", ptype)
        self._ld_next(chat_id, _HS_CTRL_ACTION)
        self._send(chat_id,
            f"🎛️ *{proj['name']}* – Was möchten Sie tun?\n\n"
            f"1 – 💡 {lamp_label} EIN\n"
            f"2 – 🌑 {lamp_label} AUS\n"
            f"3 – 🟢 Douser AUF (Bild freigeben)\n"
            f"4 – ⛔ Douser ZU (Bild sperren)\n\n"
            f"_(0 = Abbrechen)_")

    _CTRL_ACTIONS = {
        "1": ("lamp_on",     "💡 Lampe/Laser EIN"),
        "2": ("lamp_off",    "🌑 Lampe/Laser AUS"),
        "3": ("douser_open", "🟢 Douser AUF"),
        "4": ("douser_close","⛔ Douser ZU"),
    }

    def _dlg_ctrl_action(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t not in self._CTRL_ACTIONS:
            self._send(chat_id, "❌ Bitte 1, 2, 3 oder 4 eingeben.")
            return
        action, label = self._CTRL_ACTIONS[t]
        proj_name = self._ld_get(chat_id, "proj_name")
        self._ld_update_data(chat_id, "action",       action)
        self._ld_update_data(chat_id, "action_label", label)
        self._ld_next(chat_id, _HS_CTRL_CONFIRM)
        self._send(chat_id,
            f"⚠️ *Bestätigung erforderlich*\n\n"
            f"Saal: *{proj_name}*\n"
            f"Aktion: *{label}*\n\n"
            f"*ja* – Ausführen\n"
            f"*0* – Abbrechen")

    def _dlg_ctrl_confirm(self, chat_id: str, text: str) -> None:
        if text.strip().lower() not in ("ja", "yes", "j", "y"):
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Abgebrochen.")
            return
        proj_name = self._ld_get(chat_id, "proj_name")
        proj_ip   = self._ld_get(chat_id, "proj_ip")
        proj_port = self._ld_get(chat_id, "proj_port")
        proj_type = self._ld_get(chat_id, "proj_type")
        action    = self._ld_get(chat_id, "action")
        label     = self._ld_get(chat_id, "action_label")
        self._ld_reset(chat_id)
        self._send(chat_id, f"⏳ Sende Befehl an *{proj_name}*...")
        threading.Thread(
            target=self._run_ctrl_command,
            args=(chat_id, proj_name, proj_ip, proj_port, proj_type, action, label),
            daemon=True,
        ).start()

    def _run_ctrl_command(
        self,
        chat_id:   str,
        proj_name: str,
        proj_ip:   str,
        proj_port: int,
        proj_type: str,
        action:    str,
        label:     str,
    ) -> None:
        from .projector_commander import (
            cmd_lamp_on, cmd_lamp_off,
            cmd_douser_open, cmd_douser_close,
        )
        cmd_map = {
            "lamp_on":     cmd_lamp_on,
            "lamp_off":    cmd_lamp_off,
            "douser_open": cmd_douser_open,
            "douser_close":cmd_douser_close,
        }
        fn = cmd_map.get(action)
        if fn is None:
            self._send(chat_id, f"❌ Unbekannte Aktion: {action}")
            return
        try:
            result = fn(
                projector_ip=proj_ip,
                projector_port=int(proj_port),
                projector_type=proj_type,
            )
            if result.success:
                self._send(chat_id,
                    f"✅ *{proj_name}* – {label}\n"
                    f"Befehl erfolgreich gesendet."
                    + (f"\n`{result.raw_resp}`" if result.raw_resp else ""))
            else:
                self._send(chat_id,
                    f"❌ *{proj_name}* – {label}\n"
                    f"Fehler: {result.message}")
        except Exception as e:
            self._send(chat_id, f"❌ Ausnahmefehler: {e}")

    # ── Dialog 5: Status ──────────────────────────────────────────────────────

    def _build_lamp_status(self) -> str:
        from .lamp_state import LampState
        state = LampState(self._lamp_cfg.state_file)
        last = state._data.get("last_check_date", "—")
        last_results = state._data.get("last_results", [])

        lines = [
            "🔦 *Lampen-Monitor Status*\n",
            f"Letzter Check: `{last}`",
            f"Prüfzeit:      `{self._lamp_cfg.check_time}`",
            f"Warn:          `≥{self._lamp_cfg.warn_percent:.0f}%`",
            f"Kritisch:      `≥{self._lamp_cfg.critical_percent:.0f}%`",
            f"Projektoren:   `{len(self._lamp_cfg.projectors)}`",
        ]

        if last_results:
            lines.append("\n*Letztes Ergebnis:*")
            for r in last_results:
                icon = "✅" if r.get("ok") else "❓"
                if r.get("ok"):
                    pct = r.get("percent", 0)
                    if pct >= self._lamp_cfg.critical_percent:
                        icon = "⛔"
                    elif pct >= self._lamp_cfg.warn_percent:
                        icon = "⚠️"
                    lines.append(
                        f"  {icon} {r['name']}: "
                        f"`{r['runtime']}h / {r['max']}h = {pct:.1f}%`"
                    )
                else:
                    lines.append(f"  {icon} {r['name']}: nicht erreichbar")

        return "\n".join(lines)

    # ── Programm-Steuerung (Hauptmenü Option 4) ───────────────────────────────

    def send_startup_notification(self) -> None:
        """
        Sendet Hauptmenü an alle autorisierten Chats nach Programmstart.
        Wird von main.py aufgerufen, sobald alle Komponenten bereit sind.
        """
        import os
        restarted = os.environ.get("CINEMA_RESTARTED") == "1"
        header = (
            "🔄 *Neustart erfolgreich!*\n"
            "Alle Komponenten sind bereit.\n\n"
            if restarted else
            "🚀 *Programm gestartet!*\n\n"
        )
        msg = header + self._main_menu()

        # An Haupt-Chat-ID senden
        all_chats = [self._config.telegram_chat_id]
        for cid in self._config.telegram_admin_chat_ids:
            if cid not in all_chats:
                all_chats.append(cid)

        for chat_id in all_chats:
            try:
                self._send(chat_id, msg)
            except Exception as e:
                logger.warning(f"[STARTUP] Benachrichtigung an {chat_id} fehlgeschlagen: {e}")

    def _open_prog_menu(self, chat_id: str) -> None:
        self._ld_set(chat_id, _PS_MENU)
        self._send(chat_id, self._prog_menu_text())

    def _prog_menu_text(self) -> str:
        paused = self._app_state.paused
        pause_line = (
            "1 – ▶️ Monitoring fortsetzen"
            if paused else
            "1 – ⏸️ Monitoring pausieren"
        )
        status = "⏸️ PAUSIERT" if paused else "▶️ AKTIV"
        return (
            f"⚙️ *Programm-Steuerung*\n"
            f"Status: {status}\n\n"
            f"{pause_line}\n"
            f"2 – 🔄 Programm neu starten\n"
            f"3 – 🛑 Programm beenden\n"
            f"4 – 📊 Version & Laufzeit\n\n"
            f"_0 = Zurück_"
        )

    def _dlg_prog_menu(self, chat_id: str, text: str) -> None:
        t = text.strip()
        if t == "1":
            if self._app_state.paused:
                self._app_state.resume()
                self._ld_reset(chat_id)
                self._send(chat_id, "▶️ Monitoring *fortgesetzt*.")
            else:
                self._app_state.pause()
                self._ld_reset(chat_id)
                self._send(chat_id, "⏸️ Monitoring *pausiert*.\n\nMit Option 1 wieder fortsetzen.")
        elif t == "2":
            self._ld_next(chat_id, _PS_RESTART_CONFIRM)
            self._send(chat_id,
                "🔄 *Programm wirklich neu starten?*\n\n"
                "Das Programm stoppt kurz und startet sich selbst neu.\n\n"
                "*ja* bestätigen, *0* abbrechen.")
        elif t == "3":
            self._ld_next(chat_id, _PS_STOP_CONFIRM)
            self._send(chat_id,
                "🛑 *Programm wirklich beenden?*\n\n"
                "Das Programm stoppt vollständig. Manueller Neustart nötig.\n\n"
                "*ja* bestätigen, *0* abbrechen.")
        elif t == "4":
            self._ld_reset(chat_id)
            self._send(chat_id, self._build_ping())
        else:
            self._send(chat_id, "Bitte 1–4 eingeben.\n\n" + self._prog_menu_text())

    def _dlg_prog_restart_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Abgebrochen.")
            return
        self._ld_reset(chat_id)
        self._send(chat_id, "🔄 Programm wird neu gestartet...")
        import os, subprocess, sys, threading as _t
        def _do_restart():
            import time
            time.sleep(1)   # kurz warten damit Telegram-Nachricht rausgeht
            env = os.environ.copy()
            env["CINEMA_RESTARTED"] = "1"
            subprocess.Popen([sys.executable] + sys.argv, cwd=os.getcwd(), env=env)
            os._exit(0)
        _t.Thread(target=_do_restart, daemon=True).start()

    def _dlg_prog_stop_confirm(self, chat_id: str, text: str) -> None:
        if text.lower() not in ("ja", "yes", "j", "y"):
            self._ld_reset(chat_id)
            self._send(chat_id, "❌ Abgebrochen.")
            return
        self._ld_reset(chat_id)
        self._send(chat_id, "🛑 Programm wird beendet...")
        self._app_state.request_shutdown()
