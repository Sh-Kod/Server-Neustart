"""
Doremi/DCP2000 Handler – Playwright-Automation für Standard-Kinos (Kino 01–07, 09–13).

UI-Flow basiert auf den Screenshots:
  1. restart knopf.png          → Roter Power-Button → Menü: Restart/Shutdown/Logout/Cancel
  2. fehler meldung restart.png → Playback läuft → NUR Abbrechen klicken
  3. Normal restart countdown   → Countdown erscheint → NICHTS klicken, warten
  4. restarting.png             → Server fährt runter → warten
  5. server erreichbar!.png     → "Server is ready, click here to Login" → klicken

SICHERHEITSREGEL:
  - NIEMALS auf "OK" beim Playback-Popup klicken
  - NIEMALS Shutdown oder Logout klicken
  - Bei unbekanntem UI-Zustand: konservativ abbrechen
"""
import logging
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect

from .base import BaseHandler, RebootOutcome, RebootResult

logger = logging.getLogger(__name__)


class DoremiHandler(BaseHandler):
    """Handler für Doremi/DCP2000 WebUI (Standard-Kinos)."""

    # Selektoren für die Doremi/DCP2000-Oberfläche.
    # Diese wurden nach bestem Wissen aus den Screenshots abgeleitet.
    # Bei Abweichungen vom echten UI müssen sie angepasst werden.

    # Login-Formular
    SEL_USERNAME_INPUT = "input[name='username'], input[type='text'], #username"
    SEL_PASSWORD_INPUT = "input[name='password'], input[type='password'], #password"
    SEL_LOGIN_BUTTON = "input[type='submit'], button[type='submit'], #login-btn"

    # Power-Button (roter Button oben rechts)
    SEL_POWER_BUTTON = (
        "button.power, "
        "#power-btn, "
        "a.power, "
        "[title*='Power'], [title*='power'], "
        "[class*='power'], [class*='Power']"
    )

    # Power-Menü Einträge
    SEL_MENU_RESTART = "text=Restart"
    SEL_MENU_SHUTDOWN = "text=Shutdown"   # Verboten – nur zur Erkennung
    SEL_MENU_LOGOUT = "text=Logout"       # Verboten – nur zur Erkennung
    SEL_MENU_CANCEL = "text=Cancel"

    # Playback-Popup (Gefahren-Popup)
    SEL_POPUP_OK = "text=OK"
    SEL_POPUP_CANCEL = "text=Abbrechen, text=Cancel"

    # Status-Indikatoren (Pre-Check)
    SEL_NO_PLAYBACK = "text=No Playback, text=No playback"
    SEL_NO_INGEST = "text=No Ingest, text=No ingest"
    SEL_NO_EXPORT = "text=No Export, text=No export"
    SEL_PLAYBACK_ACTIVE = "text=Playback in progress, text=Play"

    # Post-Reboot Zustand
    SEL_SERVER_READY = "text=Server is ready"
    SEL_CLICK_TO_LOGIN = "text=click here to Login, text=Login"

    # Countdown-Indikator (nach erfolgreichem Restart-Klick)
    SEL_COUNTDOWN = "text=System will reboot"

    # Restarting-Indikator
    SEL_RESTARTING = "text=Restarting, text=Disconnected from WebUI, text=Soap service unavailable"

    def base_url(self) -> str:
        return f"http://{self.ip}/web/"

    def execute_reboot(self, page: Page) -> RebootOutcome:
        """Vollständiger Reboot-Flow für Doremi/DCP2000."""
        start_time = time.time()
        cinema_name = self.cinema_name

        try:
            # ─────────────────────────────────────────────
            # SCHRITT 1: Seite laden und einloggen
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 1: Login...")
            outcome = self._login(page)
            if outcome is not None:
                return outcome

            # ─────────────────────────────────────────────
            # SCHRITT 2: Pre-Check (Playback / Transfer)
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 2: Pre-Check...")
            outcome = self._pre_check(page)
            if outcome is not None:
                return outcome

            # ─────────────────────────────────────────────
            # SCHRITT 3: Reboot auslösen (Power → Restart)
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 3: Reboot auslösen...")
            outcome = self._trigger_reboot(page)
            if outcome is not None:
                return outcome

            if self.dry_run:
                self.logger.info(f"[{cinema_name}] DRY-RUN: Reboot-Flow erfolgreich durchlaufen.")
                return RebootOutcome(
                    result=RebootResult.DRY_RUN_OK,
                    message="Dry-Run: Alle Checks OK, Reboot würde ausgeführt.",
                    duration_seconds=time.time() - start_time,
                )

            # ─────────────────────────────────────────────
            # SCHRITT 4: Warten bis Server wieder online
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 4: Warten auf Wiederherstellung...")
            online = self.wait_for_server_online(page)
            if not online:
                return RebootOutcome(
                    result=RebootResult.TIMEOUT,
                    message="Server nach Reboot nicht wieder online.",
                    duration_seconds=time.time() - start_time,
                )

            # ─────────────────────────────────────────────
            # SCHRITT 5: Post-Check – nochmals einloggen
            # ─────────────────────────────────────────────
            self.logger.info(f"[{cinema_name}] Schritt 5: Post-Check / Login nach Reboot...")
            outcome = self._post_login(page)
            if outcome is not None:
                return outcome

            duration = time.time() - start_time
            self.logger.info(f"[{cinema_name}] Reboot erfolgreich! Dauer: {duration:.0f}s")
            return RebootOutcome(
                result=RebootResult.SUCCESS,
                message="Reboot erfolgreich abgeschlossen.",
                duration_seconds=duration,
            )

        except Exception as e:
            self.logger.exception(f"[{cinema_name}] Unerwarteter Fehler: {e}")
            self.take_screenshot_on_error(page, "unexpected_error")
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _login(self, page: Page) -> Optional[RebootOutcome]:
        """Öffnet die Login-Seite und loggt ein. Gibt None zurück bei Erfolg."""
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "page_load_timeout")
            return RebootOutcome(
                result=RebootResult.OFFLINE,
                message="Seite konnte nicht geladen werden (Timeout).",
            )

        # Prüfen ob Login-Formular sichtbar ist
        try:
            page.locator(self.SEL_USERNAME_INPUT).first.wait_for(
                timeout=self.ELEMENT_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            # Vielleicht schon eingeloggt?
            self.logger.debug("Login-Formular nicht gefunden – möglicherweise schon eingeloggt.")
            return None

        # Anmeldedaten eingeben
        try:
            page.locator(self.SEL_USERNAME_INPUT).first.fill(self.username)
            page.locator(self.SEL_PASSWORD_INPUT).first.fill(self.password)
            page.locator(self.SEL_LOGIN_BUTTON).first.click()
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "login_timeout")
            return RebootOutcome(
                result=RebootResult.LOGIN_FAILED,
                message="Login-Timeout – Seite reagierte nicht.",
            )
        except Exception as e:
            self.take_screenshot_on_error(page, "login_error")
            return RebootOutcome(
                result=RebootResult.LOGIN_FAILED,
                message=f"Login-Fehler: {e}",
            )

        # Prüfen ob Login erfolgreich (Power-Button oder Dashboard sichtbar)
        try:
            page.locator(self.SEL_POWER_BUTTON).first.wait_for(
                timeout=self.ELEMENT_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            # Prüfen ob wir noch auf der Login-Seite sind (Login fehlgeschlagen)
            if page.locator(self.SEL_USERNAME_INPUT).count() > 0:
                self.take_screenshot_on_error(page, "login_failed")
                return RebootOutcome(
                    result=RebootResult.LOGIN_FAILED,
                    message="Login fehlgeschlagen – Credentials falsch oder Seite unbekannt.",
                )
            # Anderer Zustand – weiter versuchen
            self.logger.debug("Power-Button nicht gefunden, aber kein Login-Fehler erkennbar.")

        self.logger.info(f"[{self.cinema_name}] Login erfolgreich.")
        return None

    def _pre_check(self, page: Page) -> Optional[RebootOutcome]:
        """
        Prüft Playback-, Ingest- und Export-Status.
        SICHERHEITSREGEL: Gibt RebootOutcome zurück, wenn etwas läuft.
        Gibt None zurück, wenn alles frei ist.
        """
        # Aktiven Playback erkennen (rote Grenze)
        if page.locator(self.SEL_PLAYBACK_ACTIVE).count() > 0:
            self.logger.warning(f"[{self.cinema_name}] PRE-CHECK: Playback aktiv → Abbruch!")
            self.take_screenshot_on_error(page, "precheck_playback")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_PLAYBACK,
                message="Pre-Check: Playback ist aktiv.",
            )

        # Prüfen ob Status-Anzeigen vorhanden (sicherer Zustand)
        has_no_playback = page.locator(self.SEL_NO_PLAYBACK).count() > 0
        has_no_ingest = page.locator(self.SEL_NO_INGEST).count() > 0
        has_no_export = page.locator(self.SEL_NO_EXPORT).count() > 0

        self.logger.info(
            f"[{self.cinema_name}] Pre-Check Status: "
            f"No-Playback={has_no_playback}, "
            f"No-Ingest={has_no_ingest}, "
            f"No-Export={has_no_export}"
        )

        # Wenn KEINE der Status-Anzeigen sichtbar sind → UI unklar
        if not (has_no_playback or has_no_ingest or has_no_export):
            self.logger.warning(
                f"[{self.cinema_name}] PRE-CHECK: Keine Status-Anzeigen erkennbar → "
                "Konservativ abgebrochen."
            )
            self.take_screenshot_on_error(page, "precheck_unclear")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="Pre-Check: Status-Anzeigen (No Playback/Ingest/Export) nicht erkennbar.",
            )

        # Wenn Ingest oder Export läuft → blockiert
        # (erkannt durch Abwesenheit von "No Ingest" / "No Export")
        if not has_no_ingest:
            self.logger.warning(f"[{self.cinema_name}] PRE-CHECK: Ingest möglicherweise aktiv.")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_TRANSFER,
                message="Pre-Check: Ingest-Status nicht als 'No Ingest' erkennbar.",
            )

        if not has_no_export:
            self.logger.warning(f"[{self.cinema_name}] PRE-CHECK: Export möglicherweise aktiv.")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_TRANSFER,
                message="Pre-Check: Export-Status nicht als 'No Export' erkennbar.",
            )

        self.logger.info(f"[{self.cinema_name}] Pre-Check bestanden – kein Playback/Transfer.")
        return None

    def _trigger_reboot(self, page: Page) -> Optional[RebootOutcome]:
        """
        Klickt den Power-Button und dann Restart.
        Fängt das Playback-Popup ab (ROTE GRENZE).
        Gibt None zurück, wenn Reboot ausgelöst wurde (oder Dry-Run).
        """
        # Power-Button klicken
        try:
            power_btn = page.locator(self.SEL_POWER_BUTTON).first
            power_btn.wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "power_btn_not_found")
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="Power-Button nicht gefunden.",
            )

        if self.dry_run:
            self.logger.info(f"[{self.cinema_name}] [DRY-RUN] Power-Button gefunden. Klick übersprungen.")
            return None  # Dry-Run OK

        page.locator(self.SEL_POWER_BUTTON).first.click()
        self.logger.info(f"[{self.cinema_name}] Power-Button geklickt.")

        # Menü abwarten
        time.sleep(1)

        # ── KRITISCH: Prüfen ob Popup "Playback läuft" erscheint BEVOR Restart geklickt wird
        # Das Popup kann auch nach dem Restart-Klick kommen – daher zweistufig prüfen.

        # Prüfen ob Restart-Option im Menü sichtbar
        try:
            restart_option = page.locator(self.SEL_MENU_RESTART)
            restart_option.wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "restart_option_not_found")
            # Menü nicht wie erwartet → abbrechen
            # Ggf. Cancel klicken falls Menü offen ist
            if page.locator(self.SEL_MENU_CANCEL).count() > 0:
                page.locator(self.SEL_MENU_CANCEL).first.click()
            return RebootOutcome(
                result=RebootResult.UI_UNCLEAR,
                message="Restart-Option im Power-Menü nicht gefunden.",
            )

        # Sicherheitscheck: Ist Shutdown/Logout sichtbar? Dann sind wir im richtigen Menü.
        # (Nur zur Verifikation – wir klicken diese NICHT)
        self.logger.debug(
            f"Menü-Optionen erkannt: "
            f"Restart={page.locator(self.SEL_MENU_RESTART).count() > 0}, "
            f"Shutdown={page.locator(self.SEL_MENU_SHUTDOWN).count() > 0}, "
            f"Logout={page.locator(self.SEL_MENU_LOGOUT).count() > 0}"
        )

        # Restart klicken (einziger erlaubter Klick)
        page.locator(self.SEL_MENU_RESTART).first.click()
        self.logger.info(f"[{self.cinema_name}] 'Restart' geklickt.")

        # ── KRITISCHE PHASE: Popup-Überwachung ──────────────────────────────
        # Sofort nach dem Klick prüfen, ob ein Playback-Popup erscheint.
        # Das ist die "rote Grenze" – wir dürfen NIEMALS "OK" klicken.
        time.sleep(1)  # Kurz warten, damit Popup erscheinen kann

        popup_outcome = self._handle_popup(page)
        if popup_outcome is not None:
            return popup_outcome

        # Kein Popup → Countdown sollte erscheinen
        self.logger.info(f"[{self.cinema_name}] Kein Playback-Popup erkannt → Reboot läuft.")

        # Countdown abwarten (NICHTS klicken)
        self._wait_for_countdown(page)

        return None  # Reboot erfolgreich ausgelöst

    def _handle_popup(self, page: Page) -> Optional[RebootOutcome]:
        """
        Überwacht das Playback-Popup.
        ROTE GRENZE: Klickt NUR "Abbrechen", NIEMALS "OK".
        Gibt RebootOutcome(BLOCKED_BY_PLAYBACK) zurück wenn Popup erkannt.
        Gibt None zurück wenn kein Popup.
        """
        # Playback-Warnung erkennen (durch Text im Popup)
        playback_warning_texts = [
            "text=Playback is currently running",
            "text=Playback läuft",
            "text=Do you really want to reboot",
        ]

        popup_detected = False
        for selector in playback_warning_texts:
            if page.locator(selector).count() > 0:
                popup_detected = True
                break

        if not popup_detected:
            # Kein Playback-Popup → OK
            return None

        # ⛔ PLAYBACK-POPUP ERKANNT → SOFORT ABBRECHEN KLICKEN
        self.logger.critical(
            f"[{self.cinema_name}] ⛔ PLAYBACK-POPUP ERKANNT! "
            "Klicke sofort 'Abbrechen' – KEIN OK!"
        )
        self.take_screenshot_on_error(page, "playback_popup_detected")

        # "Abbrechen" klicken (NUR das ist erlaubt)
        cancel_selectors = [
            "text=Abbrechen",
            "text=Cancel",
            "button:has-text('Abbrechen')",
            "button:has-text('Cancel')",
        ]
        cancel_clicked = False
        for sel in cancel_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    btn.click()
                    cancel_clicked = True
                    self.logger.critical(
                        f"[{self.cinema_name}] ✓ 'Abbrechen' geklickt – Reboot verhindert!"
                    )
                    break
            except Exception as e:
                self.logger.error(f"Abbrechen-Klick fehlgeschlagen ({sel}): {e}")

        if not cancel_clicked:
            self.logger.error(
                f"[{self.cinema_name}] ⚠️ 'Abbrechen'-Button nicht gefunden! "
                "Seite sofort neu laden um Popup zu schließen."
            )
            # Notfall: Seite neu laden, um Popup zu entfernen
            try:
                page.reload(timeout=self.PAGE_LOAD_TIMEOUT_MS)
            except Exception:
                pass

        return RebootOutcome(
            result=RebootResult.BLOCKED_BY_PLAYBACK,
            message="Playback-Popup erkannt – sofort Abbrechen geklickt. Kein Reboot.",
        )

    def _wait_for_countdown(self, page: Page) -> None:
        """Wartet auf den Countdown nach dem Restart (NICHTS klicken)."""
        try:
            page.locator(self.SEL_COUNTDOWN).first.wait_for(
                timeout=10_000
            )
            self.logger.info(f"[{self.cinema_name}] Countdown erkannt – warte (nichts klicken)...")
        except PlaywrightTimeout:
            # Countdown nicht explizit sichtbar – trotzdem weiter
            self.logger.debug("Countdown-Element nicht erkannt, aber Reboot läuft vermutlich.")

    def _post_login(self, page: Page) -> Optional[RebootOutcome]:
        """
        Nach dem Reboot: Lädt die Seite neu und loggt sich ein.
        Erkennt "Server is ready, click here to Login".
        """
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            return RebootOutcome(
                result=RebootResult.TIMEOUT,
                message="Post-Login: Seite nach Reboot nicht ladbar.",
            )

        # Prüfen ob "Server is ready, click here to Login" erscheint
        ready_texts = [
            "text=Server is ready",
            "text=click here to Login",
            "text=Server is ready, click here to Login",
        ]
        for sel in ready_texts:
            if page.locator(sel).count() > 0:
                self.logger.info(f"[{self.cinema_name}] 'Server is ready' erkannt – klicke Login...")
                try:
                    page.locator(sel).first.click()
                    time.sleep(2)
                    page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
                except Exception:
                    pass
                break

        # Nochmals einloggen
        outcome = self._login(page)
        if outcome is not None:
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=f"Post-Login nach Reboot fehlgeschlagen: {outcome.message}",
            )

        self.logger.info(f"[{self.cinema_name}] Post-Login erfolgreich.")
        return None
