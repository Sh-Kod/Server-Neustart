"""
Cinema Server Reboot – Hauptprogramm

Startet die Scheduling-Schleife und den Telegram-Controller.

Verwendung:
  python main.py                    # Normaler Start
  python main.py --status           # Zeigt Status aller Kinos
  python main.py --run kino01       # Startet sofort für ein bestimmtes Kino
  python main.py --dry-run          # Überschreibt dry_run=true temporär
"""
import argparse
import logging
import os
import signal
import sys
import time

from cinema_reboot.app_state import AppState
from cinema_reboot.config import Config
from cinema_reboot.logger_setup import setup_logging
from cinema_reboot.reboot_engine import RebootEngine
from cinema_reboot.scheduler import Scheduler
from cinema_reboot.state_manager import StateManager
from cinema_reboot.telegram_controller import TelegramController
from cinema_reboot.telegram_sender import TelegramSender

logger = logging.getLogger(__name__)

# Globales Flag für sauberes Beenden (SIGINT/SIGTERM)
_running = True


def handle_shutdown(sig, frame):
    global _running
    logger.info("Shutdown-Signal empfangen – beende nach aktuellem Zyklus...")
    _running = False


def build_components(config: Config, config_path: str):
    """Erstellt alle Kern-Komponenten."""
    app_state = AppState(timezone=config.timezone)
    state = StateManager(config.state_file)
    telegram = TelegramSender(config)
    scheduler = Scheduler(config, state)
    engine = RebootEngine(config, state, scheduler, telegram)
    controller = None
    if config.telegram_enabled:
        controller = TelegramController(
            config=config,
            app_state=app_state,
            state_manager=state,
            scheduler=scheduler,
            config_path=config_path,
        )
    return app_state, state, telegram, scheduler, engine, controller


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
    print(f"  Erlaubte Tage:   {config.allowed_days_str}")
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

        done_mark = " ✓" if done_today else ""
        print(
            f"  {status_icon} {name:<10} | "
            f"Status: {status:<22}{done_mark} | "
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


def main_loop(
    config: Config,
    app_state: AppState,
    state: StateManager,
    scheduler: Scheduler,
    engine: RebootEngine,
) -> None:
    """Hauptschleife – läuft dauerhaft und startet Reboots nach Plan."""
    global _running

    logger.info("=" * 60)
    logger.info("  Cinema Server Reboot gestartet")
    logger.info(f"  Version: {app_state.version}")
    logger.info(f"  Modus: {'DRY-RUN ⚠️' if config.dry_run else 'LIVE ✅'}")
    logger.info(f"  Wartungsfenster: {config.mw_start}–{config.mw_end} ({config.timezone})")
    logger.info(f"  Erlaubte Tage:   {config.allowed_days_str}")
    logger.info(f"  Kinos konfiguriert: {len(config.cinemas)}")
    logger.info("=" * 60)

    if config.dry_run:
        logger.warning(
            "DRY-RUN MODUS AKTIV: Das Programm navigiert und prüft, "
            "führt aber KEINEN echten Reboot durch!"
        )

    logger.info(scheduler.summary())

    import pytz
    from datetime import datetime

    interval = config.main_loop_interval_seconds
    _last_scheduler_restart = app_state.last_scheduler_restart

    while _running and not app_state.shutdown_requested:
        # Tagesreset für alle Kinos prüfen
        today = datetime.now(pytz.timezone(config.timezone)).strftime("%Y-%m-%d")
        for cinema in config.cinemas:
            state.reset_for_new_day(cinema["id"], today)

        # Scheduler-Neustart via Telegram?
        current_restart = app_state.last_scheduler_restart
        if current_restart is not None and current_restart != _last_scheduler_restart:
            scheduler._today_schedule = {}
            scheduler._build_schedule()
            _last_scheduler_restart = current_restart
            logger.info("Scheduler neu gestartet (via Telegram).")

        # Automatisierung pausiert?
        if app_state.paused:
            logger.debug("Automatisierung pausiert – überspringe Zyklus.")
            _sleep_interruptible(interval, app_state)
            continue

        # Sofort-Läufe via Telegram?
        pending = app_state.pop_pending_runs()
        if pending:
            cinemas_map = {c["id"]: c for c in config.cinemas}
            to_run = [cinemas_map[cid] for cid in pending if cid in cinemas_map]
            unknown = [cid for cid in pending if cid not in cinemas_map]
            for cid in unknown:
                logger.warning(f"Sofort-Reboot: Kino '{cid}' nicht gefunden.")
            if to_run:
                names = ", ".join(c["name"] for c in to_run)
                logger.info(f"━━━ Sofort-Reboot (Telegram): {names} ━━━")
                if config.parallel_reboot and len(to_run) > 1:
                    engine.run_parallel(to_run)
                else:
                    for cinema in to_run:
                        engine.run(cinema)

        # Welche Kinos sind planmäßig dran?
        due = scheduler.get_cinemas_due()
        if due:
            logger.info(f"Fällige Kinos: {[c['name'] for c in due]}")
            if config.parallel_reboot and len(due) > 1:
                engine.run_parallel(due)
            else:
                for cinema in due:
                    if not _running or app_state.shutdown_requested:
                        break
                    logger.info(f"━━━ Bearbeite: {cinema['name']} ━━━")
                    engine.run(cinema)
        else:
            if scheduler.in_maintenance_window():
                logger.debug("Im Wartungsfenster, aber kein Kino fällig.")
            else:
                logger.debug("Außerhalb des Wartungsfensters – warte...")

        _sleep_interruptible(interval, app_state)

    logger.info("Cinema Server Reboot beendet.")


def _sleep_interruptible(seconds: int, app_state: AppState) -> None:
    """Schläft in 1-Sekunden-Schritten, bis Zeit abgelaufen oder Stop angefordert."""
    global _running
    for _ in range(seconds):
        if not _running or app_state.shutdown_requested:
            break
        time.sleep(1)


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
        help="Führt sofort einen Reboot für das angegebene Kino durch",
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

    config_path = os.path.abspath(args.config)

    # Konfiguration laden
    try:
        config = Config(config_path)
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
    app_state, state, telegram, scheduler, engine, controller = build_components(
        config, config_path
    )

    # Signal-Handler für sauberes Beenden (CTRL+C, Windows-Shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Einmalige Befehle
    if args.status:
        cmd_status(config, state, scheduler)
        return

    if args.run:
        cmd_run_single(config, args.run, engine)
        return

    # Telegram-Controller starten (falls aktiviert)
    if controller:
        controller.start()
        logger.info("Telegram-Bot aktiv und wartet auf Nachrichten.")
    else:
        logger.info("Telegram-Bot deaktiviert (telegram.enabled = false).")

    # Hauptschleife
    try:
        main_loop(config, app_state, state, scheduler, engine)
    finally:
        if controller:
            controller.stop()


if __name__ == "__main__":
    main()
