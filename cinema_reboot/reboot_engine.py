"""
Reboot-Engine – orchestriert den gesamten Reboot-Prozess für ein Kino.

Verantwortlichkeiten:
  1. Erreichbarkeitscheck
  2. Browser starten (Playwright)
  3. Handler aufrufen (Doremi oder IMS3000)
  4. Ergebnis auswerten und State aktualisieren
  5. Telegram + lokale Benachrichtigungen senden
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import pytz
from playwright.sync_api import sync_playwright

from .config import Config
from .handlers.base import RebootOutcome, RebootResult
from .handlers.doremi import DoremiHandler
from .handlers.ims3000 import IMS3000Handler
from .notifier import raise_playback_alarm
from .scheduler import Scheduler
from .state_manager import StateManager
from .telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


class RebootEngine:
    """Führt den Reboot eines einzelnen Kinos durch."""

    def __init__(
        self,
        config: Config,
        state_manager: StateManager,
        scheduler: Scheduler,
        telegram: TelegramSender,
    ):
        self._config = config
        self._state = state_manager
        self._scheduler = scheduler
        self._telegram = telegram
        self._tz = pytz.timezone(config.timezone)

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _today_str(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    def _create_handler(self, cinema: dict):
        """Erstellt den passenden Handler je nach Kino-Typ."""
        common_args = dict(
            cinema=cinema,
            username=self._config.username,
            password=self._config.password,
            dry_run=self._config.dry_run,
            http_timeout=self._config.http_timeout_seconds,
            reboot_wait_minutes=self._config.reboot_wait_minutes,
            reboot_timeout_minutes=self._config.reboot_timeout_minutes,
        )
        if cinema["type"] == "ims3000":
            return IMS3000Handler(**common_args)
        else:
            return DoremiHandler(**common_args)

    def run(self, cinema: dict, silent: bool = False) -> RebootOutcome:
        """
        Führt den kompletten Reboot-Flow für ein Kino durch.
        Aktualisiert State und sendet Benachrichtigungen.
        silent=True: unterdrückt Start- und Erfolgs-Nachrichten (für Parallel-Modus).
        """
        cinema_id = cinema["id"]
        cinema_name = cinema["name"]
        ip = cinema["ip"]
        today = self._today_str()

        logger.info(f"═══ Starte Reboot-Flow: {cinema_name} ({ip}) ═══")

        if self._config.dry_run:
            logger.info(f"[DRY-RUN MODUS AKTIV] {cinema_name} – kein echter Reboot!")

        # ── Schritt 0: Erreichbarkeitscheck ─────────────────────────────
        handler = self._create_handler(cinema)

        logger.info(f"[{cinema_name}] Erreichbarkeitscheck...")
        if not handler.is_reachable():
            logger.warning(f"[{cinema_name}] Server nicht erreichbar: {ip}")
            next_retry = self._scheduler.next_retry_time()

            # Nur innerhalb Wartungsfenster Retry planen
            if not self._scheduler.is_within_window(next_retry):
                logger.info(f"[{cinema_name}] Nächste Wartungsfenster nicht mehr heute.")
                next_retry = None

            self._state.set_offline(cinema_id, next_retry or self._now())
            self._telegram.send_server_offline(cinema_name, ip, next_retry)
            return RebootOutcome(
                result=RebootResult.OFFLINE,
                message=f"Server {ip} nicht erreichbar.",
            )

        logger.info(f"[{cinema_name}] Server erreichbar ✓")
        if not silent:
            self._telegram.send_start_attempt(cinema_name, dry_run=self._config.dry_run)

        # ── Schritt 1-5: Browser + Handler ──────────────────────────────
        self._state.set_in_progress(cinema_id)
        outcome = self._run_with_browser(handler)

        # ── Ergebnis auswerten ───────────────────────────────────────────
        self._process_outcome(cinema, outcome, today, silent=silent)
        return outcome

    def run_parallel(self, cinemas: list) -> None:
        """
        Führt Reboots für mehrere Kinos gleichzeitig aus.
        Jedes Kino läuft in einem eigenen Thread mit eigenem Browser.
        Pre-Checks (Playback/Transfer) werden pro Kino unabhängig durchgeführt.
        Am Ende wird eine einzige Zusammenfassung per Telegram gesendet.
        """
        logger.info(f"Starte parallelen Reboot für {len(cinemas)} Kinos gleichzeitig...")

        results: dict[str, RebootOutcome] = {}

        with ThreadPoolExecutor(max_workers=len(cinemas)) as executor:
            future_to_cinema = {
                executor.submit(self.run, cinema, silent=True): cinema
                for cinema in cinemas
            }
            for future in as_completed(future_to_cinema):
                cinema = future_to_cinema[future]
                try:
                    results[cinema["name"]] = future.result()
                except Exception as e:
                    logger.error(f"Thread-Fehler für {cinema['name']}: {e}", exc_info=True)
                    results[cinema["name"]] = RebootOutcome(
                        result=RebootResult.ERROR, message=str(e)
                    )

        logger.info("Paralleler Reboot-Durchlauf abgeschlossen.")

        # Ergebnisse gruppieren und Zusammenfassung senden
        groups: dict[str, list[str]] = {
            "success": [], "blocked_by_playback": [], "blocked_by_transfer": [],
            "ui_unclear": [], "offline": [], "timeout": [], "error": [],
        }
        for name, outcome in results.items():
            v = outcome.result.value
            if v in ("dry_run_ok",):
                groups["success"].append(name)
            elif v in groups:
                groups[v].append(name)
            else:
                groups["error"].append(name)

        self._telegram.send_parallel_summary(groups, total=len(cinemas))

    def _run_with_browser(self, handler) -> RebootOutcome:
        """Startet Playwright, öffnet Browser, ruft Handler auf."""
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=self._config.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    ignore_https_errors=True,  # Self-signed Certs auf Kino-Servern
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                # navigator.webdriver entfernen damit IMS3000 keinen Automation-Browser erkennt
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page.set_default_timeout(30_000)

                try:
                    outcome = handler.execute_reboot(page)
                finally:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass

            return outcome

        except Exception as e:
            logger.exception(f"Browser-Fehler: {e}")
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=f"Browser-Fehler: {e}",
            )

    def _process_outcome(
        self,
        cinema: dict,
        outcome: RebootOutcome,
        today: str,
        silent: bool = False,
    ) -> None:
        """Wertet das Ergebnis aus, aktualisiert State und sendet Benachrichtigungen.
        silent=True: unterdrückt die Erfolgs-Nachricht (für Parallel-Modus)."""
        cinema_id = cinema["id"]
        cinema_name = cinema["name"]
        next_retry: Optional[datetime] = None

        result = outcome.result

        # Nächsten Retry berechnen (nur wenn noch im Wartungsfenster)
        if result not in (RebootResult.SUCCESS, RebootResult.DRY_RUN_OK):
            candidate = self._scheduler.next_retry_time()
            if self._scheduler.is_within_window(candidate):
                next_retry = candidate
            else:
                logger.info(
                    f"[{cinema_name}] Nächstes Wartungsfenster nicht mehr erreichbar → "
                    "Retry erst morgen."
                )

        # State aktualisieren
        if result == RebootResult.SUCCESS:
            self._state.set_success(cinema_id, today)
            if not silent:
                self._telegram.send_reboot_success(cinema_name, outcome.duration_seconds)

        elif result == RebootResult.DRY_RUN_OK:
            # Im Dry-Run keinen echten Erfolg markieren
            self._state.set_success(cinema_id, today)  # Damit wir pro Tag nur 1× testen
            logger.info(f"[{cinema_name}] [DRY-RUN] Als 'success' für heute markiert.")

        elif result == RebootResult.BLOCKED_BY_PLAYBACK:
            self._state.set_blocked_by_playback(cinema_id, next_retry or self._now())
            self._telegram.send_reboot_blocked_playback(cinema_name, next_retry)
            # LOKALER ALARM (Ton + Windows-Notification)
            raise_playback_alarm(cinema_name, enabled=self._config.local_alarm_enabled)

        elif result == RebootResult.BLOCKED_BY_TRANSFER:
            self._state.set_blocked_by_transfer(cinema_id, next_retry or self._now())
            self._telegram.send_reboot_blocked_transfer(cinema_name, next_retry)

        elif result == RebootResult.OFFLINE:
            self._state.set_offline(cinema_id, next_retry or self._now())
            # Telegram bereits in run() gesendet

        elif result == RebootResult.TIMEOUT:
            self._state.set_error(cinema_id, next_retry or self._now(), outcome.message)
            self._telegram.send_reboot_timeout(cinema_name)

        elif result == RebootResult.UI_UNCLEAR:
            self._state.set_ui_unclear(cinema_id, next_retry or self._now(), outcome.message)
            self._telegram.send_ui_unclear(cinema_name, outcome.message, next_retry)

        elif result in (RebootResult.LOGIN_FAILED, RebootResult.ERROR):
            self._state.set_error(cinema_id, next_retry or self._now(), outcome.message)
            self._telegram.send_error(cinema_name, outcome.message, next_retry)

        logger.info(
            f"[{cinema_name}] Ergebnis: {result.value} | "
            f"Dauer: {outcome.duration_seconds:.0f}s | "
            f"Next-Retry: {next_retry.strftime('%H:%M') if next_retry else 'morgen'}"
        )
