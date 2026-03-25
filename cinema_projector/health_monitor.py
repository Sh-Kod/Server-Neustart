"""
Projektor-Gesundheits-Monitor – läuft als Hintergrund-Thread.

Prüft alle poll_interval_seconds Sekunden alle konfigurierten Projektoren
via Barco Binary Protocol (TCP Port 43728).

Sendet sofortigen Telegram-Alarm wenn:
  – Farbe wechselt ZU Rot (GREEN/BLUE/YELLOW/OFFLINE → RED)
  – Fehler behoben: RED → GREEN/BLUE/YELLOW

OFFLINE (stromlos / nicht erreichbar): NIE Alarm.
  Nacht-Abschaltung ist normal – kein Alarm beim Ausgehen oder Einschalten.
GREEN/BLUE/YELLOW: kein Alarm, nur Logging.
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional

import requests

from .health_checker import HealthColor, HealthResult, check_health
from .health_state import HealthState
from .lamp_config import LampConfig
from .temp_thresholds import TempThresholds

logger = logging.getLogger(__name__)

_TELEGRAM_TIMEOUT = 10


def _send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    """Sendet eine Telegram-Nachricht direkt via API (HTML-Format)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=_TELEGRAM_TIMEOUT,
        )
        resp.raise_for_status()
        logger.debug("[GESUNDHEIT] Telegram-Alarm gesendet.")
    except Exception as e:
        logger.warning(f"[GESUNDHEIT] Telegram-Alarm fehlgeschlagen: {e}")


class HealthMonitor:
    """
    Hintergrund-Thread für kontinuierliches Projektormonitoring.
    Sendet Alarm nur bei Zustandswechsel zu/von ROT.
    """

    def __init__(self, lamp_config: LampConfig):
        self._config     = lamp_config
        self._interval   = lamp_config.health_poll_interval_seconds
        self._state      = HealthState("health_state.json")
        self._thresholds = TempThresholds("temp_thresholds.json")
        self._thread: Optional[threading.Thread] = None
        self._running    = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="HealthMonitor", daemon=True
        )
        self._thread.start()
        logger.info(
            f"[GESUNDHEIT] Monitor gestartet – "
            f"Intervall: {self._interval}s, "
            f"Projektoren: {len(self._config.projectors)}"
        )

    def stop(self) -> None:
        self._running = False

    def check_all_now(self) -> list:
        """Sofortprüfung aller Projektoren (für Telegram-Befehl, ohne State-Änderung)."""
        logger.info("[GESUNDHEIT] Sofortprüfung aller Projektoren...")
        return self._run_checks()

    def check_one_now(self, projector: dict) -> HealthResult:
        """Sofortprüfung eines einzelnen Projektors (für Telegram-Befehl)."""
        return check_health(
            cinema_id=projector["id"],
            cinema_name=projector["name"],
            projector_ip=projector["projector_ip"],
            projector_port=int(projector.get("projector_port", 43728)),
            timeout=self._config.health_timeout,
            projector_type=projector.get("projector_type", "barco"),
            snmp_temp_oid=projector.get("snmp_temp_oid", ""),
            snmp_temp_div=float(projector.get("snmp_temp_div", 1.0)),
            snmp_community=self._config.snmp_community,
            snmp_port=self._config.snmp_port,
        )

    def get_state(self) -> HealthState:
        return self._state

    def get_thresholds(self) -> TempThresholds:
        return self._thresholds

    # ── Interner Loop ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[GESUNDHEIT] Unerwarteter Fehler: {e}")
            # In 1-Sekunden-Schritten für sauberes Stop
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def _tick(self) -> None:
        results = self._run_checks()
        for result in results:
            self._process_result(result)

    def _run_checks(self) -> list:
        results = []
        for proj in self._config.projectors:
            result = check_health(
                cinema_id=proj["id"],
                cinema_name=proj["name"],
                projector_ip=proj["projector_ip"],
                projector_port=int(proj.get("projector_port", 43728)),
                timeout=self._config.health_timeout,
                projector_type=proj.get("projector_type", "barco"),
                snmp_temp_oid=proj.get("snmp_temp_oid", ""),
                snmp_temp_div=float(proj.get("snmp_temp_div", 1.0)),
                snmp_community=self._config.snmp_community,
                snmp_port=self._config.snmp_port,
            )
            results.append(result)
        return results

    def _process_result(self, result: HealthResult) -> None:
        """Vergleicht neuen Zustand mit letztem bekannten – sendet Alarm bei Bedarf."""
        prev_color = self._state.get_color(result.cinema_id)

        # Vorherige Temperatur VOR dem State-Update lesen (Spam-Schutz)
        prev_entry = self._state.get_entry(result.cinema_id)
        prev_temp  = prev_entry.get("temperature_c", -1.0)

        # State aktualisieren
        self._state.update(
            cinema_id=result.cinema_id,
            cinema_name=result.cinema_name,
            color=result.color,
            reachable=result.reachable,
            notifications=result.notifications,
            warnings=result.warnings,
            errors=result.errors,
            error_msg=result.error_msg,
            error_details=result.error_details,
            temperature_c=result.temperature_c,
            lamp_on=result.lamp_on,
        )

        # ── Temperatur-Alarm ──────────────────────────────────────────────────
        if result.reachable and result.temperature_c > 0:
            threshold = self._thresholds.get(result.cinema_id)
            if result.temperature_c >= threshold:
                # Nur Alarm wenn vorher unter Schwellwert (kein Spam)
                if prev_temp < threshold or prev_temp < 0:
                    if self._config.telegram_enabled:
                        msg = _build_temp_alert(result, threshold)
                        _send_telegram(
                            self._config.telegram_bot_token,
                            self._config.telegram_chat_id,
                            msg,
                        )

        # Kein Alarm wenn gleicher Zustand
        if result.color == prev_color:
            return

        color_icon = _color_icon(result.color)
        prev_icon  = _color_icon(prev_color)
        logger.info(
            f"[GESUNDHEIT] {result.cinema_name}: "
            f"{prev_color} {prev_icon} → {result.color} {color_icon}"
        )

        # Telegram nur wenn aktiviert
        if not self._config.telegram_enabled:
            return

        # ── Alarm-Logik ────────────────────────────────────────────────────────
        #
        # 🔴 ROT:     Projektor verbunden, aber error_count > 0 → IMMER Alarm
        # ⬛ OFFLINE: TCP nicht erreichbar (stromlos / Netzfehler) → NIE Alarm
        #             Nacht-Abschaltung ist normal, kein Alarm gewünscht.
        # 💚🔵🟡 Entwarnung: NUR wenn vorher ROT (Fehler behoben)
        #             Rückkehr aus OFFLINE (Morgen einschalten) → kein Alarm

        if result.color == HealthColor.RED:
            # Immer Alarm wenn Fehler vorhanden (egal welcher Vorzustand)
            msg = _build_red_alert(result, prev_color)
            _send_telegram(
                self._config.telegram_bot_token,
                self._config.telegram_chat_id,
                msg,
            )

        elif result.color in (HealthColor.GREEN, HealthColor.BLUE, HealthColor.YELLOW) \
                and prev_color == HealthColor.RED:
            # Projektor war ROT (Fehler), jetzt wieder normal → Entwarnung
            msg = _build_recovery_msg(result, prev_color)
            _send_telegram(
                self._config.telegram_bot_token,
                self._config.telegram_chat_id,
                msg,
            )


# ── Telegram-Nachrichten ───────────────────────────────────────────────────────

def _color_icon(color: str) -> str:
    return {
        HealthColor.GREEN:   "💚",
        HealthColor.BLUE:    "🔵",
        HealthColor.YELLOW:  "🟡",
        HealthColor.RED:     "🔴",
        HealthColor.OFFLINE: "⬛",
    }.get(color, "❓")


def _build_red_alert(result: HealthResult, prev_color: str) -> str:
    now_str   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    prev_icon = _color_icon(prev_color)

    detail = (
        f"Fehler: <b>{result.errors}</b> | "
        f"Warnungen: {result.warnings} | "
        f"Meldungen: {result.notifications}"
    )
    if result.temperature_c > 0:
        detail += f" | Temp: {result.temperature_c:.1f}°C"
    if result.error_msg:
        detail += f"\n<i>{result.error_msg}</i>"

    # Dekodierte Fehlercodes anhängen (max. 8 Zeilen um Telegram-Nachricht kurz zu halten)
    if result.error_details:
        detail += "\n\n<b>Fehleranalyse:</b>"
        for line in result.error_details[:8]:
            detail += f"\n• {line}"
        if len(result.error_details) > 8:
            detail += f"\n• … (+{len(result.error_details) - 8} weitere)"

    return (
        f"🔴 <b>[GESUNDHEIT] PROJEKTOR-ALARM</b> – {result.cinema_name}\n"
        f"<i>{now_str}</i>\n\n"
        f"{prev_icon} ➜ 🔴  Fehler erkannt!\n"
        f"{detail}"
    )


def _build_temp_alert(result: HealthResult, threshold: float) -> str:
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    return (
        f"🌡️ <b>[TEMPERATUR] ÜBERHITZUNG</b> – {result.cinema_name}\n"
        f"<i>{now_str}</i>\n\n"
        f"Temperatur: <b>{result.temperature_c:.1f}°C</b> "
        f"(Schwellwert: {threshold:.0f}°C)\n"
        f"<i>Bitte Kühlung und Luftfilter prüfen!</i>"
    )


def _build_offline_alert(result: HealthResult, prev_color: str) -> str:
    """Alarm: Projektor war eingeschaltet und ist plötzlich nicht mehr erreichbar."""
    now_str   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    prev_icon = _color_icon(prev_color)

    detail = "Projektor <b>nicht mehr erreichbar</b>"
    if result.error_msg:
        detail += f"\n<i>{result.error_msg}</i>"

    return (
        f"⬛ <b>[GESUNDHEIT] PROJEKTOR WEG</b> – {result.cinema_name}\n"
        f"<i>{now_str}</i>\n\n"
        f"{prev_icon} ➜ ⬛  War an, jetzt offline!\n"
        f"{detail}"
    )


def _build_recovery_msg(result: HealthResult, prev_color: str) -> str:
    now_str    = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    color_icon = _color_icon(result.color)
    prev_icon  = _color_icon(prev_color)

    return (
        f"{color_icon} <b>[GESUNDHEIT] Projektor wieder OK</b> – {result.cinema_name}\n"
        f"<i>{now_str}</i>\n\n"
        f"{prev_icon} ➜ {color_icon}  Wiederhergestellt\n"
        f"Meldungen: {result.notifications} | "
        f"Warnungen: {result.warnings} | "
        f"Fehler: {result.errors}"
    )
