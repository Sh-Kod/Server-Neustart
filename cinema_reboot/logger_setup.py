"""
Logging-Konfiguration – tägliche rotierende Log-Dateien + Konsole.
"""
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

_SCREENSHOT_MAX_AGE_DAYS = 7
_LOG_MAX_AGE_DAYS = 21


def _cleanup_old_files(log_dir: str) -> None:
    """Löscht Screenshots/HTML-Dumps älter als 7 Tage und Log-Dateien älter als 21 Tage."""
    now = time.time()
    screenshot_cutoff = now - _SCREENSHOT_MAX_AGE_DAYS * 86400
    log_cutoff = now - _LOG_MAX_AGE_DAYS * 86400

    for filename in os.listdir(log_dir):
        filepath = os.path.join(log_dir, filename)
        if not os.path.isfile(filepath):
            continue
        mtime = os.path.getmtime(filepath)
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".png", ".html") and mtime < screenshot_cutoff:
            try:
                os.remove(filepath)
                logging.getLogger(__name__).debug(f"Gelöscht (>7 Tage): {filename}")
            except OSError:
                pass
        elif ext in (".log",) and mtime < log_cutoff:
            try:
                os.remove(filepath)
                logging.getLogger(__name__).debug(f"Gelöscht (>21 Tage): {filename}")
            except OSError:
                pass


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    """
    Richtet das Logging ein:
      - Konsolen-Output (INFO+)
      - Tägliche Log-Datei (DEBUG+, 21 Tage aufbewahren)
      - Automatische Bereinigung: Screenshots/HTML nach 7 Tagen, Logs nach 21 Tagen
    """
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "cinema_reboot.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Konsolen-Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)

    # Datei-Handler (täglich rotierend, 21 Tage)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=21,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)

    # Playwright-Logs reduzieren (sehr verbose)
    logging.getLogger("playwright").setLevel(logging.WARNING)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logging.info(f"Logging gestartet. Log-Datei: {log_file}")
    _cleanup_old_files(log_dir)
