"""
Dialog-Manager – verwaltet mehrstufige Konversationszustände für Telegram.

Jeder Dialog-Schritt hat einen Zustand (State) und einen Kontext (Daten).
Wenn ein Nutzer mitten im Dialog "0" oder "/abbrechen" sendet, wird der Dialog
zurückgesetzt.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class DS(str, Enum):
    """Dialog States – alle möglichen Zustände."""
    IDLE = "idle"

    # Zeitplan-Dialog (Befehl 5)
    SCHEDULE_MENU = "schedule_menu"
    SCHEDULE_START = "schedule_start"
    SCHEDULE_END = "schedule_end"
    SCHEDULE_DAYS = "schedule_days"
    SCHEDULE_CONFIRM = "schedule_confirm"

    # Server-Konfiguration (Befehl 6)
    SERVER_MENU = "server_menu"
    SERVER_SELECT_EDIT = "server_select_edit"
    SERVER_EDIT_FIELD = "server_edit_field"
    SERVER_EDIT_VALUE = "server_edit_value"
    SERVER_EDIT_CONFIRM = "server_edit_confirm"
    SERVER_ADD_ID = "server_add_id"
    SERVER_ADD_NAME = "server_add_name"
    SERVER_ADD_IP = "server_add_ip"
    SERVER_ADD_TYPE = "server_add_type"
    SERVER_ADD_CONFIRM = "server_add_confirm"
    SERVER_DISABLE_SELECT = "server_disable_select"
    SERVER_DISABLE_CONFIRM = "server_disable_confirm"

    # Zugangsdaten (Befehl 7)
    CREDS_USERNAME = "creds_username"
    CREDS_PASSWORD = "creds_password"
    CREDS_CONFIRM = "creds_confirm"

    # Herunterfahren
    SHUTDOWN_CONFIRM = "shutdown_confirm"


@dataclass
class DialogContext:
    """Aktueller Dialog-Zustand mit gespeicherten Zwischenwerten."""
    state: DS = DS.IDLE
    data: Dict[str, Any] = field(default_factory=dict)


# Befehle die einen laufenden Dialog sofort abbrechen
CANCEL_TRIGGERS = {"0", "/abbrechen", "/cancel", "/stop", "/exit"}


class DialogManager:
    """
    Einfache Zustandsmaschine für mehrstufige Telegram-Dialoge.

    Verwendung:
      dm = DialogManager()
      dm.start(DS.SCHEDULE_MENU)
      dm.set("new_start", "04:00")
      dm.next(DS.SCHEDULE_CONFIRM)
      dm.reset()  # Bei Abbruch oder nach Fertigstellung
    """

    def __init__(self):
        self._ctx = DialogContext()

    @property
    def state(self) -> DS:
        return self._ctx.state

    @property
    def is_idle(self) -> bool:
        return self._ctx.state == DS.IDLE

    def start(self, state: DS, **initial_data) -> None:
        """Startet einen neuen Dialog."""
        self._ctx = DialogContext(state=state, data=dict(initial_data))

    def next(self, state: DS) -> None:
        """Wechselt zum nächsten Schritt im selben Dialog."""
        self._ctx.state = state

    def set(self, key: str, value: Any) -> None:
        """Speichert einen Wert im Dialog-Kontext."""
        self._ctx.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Liest einen gespeicherten Wert aus dem Kontext."""
        return self._ctx.data.get(key, default)

    def reset(self) -> None:
        """Setzt den Dialog zurück (Abbruch oder Fertigstellung)."""
        self._ctx = DialogContext()

    def is_cancel(self, text: str) -> bool:
        """Gibt True zurück, wenn der Nutzer den Dialog abbrechen will."""
        return text.strip().lower() in CANCEL_TRIGGERS

    def all_data(self) -> Dict[str, Any]:
        return dict(self._ctx.data)
