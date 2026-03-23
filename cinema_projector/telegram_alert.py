"""
Telegram-Benachrichtigungen für den Lampen-Monitor.
Nutzt denselben Bot/Chat wie das Reboot-Modul, mit [LAMPE]-Prefix.
Sendet NUR bei Warnungen (≥145%) oder Fehlern – kein Spam bei normalen Werten.
"""
import logging
from typing import List

import requests

from .lamp_checker import LampResult

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def _send(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        logger.debug("[LAMPE] Telegram-Nachricht gesendet.")
    except Exception as e:
        logger.warning(f"[LAMPE] Telegram-Fehler: {e}")


def send_daily_report(
    bot_token: str,
    chat_id: str,
    results: List[LampResult],
    warn_percent: float,
    critical_percent: float,
) -> None:
    """
    Sendet Tagesbericht nur wenn mindestens eine Lampe ≥warn_percent oder ein Fehler vorliegt.
    Bei allen Lampen unter warn_percent: kein Telegram.
    """
    criticals = [r for r in results if r.ok and r.percent >= critical_percent]
    warnings  = [r for r in results if r.ok and warn_percent <= r.percent < critical_percent]
    errors    = [r for r in results if not r.ok]

    if not criticals and not warnings and not errors:
        logger.info("[LAMPE] Alle Lampen OK – kein Alarm nötig.")
        return

    lines = ["🔦 <b>[LAMPE] Tagesprüfung</b>"]

    if criticals:
        lines.append(f"\n⛔ <b>KRITISCH (≥{int(critical_percent)}%):</b>")
        for r in criticals:
            lines.append(
                f"  • {r.cinema_name}: {r.runtime_hours}h / {r.max_hours}h"
                f" = <b>{r.percent:.1f}%</b>"
            )

    if warnings:
        lines.append(f"\n⚠️ <b>WARNUNG (≥{int(warn_percent)}%):</b>")
        for r in warnings:
            lines.append(
                f"  • {r.cinema_name}: {r.runtime_hours}h / {r.max_hours}h"
                f" = <b>{r.percent:.1f}%</b>"
            )

    if errors:
        lines.append("\n❓ <b>Nicht erreichbar:</b>")
        for r in errors:
            lines.append(f"  • {r.cinema_name} ({r.projector_ip}): {r.error}")

    _send(bot_token, chat_id, "\n".join(lines))


def send_all_ok_summary(
    bot_token: str,
    chat_id: str,
    results: List[LampResult],
) -> None:
    """Optionale Zusammenfassung wenn alle Lampen OK (wird nicht automatisch gesendet)."""
    lines = ["🔦 <b>[LAMPE] Alle Lampen OK</b>"]
    for r in results:
        if r.ok:
            lines.append(f"  ✅ {r.cinema_name}: {r.runtime_hours}h / {r.max_hours}h = {r.percent:.1f}%")
        else:
            lines.append(f"  ❓ {r.cinema_name}: nicht erreichbar")
    _send(bot_token, chat_id, "\n".join(lines))
