"""
LampTelegramController – Hauptmenü mit 3 Bereichen + Lampen-Befehle.

Erbt von cinema_reboot.TelegramController.
cinema_reboot/ wird dabei NICHT verändert.

Hauptmenü (3 Bereiche):
  1 – 🔄 Server-Neustart  → Untermenü mit allen Reboot-Befehlen
  2 – 🔦 Lampen-Monitor   → Untermenü mit Lampen-Befehlen
  3 – 💚 Projektor-Gesundheit → (kommt nach Screenshots)

Lampen-Untermenü:
  1 – Alle Projektoren sofort prüfen
  2 – Einzelner Kino-Check
  3 – Prüfzeit ändern
  4 – Projektor-IP bearbeiten
  5 – Status (letzter Check)
"""
import logging
import threading
from typing import Optional

from cinema_reboot.config_writer import update_cinema_in_config, update_config_value
from cinema_reboot.telegram_controller import TelegramController

from .lamp_config import LampConfig
from .lamp_monitor import LampMonitor

logger = logging.getLogger(__name__)

# Dialog-Zustände
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
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._lamp        = lamp_monitor
        self._lamp_cfg    = lamp_config
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
            self._ld_reset(chat_id)
            self._send(chat_id,
                "💚 *Projektor-Gesundheit*\n\n"
                "⏳ _Wird gerade entwickelt..._\n"
                "_(Screenshots ausstehend)_\n\n"
                "_(0 = Zurück)_")
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
            f"3 – 💚 Projektor-Gesundheit\n\n"
            f"_0 oder /abbrechen = Abbrechen_"
        )

    def _reboot_submenu_text(self) -> str:
        paused = "⏸️ pausiert" if self._app_state.paused else "▶️ läuft"
        mode   = "⚠️ DRY-RUN"  if self._config.dry_run   else "✅ LIVE"
        return (
            f"🔄 *Server-Neustart*  ({paused} | {mode})\n\n"
            f"1 – Status aller Kinos\n"
            f"2 – Letzter Reboot (alle Säle)\n"
            f"3 – Automatisierung pausieren\n"
            f"4 – Automatisierung fortsetzen\n"
            f"5 – Wartungsfenster ändern\n"
            f"6 – Server konfigurieren\n"
            f"7 – Zugangsdaten ändern\n"
            f"8 – Sofort-Reboot auslösen\n"
            f"9 – Scheduler neu starten\n"
            f"10 – Programm beenden\n"
            f"11 – Browser-Modus umschalten\n"
            f"12 – Version & Laufzeit\n\n"
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
        }
        handler = dispatch.get(state)
        if handler:
            handler(chat_id, text)
        else:
            self._ld_reset(chat_id)
            self._send(chat_id, "❓ Unbekannter Zustand – zurückgesetzt.")

    # ── Reboot-Untermenü ─────────────────────────────────────────────────────

    def _dlg_reboot_submenu(self, chat_id: str, text: str) -> None:
        """Leitet Auswahl im Reboot-Untermenü weiter.
        '2' → Letzter-Reboot-Status, alle anderen → Original-Reboot-Handler."""
        self._ld_reset(chat_id)
        if text.strip() == "2":
            self._send(chat_id, self._build_last_reboot_status())
        else:
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
