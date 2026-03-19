"""
Logging-Konfiguration – tägliche rotierende Log-Dateien + Konsole.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    """
    Richtet das Logging ein:
      - Konsolen-Output (INFO+)
      - Tägliche Log-Datei (DEBUG+, 30 Tage aufbewahren)
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

    # Datei-Handler (täglich rotierend, 30 Tage)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,
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
