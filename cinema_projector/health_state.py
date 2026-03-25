"""
Persistiert den letzten bekannten Gesundheitsstatus jedes Projektors.
Speichert: Farbe, Zeitstempel, Zähler, Fehlerbeschreibung.
"""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class HealthState:
    def __init__(self, state_file: str):
        self._file = os.path.abspath(state_file)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._file):
            try:
                with open(self._file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.warning(f"[GESUNDHEIT] State lesen fehlgeschlagen: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        try:
            parent = os.path.dirname(self._file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[GESUNDHEIT] State schreiben fehlgeschlagen: {e}")

    def get_color(self, cinema_id: str) -> str:
        """Gibt den letzten bekannten Farbstatus zurück (default: 'unknown')."""
        return self._data.get(cinema_id, {}).get("color", "unknown")

    def get_entry(self, cinema_id: str) -> dict:
        return dict(self._data.get(cinema_id, {}))

    def get_all(self) -> dict:
        return dict(self._data)

    def update(
        self,
        cinema_id:     str,
        cinema_name:   str,
        color:         str,
        reachable:     bool,
        notifications: int = 0,
        warnings:      int = 0,
        errors:        int = 0,
        error_msg:     str = "",
    ) -> None:
        """Speichert den aktuellen Zustand mit Zeitstempel.
        'last_changed' wird nur aktualisiert, wenn sich die Farbe geändert hat.
        """
        now = datetime.now().isoformat(timespec="seconds")
        prev = self._data.get(cinema_id, {})
        prev_color = prev.get("color", "unknown")

        self._data[cinema_id] = {
            "name":          cinema_name,
            "color":         color,
            "reachable":     reachable,
            "notifications": notifications,
            "warnings":      warnings,
            "errors":        errors,
            "error_msg":     error_msg,
            "last_checked":  now,
            "last_changed":  now if prev_color != color else prev.get("last_changed", now),
        }
        self._save()
