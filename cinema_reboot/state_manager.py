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
from datetime import datetime, timezone
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
    """Liest und schreibt den persistenten Zustand aller Kinos."""

    def __init__(self, state_file: str):
        self._path = os.path.abspath(state_file)
        self._state: dict = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        else:
            self._state = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)

    def _get_cinema(self, cinema_id: str) -> dict:
        if cinema_id not in self._state:
            self._state[cinema_id] = {
                "last_success_date": None,
                "next_retry_time": None,
                "last_error": None,
                "status": Status.IDLE,
            }
        return self._state[cinema_id]

    def get_status(self, cinema_id: str) -> str:
        return self._get_cinema(cinema_id)["status"]

    def get_last_success_date(self, cinema_id: str) -> Optional[str]:
        return self._get_cinema(cinema_id)["last_success_date"]

    def get_next_retry_time(self, cinema_id: str) -> Optional[datetime]:
        raw = self._get_cinema(cinema_id).get("next_retry_time")
        if raw is None:
            return None
        return datetime.fromisoformat(raw)

    def was_successful_today(self, cinema_id: str, today: str) -> bool:
        """Gibt True zurück, wenn das Kino heute bereits erfolgreich rebootet wurde."""
        entry = self._get_cinema(cinema_id)
        return (
            entry["status"] == Status.SUCCESS
            and entry["last_success_date"] == today
        )

    def set_success(self, cinema_id: str, today: str) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.SUCCESS
        entry["last_success_date"] = today
        entry["next_retry_time"] = None
        entry["last_error"] = None
        self._save()

    def set_blocked_by_playback(self, cinema_id: str, next_retry: datetime) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.BLOCKED_BY_PLAYBACK
        entry["next_retry_time"] = next_retry.isoformat()
        entry["last_error"] = "Playback läuft – Reboot abgebrochen"
        self._save()

    def set_blocked_by_transfer(self, cinema_id: str, next_retry: datetime) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.BLOCKED_BY_TRANSFER
        entry["next_retry_time"] = next_retry.isoformat()
        entry["last_error"] = "Transfer/Ingest/Export aktiv – Reboot abgebrochen"
        self._save()

    def set_offline(self, cinema_id: str, next_retry: datetime) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.OFFLINE
        entry["next_retry_time"] = next_retry.isoformat()
        entry["last_error"] = "Server nicht erreichbar"
        self._save()

    def set_ui_unclear(self, cinema_id: str, next_retry: datetime, detail: str = "") -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.UI_UNCLEAR
        entry["next_retry_time"] = next_retry.isoformat()
        entry["last_error"] = f"UI-Zustand unklar – konservativ abgebrochen. {detail}"
        self._save()

    def set_error(self, cinema_id: str, next_retry: datetime, error: str) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.ERROR
        entry["next_retry_time"] = next_retry.isoformat()
        entry["last_error"] = error
        self._save()

    def set_in_progress(self, cinema_id: str) -> None:
        entry = self._get_cinema(cinema_id)
        entry["status"] = Status.IN_PROGRESS
        self._save()

    def reset_for_new_day(self, cinema_id: str, today: str) -> None:
        """Setzt den Status zurück, wenn ein neuer Tag begonnen hat."""
        entry = self._get_cinema(cinema_id)
        last_success = entry.get("last_success_date")
        if last_success != today and entry["status"] == Status.SUCCESS:
            # Neuer Tag → zurücksetzen
            entry["status"] = Status.IDLE
            entry["next_retry_time"] = None
            entry["last_error"] = None
            self._save()

    def get_all(self) -> dict:
        return dict(self._state)
