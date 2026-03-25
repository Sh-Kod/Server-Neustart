"""
State-Manager – persistiert den Status jedes Kinos in einer JSON-Datei.

Jeder Kino-Eintrag enthält:
  - last_success_date  : "YYYY-MM-DD" oder null
  - next_retry_time    : ISO-8601-Zeitstempel oder null
  - last_error         : Fehlerbeschreibung oder null
  - status             : idle | success | blocked_by_playback |
                         blocked_by_transfer | error | offline | ui_unclear
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional



# Alle möglichen Status-Werte
class Status:
    IDLE = "idle"
    SUCCESS = "success"
    BLOCKED_BY_PLAYBACK = "blocked_by_playback"
    BLOCKED_BY_TRANSFER = "blocked_by_transfer"
    ERROR = "error"
    OFFLINE = "offline"
    UI_UNCLEAR = "ui_unclear"
    IN_PROGRESS = "in_progress"


class StateManager:
    """Liest und schreibt den persistenten Zustand aller Kinos.
    Thread-safe: alle Methoden sind mit einem Lock geschützt."""

    def __init__(self, state_file: str):
        self._path = os.path.abspath(state_file)
        self._state: dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        else:
            self._state = {}

    def _save(self) -> None:
        """Schreibt den State in die Datei. Muss mit gehaltenem Lock aufgerufen werden."""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)

    def _get_cinema(self, cinema_id: str) -> dict:
        """Gibt den Eintrag für ein Kino zurück. Muss mit gehaltenem Lock aufgerufen werden."""
        if cinema_id not in self._state:
            self._state[cinema_id] = {
                "last_success_date": None,
                "last_reboot_at":    None,   # ISO-Datetime des letzten erfolgreichen Reboots
                "last_attempt_at":   None,   # ISO-Datetime des letzten Versuchs (inkl. Fehler)
                "attempt_count":     0,       # Anzahl Versuche heute
                "last_reset_date": None,
                "next_retry_time": None,
                "last_error": None,
                "status": Status.IDLE,
            }
        return self._state[cinema_id]

    def get_status(self, cinema_id: str) -> str:
        with self._lock:
            return self._get_cinema(cinema_id)["status"]

    def get_last_success_date(self, cinema_id: str) -> Optional[str]:
        with self._lock:
            return self._get_cinema(cinema_id)["last_success_date"]

    def get_next_retry_time(self, cinema_id: str) -> Optional[datetime]:
        with self._lock:
            raw = self._get_cinema(cinema_id).get("next_retry_time")
            if raw is None:
                return None
            return datetime.fromisoformat(raw)

    def was_successful_today(self, cinema_id: str, today: str) -> bool:
        """Gibt True zurück, wenn das Kino heute bereits erfolgreich rebootet wurde."""
        with self._lock:
            entry = self._get_cinema(cinema_id)
            return (
                entry["status"] == Status.SUCCESS
                and entry["last_success_date"] == today
            )

    def get_last_reboot_at(self, cinema_id: str) -> Optional[str]:
        with self._lock:
            return self._get_cinema(cinema_id).get("last_reboot_at")

    def get_last_attempt_at(self, cinema_id: str) -> Optional[str]:
        with self._lock:
            return self._get_cinema(cinema_id).get("last_attempt_at")

    def get_attempt_count(self, cinema_id: str) -> int:
        with self._lock:
            return self._get_cinema(cinema_id).get("attempt_count", 0)

    def record_attempt(self, cinema_id: str, at_time: datetime) -> None:
        """Zählt einen Reboot-Versuch (wird vor jedem Run aufgerufen)."""
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["attempt_count"] = entry.get("attempt_count", 0) + 1
            entry["last_attempt_at"] = at_time.isoformat()
            self._save()

    def set_success(self, cinema_id: str, today: str, at_time: Optional[datetime] = None) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.SUCCESS
            entry["last_success_date"] = today
            entry["last_reboot_at"] = (at_time or datetime.now()).isoformat()
            entry["next_retry_time"] = None
            entry["last_error"] = None
            self._save()

    def set_blocked_by_playback(self, cinema_id: str, next_retry: Optional[datetime]) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.BLOCKED_BY_PLAYBACK
            entry["next_retry_time"] = next_retry.isoformat() if next_retry else None
            entry["last_error"] = "Playback läuft – Reboot abgebrochen"
            self._save()

    def set_blocked_by_transfer(self, cinema_id: str, next_retry: Optional[datetime]) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.BLOCKED_BY_TRANSFER
            entry["next_retry_time"] = next_retry.isoformat() if next_retry else None
            entry["last_error"] = "Transfer/Ingest/Export aktiv – Reboot abgebrochen"
            self._save()

    def set_offline(self, cinema_id: str, next_retry: Optional[datetime]) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.OFFLINE
            entry["next_retry_time"] = next_retry.isoformat() if next_retry else None
            entry["last_error"] = "Server nicht erreichbar"
            self._save()

    def set_ui_unclear(self, cinema_id: str, next_retry: Optional[datetime], detail: str = "") -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.UI_UNCLEAR
            entry["next_retry_time"] = next_retry.isoformat() if next_retry else None
            entry["last_error"] = f"UI-Zustand unklar – konservativ abgebrochen. {detail}"
            self._save()

    def set_error(self, cinema_id: str, next_retry: Optional[datetime], error: str) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.ERROR
            entry["next_retry_time"] = next_retry.isoformat() if next_retry else None
            entry["last_error"] = error
            self._save()

    def set_in_progress(self, cinema_id: str) -> None:
        with self._lock:
            entry = self._get_cinema(cinema_id)
            entry["status"] = Status.IN_PROGRESS
            self._save()

    def reset_for_new_day(self, cinema_id: str, today: str) -> None:
        """Setzt den Status zurück, wenn ein neuer Tag begonnen hat.

        Wird in jeder Loop-Iteration aufgerufen. last_reset_date stellt sicher,
        dass der Reset pro Tag nur einmal passiert – damit laufende Retries
        nicht bei jedem Zyklus gelöscht werden.
        """
        with self._lock:
            entry = self._get_cinema(cinema_id)

            # Heute bereits zurückgesetzt?
            if entry.get("last_reset_date") == today:
                return

            status = entry["status"]

            # Laufenden Prozess nicht unterbrechen
            if status == Status.IN_PROGRESS:
                return

            # Heute bereits erfolgreich – nichts tun
            if status == Status.SUCCESS and entry.get("last_success_date") == today:
                return

            # Neuer Tag → alle tagesbezogenen Felder zurücksetzen
            entry["status"] = Status.IDLE
            entry["next_retry_time"] = None
            entry["last_error"] = None
            entry["attempt_count"] = 0
            entry["last_attempt_at"] = None
            entry["last_reset_date"] = today
            self._save()

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._state)
