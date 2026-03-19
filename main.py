"""
Cinema Server Reboot – Hauptprogramm

Startet die Scheduling-Schleife. Läuft als Windows-Hintergrundprozess.

Verwendung:
  python main.py                    # Normaler Start
  python main.py --status           # Zeigt Status aller Kinos
  python main.py --run kino01       # Startet sofort für ein bestimmtes Kino
  python main.py --dry-run          # Überschreibt dry_run=true temporär
"""
import argparse
import logging
import signal
import sys
import time

from cinema_reboot.config import Config
from cinema_reboot.logger_setup import setup_logging
from cinema_reboot.reboot_engine import RebootEngine
from cinema_reboot.scheduler import Scheduler
from cinema_reboot.state_manager import StateManager
from cinema_reboot.telegram_sender import TelegramSender

logger = logging.getLogger(__name__)

# Globales Flag für sauberes Beenden
_running = True


def handle_shutdown(sig, frame):
    global _running
    logger.info("Shutdown-Signal empfangen – beende nach aktuellem Zyklus...")
    _running = False


def build_components(config: Config):
    """Erstellt alle Kern-Komponenten."""
    state = StateManager(config.state_file)
    telegram = TelegramSender(config)
    scheduler = Scheduler(config, state)
    engine = RebootEngine(config, state, scheduler, telegram)
    return state, telegram, scheduler, engine


def cmd_status(config: Config, state: StateManager, scheduler: Scheduler) -> None:
    """Zeigt den aktuellen Status aller Kinos."""
    import pytz
    from datetime import datetime
    tz = pytz.timezone(config.timezone)
    now = datetime.now(tz)

    print(f"\n{'═' * 60}")
    print(f"  Cinema Reboot – Status  ({now.strftime('%d.%m.%Y %H:%M:%S')})")
    print(f"  Modus: {'⚠️  DRY-RUN' if config.dry_run else '✅ LIVE'}")
    print(f"  Wartungsfenster: {config.mw_start} – {config.mw_end} ({config.timezone})")
    print(f"  Im Wartungsfenster: {'JA' if scheduler.in_maintenance_window() else 'nein'}")
    print(f"{'═' * 60}")

    today = now.strftime("%Y-%m-%d")
    for cinema in config.cinemas:
        cid = cinema["id"]
        name = cinema["name"]
        status = state.get_status(cid)
        last_success = state.get_last_success_date(cid) or "—"
        next_retry = state.get_next_retry_time(cid)
        sched_time = scheduler.get_scheduled_time(cid)

        retry_str = next_retry.strftime("%H:%M") if next_retry else "—"
        sched_str = sched_time.strftime("%H:%M:%S") if sched_time else "?"
        done_today = state.was_successful_today(cid, today)

        status_icon = {
            "idle": "⏳",
            "success": "✅",
            "blocked_by_playback": "🔴",
            "blocked_by_transfer": "🟡",
            "error": "❌",
            "offline": "📴",
            "ui_unclear": "❓",
            "in_progress": "🔄",
        }.get(status, "?")

        print(
            f"  {status_icon} {name:<10} | "
            f"Status: {status:<22} | "
            f"Geplant: {sched_str} | "
            f"Next-Retry: {retry_str} | "
            f"Letzter Erfolg: {last_success}"
        )

    print(f"{'═' * 60}\n")


def cmd_run_single(config: Config, cinema_id: str, engine: RebootEngine) -> None:
    """Führt sofort einen Reboot für ein bestimmtes Kino durch."""
    cinemas = {c["id"]: c for c in config.cinemas}
    if cinema_id not in cinemas:
        print(f"Kino '{cinema_id}' nicht gefunden. Verfügbare IDs: {', '.join(cinemas.keys())}")
        sys.exit(1)
    cinema = cinemas[cinema_id]
    print(f"Starte Reboot-Flow für {cinema['name']} ({cinema['ip']})...")
    outcome = engine.run(cinema)
    print(f"Ergebnis: {outcome.result.value} – {outcome.message}")


def main_loop(config: Config, state: StateManager, scheduler: Scheduler, engine: RebootEngine) -> None:
    """Hauptschleife – läuft dauerhaft und startet Reboots nach Plan."""
    global _running

    logger.info("=" * 60)
    logger.info("  Cinema Server Reboot gestartet")
    logger.info(f"  Modus: {'DRY-RUN ⚠️' if config.dry_run else 'LIVE ✅'}")
    logger.info(f"  Wartungsfenster: {config.mw_start}–{config.mw_end} ({config.timezone})")
    logger.info(f"  Kinos konfiguriert: {len(config.cinemas)}")
    logger.info("=" * 60)

    if config.dry_run:
        logger.warning(
            "DRY-RUN MODUS AKTIV: Das Programm navigiert und prüft, "
            "führt aber KEINEN echten Reboot durch!"
        )

    logger.info(scheduler.summary())

    interval = config.main_loop_interval_seconds

    while _running:
        # Tagesreset für alle Kinos prüfen
        import pytz
        from datetime import datetime
        today = datetime.now(pytz.timezone(config.timezone)).strftime("%Y-%m-%d")
        for cinema in config.cinemas:
            state.reset_for_new_day(cinema["id"], today)

        # Welche Kinos sind dran?
        due = scheduler.get_cinemas_due()

        if due:
            logger.info(f"Fällige Kinos: {[c['name'] for c in due]}")
            for cinema in due:
                if not _running:
                    break
                logger.info(f"━━━ Bearbeite: {cinema['name']} ━━━")
                engine.run(cinema)
        else:
            if scheduler.in_maintenance_window():
                logger.debug("Im Wartungsfenster, aber kein Kino fällig.")
            else:
                logger.debug("Außerhalb des Wartungsfensters – warte...")

        # Warten bis zum nächsten Prüfzyklus
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)

    logger.info("Cinema Server Reboot beendet.")


def main():
    parser = argparse.ArgumentParser(
        description="Cinema Server Reboot – Automatisches Reboot-Tool für Kino-Server"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Pfad zur Konfigurationsdatei (Standard: config.yaml)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Zeigt den aktuellen Status aller Kinos und beendet das Programm",
    )
    parser.add_argument(
        "--run",
        metavar="KINO_ID",
        help="Führt sofort einen Reboot für das angegebene Kino durch (z.B. kino01)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Aktiviert Dry-Run-Modus (überschreibt config.yaml Einstellung)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Zeigt DEBUG-Logs in der Konsole",
    )
    args = parser.parse_args()

    # Konfiguration laden
    try:
        config = Config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Konfigurationsfehler: {e}")
        sys.exit(1)

    # Logging einrichten
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(config.log_dir, level=log_level)

    # Dry-Run via Kommandozeile überschreiben
    if args.dry_run:
        config._raw["settings"]["dry_run"] = True
        logger.warning("Dry-Run via Kommandozeile aktiviert.")

    # Komponenten erstellen
    state, telegram, scheduler, engine = build_components(config)

    # Signal-Handler für sauberes Beenden (CTRL+C, Windows-Shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Kommando ausführen
    if args.status:
        cmd_status(config, state, scheduler)
        return

    if args.run:
        cmd_run_single(config, args.run, engine)
        return

    # Standard: Hauptschleife
    main_loop(config, state, scheduler, engine)


if __name__ == "__main__":
    main()
