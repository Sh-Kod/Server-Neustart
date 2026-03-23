"""
Speichert wann zuletzt geprüft wurde – verhindert mehrfache Meldungen pro Tag.
"""
import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


class LampState:
    def __init__(self, state_file: str):
        self._file = state_file
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self._file):
            try:
                with open(self._file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[LAMPE] State-Datei lesen fehlgeschlagen: {e}")
        return {}

    def _save(self) -> None:
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.warning(f"[LAMPE] State-Datei schreiben fehlgeschlagen: {e}")

    def was_checked_today(self) -> bool:
        return self._data.get("last_check_date") == date.today().isoformat()

    def mark_checked(self) -> None:
        self._data["last_check_date"] = date.today().isoformat()
        self._save()
