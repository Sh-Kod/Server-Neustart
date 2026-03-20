"""
Basis-Handler – abstrakte Klasse für alle Kino-Typen.

Jeder Handler implementiert den vollständigen Reboot-Flow für einen bestimmten
Server-Typ (Doremi/DCP2000 oder IMS3000). Die Basis-Klasse stellt gemeinsame
Hilfsmethoden bereit.
"""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


logger = logging.getLogger(__name__)


class RebootResult(Enum):
    """Mögliche Ergebnisse eines Reboot-Versuchs."""
    SUCCESS = "success"
    BLOCKED_BY_PLAYBACK = "blocked_by_playback"
    BLOCKED_BY_TRANSFER = "blocked_by_transfer"
    OFFLINE = "offline"
    UI_UNCLEAR = "ui_unclear"
    TIMEOUT = "timeout"
    LOGIN_FAILED = "login_failed"
    ERROR = "error"
    DRY_RUN_OK = "dry_run_ok"  # Im Dry-Run: alles OK, aber kein Klick


@dataclass
class RebootOutcome:
    """Detailliertes Ergebnis eines Reboot-Versuchs."""
    result: RebootResult
    message: str = ""
    duration_seconds: float = 0.0


class BaseHandler(ABC):
    """Abstrakte Basisklasse für alle Kino-Handler."""

    # Standard-Timeouts
    PAGE_LOAD_TIMEOUT_MS = 30_000     # 30 Sekunden für Seitenladung
    ELEMENT_TIMEOUT_MS = 10_000       # 10 Sekunden für Element-Suche
    POPUP_WAIT_MS = 5_000             # 5 Sekunden auf Popup warten

    def __init__(
        self,
        cinema: dict,
        username: str,
        password: str,
        dry_run: bool,
        http_timeout: int,
        reboot_wait_minutes: int,
        reboot_timeout_minutes: int,
    ):
        self.cinema = cinema
        self.cinema_id = cinema["id"]
        self.cinema_name = cinema["name"]
        self.ip = cinema["ip"]
        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.http_timeout = http_timeout
        self.reboot_wait_minutes = reboot_wait_minutes
        self.reboot_timeout_minutes = reboot_timeout_minutes
        self.logger = logging.getLogger(f"{__name__}.{self.cinema_id}")

    @abstractmethod
    def base_url(self) -> str:
        """Gibt die Basis-URL des WebUI zurück."""
        ...

    @abstractmethod
    def execute_reboot(self, page: Page) -> RebootOutcome:
        """
        Führt den vollständigen Reboot-Flow aus.
        Wird von der Reboot-Engine mit einer aktiven Playwright-Page aufgerufen.
        """
        ...

    def is_reachable(self) -> bool:
        """
        Schneller HTTP-Erreichbarkeitscheck per GET-Request.
        Gibt True zurück, wenn der Server antwortet (auch bei Login-Redirect).
        """
        url = self.base_url()
        try:
            resp = requests.get(url, timeout=self.http_timeout, allow_redirects=True)
            # Auch 401/403 zählt als "erreichbar" (Server ist da, Anmeldung nötig)
            reachable = resp.status_code < 500
            self.logger.debug(f"Erreichbarkeitscheck {url}: HTTP {resp.status_code} → {'OK' if reachable else 'FEHLER'}")
            return reachable
        except requests.RequestException as e:
            self.logger.debug(f"Erreichbarkeitscheck {url}: Nicht erreichbar – {e}")
            return False

    def wait_for_server_online(self, page: Page) -> bool:
        """
        Wartet nach dem Reboot darauf, dass der Server wieder erreichbar ist.
        Gibt True zurück, wenn Login-Seite erscheint.
        Gibt False zurück bei Timeout.
        """
        timeout_seconds = self.reboot_timeout_minutes * 60
        poll_interval = 30  # Alle 30 Sekunden prüfen
        elapsed = 0

        self.logger.info(
            f"Warte auf Wiederherstellung "
            f"(max. {self.reboot_timeout_minutes} Minuten)..."
        )

        # Erste Wartezeit: Server fährt erst runter
        initial_wait = self.reboot_wait_minutes * 60
        self.logger.info(f"Initiale Wartezeit: {self.reboot_wait_minutes} Minuten...")
        time.sleep(initial_wait)
        elapsed += initial_wait

        while elapsed < timeout_seconds:
            if self.is_reachable():
                self.logger.info(f"Server wieder erreichbar nach {elapsed}s.")
                return True
            self.logger.debug(f"Server noch offline... ({elapsed}s / {timeout_seconds}s)")
            time.sleep(poll_interval)
            elapsed += poll_interval

        self.logger.error(f"Server nach {self.reboot_timeout_minutes} Minuten NICHT wieder online!")
        return False

    def safe_click(self, page: Page, selector: str, description: str) -> bool:
        """
        Klickt ein Element sicher. Im Dry-Run-Modus wird der Klick NICHT ausgeführt.
        Gibt True zurück bei Erfolg.
        """
        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Würde klicken: {description} (Selector: {selector})")
            return True
        try:
            page.locator(selector).click(timeout=self.ELEMENT_TIMEOUT_MS)
            self.logger.info(f"Geklickt: {description}")
            return True
        except PlaywrightTimeout:
            self.logger.warning(f"Element nicht gefunden/klickbar: {description} ({selector})")
            return False

    def take_screenshot_on_error(self, page: Page, filename: str) -> None:
        """Erstellt einen Screenshot und HTML-Dump zur Fehlerdiagnose."""
        try:
            path = f"logs/screenshot_{self.cinema_id}_{filename}.png"
            page.screenshot(path=path)
            self.logger.info(f"Screenshot gespeichert: {path}")
        except Exception as e:
            self.logger.debug(f"Screenshot fehlgeschlagen: {e}")
        try:
            html_path = f"logs/dump_{self.cinema_id}_{filename}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(f"<!-- URL: {page.url} -->\n")
                f.write(page.content())
            self.logger.info(f"HTML-Dump gespeichert: {html_path}")
        except Exception as e:
            self.logger.debug(f"HTML-Dump fehlgeschlagen: {e}")
