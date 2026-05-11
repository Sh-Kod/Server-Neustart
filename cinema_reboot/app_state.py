"""
Gemeinsamer Anwendungszustand – thread-sicher geteilt zwischen
Hauptschleife und Telegram-Controller.
"""
import subprocess
import threading
from datetime import datetime
from typing import Optional, Set

import pytz


def _read_version() -> str:
    """Liest den aktuellen Git-Commit-Hash als Versions-Suffix."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return f"1.2.0 ({result.stdout.strip()})"
    except Exception:
        pass
    return "1.2.0"


VERSION = _read_version()


class AppState:
    """Thread-sicherer gemeinsamer Zustand für das gesamte Programm."""

    def __init__(self, timezone: str = "Europe/Berlin"):
        self._lock = threading.Lock()
        self._tz = pytz.timezone(timezone)
        self._paused: bool = False
        self._start_time: datetime = datetime.now(self._tz)
        self._last_scheduler_restart: Optional[datetime] = None
        self._shutdown_requested: bool = False
        self._update_available: bool = False
        self._pending_runs: Set[str] = set()  # cinema_ids für sofortigen Lauf
        self._reboot_enabled: bool = True
        self.version: str = VERSION

    # ── Pause / Resume ───────────────────────────────────────────────────────

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    # ── Shutdown ─────────────────────────────────────────────────────────────

    @property
    def shutdown_requested(self) -> bool:
        with self._lock:
            return self._shutdown_requested

    def request_shutdown(self) -> None:
        with self._lock:
            self._shutdown_requested = True

    # ── Update ───────────────────────────────────────────────────────────────

    @property
    def update_available(self) -> bool:
        with self._lock:
            return self._update_available

    def signal_update(self) -> None:
        """Wird vom Hintergrund-Updater aufgerufen wenn ein Update gezogen wurde."""
        with self._lock:
            self._update_available = True
            self._shutdown_requested = True

    # ── Zeiten ───────────────────────────────────────────────────────────────

    @property
    def start_time(self) -> datetime:
        return self._start_time

    @property
    def last_scheduler_restart(self) -> Optional[datetime]:
        with self._lock:
            return self._last_scheduler_restart

    def mark_scheduler_restart(self) -> None:
        with self._lock:
            self._last_scheduler_restart = datetime.now(self._tz)
            self._paused = False  # Nach Neustart automatisch fortsetzen

    # ── Modul-Steuerung ──────────────────────────────────────────────────────

    @property
    def reboot_enabled(self) -> bool:
        with self._lock:
            return self._reboot_enabled

    def set_reboot_enabled(self, v: bool) -> None:
        with self._lock:
            self._reboot_enabled = v

    # ── Manuelle Sofortläufe ─────────────────────────────────────────────────

    def request_run(self, cinema_id: str) -> None:
        """Meldet ein Kino für sofortigen Reboot-Versuch an."""
        with self._lock:
            self._pending_runs.add(cinema_id)

    def pop_pending_runs(self) -> Set[str]:
        """Gibt alle angeforderten Sofortläufe zurück und leert die Liste."""
        with self._lock:
            runs = set(self._pending_runs)
            self._pending_runs.clear()
            return runs

    def has_pending_runs(self) -> bool:
        with self._lock:
            return bool(self._pending_runs)
