"""
Watchdog für Cinema Server Reboot.

Prüft alle 60 Sekunden ob das Hauptprogramm läuft (via TCP-Port 47392).
Sendet eine Telegram-Nachricht wenn es ausgefallen ist.
Nach einem Alarm: erneuter Alarm frühestens nach 10 Minuten.

Start: python watchdog_cinema.py
Auto-Start: via Windows Task Scheduler (Trigger: Bei Anmeldung)
"""
import os
import socket
import time
from pathlib import Path

import requests
import yaml

# ── Konfiguration ─────────────────────────────────────────────────────────────

_BASE_DIR      = Path(__file__).resolve().parent
_CONFIG_PATH   = _BASE_DIR / "config.yaml"
_LOCK_PORT     = 47392        # Muss mit main.py übereinstimmen
_CHECK_INTERVAL   = 60        # Sekunden zwischen Prüfungen
_ALERT_COOLDOWN   = 600       # Sekunden bis zum nächsten Alarm (10 Min.)
_TELEGRAM_TIMEOUT = 10


def _load_telegram_config() -> tuple[str, str]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["telegram"]["bot_token"], str(cfg["telegram"]["chat_id"])


# ── Kernfunktionen ─────────────────────────────────────────────────────────────

def _is_running() -> bool:
    """True wenn Cinema Server Reboot läuft (Port 47392 belegt)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", _LOCK_PORT))
        sock.close()
        return False  # Bind erfolgreich → Port frei → Programm nicht aktiv
    except OSError:
        return True   # Port belegt → Programm läuft


def _send_alert(bot_token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=_TELEGRAM_TIMEOUT,
        )
    except Exception:
        pass  # Kein Absturz wenn Telegram nicht erreichbar


# ── Hauptschleife ──────────────────────────────────────────────────────────────

def main() -> None:
    bot_token, chat_id = _load_telegram_config()
    last_alert: float = 0.0

    while True:
        time.sleep(_CHECK_INTERVAL)

        if _is_running():
            continue

        now = time.time()
        if now - last_alert < _ALERT_COOLDOWN:
            continue

        _send_alert(
            bot_token,
            chat_id,
            "⚠️ <b>Cinema Server Reboot – AUSGEFALLEN</b>\n"
            "Das Programm läuft nicht mehr.\n"
            "<i>Bitte server_neustart.vbs manuell starten.</i>",
        )
        last_alert = now


if __name__ == "__main__":
    main()
