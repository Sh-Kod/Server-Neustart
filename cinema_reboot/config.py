"""
Konfigurationsmodul – lädt und validiert config.yaml.
"""
import os
import yaml


class Config:
    """Lädt die Konfiguration aus einer YAML-Datei und stellt sie bereit."""

    def __init__(self, config_path: str = "config.yaml"):
        config_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Konfigurationsdatei nicht gefunden: {config_path}\n"
                "Bitte config.yaml im Programmordner anlegen."
            )
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._raw = raw
        self._validate(raw)

    def _validate(self, raw: dict) -> None:
        required_keys = ["cinemas", "credentials", "maintenance_window", "telegram", "settings"]
        for key in required_keys:
            if key not in raw:
                raise ValueError(f"Fehlender Pflichtschlüssel in config.yaml: '{key}'")

        if not raw["cinemas"]:
            raise ValueError("Keine Kinos in der Konfiguration definiert.")

        for cinema in raw["cinemas"]:
            for field in ["id", "name", "ip", "type"]:
                if field not in cinema:
                    raise ValueError(f"Kino-Eintrag fehlt Feld '{field}': {cinema}")
            if cinema["type"] not in ("doremi", "ims3000"):
                raise ValueError(
                    f"Unbekannter Kino-Typ '{cinema['type']}' für {cinema['id']}. "
                    "Erlaubt: 'doremi', 'ims3000'"
                )

    @property
    def cinemas(self) -> list[dict]:
        """Gibt nur aktivierte Kinos zurück."""
        return [c for c in self._raw["cinemas"] if c.get("enabled", True)]

    @property
    def credentials(self) -> dict:
        return self._raw["credentials"]

    @property
    def username(self) -> str:
        return self._raw["credentials"]["username"]

    @property
    def password(self) -> str:
        return self._raw["credentials"]["password"]

    @property
    def maintenance_window(self) -> dict:
        return self._raw["maintenance_window"]

    @property
    def mw_start(self) -> str:
        return self._raw["maintenance_window"]["start"]

    @property
    def mw_end(self) -> str:
        return self._raw["maintenance_window"]["end"]

    @property
    def timezone(self) -> str:
        return self._raw["maintenance_window"]["timezone"]

    @property
    def telegram(self) -> dict:
        return self._raw["telegram"]

    @property
    def telegram_enabled(self) -> bool:
        return self._raw["telegram"].get("enabled", False)

    @property
    def telegram_token(self) -> str:
        return self._raw["telegram"]["bot_token"]

    @property
    def telegram_chat_id(self) -> str:
        return str(self._raw["telegram"]["chat_id"])

    @property
    def settings(self) -> dict:
        return self._raw["settings"]

    def get_setting(self, key: str, default=None):
        return self._raw["settings"].get(key, default)

    @property
    def dry_run(self) -> bool:
        return self._raw["settings"].get("dry_run", True)

    @property
    def headless(self) -> bool:
        return self._raw["settings"].get("headless", True)

    @property
    def reboot_wait_minutes(self) -> int:
        return int(self._raw["settings"].get("reboot_wait_minutes", 10))

    @property
    def reboot_timeout_minutes(self) -> int:
        return int(self._raw["settings"].get("reboot_timeout_minutes", 20))

    @property
    def retry_interval_minutes(self) -> int:
        return int(self._raw["settings"].get("retry_interval_minutes", 60))

    @property
    def short_retry_interval_minutes(self) -> int:
        """Retry-Intervall (Minuten) in der letzten Stunde des Wartungsfensters."""
        return int(self._raw["settings"].get("short_retry_interval_minutes", 15))

    @property
    def short_retry_threshold_minutes(self) -> int:
        """Ab wie vielen verbleibenden Fenster-Minuten das kurze Intervall greift."""
        return int(self._raw["settings"].get("short_retry_threshold_minutes", 60))

    @property
    def group_size(self) -> int:
        """Anzahl Kinos pro Startgruppe (Gruppen-Reboot)."""
        return int(self._raw["settings"].get("group_size", 4))

    @property
    def group_interval_minutes(self) -> int:
        """Pausenzeit zwischen zwei Gruppen in Minuten."""
        return int(self._raw["settings"].get("group_interval_minutes", 2))

    @property
    def startup_wait_minutes(self) -> int:
        """Max. Wartezeit nach Reboot, bis Server hochgefahren sein muss (Minuten).
        Nach Ablauf → Sofort-Telegram-Alarm."""
        return int(self._raw["settings"].get(
            "startup_wait_minutes",
            self._raw["settings"].get("reboot_timeout_minutes", 15),
        ))

    @property
    def http_timeout_seconds(self) -> int:
        return int(self._raw["settings"].get("http_timeout_seconds", 10))

    @property
    def log_dir(self) -> str:
        return self._raw["settings"].get("log_dir", "logs")

    @property
    def state_file(self) -> str:
        return self._raw["settings"].get("state_file", "state.json")

    @property
    def main_loop_interval_seconds(self) -> int:
        return int(self._raw["settings"].get("main_loop_interval_seconds", 60))

    @property
    def parallel_reboot(self) -> bool:
        return self._raw["settings"].get("parallel_reboot", False)

    @property
    def local_alarm_enabled(self) -> bool:
        return self._raw["settings"].get("local_alarm_enabled", True)

    # ── Wartungsfenster: erlaubte Wochentage ─────────────────────────────────

    @property
    def allowed_days(self) -> list[str]:
        """Erlaubte Wochentage als Kurzliste (z.B. ['Mo','Di']).
        Leere Liste oder nicht gesetzt = alle Tage erlaubt."""
        return self._raw["maintenance_window"].get("allowed_days", []) or []

    @property
    def allowed_days_str(self) -> str:
        """Lesbare Darstellung, z.B. 'Mo, Di, Mi' oder 'Alle Tage'."""
        days = self.allowed_days
        return ", ".join(days) if days else "Alle Tage"

    # ── Telegram: mehrere autorisierte Chat-IDs ───────────────────────────────

    @property
    def telegram_admin_chat_ids(self) -> list[str]:
        """Liste autorisierter Chat-IDs. Leer → nur telegram_chat_id gilt."""
        raw = self._raw["telegram"].get("admin_chat_ids", []) or []
        return [str(x) for x in raw]
