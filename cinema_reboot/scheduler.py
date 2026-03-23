"""
Scheduler – entscheidet, welche Kinos jetzt bearbeitet werden sollen.

Logik:
  - Nur im Wartungsfenster (z.B. 03:00–06:00 Europe/Berlin) aktiv.
  - Jedem Kino wird beim ersten Lauf des Tages eine zufällige Startzeit
    im Fenster zugewiesen (damit nicht alle gleichzeitig rebooten).
  - Ein Kino ist "dran", wenn:
      1. Wartungsfenster aktiv
      2. Noch nicht erfolgreich heute
      3. Zufällige Startzeit bereits erreicht
      4. Kein aktiver next_retry_time in der Zukunft
"""
import json
import os
import random
from datetime import datetime, timedelta
from typing import Optional
import pytz

from .config import Config
from .state_manager import StateManager, Status


class ScheduledCinema:
    """Repräsentiert ein geplantes Kino mit zufälliger Startzeit."""
    def __init__(self, cinema: dict, scheduled_time: datetime):
        self.cinema = cinema
        self.scheduled_time = scheduled_time


class Scheduler:
    """Verwaltet die tagesbasierte Zufallsplanung für alle Kinos."""

    SCHEDULE_FILE = "schedule_today.json"

    def __init__(self, config: Config, state_manager: StateManager):
        self._config = config
        self._state = state_manager
        self._tz = pytz.timezone(config.timezone)
        self._schedule_file = os.path.abspath(self.SCHEDULE_FILE)
        self._today_schedule: dict[str, str] = {}  # cinema_id -> ISO-Zeit
        self._load_schedule()

    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _parse_time(self, time_str: str, date: datetime) -> datetime:
        """Kombiniert ein HH:MM-String mit einem Datum zur vollständigen Zeit."""
        h, m = map(int, time_str.split(":"))
        return date.replace(hour=h, minute=m, second=0, microsecond=0)

    def in_maintenance_window(self) -> bool:
        """Gibt True zurück, wenn der aktuelle Moment im Wartungsfenster liegt."""
        now = self._now()
        window_start = self._parse_time(self._config.mw_start, now)
        window_end = self._parse_time(self._config.mw_end, now)
        if not (window_start <= now < window_end):
            return False
        # Wochentag-Filter (leere Liste = alle Tage erlaubt)
        allowed_days = self._config.allowed_days
        if allowed_days:
            day_abbr = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][now.weekday()]
            if day_abbr not in allowed_days:
                return False
        return True

    def get_window_end(self) -> datetime:
        now = self._now()
        return self._parse_time(self._config.mw_end, now)

    def _today_str(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    def _load_schedule(self) -> None:
        """Lädt den Tagesplan aus der Datei oder erstellt einen neuen."""
        today = self._today_str()
        if os.path.exists(self._schedule_file):
            with open(self._schedule_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                self._today_schedule = data.get("schedule", {})
                return
        # Neuer Tag oder Datei fehlt → neuen Plan erstellen
        self._today_schedule = {}
        self._build_schedule()

    def _build_schedule(self) -> None:
        """Weist jedem Kino eine zufällige Startzeit im Wartungsfenster zu."""
        today = self._today_str()
        now = self._now()
        window_start = self._parse_time(self._config.mw_start, now)
        window_end = self._parse_time(self._config.mw_end, now)
        window_seconds = int((window_end - window_start).total_seconds())

        for cinema in self._config.cinemas:
            cid = cinema["id"]
            if cid not in self._today_schedule:
                offset = random.randint(0, max(0, window_seconds - 120))
                scheduled = window_start + timedelta(seconds=offset)
                self._today_schedule[cid] = scheduled.isoformat()

        self._save_schedule(today)

    def _save_schedule(self, today: str) -> None:
        data = {"date": today, "schedule": self._today_schedule}
        with open(self._schedule_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_scheduled_time(self, cinema_id: str) -> Optional[datetime]:
        raw = self._today_schedule.get(cinema_id)
        if raw is None:
            return None
        return datetime.fromisoformat(raw)

    def is_due(self, cinema_id: str) -> bool:
        """
        Gibt True zurück, wenn ein Kino jetzt bearbeitet werden soll.
        Bedingungen:
          1. Im Wartungsfenster
          2. Zufällige Startzeit erreicht
          3. Kein aktiver Retry in der Zukunft
          4. Noch nicht erfolgreich heute
        """
        if not self.in_maintenance_window():
            return False

        today = self._today_str()

        # Schon erfolgreich heute?
        if self._state.was_successful_today(cinema_id, today):
            return False

        # Status läuft gerade?
        if self._state.get_status(cinema_id) == Status.IN_PROGRESS:
            return False

        # Zufällige Startzeit erreicht?
        scheduled = self.get_scheduled_time(cinema_id)
        now = self._now()
        if scheduled is None or now < scheduled:
            return False

        # Aktiver Retry in der Zukunft?
        next_retry = self._state.get_next_retry_time(cinema_id)
        if next_retry is not None:
            # Zeitzonen-sicher vergleichen
            if next_retry.tzinfo is None:
                next_retry = self._tz.localize(next_retry)
            if now < next_retry:
                return False

        return True

    def get_cinemas_due(self) -> list[dict]:
        """Gibt die Liste der Kinos zurück, die jetzt bearbeitet werden sollen."""
        self._ensure_schedule_fresh()
        return [c for c in self._config.cinemas if self.is_due(c["id"])]

    def _ensure_schedule_fresh(self) -> None:
        """Stellt sicher, dass der Plan für heute aktuell ist."""
        today = self._today_str()
        if os.path.exists(self._schedule_file):
            with open(self._schedule_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") != today:
                self._today_schedule = {}
                self._build_schedule()

    def next_retry_time(self, from_time: Optional[datetime] = None) -> datetime:
        """Berechnet den nächsten Retry-Zeitpunkt (from_time + retry_interval)."""
        if from_time is None:
            from_time = self._now()
        return from_time + timedelta(minutes=self._config.retry_interval_minutes)

    def is_within_window(self, dt: datetime) -> bool:
        """Prüft, ob ein Zeitpunkt im aktuellen Wartungsfenster liegt (Start UND Ende)."""
        now = self._now()
        window_start = self._parse_time(self._config.mw_start, now)
        window_end = self._parse_time(self._config.mw_end, now)
        if dt.tzinfo is None:
            dt = self._tz.localize(dt)
        if not (window_start <= dt < window_end):
            return False
        # Wochentag-Filter
        allowed_days = self._config.allowed_days
        if allowed_days:
            day_abbr = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dt.weekday()]
            if day_abbr not in allowed_days:
                return False
        return True

    def summary(self) -> str:
        """Gibt eine lesbare Übersicht des heutigen Plans aus."""
        lines = ["📅 Heutiger Reboot-Plan:"]
        for cinema in self._config.cinemas:
            cid = cinema["id"]
            name = cinema["name"]
            t = self.get_scheduled_time(cid)
            t_str = t.strftime("%H:%M:%S") if t else "?"
            status = self._state.get_status(cid)
            lines.append(f"  {name}: geplant {t_str}, Status: {status}")
        return "\n".join(lines)
