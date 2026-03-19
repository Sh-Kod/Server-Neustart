"""
Config-Writer – liest config.yaml, ändert einen Wert und speichert zurück.

HINWEIS: Beim Speichern gehen Kommentare in der YAML-Datei verloren.
Das ist für Laufzeitänderungen via Telegram akzeptabel.
"""
import logging
import os
import shutil
from datetime import datetime
from typing import Any, List

import yaml

logger = logging.getLogger(__name__)


def _navigate(data: dict, key_path: List[str]) -> tuple[dict, str]:
    """Navigiert zu einem verschachtelten Schlüssel und gibt (parent, last_key) zurück."""
    node = data
    for key in key_path[:-1]:
        if key not in node:
            node[key] = {}
        node = node[key]
    return node, key_path[-1]


def update_config_value(config_path: str, key_path: List[str], value: Any) -> None:
    """
    Liest config.yaml, setzt einen verschachtelten Wert und speichert.

    Beispiel:
      update_config_value("config.yaml", ["maintenance_window", "start"], "04:00")
    """
    config_path = os.path.abspath(config_path)

    # Backup erstellen
    backup_path = config_path + ".bak"
    shutil.copy2(config_path, backup_path)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    parent, last_key = _navigate(data, key_path)
    old_value = parent.get(last_key, "<nicht vorhanden>")
    parent[last_key] = value

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(
        f"Config geändert: {'.'.join(key_path)} "
        f"'{old_value}' → '{value}' | Backup: {backup_path}"
    )


def add_cinema_to_config(config_path: str, cinema: dict) -> None:
    """Fügt einen neuen Kino-Eintrag zur config.yaml hinzu."""
    config_path = os.path.abspath(config_path)
    backup_path = config_path + ".bak"
    shutil.copy2(config_path, backup_path)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    data["cinemas"].append(cinema)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"Neues Kino hinzugefügt: {cinema}")


def update_cinema_in_config(config_path: str, cinema_id: str, field: str, value: Any) -> None:
    """Ändert ein Feld eines bestehenden Kino-Eintrags."""
    config_path = os.path.abspath(config_path)
    backup_path = config_path + ".bak"
    shutil.copy2(config_path, backup_path)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    found = False
    for cinema in data["cinemas"]:
        if cinema["id"] == cinema_id:
            old = cinema.get(field, "<nicht vorhanden>")
            cinema[field] = value
            found = True
            logger.info(f"Kino {cinema_id}: {field} '{old}' → '{value}'")
            break

    if not found:
        raise ValueError(f"Kino '{cinema_id}' nicht in config.yaml gefunden.")

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def update_credentials_in_config(config_path: str, username: str, password: str) -> None:
    """Ändert die globalen Zugangsdaten in config.yaml."""
    config_path = os.path.abspath(config_path)
    backup_path = config_path + ".bak"
    shutil.copy2(config_path, backup_path)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    data["credentials"]["username"] = username
    data["credentials"]["password"] = password  # Klartext – TELEGRAM-NACHRICHT DANACH LÖSCHEN!

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"Zugangsdaten geändert: username='{username}' (Passwort nicht geloggt)")
