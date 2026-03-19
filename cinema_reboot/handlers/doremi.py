"""
Doremi/DCP2000 Handler – Playwright-Automation für Kinos 01–07, 09–13.

UI-Flow (bestätigt durch Screenshots):
  1. Login-Seite: http://{ip}/web/
     → Username / Password / Login-Button
  2. Dashboard: /web/overview/ oder /web/overview/index.php
     → Statusbar unten: "Playback in progress" | "No Playback" | "No Ingest" | "No Export"
     → Power-Button oben rechts: title="Reboot or Shutdown the system"
  3. Power-Menü: "What do you want to do ?"
     → Restart ✅ | Shutdown ❌ | Logout ❌ | Cancel (Abbruch)
  4. Playback-Popup (ROTE GRENZE): "Playback is currently running!"
     → OK ❌ NIEMALS | Abbrechen ✅ SOFORT
  5. Countdown: "System will reboot after X seconds. Cancel"
     → Nichts klicken, einfach warten
  6. Restarting:
     → Banner: "You are disconnected from the WebUI (Soap service unavailable)."
     → Overlay: "Restarting..."
  7. Server bereit:
     → Entweder: "Server is ready, click here to Login" → klicken
     → Oder: direkt die normale Login-Seite

SICHERHEITSREGELN:
  - NIEMALS OK beim Playback-Popup klicken
  - NIEMALS Shutdown oder Logout im Power-Menü klicken
  - Bei unbekanntem UI-Zustand: konservativ abbrechen (UI_UNCLEAR)
"""
import logging
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from .base import BaseHandler, RebootOutcome, RebootResult

logger = logging.getLogger(__name__)


class DoremiHandler(BaseHandler):
    """Handler für Doremi/DCP2000 WebUI (Kinos 01–07, 09–13)."""

    # ── Login ─────────────────────────────────────────────────────────────────
    SEL_USERNAME_INPUT  = "input[name='username']"
    SEL_PASSWORD_INPUT  = "input[name='password']"
    SEL_LOGIN_BUTTON    = "button:has-text('Login')"

    # ── Power-Button oben rechts ──────────────────────────────────────────────
    # Tooltip bestätigt durch Screenshot: "Reboot or Shutdown the system"
    SEL_POWER_BUTTON = "[title='Reboot or Shutdown the system']"

    # ── Power-Menü ("What do you want to do ?") ───────────────────────────────
    SEL_MENU_DIALOG   = "text=What do you want to do"
    SEL_MENU_RESTART  = "button:has-text('Restart')"   # ✅ EINZIGER ERLAUBTER KLICK
    SEL_MENU_SHUTDOWN = "button:has-text('Shutdown')"  # ❌ nur zur Erkennung
    SEL_MENU_LOGOUT   = "button:has-text('Logout')"    # ❌ nur zur Erkennung
    SEL_MENU_CANCEL   = "button:has-text('Cancel')"

    # ── Pre-Check Statusbar (unten auf dem Dashboard) ────────────────────────
    SEL_PLAYBACK_IN_PROGRESS = "text=Playback in progress"  # → SOFORT ABBRECHEN
    SEL_NO_PLAYBACK          = "text=No Playback"            # → sicher
    SEL_NO_INGEST            = "text=No Ingest"              # → sicher
    SEL_NO_EXPORT            = "text=No Export"              # → sicher

    # ── Playback-Popup (ROTE GRENZE) ──────────────────────────────────────────
    SEL_POPUP_PLAYBACK_TEXT = "text=Playback is currently running"
    SEL_POPUP_CANCEL        = "button:has-text('Abbrechen')"  # ✅ SOFORT KLICKEN
    SEL_POPUP_OK            = "button:has-text('OK')"         # ❌ NIEMALS KLICKEN

    # ── Countdown nach Restart-Klick ──────────────────────────────────────────
    SEL_COUNTDOWN = "text=System will reboot after"

    # ── Restarting-Zustand ────────────────────────────────────────────────────
    SEL_RESTARTING   = "text=Restarting..."
    SEL_DISCONNECTED = "text=You are disconnected from the WebUI"

    # ── Server wieder bereit ──────────────────────────────────────────────────
    SEL_SERVER_READY = "text=Server is ready, click here to Login"

    def base_url(self) -> str:
        return f"http://{self.ip}/web/"

    def execute_reboot(self, page: Page) -> RebootOutcome:
        """Vollständiger Reboot-Flow für Doremi/DCP2000."""
        start_time = time.time()

        try:
            # ── Schritt 1: Login ──────────────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 1: Login...")
            outcome = self._login(page)
            if outcome is not None:
                return outcome

            # ── Schritt 2: Pre-Check Statusbar ───────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 2: Pre-Check (Statusbar)...")
            outcome = self._pre_check(page)
            if outcome is not None:
                return outcome

            # ── Schritt 3: Reboot auslösen ────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 3: Reboot auslösen...")
            outcome = self._trigger_reboot(page)
            if outcome is not None:
                return outcome

            if self.dry_run:
                self.logger.info(f"[{self.cinema_name}] DRY-RUN: Flow erfolgreich durchlaufen.")
                return RebootOutcome(
                    result=RebootResult.DRY_RUN_OK,
                    message="Dry-Run: Alle Checks OK, Reboot würde ausgeführt.",
                    duration_seconds=time.time() - start_time,
                )

            # ── Schritt 4: Warten bis Server wieder online ────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 4: Warte auf Wiederherstellung...")
            online = self.wait_for_server_online(page)
            if not online:
                return RebootOutcome(
                    result=RebootResult.TIMEOUT,
                    message="Server nach Reboot nicht wieder online.",
                    duration_seconds=time.time() - start_time,
                )

            # ── Schritt 5: Post-Login ─────────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 5: Post-Login nach Reboot...")
            outcome = self._post_login(page)
            if outcome is not None:
                return outcome

            duration = time.time() - start_time
            self.logger.info(f"[{self.cinema_name}] ✅ Reboot erfolgreich! Dauer: {duration:.0f}s")
            return RebootOutcome(
                result=RebootResult.SUCCESS,
                message="Reboot erfolgreich abgeschlossen.",
                duration_seconds=duration,
            )

        except Exception as e:
            self.logger.exception(f"[{self.cinema_name}] Unerwarteter Fehler: {e}")
            self.take_screenshot_on_error(page, "unexpected_error")
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=str(e),
                duration_seconds=time.time() - start_time,
            )

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self, page: Page) -> Optional[RebootOutcome]:
        """Öffnet Login-Seite und meldet sich an. Gibt None bei Erfolg zurück."""
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "page_load_timeout")
            return RebootOutcome(result=RebootResult.OFFLINE,
                                 message="Seite konnte nicht geladen werden.")

        # Prüfen ob Login-Formular vorhanden
        try:
            page.locator(self.SEL_USERNAME_INPUT).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.logger.debug("Login-Formular nicht gefunden – möglicherweise schon eingeloggt.")
            return None

        try:
            page.locator(self.SEL_USERNAME_INPUT).fill(self.username)
            page.locator(self.SEL_PASSWORD_INPUT).fill(self.password)
            page.locator(self.SEL_LOGIN_BUTTON).click()
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "login_timeout")
            return RebootOutcome(result=RebootResult.LOGIN_FAILED,
                                 message="Login-Timeout.")
        except Exception as e:
            self.take_screenshot_on_error(page, "login_error")
            return RebootOutcome(result=RebootResult.LOGIN_FAILED,
                                 message=f"Login-Fehler: {e}")

        # Login-Erfolg: Power-Button muss sichtbar sein
        try:
            page.locator(self.SEL_POWER_BUTTON).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            # Noch auf Login-Seite? → Credentials falsch
            if page.locator(self.SEL_USERNAME_INPUT).count() > 0:
                self.take_screenshot_on_error(page, "login_failed")
                return RebootOutcome(result=RebootResult.LOGIN_FAILED,
                                     message="Login fehlgeschlagen – Credentials falsch.")
            self.logger.debug("Power-Button nicht sichtbar, aber Login scheint OK.")

        self.logger.info(f"[{self.cinema_name}] Login erfolgreich.")
        return None

    # ── Pre-Check ─────────────────────────────────────────────────────────────

    def _pre_check(self, page: Page) -> Optional[RebootOutcome]:
        """
        Prüft die untere Statusbar auf Playback/Ingest/Export.
        SICHERHEITSREGEL: Bei 'Playback in progress' → sofort ABBRUCH.
        Gibt None zurück wenn alles sicher ist.
        """
        # ⛔ ROTE GRENZE: Playback läuft
        if page.locator(self.SEL_PLAYBACK_IN_PROGRESS).count() > 0:
            self.logger.warning(
                f"[{self.cinema_name}] ⛔ PRE-CHECK: 'Playback in progress' erkannt → ABBRUCH!")
            self.take_screenshot_on_error(page, "precheck_playback_active")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_PLAYBACK,
                message="Pre-Check: 'Playback in progress' in Statusbar sichtbar.",
            )

        no_playback = page.locator(self.SEL_NO_PLAYBACK).count() > 0
        no_ingest   = page.locator(self.SEL_NO_INGEST).count() > 0
        no_export   = page.locator(self.SEL_NO_EXPORT).count() > 0

        self.logger.info(
            f"[{self.cinema_name}] Pre-Check: "
            f"No-Playback={no_playback}, No-Ingest={no_ingest}, No-Export={no_export}"
        )

        # Wenn gar keine Statusanzeige erkennbar → UI unklar
        if not (no_playback or no_ingest or no_export):
            self.take_screenshot_on_error(page, "precheck_unclear")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="Pre-Check: Keine Statusanzeigen erkennbar (No Playback/Ingest/Export).",
            )

        # Ingest oder Export aktiv?
        if not no_ingest:
            return RebootOutcome(result=RebootResult.BLOCKED_BY_TRANSFER,
                                 message="Pre-Check: Ingest möglicherweise aktiv.")
        if not no_export:
            return RebootOutcome(result=RebootResult.BLOCKED_BY_TRANSFER,
                                 message="Pre-Check: Export möglicherweise aktiv.")

        self.logger.info(f"[{self.cinema_name}] Pre-Check bestanden ✓")
        return None

    # ── Reboot auslösen ───────────────────────────────────────────────────────

    def _trigger_reboot(self, page: Page) -> Optional[RebootOutcome]:
        """
        Power-Button → Power-Menü → Restart.
        Danach: Playback-Popup abfangen (ROTE GRENZE).
        Gibt None zurück wenn Reboot erfolgreich ausgelöst (oder Dry-Run).
        """
        # Power-Button finden
        try:
            page.locator(self.SEL_POWER_BUTTON).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "power_btn_not_found")
            return RebootOutcome(result=RebootResult.UI_UNCLEAR,
                                 message="Power-Button nicht gefunden.")

        if self.dry_run:
            self.logger.info(f"[{self.cinema_name}] [DRY-RUN] Power-Button gefunden – Klick übersprungen.")
            return None

        # Power-Button klicken
        page.locator(self.SEL_POWER_BUTTON).click()
        self.logger.info(f"[{self.cinema_name}] Power-Button geklickt.")
        time.sleep(1)

        # Menü "What do you want to do?" abwarten
        try:
            page.locator(self.SEL_MENU_RESTART).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "menu_not_found")
            # Sicherheitshalber Cancel klicken falls Menü offen
            if page.locator(self.SEL_MENU_CANCEL).count() > 0:
                page.locator(self.SEL_MENU_CANCEL).click()
            return RebootOutcome(result=RebootResult.UI_UNCLEAR,
                                 message="Power-Menü nicht wie erwartet erschienen.")

        # Sicherheitslog: Was ist im Menü sichtbar?
        self.logger.debug(
            f"Power-Menü: Restart={page.locator(self.SEL_MENU_RESTART).count() > 0}, "
            f"Shutdown={page.locator(self.SEL_MENU_SHUTDOWN).count() > 0}, "
            f"Logout={page.locator(self.SEL_MENU_LOGOUT).count() > 0}"
        )

        # ✅ NUR "Restart" klicken
        page.locator(self.SEL_MENU_RESTART).click()
        self.logger.info(f"[{self.cinema_name}] 'Restart' geklickt.")
        time.sleep(1)

        # ── KRITISCHE PHASE: Playback-Popup abfangen ──────────────────────────
        popup_outcome = self._handle_popup(page)
        if popup_outcome is not None:
            return popup_outcome

        # Kein Popup → Countdown abwarten (nichts klicken)
        self.logger.info(f"[{self.cinema_name}] Kein Playback-Popup → Reboot läuft.")
        self._wait_for_countdown(page)
        return None

    def _handle_popup(self, page: Page) -> Optional[RebootOutcome]:
        """
        ⛔ ROTE GRENZE: Playback-Popup abfangen.
        Klickt SOFORT 'Abbrechen', NIEMALS 'OK'.
        """
        if page.locator(self.SEL_POPUP_PLAYBACK_TEXT).count() == 0:
            return None  # Kein Popup → OK

        # ⛔ POPUP ERKANNT
        self.logger.critical(
            f"[{self.cinema_name}] ⛔ PLAYBACK-POPUP ERKANNT! Klicke sofort 'Abbrechen'!")
        self.take_screenshot_on_error(page, "playback_popup_detected")

        # Sicherstellen dass OK NICHT geklickt wird
        if page.locator(self.SEL_POPUP_OK).count() > 0:
            self.logger.critical(
                f"[{self.cinema_name}] OK-Button sichtbar – wird NICHT geklickt!")

        # 'Abbrechen' klicken
        try:
            page.locator(self.SEL_POPUP_CANCEL).click(timeout=5_000)
            self.logger.critical(
                f"[{self.cinema_name}] ✓ 'Abbrechen' geklickt – Reboot verhindert!")
        except Exception as e:
            self.logger.error(f"[{self.cinema_name}] 'Abbrechen'-Klick fehlgeschlagen: {e}")
            # Notfall: Seite neu laden
            try:
                page.reload(timeout=self.PAGE_LOAD_TIMEOUT_MS)
            except Exception:
                pass

        return RebootOutcome(
            result=RebootResult.BLOCKED_BY_PLAYBACK,
            message="Playback-Popup erkannt – 'Abbrechen' geklickt. Kein Reboot.",
        )

    def _wait_for_countdown(self, page: Page) -> None:
        """Wartet auf den Countdown-Text. Nichts klicken!"""
        try:
            page.locator(self.SEL_COUNTDOWN).wait_for(timeout=10_000)
            self.logger.info(
                f"[{self.cinema_name}] Countdown erkannt ('System will reboot after...') "
                "– warte, nichts klicken.")
        except PlaywrightTimeout:
            self.logger.debug("Countdown-Text nicht erkannt – Reboot läuft vermutlich trotzdem.")

    # ── Post-Login ────────────────────────────────────────────────────────────

    def _post_login(self, page: Page) -> Optional[RebootOutcome]:
        """
        Nach Reboot: Login-Seite neu laden.
        Akzeptiert:
          1. "Server is ready, click here to Login" → klicken → Login
          2. Direkt die normale Login-Seite
        """
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            return RebootOutcome(result=RebootResult.TIMEOUT,
                                 message="Post-Login: Seite nach Reboot nicht ladbar.")

        # Fall 1: "Server is ready, click here to Login"
        if page.locator(self.SEL_SERVER_READY).count() > 0:
            self.logger.info(f"[{self.cinema_name}] 'Server is ready' erkannt – klicke...")
            try:
                page.locator(self.SEL_SERVER_READY).click()
                time.sleep(2)
                page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
            except Exception:
                pass

        # Fall 2: Direkt Login-Seite (oder nach Klick auf "Server is ready")
        outcome = self._login(page)
        if outcome is not None:
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=f"Post-Login nach Reboot fehlgeschlagen: {outcome.message}",
            )

        self.logger.info(f"[{self.cinema_name}] Post-Login erfolgreich ✓")
        return None
