"""Auto-Update via Git.

Wird beim Programmstart aufgerufen. Prüft ob neue Commits im Remote-Repo
vorliegen, lädt sie herunter und startet das Programm bei Bedarf neu.
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(_BASE_DIR),
    )


def check_and_update() -> bool:
    """Prüft auf Updates und installiert sie.

    Returns:
        True  – ein Neustart ist nötig (wurde aktualisiert)
        False – kein Update oder Git nicht verfügbar
    """
    # Git vorhanden?
    if _git("--version").returncode != 0:
        logger.debug("Git nicht gefunden – Auto-Update übersprungen.")
        return False

    # Im Git-Repo?
    result = _git("rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        logger.debug("Kein Git-Repository – Auto-Update übersprungen.")
        return False

    branch = result.stdout.strip()
    logger.info(f"Prüfe auf Updates (Branch: {branch})...")

    # Remote-Stand holen
    result = _git("fetch", "origin", branch)
    if result.returncode != 0:
        logger.warning(f"Git fetch fehlgeschlagen: {result.stderr.strip()}")
        return False

    # Wieviele neue Commits?
    result = _git("rev-list", "HEAD..FETCH_HEAD", "--count")
    if result.returncode != 0:
        return False

    count = result.stdout.strip()
    if count == "0":
        logger.info("Kein Update verfügbar.")
        return False

    logger.info(f"Update gefunden: {count} neuer Commit(s) – wird installiert...")

    # requirements.txt vor dem Pull merken
    req_file = _BASE_DIR / "requirements.txt"
    req_before = req_file.read_text(encoding="utf-8") if req_file.exists() else ""

    # Pull
    result = _git("pull", "origin", branch)
    if result.returncode != 0:
        logger.error(f"Git pull fehlgeschlagen: {result.stderr.strip()}")
        return False

    logger.info("Code aktualisiert.")

    # requirements.txt geändert → Pakete aktualisieren
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

    logger.info("Update abgeschlossen – Neustart...")
    return True
