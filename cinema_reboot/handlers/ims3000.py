"""
IMS3000 Handler – Playwright-Automation für Kino 08 (abweichendes UI).

UI-Flow basiert auf den Screenshots:
  1. Kino 8 IP und anmelde seite.png   → Login-Seite (/web/login.php)
  2. Kino 8 Power knopf recht.png      → Dashboard: "No playback in progress"
                                           + roter Logout/Power-Button oben rechts
  3. Kino 8 Reboot.png                 → Power-Dialog: Standby/Reboot/Shutdown/Logout
  4. Kino 8 Meldung reset abbrechen.png → Popup: Playback läuft → Abbrechen
  5. Kino 8 Contdown.png               → Countdown: "System will reboot in X seconds"
  6. Kino 8 Restarting.png             → Restarting-Overlay
  7. Kino 8 wieder erreichbar.png      → Login-Seite wieder sichtbar

SICHERHEITSREGEL:
  - NIEMALS auf "OK" beim Playback-Popup klicken
  - Im Power-Dialog NUR "Reboot" klicken (nicht Standby, Shutdown, Logout)
  - "No playback in progress" muss VOR dem Reboot-Auslösen sichtbar sein
"""
import logging
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from .base import BaseHandler, RebootOutcome, RebootResult

logger = logging.getLogger(__name__)


class IMS3000Handler(BaseHandler):
    """Handler für IMS3000 WebUI (Kino 08)."""

    # IMS3000 Login-Seite
    LOGIN_PATH = "/web/login.php"

    # Selektoren für IMS3000
    SEL_USERNAME_INPUT = "input[name='username'], input[type='text'], #username, input[name='user']"
    SEL_PASSWORD_INPUT = "input[name='password'], input[type='password'], #password, input[name='pass']"
    SEL_LOGIN_BUTTON = "input[type='submit'], button[type='submit'], #login-btn, button:has-text('Login')"

    # Power/Logout-Button oben rechts (bei IMS3000 heißt er "Logout" ist aber Power)
    SEL_POWER_BUTTON = (
        "button.logout, "
        "a.logout, "
        "#logout-btn, "
        "[title*='Logout'], [title*='Power'], "
        "[class*='logout'], [class*='power'], "
        "text=Logout"
    )

    # Power-Dialog Einträge (nach Klick auf Power/Logout-Button)
    SEL_DIALOG_REBOOT = "text=Reboot"
    SEL_DIALOG_STANDBY = "text=Standby"    # Verboten
    SEL_DIALOG_SHUTDOWN = "text=Shutdown"  # Verboten
    SEL_DIALOG_LOGOUT = "text=Logout"      # Verboten

    # Playback-Status (Pre-Check)
    # Das Bild zeigt: "No playback in progress" soll sichtbar sein
    SEL_NO_PLAYBACK = (
        "text=No playback in progress, "
        "text=No Playback in progress, "
        "text=No playback"
    )
    SEL_PLAYBACK_ACTIVE = "text=Playback in progress, text=Playback läuft"

    # Countdown nach Reboot
    SEL_COUNTDOWN = "text=System will reboot in, text=System will reboot after"

    # Restarting-Overlay
    SEL_RESTARTING = "text=Restarting, text=Shutdown"

    def base_url(self) -> str:
        return f"http://{self.ip}{self.LOGIN_PATH}"

    def execute_reboot(self, page: Page) -> RebootOutcome:
        """Vollständiger Reboot-Flow für IMS3000 (Kino 08)."""
        start_time = time.time()
        cinema_name = self.cinema_name

        try:
            # ─────────────────────────────────────────────
            # SCHRITT 1: Login
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 1: IMS3000 Login...")
            outcome = self._login(page)
            if outcome is not None:
                return outcome

            # ─────────────────────────────────────────────
            # SCHRITT 2: Pre-Check
            # "No playback in progress" muss sichtbar sein
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 2: Pre-Check (No playback in progress)...")
            outcome = self._pre_check(page)
            if outcome is not None:
                return outcome

            # ─────────────────────────────────────────────
            # SCHRITT 3: Reboot auslösen
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 3: Reboot auslösen...")
            outcome = self._trigger_reboot(page)
            if outcome is not None:
                return outcome

            if self.dry_run:
                self.logger.info(f"[{cinema_name}] DRY-RUN: IMS3000 Flow erfolgreich durchlaufen.")
                return RebootOutcome(
                    result=RebootResult.DRY_RUN_OK,
                    message="Dry-Run: Alle Checks OK, Reboot würde ausgeführt.",
                    duration_seconds=time.time() - start_time,
                )

            # ─────────────────────────────────────────────
            # SCHRITT 4: Warten bis wieder online
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 4: Warten auf Wiederherstellung...")
            online = self.wait_for_server_online(page)
            if not online:
                return RebootOutcome(
                    result=RebootResult.TIMEOUT,
                    message="IMS3000 nach Reboot nicht wieder online.",
                    duration_seconds=time.time() - start_time,
                )

            # ─────────────────────────────────────────────
            # SCHRITT 5: Post-Login
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 5: Post-Login...")
            outcome = self._post_login(page)
            if outcome is not None:
                return outcome

            duration = time.time() - start_time
            self.logger.info(f"[{cinema_name}] IMS3000 Reboot erfolgreich! Dauer: {duration:.0f}s")
            return RebootOutcome(
                result=RebootResult.SUCCESS,
                message="IMS3000 Reboot erfolgreich abgeschlossen.",
                duration_seconds=duration,
            )

        except Exception as e:
            self.logger.exception(f"[{cinema_name}] Unerwarteter Fehler: {e}")
            self.take_screenshot_on_error(page, "ims3000_unexpected_error")
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _login(self, page: Page) -> Optional[RebootOutcome]:
        """Öffnet die IMS3000 Login-Seite und loggt ein."""
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_page_load_timeout")
            return RebootOutcome(
                result=RebootResult.OFFLINE,
                message="IMS3000 Seite konnte nicht geladen werden.",
            )

        # Prüfen ob Login-Formular sichtbar
        try:
            page.locator(self.SEL_USERNAME_INPUT).first.wait_for(
                timeout=self.ELEMENT_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            # Ggf. schon eingeloggt
            self.logger.debug("IMS3000 Login-Formular nicht gefunden – evtl. schon eingeloggt.")
            return None

        try:
            page.locator(self.SEL_USERNAME_INPUT).first.fill(self.username)
            page.locator(self.SEL_PASSWORD_INPUT).first.fill(self.password)
            page.locator(self.SEL_LOGIN_BUTTON).first.click()
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_login_timeout")
            return RebootOutcome(
                result=RebootResult.LOGIN_FAILED,
                message="IMS3000 Login-Timeout.",
            )

        # Login-Erfolg prüfen: Dashboard muss sichtbar sein
        try:
            page.locator(self.SEL_POWER_BUTTON).first.wait_for(
                timeout=self.ELEMENT_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            if page.locator(self.SEL_USERNAME_INPUT).count() > 0:
                self.take_screenshot_on_error(page, "ims3000_login_failed")
                return RebootOutcome(
                    result=RebootResult.LOGIN_FAILED,
                    message="IMS3000 Login fehlgeschlagen.",
                )

        self.logger.info(f"[{self.cinema_name}] IMS3000 Login erfolgreich.")
        return None

    def _pre_check(self, page: Page) -> Optional[RebootOutcome]:
        """
        Prüft ob "No playback in progress" sichtbar ist.
        Das ist die Mindestvoraussetzung für IMS3000 Reboot.
        """
        # Aktiven Playback erkennen
        if page.locator(self.SEL_PLAYBACK_ACTIVE).count() > 0:
            self.logger.warning(
                f"[{self.cinema_name}] IMS3000 PRE-CHECK: Playback aktiv → Abbruch!"
            )
            self.take_screenshot_on_error(page, "ims3000_precheck_playback")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_PLAYBACK,
                message="IMS3000 Pre-Check: Playback ist aktiv.",
            )

        # "No playback in progress" muss explizit sichtbar sein
        no_playback_visible = page.locator(self.SEL_NO_PLAYBACK).count() > 0

        self.logger.info(
            f"[{self.cinema_name}] IMS3000 Pre-Check: "
            f"No-Playback-sichtbar={no_playback_visible}"
        )

        if not no_playback_visible:
            self.logger.warning(
                f"[{self.cinema_name}] IMS3000 PRE-CHECK: "
                "'No playback in progress' NICHT erkennbar → konservativ abgebrochen."
            )
            self.take_screenshot_on_error(page, "ims3000_precheck_unclear")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="IMS3000 Pre-Check: 'No playback in progress' nicht sichtbar.",
            )

        self.logger.info(f"[{self.cinema_name}] IMS3000 Pre-Check bestanden.")
        return None

    def _trigger_reboot(self, page: Page) -> Optional[RebootOutcome]:
        """
        Klickt den Power/Logout-Button und wählt 'Reboot'.
        Fängt Playback-Popup ab.
        """
        # Power-Button finden
        try:
            power_btn = page.locator(self.SEL_POWER_BUTTON).first
            power_btn.wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_power_btn_not_found")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="IMS3000 Power/Logout-Button nicht gefunden.",
            )

        if self.dry_run:
            self.logger.info(
                f"[{self.cinema_name}] [DRY-RUN] IMS3000 Power-Button gefunden. "
                "Klick übersprungen."
            )
            return None

        # Power-Button klicken
        page.locator(self.SEL_POWER_BUTTON).first.click()
        self.logger.info(f"[{self.cinema_name}] IMS3000 Power/Logout-Button geklickt.")
        time.sleep(1)

        # Power-Dialog prüfen: Reboot-Option muss sichtbar sein
        try:
            reboot_option = page.locator(self.SEL_DIALOG_REBOOT)
            reboot_option.wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_reboot_option_not_found")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="IMS3000 'Reboot'-Option im Power-Dialog nicht gefunden.",
            )

        # Sicherheitslog: Was ist im Dialog sichtbar?
        self.logger.debug(
            f"IMS3000 Power-Dialog erkannt: "
            f"Reboot={page.locator(self.SEL_DIALOG_REBOOT).count() > 0}, "
            f"Standby={page.locator(self.SEL_DIALOG_STANDBY).count() > 0}, "
            f"Shutdown={page.locator(self.SEL_DIALOG_SHUTDOWN).count() > 0}"
        )

        # NUR "Reboot" klicken
        page.locator(self.SEL_DIALOG_REBOOT).first.click()
        self.logger.info(f"[{self.cinema_name}] IMS3000 'Reboot' geklickt.")
        time.sleep(1)

        # ── KRITISCH: Playback-Popup abfangen ────────────────────────────
        popup_outcome = self._handle_popup(page)
        if popup_outcome is not None:
            return popup_outcome

        # Countdown abwarten (NICHTS klicken)
        self._wait_for_countdown(page)

        return None

    def _handle_popup(self, page: Page) -> Optional[RebootOutcome]:
        """
        IMS3000 Playback-Popup abfangen.
        ROTE GRENZE: Nur Abbrechen, niemals OK.
        """
        playback_warning_texts = [
            "text=Playback is currently running",
            "text=Do you really want to reboot",
            "text=Playback läuft",
        ]

        popup_detected = False
        for selector in playback_warning_texts:
            if page.locator(selector).count() > 0:
                popup_detected = True
                break

        if not popup_detected:
            return None

        # ⛔ POPUP ERKANNT
        self.logger.critical(
            f"[{self.cinema_name}] ⛔ IMS3000 PLAYBACK-POPUP ERKANNT! "
            "Klicke sofort 'Abbrechen'!"
        )
        self.take_screenshot_on_error(page, "ims3000_playback_popup")

        cancel_selectors = [
            "text=Abbrechen",
            "text=Cancel",
            "button:has-text('Abbrechen')",
            "button:has-text('Cancel')",
        ]
        for sel in cancel_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    btn.click()
                    self.logger.critical(
                        f"[{self.cinema_name}] ✓ IMS3000 'Abbrechen' geklickt – Reboot verhindert!"
                    )
                    break
            except Exception as e:
                self.logger.error(f"IMS3000 Abbrechen fehlgeschlagen ({sel}): {e}")

        return RebootOutcome(
            result=RebootResult.BLOCKED_BY_PLAYBACK,
            message="IMS3000 Playback-Popup erkannt – Abbrechen geklickt.",
        )

    def _wait_for_countdown(self, page: Page) -> None:
        """Wartet auf IMS3000 Countdown (NICHTS klicken)."""
        try:
            page.locator(self.SEL_COUNTDOWN).first.wait_for(timeout=10_000)
            self.logger.info(
                f"[{self.cinema_name}] IMS3000 Countdown erkannt – warte (nichts klicken)..."
            )
        except PlaywrightTimeout:
            self.logger.debug("IMS3000 Countdown nicht erkannt – Reboot läuft vermutlich.")

    def _post_login(self, page: Page) -> Optional[RebootOutcome]:
        """Nach IMS3000 Reboot: Login-Seite öffnen und einloggen."""
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            return RebootOutcome(
                result=RebootResult.TIMEOUT,
                message="IMS3000 Post-Login: Seite nach Reboot nicht ladbar.",
            )

        outcome = self._login(page)
        if outcome is not None:
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=f"IMS3000 Post-Login fehlgeschlagen: {outcome.message}",
            )

        self.logger.info(f"[{self.cinema_name}] IMS3000 Post-Login erfolgreich.")
        return None
