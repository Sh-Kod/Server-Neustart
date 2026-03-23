"""
Konfiguration für den Lampen-Monitor.
Liest aus derselben config.yaml wie das Reboot-Modul.
Völlig unabhängig von cinema_reboot.config – keine gemeinsamen Klassen.
"""
import yaml


class LampConfig:
    def __init__(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        pm = raw.get("projector_monitor", {})

        self.enabled              = pm.get("enabled", True)
        self.check_time           = pm.get("check_time", "20:00")
        self.warn_percent         = float(pm.get("warn_percent", 145))
        self.critical_percent     = float(pm.get("critical_percent", 150))
        self.snmp_community       = pm.get("snmp_community", "public")
        self.snmp_port            = int(pm.get("snmp_port", 161))
        self.snmp_timeout         = int(pm.get("snmp_timeout", 5))
        self.state_file           = pm.get("state_file", "lamp_state.json")

        # Zeitzone aus maintenance_window
        mw = raw.get("maintenance_window", {})
        self.timezone = mw.get("timezone", "Europe/Berlin")

        # Telegram (selber Bot/Chat wie Reboot)
        tg = raw.get("telegram", {})
        self.telegram_bot_token = tg.get("bot_token", "")
        self.telegram_chat_id   = tg.get("chat_id", "")
        self.telegram_enabled   = tg.get("enabled", False)

        # Projektoren: nur Kinos mit projector_ip Eintrag
        cinemas = raw.get("cinemas", [])
        self.projectors = [
            {
                "id":           c["id"],
                "name":         c["name"],
                "projector_ip": c["projector_ip"],
            }
            for c in cinemas
            if c.get("enabled", True) and c.get("projector_ip")
        ]
