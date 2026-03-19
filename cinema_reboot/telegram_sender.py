"""
Telegram-Sender – sendet Nachrichten über die Telegram Bot API.

Alle Nachrichten enthalten:
  - Kino-Name und -Nummer
  - Uhrzeit (Europe/Berlin)
  - Grund / Status
  - Nächster Retry-Zeitpunkt (wenn vorhanden)
"""
import logging
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
            f"Detail: {detail}\n"
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
            f"Fehler: {error}{retry_str}"
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

    def send_status(self, status_text: str) -> None:
        """Sendet eine freie Status-Nachricht."""
        self._send(f"{EMOJI_INFO} {status_text}")
