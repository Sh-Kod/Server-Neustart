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
from cinema_reboot.barco_projector import read_lamp_on
from cinema_reboot.config import Config
from cinema_reboot.logger_setup import setup_logging
from cinema_reboot.reboot_engine import RebootEngine
from cinema_reboot.scheduler import Scheduler
from cinema_reboot.state_manager import StateManager
from cinema_reboot.telegram_controller import TelegramController
from cinema_reboot.telegram_sender import TelegramSender
from cinema_reboot.updater import check_and_update, start_background_updater
from cinema_projector.lamp_config import LampConfig
from cinema_projector.lamp_controller import LampTelegramController
from cinema_projector.lamp_monitor import LampMonitor
from cinema_projector.health_monitor import HealthMonitor

logger = logging.getLogger(__name__)

# Globales Flag für sauberes Beenden (SIGINT/SIGTERM)
_running = True

# Datei-Handle für Einzelinstanz-Sperre (global, damit GC es nicht schließt)
_instance_lock_fh = None


def _acquire_single_instance_lock() -> bool:
    """Exklusive Lock-Datei-Sperre – verhindert Doppelstart (z.B. doppelter Klick auf start_hidden.vbs).
    Gibt True zurück wenn die Sperre erhalten wurde, False wenn eine andere Instanz läuft."""
    global _instance_lock_fh
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cinema_reboot.lock")
    try:
        _instance_lock_fh = open(lock_path, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(_instance_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_instance_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _instance_lock_fh.write(str(os.getpid()))
        _instance_lock_fh.flush()
        return True
    except OSError:
        return False


def handle_shutdown(sig, frame):
    global _running
    logger.info("Shutdown-Signal empfangen – beende nach aktuellem Zyklus...")
    _running = False


def build_components(
    config: Config,
    config_path: str,
    lamp_monitor=None,
    lamp_config=None,
    health_monitor=None,
):
    """Erstellt alle Kern-Komponenten."""
    app_state = AppState(timezone=config.timezone)
    state = StateManager(config.state_file)
    telegram = TelegramSender(config)
    scheduler = Scheduler(config, state)
    engine = RebootEngine(config, state, scheduler, telegram)
    controller = None
    if config.telegram_enabled:
        if lamp_monitor and lamp_config:
            controller = LampTelegramController(
                lamp_monitor=lamp_monitor,
                lamp_config=lamp_config,
                health_monitor=health_monitor,
                config=config,
                app_state=app_state,
                state_manager=state,
                scheduler=scheduler,
                config_path=config_path,
            )
        else:
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


def cmd_test_projector(config: Config, cinema_id: str) -> None:
    """Liest den Projektor-Lampenstatus – kein Reboot, nur Test."""
    cinemas = {c["id"]: c for c in config.cinemas}
    if cinema_id not in cinemas:
        print(f"Kino '{cinema_id}' nicht gefunden.")
        print(f"Verfügbare IDs: {', '.join(cinemas.keys())}")
        sys.exit(1)

    cinema = cinemas[cinema_id]
    projector_ip = cinema.get("projector_ip")

    print(f"\n{'═' * 50}")
    print(f"  Projektor-Test: {cinema['name']}")
    print(f"{'═' * 50}")

    if not projector_ip:
        print(f"  ❌ Kein 'projector_ip' in config.yaml für {cinema['name']} eingetragen.")
        print(f"     Bitte ergänzen und nochmal versuchen.")
        print(f"{'═' * 50}\n")
        sys.exit(1)

    projector_type = cinema.get("projector_type", "barco").lower()
    default_port   = 5004 if projector_type == "christie" else 43728
    projector_port = int(cinema.get("projector_port", default_port))
    print(f"  Projektor IP:   {projector_ip}")
    print(f"  Projektor Port: {projector_port}")
    print(f"  Projektor Typ:  {projector_type}")
    print(f"  Verbinde...")

    if projector_type == "christie":
        from cinema_reboot.reboot_engine import _read_lamp_on_christie
        lamp_on = _read_lamp_on_christie(projector_ip, projector_port)
    else:
        lamp_on = read_lamp_on(projector_ip, projector_port)

    print(f"{'─' * 50}")
    if lamp_on is True:
        print(f"  🔆 LAMPE AN  → Vorstellung läuft!")
        print(f"     Reboot würde BLOCKIERT werden.")
    elif lamp_on is False:
        print(f"  ⬛ LAMPE AUS → Kein Film läuft.")
        print(f"     Reboot würde ERLAUBT sein.")
    else:
        print(f"  ⚠️  KEINE ANTWORT vom Projektor.")
        print(f"     Projektor nicht erreichbar oder IP falsch.")
        print(f"     Reboot würde trotzdem fortgesetzt (mit Warnung).")
    print(f"{'═' * 50}\n")


def cmd_test_lamps(config_path: str) -> None:
    """Prüft sofort alle konfigurierten Projektoren via SNMP."""
    from cinema_projector.lamp_config import LampConfig
    from cinema_projector.lamp_monitor import LampMonitor

    try:
        lamp_cfg = LampConfig(config_path)
    except Exception as e:
        print(f"Fehler beim Laden der Lampen-Konfiguration: {e}")
        sys.exit(1)

    if not lamp_cfg.projectors:
        print("Keine Projektoren in config.yaml konfiguriert (projector_ip fehlt).")
        sys.exit(1)

    monitor = LampMonitor(lamp_cfg)
    results = monitor.run_now()

    print(f"\n{'═' * 60}")
    print(f"  Lampen-Test – {len(results)} Projektoren")
    print(f"  Warn: ≥{lamp_cfg.warn_percent:.0f}%   Kritisch: ≥{lamp_cfg.critical_percent:.0f}%")
    print(f"{'═' * 60}")
    for r in results:
        if r.ok:
            if r.percent >= lamp_cfg.critical_percent:
                icon = "⛔"
            elif r.percent >= lamp_cfg.warn_percent:
                icon = "⚠️ "
            else:
                icon = "✅"
            print(f"  {icon} {r.cinema_name:<10} {r.runtime_hours:>5}h / {r.max_hours}h = {r.percent:.1f}%")
        else:
            print(f"  ❓ {r.cinema_name:<10} nicht erreichbar – {r.error}")
    print(f"{'═' * 60}\n")


def main_loop(
    config: Config,
    app_state: AppState,
    state: StateManager,
    scheduler: Scheduler,
    engine: RebootEngine,
    telegram: TelegramSender,
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
    _was_in_window = False          # Für Fenster-Ende Erkennung
    _all_done_reported = False      # Damit wir "Alle erledigt" nur einmal senden
    _window_closed_reported = False # Damit wir den Abschlussbericht nur einmal senden
    _last_date = ""                 # Für Tageswechsel-Erkennung

    while _running and not app_state.shutdown_requested:
        # Tagesreset für alle Kinos prüfen
        today = datetime.now(pytz.timezone(config.timezone)).strftime("%Y-%m-%d")
        if today != _last_date:
            _last_date = today
            _all_done_reported = False
            _window_closed_reported = False
            _was_in_window = False
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
        if pending and app_state.reboot_enabled:
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
        elif pending and not app_state.reboot_enabled:
            logger.info("Sofort-Reboot ignoriert – Server-Neustart-Modul ist deaktiviert.")

        # Welche Kinos sind planmäßig dran?
        if app_state.reboot_enabled:
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

        # ── "Alle Säle erledigt" Nachricht ───────────────────────────────────
        if not _all_done_reported and scheduler.in_maintenance_window():
            enabled_ids = [c["id"] for c in config.cinemas if c.get("enabled", True)]
            all_done = all(state.was_successful_today(cid, today) for cid in enabled_ids)
            if all_done and enabled_ids:
                names = [c["name"] for c in config.cinemas if c.get("enabled", True)]
                logger.info("Alle Säle erfolgreich neu gestartet – sende Abschlussmeldung.")
                telegram.send_all_done(names)
                _all_done_reported = True

        # ── Wartungsfenster gerade geschlossen → Abschlussbericht ────────────
        in_window_now = scheduler.in_maintenance_window()
        if _was_in_window and not in_window_now and not _window_closed_reported:
            enabled = [c for c in config.cinemas if c.get("enabled", True)]
            failed = [c["name"] for c in enabled if not state.was_successful_today(c["id"], today)]
            succeeded = [c["name"] for c in enabled if state.was_successful_today(c["id"], today)]
            if failed:
                logger.info(f"Wartungsfenster beendet. Nicht erledigt: {failed}")
                telegram.send_window_closed_report(failed, succeeded)
            _window_closed_reported = True
        _was_in_window = in_window_now

        _sleep_interruptible(interval, app_state)

    logger.info("Cinema Server Reboot beendet.")


def _sleep_interruptible(seconds: int, app_state: AppState) -> None:
    """Schläft in 1-Sekunden-Schritten, bis Zeit abgelaufen oder Stop angefordert."""
    global _running
    for _ in range(seconds):
        if not _running or app_state.shutdown_requested:
            break
        time.sleep(1)


def _migrate_config(config_path: str, config: "Config") -> None:
    """Ergänzt fehlende Einstellungen automatisch in config.yaml.
    Wird bei jedem Programmstart ausgeführt – sicher, da nur FEHLENDE Werte gesetzt werden.
    So muss der Kunde die config.yaml nicht manuell anpassen."""
    from cinema_reboot.config_writer import update_config_value

    migrations = [
        # (yaml-Pfad,                                              Standard-Wert,   Beschreibung)
        (["settings", "startup_wait_minutes"],                        15,  "Max. Wartezeit Hochfahren (Min.)"),
        (["settings", "group_size"],                                   4,  "Kinos pro Startgruppe"),
        (["settings", "group_interval_minutes"],                       2,  "Pause zwischen Gruppen (Min.)"),
        (["projector_monitor", "health_poll_interval_seconds"],       60,  "Gesundheits-Monitor Intervall (Sek.)"),
        (["projector_monitor", "health_timeout"],                      5,  "Gesundheits-Monitor TCP-Timeout (Sek.)"),
    ]

    for key_path, default, description in migrations:
        # Abschnitt (erste Ebene) und Schlüssel (letzte Ebene) bestimmen
        section_key = key_path[0]
        leaf_key    = key_path[-1]
        section     = config._raw.setdefault(section_key, {})
        if leaf_key not in section:
            try:
                update_config_value(config_path, key_path, default)
                section[leaf_key] = default
                logger.info(f"Config-Migration: '{'/'.join(key_path)}' = {default} ergänzt ({description})")
            except Exception as e:
                logger.warning(f"Config-Migration fehlgeschlagen für '{'/'.join(key_path)}': {e}")


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
    parser.add_argument(
        "--test-projector",
        metavar="KINO_ID",
        help="Liest nur den Projektor-Lampenstatus für ein Kino (kein Reboot!)",
    )
    parser.add_argument(
        "--test-lamps",
        action="store_true",
        help="Prüft sofort alle Lampen via SNMP und zeigt Ergebnis (kein Reboot!)",
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

    # Config-Migration: fehlende Einstellungen automatisch ergänzen
    _migrate_config(config_path, config)

    # Dry-Run via Kommandozeile überschreiben
    if args.dry_run:
        config._raw["settings"]["dry_run"] = True
        logger.warning("Dry-Run via Kommandozeile aktiviert.")

    # Lampen-Monitor und Gesundheits-Monitor vorzeitig erstellen
    lamp_cfg       = None
    lamp_monitor   = None
    health_monitor = None
    try:
        lamp_cfg = LampConfig(config_path)
        if lamp_cfg.enabled and lamp_cfg.projectors:
            lamp_monitor   = LampMonitor(lamp_cfg)
            health_monitor = HealthMonitor(lamp_cfg)
    except Exception as e:
        logger.warning(f"Lampen-/Gesundheits-Konfiguration konnte nicht geladen werden: {e}")

    # Komponenten erstellen
    app_state, state, telegram, scheduler, engine, controller = build_components(
        config, config_path,
        lamp_monitor=lamp_monitor,
        lamp_config=lamp_cfg,
        health_monitor=health_monitor,
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

    if args.test_projector:
        cmd_test_projector(config, args.test_projector)
        return

    if args.test_lamps:
        cmd_test_lamps(config_path)
        return

    # Einzelinstanz-Sperre – verhindert Doppelstart via start_hidden.vbs
    is_daemon = not (args.status or args.run or args.test_projector or args.test_lamps)
    if is_daemon and not _acquire_single_instance_lock():
        print("[Cinema Reboot] Eine andere Instanz läuft bereits – beende.")
        logger.warning("Zweite Instanz erkannt – wird sofort beendet.")
        sys.exit(0)

    # Auto-Update prüfen – bei Änderung Prozess neu starten
    if check_and_update():
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Telegram-Controller starten (falls aktiviert)
    if controller:
        controller.start()
        logger.info("Telegram-Bot aktiv und wartet auf Nachrichten.")
    else:
        logger.info("Telegram-Bot deaktiviert (telegram.enabled = false).")

    # Hintergrund-Updater starten (prüft alle 30 Sek. auf neue Commits)
    start_background_updater(app_state, notify_fn=telegram.send_update_installed)

    # Lampen-Monitor starten
    if lamp_monitor:
        lamp_monitor.start()
        logger.info("Lampen-Monitor gestartet.")
    else:
        logger.info("Lampen-Monitor deaktiviert oder keine Projektoren konfiguriert.")

    # Gesundheits-Monitor starten
    if health_monitor:
        health_monitor.start()
        logger.info(
            f"Gesundheits-Monitor gestartet – "
            f"Intervall: {lamp_cfg.health_poll_interval_seconds}s"
        )
    else:
        logger.info("Gesundheits-Monitor deaktiviert oder keine Projektoren konfiguriert.")

    # Startup-Benachrichtigung via Telegram (zeigt Hauptmenü)
    if controller and hasattr(controller, "send_startup_notification"):
        controller.send_startup_notification()

    # Hauptschleife
    try:
        main_loop(config, app_state, state, scheduler, engine, telegram)
    finally:
        if controller:
            controller.stop()
        if lamp_monitor:
            lamp_monitor.stop()
        if health_monitor:
            health_monitor.stop()

    # Neustart nach Hintergrund-Update
    if app_state.update_available:
        logger.info("Starte Programm nach Update neu...")
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
