"""
Telegram-Sender – sendet Nachrichten über die Telegram Bot API.

Alle Nachrichten enthalten:
  - Kino-Name und -Nummer
  - Uhrzeit (Europe/Berlin)
  - Grund / Status
  - Nächster Retry-Zeitpunkt (wenn vorhanden)
"""
import html
import logging
import threading
import requests
from datetime import datetime
from typing import Optional
import pytz

from .config import Config

logger = logging.getLogger(__name__)

# Emoji-Codes für verschiedene Nachrichtentypen
EMOJI_OK = "✅"
EMOJI_WARN = "⚠️"
EMOJI_ERROR = "❌"
EMOJI_INFO = "ℹ️"
EMOJI_FIRE = "🔥"  # Kritischer Alarm


class TelegramSender:
    """Sendet Nachrichten an einen Telegram-Bot."""

    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: Config):
        self._config = config
        self._tz = pytz.timezone(config.timezone)
        self._enabled = config.telegram_enabled
        self._lock = threading.Lock()
        if self._enabled:
            self._token = config.telegram_token
            self._chat_id = config.telegram_chat_id

    def _now_str(self) -> str:
        return datetime.now(self._tz).strftime("%d.%m.%Y %H:%M:%S")

    def _send(self, text: str) -> bool:
        """Sendet eine Nachricht. Gibt True zurück bei Erfolg."""
        if not self._enabled:
            logger.debug(f"[Telegram DEAKTIVIERT] Nachricht würde lauten:\n{text}")
            return True

        url = self.API_URL.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            with self._lock:
                resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.debug("Telegram-Nachricht erfolgreich gesendet.")
                return True
            else:
                logger.error(f"Telegram-Fehler {resp.status_code}: {resp.text}")
                return False
        except requests.RequestException as e:
            logger.error(f"Telegram-Netzwerkfehler: {e}")
            return False

    def send_reboot_success(self, cinema_name: str, duration_seconds: float) -> None:
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        text = (
            f"{EMOJI_OK} <b>Reboot erfolgreich</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Dauer: {minutes}m {seconds}s\n"
            f"Server ist wieder online."
        )
        self._send(text)

    def send_reboot_blocked_playback(
        self,
        cinema_name: str,
        next_retry: Optional[datetime] = None,
    ) -> None:
        retry_str = ""
        if next_retry:
            retry_str = f"\nNächster Versuch: {next_retry.strftime('%H:%M:%S')} Uhr"

        text = (
            f"{EMOJI_FIRE} <b>REBOOT ABGEBROCHEN – Playback läuft!</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Grund: Playback ist aktiv – Reboot wurde NICHT ausgeführt.\n"
            f"Aktion: Popup mit <b>Abbrechen</b> bestätigt.{retry_str}"
        )
        self._send(text)

    def send_reboot_blocked_transfer(
        self,
        cinema_name: str,
        next_retry: Optional[datetime] = None,
    ) -> None:
        retry_str = ""
        if next_retry:
            retry_str = f"\nNächster Versuch: {next_retry.strftime('%H:%M:%S')} Uhr"

        text = (
            f"{EMOJI_WARN} <b>Reboot verzögert – Transfer aktiv</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Grund: Ingest/Export/Transfer läuft.{retry_str}"
        )
        self._send(text)

    def send_server_offline(
        self,
        cinema_name: str,
        ip: str,
        next_retry: Optional[datetime] = None,
    ) -> None:
        retry_str = ""
        if next_retry:
            retry_str = f"\nNächster Versuch: {next_retry.strftime('%H:%M:%S')} Uhr"

        text = (
            f"{EMOJI_ERROR} <b>Server nicht erreichbar</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"IP: {ip}\n"
            f"Zeit: {self._now_str()}\n"
            f"Grund: HTTP-Verbindung fehlgeschlagen.{retry_str}"
        )
        self._send(text)

    def send_ui_unclear(
        self,
        cinema_name: str,
        detail: str,
        next_retry: Optional[datetime] = None,
    ) -> None:
        retry_str = ""
        if next_retry:
            retry_str = f"\nNächster Versuch: {next_retry.strftime('%H:%M:%S')} Uhr"

        text = (
            f"{EMOJI_WARN} <b>Reboot abgebrochen – UI unklar</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Detail: {html.escape(str(detail)[:400])}\n"
            f"Aktion: Konservativ abgebrochen (kein Reboot).{retry_str}"
        )
        self._send(text)

    def send_error(
        self,
        cinema_name: str,
        error: str,
        next_retry: Optional[datetime] = None,
    ) -> None:
        retry_str = ""
        if next_retry:
            retry_str = f"\nNächster Versuch: {next_retry.strftime('%H:%M:%S')} Uhr"

        text = (
            f"{EMOJI_ERROR} <b>Technischer Fehler</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Fehler: {html.escape(str(error)[:400])}{retry_str}"
        )
        self._send(text)

    def send_reboot_timeout(self, cinema_name: str) -> None:
        text = (
            f"{EMOJI_ERROR} <b>Reboot-Timeout – Server offline!</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}\n"
            f"Der Server ist nach dem Reboot nicht wieder online gegangen.\n"
            f"⚠️ BITTE MANUELL PRÜFEN!"
        )
        self._send(text)

    def send_start_attempt(self, cinema_name: str, dry_run: bool = False) -> None:
        mode = " [DRY-RUN]" if dry_run else ""
        text = (
            f"{EMOJI_INFO} <b>Reboot-Versuch gestartet{mode}</b>\n"
            f"Kino: <b>{cinema_name}</b>\n"
            f"Zeit: {self._now_str()}"
        )
        self._send(text)

    def send_parallel_summary(self, groups: dict, total: int) -> None:
        """Sendet eine Zusammenfassung nach einem parallelen Reboot."""
        success = groups.get("success", [])
        blocked_play = groups.get("blocked_by_playback", [])
        blocked_transfer = groups.get("blocked_by_transfer", [])
        ui_unclear = groups.get("ui_unclear", [])
        offline = groups.get("offline", [])
        timeout = groups.get("timeout", [])
        errors = groups.get("error", [])

        lines = [
            f"{EMOJI_INFO} <b>Paralleler Reboot abgeschlossen</b>",
            f"Zeit: {self._now_str()}",
            f"Gesamt: {total} Kinos",
            "",
        ]
        if success:
            names = ", ".join(success)
            lines.append(f"{EMOJI_OK} Erfolgreich ({len(success)}): {names}")
        if blocked_play:
            names = ", ".join(blocked_play)
            lines.append(f"{EMOJI_FIRE} Playback aktiv ({len(blocked_play)}): {names}")
        if blocked_transfer:
            names = ", ".join(blocked_transfer)
            lines.append(f"{EMOJI_WARN} Transfer aktiv ({len(blocked_transfer)}): {names}")
        if ui_unclear:
            names = ", ".join(ui_unclear)
            lines.append(f"{EMOJI_WARN} UI unklar ({len(ui_unclear)}): {names}")
        if offline:
            names = ", ".join(offline)
            lines.append(f"{EMOJI_ERROR} Offline ({len(offline)}): {names}")
        if timeout:
            names = ", ".join(timeout)
            lines.append(f"{EMOJI_ERROR} Timeout ({len(timeout)}): {names}")
        if errors:
            names = ", ".join(errors)
            lines.append(f"{EMOJI_ERROR} Fehler ({len(errors)}): {names}")

        self._send("\n".join(lines))

    def send_status(self, status_text: str) -> None:
        """Sendet eine freie Status-Nachricht."""
        self._send(f"{EMOJI_INFO} {status_text}")

    def send_all_done(self, cinema_names: list[str]) -> None:
        """Sendet eine Erfolgsmeldung wenn alle Säle erfolgreich neu gestartet wurden."""
        names = "\n".join(f"  {EMOJI_OK} {n}" for n in cinema_names)
        self._send(
            f"{EMOJI_OK} <b>Alle Säle erledigt!</b>\n"
            f"Zeit: {self._now_str()}\n\n"
            f"{names}"
        )

    def send_window_closed_report(self, failed: list[str], succeeded: list[str]) -> None:
        """Sendet einen Abschlussbericht wenn das Wartungsfenster geschlossen wurde."""
        lines = [f"{EMOJI_WARN} <b>Wartungsfenster beendet – nicht alle Säle erledigt</b>",
                 f"Zeit: {self._now_str()}", ""]
        if failed:
            lines.append(f"{EMOJI_ERROR} Nicht geschafft ({len(failed)}):")
            for n in failed:
                lines.append(f"  • {n}")
        if succeeded:
            lines.append(f"\n{EMOJI_OK} Erfolgreich ({len(succeeded)}):")
            for n in succeeded:
                lines.append(f"  • {n}")
        self._send("\n".join(lines))
