"""
IMS3000 Handler – Playwright-Automation für Kino 08.

UI-Flow (bestätigt durch Screenshots):
  1. Login-Seite: http://{ip}/web/login.php
     → "Kino 08" / Username / Password / Login-Button
  2. Dashboard: /web/index.php
     → Playback-Bereich Mitte:
       - "No playback in progress" sichtbar → kein Film → Reboot OK
       - "Show playlist" sichtbar → Film läuft aktiv → ABBRUCH (BLOCKED_BY_PLAYBACK)
       - Keines → UI unklar → konservativ ABBRUCH (UI_UNCLEAR)
     → Power-Button oben rechts: roter "⏻ Logout"-Button (öffnet Power-Menü)
  3. Power-Dialog: "IMS3000 - Power management"
     → Standby ❌ | Reboot ✅ | Shutdown ❌ | Logout ❌ | Close (Abbruch)
  4. Popups nach Reboot-Klick (ROTE GRENZE):
     - "Playback is currently running!" → OK ❌ NIEMALS | Abbrechen ✅ SOFORT
     - "Ingest is currently running!"   → OK ❌ NIEMALS | Abbrechen ✅ SOFORT
  5. Countdown: "System will reboot in X seconds. Cancel"
     → Nichts klicken, einfach warten
  6. Restarting:
     → Banner: "Your connection is slow or soap service is unavailable"
     → Dialog: "Shutdown / Reboot" + "Restarting..." + Spinner
  7. Server bereit:
     → Direkt die normale Login-Seite /web/login.php erscheint wieder
     → Kein spezieller "ready"-Screen (anders als Doremi)

SICHERHEITSREGELN:
  - NIEMALS OK beim Playback-Popup klicken
  - Im Power-Dialog NUR "Reboot" klicken (nicht Standby, Shutdown, Logout)
  - "No playback in progress" muss VOR dem Reboot sichtbar sein
  - Bei unbekanntem UI-Zustand: konservativ abbrechen (UI_UNCLEAR)
"""
import logging
import time
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from .base import BaseHandler, RebootOutcome, RebootResult

logger = logging.getLogger(__name__)


class IMS3000Handler(BaseHandler):
    """Handler für IMS3000 WebUI (Kino 08)."""

    LOGIN_PATH = "/web/login.php"

    # ── Login ─────────────────────────────────────────────────────────────────
    SEL_USERNAME_INPUT = "input[name='username']"
    SEL_PASSWORD_INPUT = "input[name='password']"
    SEL_LOGIN_BUTTON   = "button:has-text('Login')"

    # ── Power-Button oben rechts ──────────────────────────────────────────────
    # Roter "⏻ Logout"-Button in der Navigation → öffnet Power-Dialog
    # HINWEIS: Dieser Button heißt "Logout" aber öffnet das Power-Menü.
    # Er wird geklickt BEVOR der Dialog offen ist, daher kein Konflikt
    # mit dem "Logout"-Button im Dialog selbst.
    SEL_POWER_BUTTON = "#header-logout"

    # ── Power-Dialog "IMS3000 - Power management" ─────────────────────────────
    SEL_DIALOG_TITLE    = "text=IMS3000 - Power management"
    SEL_DIALOG_REBOOT   = "button:has-text('Reboot')"    # ✅ EINZIGER ERLAUBTER KLICK
    SEL_DIALOG_STANDBY  = "button:has-text('Standby')"   # ❌ nur zur Erkennung
    SEL_DIALOG_SHUTDOWN = "button:has-text('Shutdown')"  # ❌ nur zur Erkennung
    SEL_DIALOG_CLOSE    = "button:has-text('Close')"     # Abbruch

    # ── Pre-Check Playback-Bereich (Mitte des Dashboards) ────────────────────
    # "No playback in progress" MUSS sichtbar sein – sonst kein Reboot
    SEL_NO_PLAYBACK = "text=No playback in progress"
    # "Show playlist" erscheint NUR wenn ein Film aktiv läuft → BLOCKED_BY_PLAYBACK
    SEL_PLAYBACK_ACTIVE = "text=Show playlist"

    # ── Popups nach Reboot-Klick (ROTE GRENZE) ───────────────────────────────
    SEL_POPUP_PLAYBACK_TEXT = "text=Playback is currently running"
    SEL_POPUP_INGEST_TEXT   = "text=Ingest is currently running"
    SEL_POPUP_CANCEL        = "button:has-text('Abbrechen')"  # ✅ SOFORT KLICKEN
    SEL_POPUP_OK            = "button:has-text('OK')"         # ❌ NIEMALS KLICKEN

    # ── Countdown nach Reboot-Klick ───────────────────────────────────────────
    SEL_COUNTDOWN = "text=System will reboot in"

    # ── Restarting-Zustand ────────────────────────────────────────────────────
    SEL_RESTARTING       = "text=Restarting..."
    SEL_RESTARTING_TITLE = "text=Shutdown / Reboot"
    SEL_SLOW_CONNECTION  = "text=Your connection is slow or soap service is unavailable"

    def base_url(self) -> str:
        return f"http://{self.ip}{self.LOGIN_PATH}"

    def execute_reboot(self, page: Page) -> RebootOutcome:
        """Vollständiger Reboot-Flow für IMS3000 (Kino 08)."""
        start_time = time.time()

        try:
            # ── Schritt 1: Login ──────────────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 1: IMS3000 Login...")
            outcome = self._login(page)
            if outcome is not None:
                return outcome

            # ── Schritt 2: Pre-Check ──────────────────────────────────────────
            self.logger.info(
                f"[{self.cinema_name}] Schritt 2: Pre-Check ('No playback in progress')...")
            outcome = self._pre_check(page)
            if outcome is not None:
                return outcome

            # ── Schritt 3: Reboot auslösen ────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 3: Reboot auslösen...")
            outcome = self._trigger_reboot(page)
            if outcome is not None:
                return outcome

            if self.dry_run:
                self.logger.info(f"[{self.cinema_name}] DRY-RUN: IMS3000 Flow erfolgreich.")
                return RebootOutcome(
                    result=RebootResult.DRY_RUN_OK,
                    message="Dry-Run: Alle Checks OK, Reboot würde ausgeführt.",
                    duration_seconds=time.time() - start_time,
                )

            # ── Schritt 4: Warten bis wieder online ───────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 4: Warte auf Wiederherstellung...")
            online = self.wait_for_server_online(page)
            if not online:
                return RebootOutcome(
                    result=RebootResult.TIMEOUT,
                    message="IMS3000 nach Reboot nicht wieder online.",
                    duration_seconds=time.time() - start_time,
                )

            # ── Schritt 5: Post-Login ─────────────────────────────────────────
            self.logger.info(f"[{self.cinema_name}] Schritt 5: Post-Login...")
            outcome = self._post_login(page)
            if outcome is not None:
                return outcome

            duration = time.time() - start_time
            self.logger.info(
                f"[{self.cinema_name}] ✅ IMS3000 Reboot erfolgreich! Dauer: {duration:.0f}s")
            return RebootOutcome(
                result=RebootResult.SUCCESS,
                message="IMS3000 Reboot erfolgreich abgeschlossen.",
                duration_seconds=duration,
            )

        except Exception as e:
            self.logger.exception(f"[{self.cinema_name}] Unerwarteter Fehler: {e}")
            self.take_screenshot_on_error(page, "ims3000_unexpected_error")
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=str(e),
                duration_seconds=time.time() - start_time,
            )

    # ── Login ─────────────────────────────────────────────────────────────────

    def _login(self, page: Page) -> Optional[RebootOutcome]:
        """Öffnet /web/login.php und meldet sich an."""
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_page_load_timeout")
            return RebootOutcome(result=RebootResult.OFFLINE,
                                 message="IMS3000 Login-Seite nicht ladbar.")

        try:
            page.locator(self.SEL_USERNAME_INPUT).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.logger.debug("IMS3000 Login-Formular nicht gefunden – evtl. schon eingeloggt.")
            return None

        try:
            page.locator(self.SEL_USERNAME_INPUT).fill(self.username)
            page.locator(self.SEL_PASSWORD_INPUT).fill(self.password)
            page.locator(self.SEL_LOGIN_BUTTON).click()
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_login_timeout")
            return RebootOutcome(result=RebootResult.LOGIN_FAILED,
                                 message="IMS3000 Login-Timeout.")

        # Login-Erfolg prüfen: Power-Button in DOM ODER Login-Form verschwunden
        if page.locator(self.SEL_POWER_BUTTON).count() == 0:
            if page.locator(self.SEL_USERNAME_INPUT).count() > 0:
                self.take_screenshot_on_error(page, "ims3000_login_failed")
                return RebootOutcome(result=RebootResult.LOGIN_FAILED,
                                     message="IMS3000 Login fehlgeschlagen.")

        self.logger.info(f"[{self.cinema_name}] IMS3000 Login erfolgreich.")
        return None

    # ── Pre-Check ─────────────────────────────────────────────────────────────

    def _pre_check(self, page: Page) -> Optional[RebootOutcome]:
        """
        Prüft den Playback-Status im IMS3000 Dashboard (3-stufig):
          1. 'No playback in progress' sichtbar → kein Film → Reboot OK
          2. 'Show playlist' sichtbar → Film läuft aktiv → BLOCKED_BY_PLAYBACK
          3. Keines von beiden → Zustand unklar → UI_UNCLEAR (konservativ)
        """
        no_playback_visible = page.locator(self.SEL_NO_PLAYBACK).count() > 0
        playback_active = page.locator(self.SEL_PLAYBACK_ACTIVE).count() > 0

        self.logger.info(
            f"[{self.cinema_name}] IMS3000 Pre-Check: "
            f"No-Playback={no_playback_visible}, Playback-Aktiv={playback_active}"
        )

        if no_playback_visible:
            self.logger.info(f"[{self.cinema_name}] IMS3000 Pre-Check bestanden ✓")
            return None

        if playback_active:
            self.logger.warning(
                f"[{self.cinema_name}] ⛔ IMS3000 PRE-CHECK: "
                "'Show playlist' erkannt → Film läuft! ABBRUCH.")
            self.take_screenshot_on_error(page, "ims3000_precheck_playback_active")
            return RebootOutcome(
                result=RebootResult.BLOCKED_BY_PLAYBACK,
                message="IMS3000 Pre-Check: Film läuft (Show playlist sichtbar).",
            )

        # Keines der bekannten Zustände erkannt → konservativ abbrechen
        self.logger.warning(
            f"[{self.cinema_name}] ⛔ IMS3000 PRE-CHECK: "
            "Weder 'No playback' noch 'Show playlist' erkannt → UI unklar, abgebrochen.")
        self.take_screenshot_on_error(page, "ims3000_precheck_unclear")
        return RebootOutcome(
            result=RebootResult.UI_UNCLEAR,
            message="IMS3000 Pre-Check: UI-Zustand nicht erkennbar.",
        )

    # ── Reboot auslösen ───────────────────────────────────────────────────────

    def _trigger_reboot(self, page: Page) -> Optional[RebootOutcome]:
        """
        Power/Logout-Button → Power-Dialog → Reboot.
        Danach: Playback-Popup abfangen (ROTE GRENZE).
        """
        # Power-Button (nav "Logout") finden – count() wie Pre-Check (kein visibility-Check)
        if page.locator(self.SEL_POWER_BUTTON).count() == 0:
            self.take_screenshot_on_error(page, "ims3000_power_btn_not_found")
            return RebootOutcome(result=RebootResult.UI_UNCLEAR,
                                 message="IMS3000 Power/Logout-Button nicht gefunden.")

        if self.dry_run:
            self.logger.info(
                f"[{self.cinema_name}] [DRY-RUN] IMS3000 Power-Button gefunden – Klick übersprungen.")
            return None

        # Power-Button klicken – force=True umgeht CSS-Visibility-Prüfung
        page.locator(self.SEL_POWER_BUTTON).first.click(force=True)
        self.logger.info(f"[{self.cinema_name}] IMS3000 Power/Logout-Button geklickt.")
        time.sleep(1)

        # Power-Dialog "IMS3000 - Power management" abwarten
        try:
            page.locator(self.SEL_DIALOG_TITLE).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_dialog_not_found")
            return RebootOutcome(result=RebootResult.UI_UNCLEAR,
                                 message="IMS3000 Power-Dialog nicht erschienen.")

        # Reboot-Button im Dialog finden
        try:
            page.locator(self.SEL_DIALOG_REBOOT).wait_for(timeout=self.ELEMENT_TIMEOUT_MS)
        except PlaywrightTimeout:
            self.take_screenshot_on_error(page, "ims3000_reboot_btn_not_found")
            if page.locator(self.SEL_DIALOG_CLOSE).count() > 0:
                page.locator(self.SEL_DIALOG_CLOSE).click()
            return RebootOutcome(result=RebootResult.UI_UNCLEAR,
                                 message="IMS3000 'Reboot'-Button im Dialog nicht gefunden.")

        # Sicherheitslog
        self.logger.debug(
            f"IMS3000 Power-Dialog: "
            f"Reboot={page.locator(self.SEL_DIALOG_REBOOT).count() > 0}, "
            f"Standby={page.locator(self.SEL_DIALOG_STANDBY).count() > 0}, "
            f"Shutdown={page.locator(self.SEL_DIALOG_SHUTDOWN).count() > 0}"
        )

        # Button-JS analysieren
        btn_info = page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Reboot');
            if (!btn) return 'NICHT GEFUNDEN';
            return JSON.stringify({
                onclick: btn.getAttribute('onclick'),
                type: btn.type,
                name: btn.name,
                id: btn.id,
                disabled: btn.disabled,
                outerHTML: btn.outerHTML.substring(0, 300)
            });
        }""")
        self.logger.info(f"[{self.cinema_name}] Reboot-Button HTML: {btn_info}")

        # Netzwerk-Requests während des Klicks abfangen
        captured_requests: list[str] = []
        page.on("request", lambda req: captured_requests.append(
            f"{req.method} {req.url}" if req.method != "GET" or "power" in req.url.lower()
            else None
        ) if ("power" in req.url.lower() or "reboot" in req.url.lower()
              or req.method == "POST") else None)

        # ✅ NUR "Reboot" klicken
        page.locator(self.SEL_DIALOG_REBOOT).click()
        self.logger.info(f"[{self.cinema_name}] IMS3000 'Reboot' geklickt.")

        # Debug-Screenshot direkt nach Reboot-Klick (zeigt ob Dialog geschlossen)
        time.sleep(1)
        reqs = [r for r in captured_requests if r]
        self.logger.info(f"[{self.cinema_name}] Netzwerk-Requests nach Reboot-Klick: "
                         f"{reqs if reqs else 'KEINE'}")
        self.take_screenshot_on_error(page, "ims3000_after_reboot_click")

        # ── KRITISCHE PHASE: Playback- oder Ingest-Popup abfangen ─────────────
        # IMS3000 braucht 2-4 Sekunden bis das Popup erscheint → mehrmals prüfen
        popup_outcome = None
        for attempt in range(4):
            time.sleep(1)
            popup_outcome = self._handle_popup(page)
            if popup_outcome is not None:
                break  # Popup erkannt und Abbrechen geklickt
            self.logger.debug(
                f"[{self.cinema_name}] Popup-Check {attempt + 1}/4: kein Popup sichtbar."
            )

        if popup_outcome is not None:
            return popup_outcome

        # Kein Popup nach 4 Sekunden → Countdown abwarten (nichts klicken)
        self.logger.info(f"[{self.cinema_name}] Kein Popup erkannt → IMS3000 Reboot läuft.")
        countdown_found = self._wait_for_countdown(page)
        if not countdown_found:
            self.logger.warning(
                f"[{self.cinema_name}] ⚠️  Countdown NICHT erkannt – Reboot evtl. nicht gestartet!")
            self.take_screenshot_on_error(page, "ims3000_countdown_missing")
        return None

    def _handle_popup(self, page: Page) -> Optional[RebootOutcome]:
        """
        ⛔ ROTE GRENZE: Playback- oder Ingest-Popup nach Reboot-Klick abfangen.
        Klickt SOFORT 'Abbrechen', NIEMALS 'OK'.

        Mögliche Popups:
          - "Playback is currently running!" → BLOCKED_BY_PLAYBACK
          - "Ingest is currently running!"   → BLOCKED_BY_TRANSFER
        """
        playback_popup = page.locator(self.SEL_POPUP_PLAYBACK_TEXT).count() > 0
        ingest_popup   = page.locator(self.SEL_POPUP_INGEST_TEXT).count() > 0

        if not playback_popup and not ingest_popup:
            return None  # Kein Popup → OK

        # ⛔ POPUP ERKANNT
        if playback_popup:
            popup_type = "PLAYBACK"
            result = RebootResult.BLOCKED_BY_PLAYBACK
            message = "IMS3000 Playback-Popup erkannt – 'Abbrechen' geklickt. Kein Reboot."
            screenshot_name = "ims3000_playback_popup"
        else:
            popup_type = "INGEST"
            result = RebootResult.BLOCKED_BY_TRANSFER
            message = "IMS3000 Ingest-Popup erkannt – 'Abbrechen' geklickt. Kein Reboot."
            screenshot_name = "ims3000_ingest_popup"

        self.logger.critical(
            f"[{self.cinema_name}] ⛔ IMS3000 {popup_type}-POPUP ERKANNT! "
            "Klicke sofort 'Abbrechen'!")
        self.take_screenshot_on_error(page, screenshot_name)

        if page.locator(self.SEL_POPUP_OK).count() > 0:
            self.logger.critical(
                f"[{self.cinema_name}] OK-Button sichtbar – wird NICHT geklickt!")

        try:
            page.locator(self.SEL_POPUP_CANCEL).click(timeout=5_000)
            self.logger.critical(
                f"[{self.cinema_name}] ✓ IMS3000 'Abbrechen' geklickt – Reboot verhindert!")
        except Exception as e:
            self.logger.error(f"[{self.cinema_name}] 'Abbrechen'-Klick fehlgeschlagen: {e}")
            try:
                page.reload(timeout=self.PAGE_LOAD_TIMEOUT_MS)
            except Exception:
                pass

        return RebootOutcome(result=result, message=message)

    def _wait_for_countdown(self, page: Page) -> bool:
        """Wartet auf IMS3000 Countdown-Text. Nichts klicken! Gibt True zurück wenn erkannt."""
        try:
            page.locator(self.SEL_COUNTDOWN).wait_for(timeout=10_000)
            self.logger.info(
                f"[{self.cinema_name}] IMS3000 Countdown erkannt "
                "('System will reboot in...') – warte, nichts klicken.")
            return True
        except PlaywrightTimeout:
            self.logger.debug("IMS3000 Countdown nicht erkannt – Reboot läuft vermutlich.")
            return False

    # ── Post-Login ────────────────────────────────────────────────────────────

    def _post_login(self, page: Page) -> Optional[RebootOutcome]:
        """
        Nach IMS3000 Reboot: Login-Seite laden und einloggen.
        IMS3000 zeigt nach Reboot direkt die Login-Seite /web/login.php
        (kein spezieller "Server is ready"-Screen wie bei Doremi).
        """
        try:
            page.goto(self.base_url(), timeout=self.PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=self.PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            return RebootOutcome(result=RebootResult.TIMEOUT,
                                 message="IMS3000 Post-Login: Seite nach Reboot nicht ladbar.")

        outcome = self._login(page)
        if outcome is not None:
            return RebootOutcome(
                result=RebootResult.ERROR,
                message=f"IMS3000 Post-Login fehlgeschlagen: {outcome.message}",
            )

        self.logger.info(f"[{self.cinema_name}] IMS3000 Post-Login erfolgreich ✓")
        return None
