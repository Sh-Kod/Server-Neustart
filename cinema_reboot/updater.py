"""Auto-Update via Git.

Zwei Modi:
  1. check_and_update()         – einmaliger Check beim Programmstart
  2. start_background_updater() – Hintergrund-Thread, prüft alle 30 Sek.
                                   Bei Update: zieht Code + signalisiert Neustart
"""
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cinema_reboot.app_state import AppState

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
UPDATE_INTERVAL_SECONDS = 30


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(_BASE_DIR),
    )


def _git_available() -> bool:
    return _git("--version").returncode == 0


def _current_branch() -> str | None:
    result = _git("rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _fetch_and_count(branch: str) -> int:
    """Gibt Anzahl neuer Commits im Remote zurück, -1 bei Fehler."""
    if _git("fetch", "origin", branch).returncode != 0:
        return -1
    result = _git("rev-list", "HEAD..FETCH_HEAD", "--count")
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _apply_update(branch: str) -> bool:
    """Zieht den neuen Code und aktualisiert Abhängigkeiten. Gibt True zurück bei Erfolg."""
    req_file = _BASE_DIR / "requirements.txt"
    req_before = req_file.read_text(encoding="utf-8") if req_file.exists() else ""

    result = _git("pull", "origin", branch)
    if result.returncode != 0:
        logger.error(f"Git pull fehlgeschlagen: {result.stderr.strip()}")
        return False

    logger.info("Code aktualisiert.")

    req_after = req_file.read_text(encoding="utf-8") if req_file.exists() else ""
    if req_after != req_before:
        logger.info("requirements.txt geändert – installiere neue Abhängigkeiten...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "-r", "requirements.txt"],
            capture_output=True,
            text=True,
            cwd=str(_BASE_DIR),
        )
        if result.returncode != 0:
            logger.warning(f"pip install fehlgeschlagen: {result.stderr.strip()}")
        else:
            logger.info("Abhängigkeiten aktualisiert.")

    return True


def check_and_update() -> bool:
    """Einmaliger Update-Check beim Programmstart.

    Returns:
        True  – ein Neustart ist nötig (wurde aktualisiert)
        False – kein Update oder Git nicht verfügbar
    """
    if not _git_available():
        logger.debug("Git nicht gefunden – Auto-Update übersprungen.")
        return False

    branch = _current_branch()
    if branch is None:
        logger.debug("Kein Git-Repository – Auto-Update übersprungen.")
        return False

    logger.info(f"Prüfe auf Updates (Branch: {branch})...")

    count = _fetch_and_count(branch)
    if count <= 0:
        if count == 0:
            logger.info("Kein Update verfügbar.")
        return False

    logger.info(f"Update gefunden: {count} neuer Commit(s) – wird installiert...")
    if _apply_update(branch):
        logger.info("Update abgeschlossen – Neustart...")
        return True

    return False


def start_background_updater(app_state: "AppState", notify_fn=None) -> None:
    """Startet einen Daemon-Thread, der alle 30 Sekunden auf Updates prüft.

    Bei einem gefundenen Update wird der Code gezogen und app_state.signal_update()
    aufgerufen – das beendet die Hauptschleife, woraufhin main.py den Prozess neu startet.

    notify_fn: optionale Funktion die vor dem Neustart aufgerufen wird (z.B. Telegram-Nachricht)
    """
    if not _git_available():
        logger.debug("Git nicht gefunden – Hintergrund-Updater deaktiviert.")
        return

    branch = _current_branch()
    if branch is None:
        logger.debug("Kein Git-Repository – Hintergrund-Updater deaktiviert.")
        return

    def _loop() -> None:
        logger.info(f"Hintergrund-Updater gestartet (alle {UPDATE_INTERVAL_SECONDS}s, Branch: {branch}).")
        while not app_state.shutdown_requested:
            time.sleep(UPDATE_INTERVAL_SECONDS)
            if app_state.shutdown_requested:
                break
            try:
                count = _fetch_and_count(branch)
                if count > 0:
                    logger.info(f"Hintergrund-Update: {count} neuer Commit(s) gefunden – installiere...")
                    if _apply_update(branch):
                        logger.info("Hintergrund-Update abgeschlossen – signalisiere Neustart.")
                        if notify_fn:
                            try:
                                notify_fn(count)
                            except Exception as e:
                                logger.warning(f"Update-Benachrichtigung fehlgeschlagen: {e}")
                        app_state.signal_update()
                        break
                elif count == 0:
                    logger.debug("Hintergrund-Update: kein neuer Commit.")
            except Exception as exc:
                logger.warning(f"Hintergrund-Updater Fehler: {exc}")

    thread = threading.Thread(target=_loop, name="bg-updater", daemon=True)
    thread.start()
