"""
Temperatur-Schwellwert-Verwaltung pro Projektor.
Gespeichert in temp_thresholds.json, editierbar via Telegram.
Standard: 70°C für alle Projektoren.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD_C = 70.0
_STATE_FILE = "temp_thresholds.json"


class TempThresholds:
    def __init__(self, state_file: str = _STATE_FILE):
        self._file = os.path.abspath(state_file)
        self._data: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._file):
            try:
                with open(self._file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.warning(f"[TEMP] Schwellwert-Datei nicht lesbar: {e}")
                self._data = {}

    def _save(self) -> None:
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[TEMP] Schwellwert-Datei nicht schreibbar: {e}")

    def get(self, cinema_id: str) -> float:
        """Gibt den Temperatur-Schwellwert für ein Kino zurück (Standard: 70°C)."""
        return float(self._data.get(cinema_id, _DEFAULT_THRESHOLD_C))

    def set(self, cinema_id: str, threshold_c: float) -> None:
        """Setzt den Temperatur-Schwellwert für ein Kino und speichert."""
        self._data[cinema_id] = round(float(threshold_c), 1)
        self._save()
        logger.info(f"[TEMP] Schwellwert {cinema_id}: {threshold_c}°C")

    def get_all(self) -> dict[str, float]:
        return dict(self._data)
