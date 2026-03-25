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

from .barco_projector import read_lamp_on
from .config import Config
from .handlers.base import RebootOutcome, RebootResult
from .handlers.doremi import DoremiHandler
from .handlers.ims3000 import IMS3000Handler
from .notifier import raise_playback_alarm
from .scheduler import Scheduler
from .state_manager import StateManager
from .telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


def _read_lamp_on_christie(
    projector_ip: str,
    projector_port: int = 5004,
    timeout: int = 8,
) -> Optional[bool]:
    """
    Liest den Laser-/Lampenstatus eines Christie CineLife+ Projektors via WebSocket.

    Gibt zurück:
      True  → Laser AN (Vorstellung läuft vermutlich)
      False → Laser AUS (sicher aus)
      None  → Verbindungsfehler / Projektor nicht erreichbar

    Sucht in den StatusItems nach Einträgen mit 'laser' oder 'lamp' im Namen
    und wertet deren alarmstate sowie value-Feld aus.
    """
    try:
        import websocket as _ws
        import json, xml.etree.ElementTree as ET
    except ImportError:
        logger.warning("[LAMPE] Christie: websocket-client nicht installiert.")
        return None

    ws_url = f"ws://{projector_ip}:{projector_port}/"
    try:
        ws = _ws.create_connection(ws_url, timeout=timeout)
    except Exception as e:
        logger.info(f"[LAMPE] Christie {projector_ip}: OFFLINE ({e})")
        return None

    xml_str = None
    try:
        ws.settimeout(timeout)
        for _ in range(20):
            try:
                data = json.loads(ws.recv())
                if data.get("method") == 2011:
                    props = data.get("result", {}).get("properties", [])
                    if props:
                        xml_str = props[0].get("value", "")
                        break
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception as e:
        logger.warning(f"[LAMPE] Christie {projector_ip}: Lesefehler – {e}")
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if not xml_str:
        logger.warning(f"[LAMPE] Christie {projector_ip}: Keine StatusItems empfangen.")
        return None

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    for item in root.findall("StatusItem"):
        name = (item.findtext("name", "") or "").lower()
        if "laser" not in name and "lamp" not in name:
            continue
        val = (item.findtext("value", "") or "").lower()
        # Typische Christie-Werte: "On", "Off", "1", "0", "true", "false"
        if val in ("on", "1", "true", "running", "active"):
            logger.info(f"[LAMPE] Christie {projector_ip}: Laser/Lampe AN ({name}={val})")
            return True
        if val in ("off", "0", "false", "standby", "idle"):
            logger.info(f"[LAMPE] Christie {projector_ip}: Laser/Lampe AUS ({name}={val})")
            return False

    # StatusItems enthalten keinen Laser-Eintrag → unbekannt
    logger.info(f"[LAMPE] Christie {projector_ip}: Kein Laser-StatusItem gefunden.")
    return None


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
            reboot_timeout_minutes=self._config.startup_wait_minutes,
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
                logger.info(f"[{cinema_name}] Retry-Zeit außerhalb des Wartungsfensters – kein weiterer Retry heute.")
                next_retry = None

            self._state.set_offline(cinema_id, next_retry)
            self._telegram.send_server_offline(cinema_name, ip, next_retry)
            return RebootOutcome(
                result=RebootResult.OFFLINE,
                message=f"Server {ip} nicht erreichbar.",
            )

        logger.info(f"[{cinema_name}] Server erreichbar ✓")

        # ── Projektor-Lampenstatus lesen (optional, nur wenn projector_ip konfiguriert) ──
        # Sicherheitsprüfung: Lampe AN → Vorstellung läuft → Reboot BLOCKIERT
        # Lampe AUS (bestätigt) → Reboot erlaubt (aber DoreMi-Check folgt noch)
        # Projektor OFFLINE / nicht lesbar → Lampen-Check übersprungen, DoreMi-Check entscheidet
        projector_ip   = cinema.get("projector_ip")
        projector_type = cinema.get("projector_type", "barco").lower()
        if projector_ip:
            projector_port = int(cinema.get("projector_port", 43728))
            logger.info(
                f"[{cinema_name}] Projektor-Lampenstatus lesen "
                f"({projector_ip}:{projector_port}, Typ: {projector_type})..."
            )
            if projector_type == "christie":
                lamp_on = _read_lamp_on_christie(projector_ip, projector_port)
            else:
                lamp_on = read_lamp_on(projector_ip, projector_port)

            if lamp_on is True:
                # Lampe AN → Vorstellung läuft → KEIN Reboot (erste Sicherheitsschranke)
                logger.warning(
                    f"[{cinema_name}] ⛔ Projektor-Lampe AN "
                    f"→ Vorstellung läuft! Reboot abgebrochen."
                )
                outcome = RebootOutcome(
                    result=RebootResult.BLOCKED_BY_PLAYBACK,
                    message="Projektor-Lampe AN – Vorstellung läuft.",
                )
                self._process_outcome(cinema, outcome, today, silent=silent)
                return outcome
            elif lamp_on is False:
                # Lampe AUS bestätigt – Reboot grundsätzlich möglich
                # DoreMi-/IMS-Prüfung folgt noch als zweite Sicherheitsschranke
                logger.info(f"[{cinema_name}] Projektor-Lampe AUS ✓ – DoreMi-Check folgt.")
            else:
                # None = Projektor OFFLINE (nachts stromlos) oder Antwort unklar
                # → Lampen-Check übersprungen, DoreMi-Prüfung entscheidet allein
                logger.info(
                    f"[{cinema_name}] Projektor nicht erreichbar (OFFLINE/stromlos) – "
                    f"Lampen-Check übersprungen, DoreMi-Check läuft weiter."
                )
        else:
            logger.debug(f"[{cinema_name}] Kein projector_ip konfiguriert – Projektor-Check übersprungen.")

        if not silent:
            self._telegram.send_start_attempt(cinema_name, dry_run=self._config.dry_run)

        # ── Versuch zählen ───────────────────────────────────────────────
        self._state.record_attempt(cinema_id, self._now())

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

        # Nächsten Retry berechnen (nur wenn Retry-Zeit noch im Wartungsfenster liegt)
        if result not in (RebootResult.SUCCESS, RebootResult.DRY_RUN_OK):
            candidate = self._scheduler.next_retry_time()
            if self._scheduler.is_within_window(candidate):
                next_retry = candidate
            else:
                logger.info(
                    f"[{cinema_name}] Retry-Zeit liegt außerhalb des Wartungsfensters → "
                    "kein weiterer Retry heute."
                )

        # State aktualisieren
        if result == RebootResult.SUCCESS:
            self._state.set_success(cinema_id, today, at_time=self._now())
            if not silent:
                self._telegram.send_reboot_success(cinema_name, outcome.duration_seconds)

        elif result == RebootResult.DRY_RUN_OK:
            self._state.set_success(cinema_id, today, at_time=self._now())
            logger.info(f"[{cinema_name}] [DRY-RUN] Als 'success' für heute markiert.")

        elif result == RebootResult.BLOCKED_BY_PLAYBACK:
            self._state.set_blocked_by_playback(cinema_id, next_retry)
            self._telegram.send_reboot_blocked_playback(cinema_name, next_retry)
            # LOKALER ALARM (Ton + Windows-Notification)
            raise_playback_alarm(cinema_name, enabled=self._config.local_alarm_enabled)

        elif result == RebootResult.BLOCKED_BY_TRANSFER:
            self._state.set_blocked_by_transfer(cinema_id, next_retry)
            self._telegram.send_reboot_blocked_transfer(cinema_name, next_retry)

        elif result == RebootResult.OFFLINE:
            self._state.set_offline(cinema_id, next_retry)
            # Telegram bereits in run() gesendet

        elif result == RebootResult.TIMEOUT:
            self._state.set_error(cinema_id, next_retry, outcome.message)
            self._telegram.send_reboot_timeout(cinema_name)

        elif result == RebootResult.UI_UNCLEAR:
            self._state.set_ui_unclear(cinema_id, next_retry, outcome.message)
            self._telegram.send_ui_unclear(cinema_name, outcome.message, next_retry)

        elif result in (RebootResult.LOGIN_FAILED, RebootResult.ERROR):
            self._state.set_error(cinema_id, next_retry, outcome.message)
            self._telegram.send_error(cinema_name, outcome.message, next_retry)

        logger.info(
            f"[{cinema_name}] Ergebnis: {result.value} | "
            f"Dauer: {outcome.duration_seconds:.0f}s | "
            f"Next-Retry: {next_retry.strftime('%H:%M') if next_retry else 'morgen'}"
        )
