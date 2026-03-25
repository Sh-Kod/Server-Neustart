"""
Lampen-Monitor – läuft als Hintergrund-Thread neben dem Reboot-Scheduler.
Prüft täglich zur konfigurierten Zeit alle Projektoren via SNMP.
Sendet Telegram-Alarm nur bei Warnungen (≥145%) oder Fehlern.
"""
import logging
import threading
import time
from datetime import datetime

import pytz

from .lamp_checker import check_lamp
from .lamp_config import LampConfig
from .lamp_state import LampState
from .telegram_alert import send_daily_report

logger = logging.getLogger(__name__)


class LampMonitor:
    def __init__(self, config: LampConfig):
        self._config  = config
        self._state   = LampState(config.state_file)
        self._thread  = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, name="LampMonitor", daemon=True
        )
        self._thread.start()
        logger.info(
            f"[LAMPE] Monitor gestartet – Prüfzeit: {self._config.check_time}, "
            f"Warn: {self._config.warn_percent}%, Kritisch: {self._config.critical_percent}%, "
            f"Projektoren: {len(self._config.projectors)}"
        )

    def stop(self) -> None:
        self._running = False

    # ── interne Schleife ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[LAMPE] Unerwarteter Fehler: {e}")
            time.sleep(60)  # jede Minute prüfen ob Prüfzeit erreicht

    def _tick(self) -> None:
        tz  = pytz.timezone(self._config.timezone)
        now = datetime.now(tz)

        h, m = map(int, self._config.check_time.split(":"))
        if now.hour != h or now.minute != m:
            return  # noch nicht die Prüfzeit

        if self._state.was_checked_today():
            return  # heute schon geprüft

        logger.info(f"[LAMPE] Tagesprüfung um {self._config.check_time} Uhr gestartet...")
        self._state.mark_checked()

        results = self._run_checks()
        self._state.save_results(results)

        if self._config.telegram_enabled:
            send_daily_report(
                bot_token=self._config.telegram_bot_token,
                chat_id=self._config.telegram_chat_id,
                results=results,
                warn_percent=self._config.warn_percent,
                critical_percent=self._config.critical_percent,
            )
        else:
            logger.info("[LAMPE] Telegram deaktiviert – nur Log-Ausgabe.")

    def _run_checks(self) -> list:
        results = []
        for proj in self._config.projectors:
            # Christie-Projektoren haben keinen SNMP-Lampenzähler → überspringen
            if proj.get("projector_type", "barco").lower() != "barco":
                logger.debug(
                    f"[LAMPE] {proj['name']}: kein SNMP-Check "
                    f"(Typ: {proj.get('projector_type', '?')})"
                )
                continue
            result = check_lamp(
                cinema_id=proj["id"],
                cinema_name=proj["name"],
                projector_ip=proj["projector_ip"],
                community=self._config.snmp_community,
                port=self._config.snmp_port,
                timeout=self._config.snmp_timeout,
            )
            results.append(result)
        return results

    def run_now(self) -> list:
        """Sofortprüfung (z. B. für --test-lamps CLI-Befehl). Ignoriert Tages-State."""
        logger.info("[LAMPE] Sofortprüfung gestartet...")
        return self._run_checks()
