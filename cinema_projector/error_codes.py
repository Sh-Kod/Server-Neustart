"""
Fehlercode-Datenbank für Barco DP2K und Christie CP4435-RGB Projektoren.

Barco:
  Die Status-Antwort liefert 32-Bit-Bitmask-Felder (notifications / warnings / errors).
  Jedes Bit entspricht einem bestimmten Zustand. Die Tabelle basiert auf TDE4313 und
  öffentlich dokumentierten Barco-Fehlercodes.

Christie:
  Die StatusItems XML enthält lesbare Namen und Werte je Komponente.
  Diese werden direkt weitergegeben (kein Lookup nötig).
"""

# ── Barco DP2K Bitmask-Tabellen ──────────────────────────────────────────────
# Format: Bit-Position → (Kurzname, Beschreibung)
# Quelle: Barco TDE4313 (RS232/TCP Commands for DP Series) + Barco SNMP White Paper

BARCO_NOTIFICATIONS: dict[int, tuple[str, str]] = {
    # Bit : (code, beschreibung)
    0:  ("LAMP_PCT",    "Lampenstunden-Schwellwert überschritten"),
    1:  ("CLO_MODE",    "CLO-Modus aktiv (Constant Light Output)"),
    2:  ("COLOR_CAL",   "Farbkalibrierung aktiv"),
    3:  ("ALT_GAMUT",   "Alternativer Farbbereich aktiv"),
    4:  ("LAMP_NEW",    "Neue Lampe erkannt (Zähler zurückgesetzt)"),
    5:  ("LENS_CAL",    "Linsenposition kalibriert"),
    8:  ("ICP_CONN",    "ICP-Verbindung aktiv"),
    9:  ("ICP_CFG",     "ICP-Konfigurationsänderung"),
    16: ("TEST_PAT",    "Testbild aktiv"),
    17: ("DOUSER_OFF",  "Douser/Shutter geschlossen"),
    24: ("LAMP_AGE",    "Lampenalterungskorrektur aktiv"),
    25: ("PWR_DEV",     "Lampenleistungsabweichung (Notification)"),
    26: ("COOL_FAN",    "Kühlluft-Modus aktiv"),
    27: ("SEC_LAMP",    "Sekundäre Lampenreferenz"),
}

BARCO_WARNINGS: dict[int, tuple[str, str]] = {
    0:  ("LAMP_LIFE",   "Lampenstunden Warnung (≥80% Lebensdauer)"),
    1:  ("LAMP_TEMP",   "Lampentemperatur Warnung"),
    2:  ("CASE_TEMP",   "Gehäusetemperatur Warnung"),
    3:  ("LPS_TEMP",    "LPS-Temperatur Warnung"),
    4:  ("LAMP_PWR",    "Lampenleistungsabweichung >5%"),
    5:  ("FAN_SLOW",    "Lüfterdrehzahl unter Sollwert"),
    6:  ("VOLT_LOW",    "Versorgungsspannung zu niedrig"),
    7:  ("VOLT_HIGH",   "Versorgungsspannung zu hoch"),
    8:  ("LAMP_IGN",    "Lampenzündung verzögert"),
    9:  ("ICP_WARN",    "ICP-Verbindungswarnung"),
    16: ("FILTER_DUST", "Luftfilter verschmutzt"),
    17: ("LPS_COMM",    "LPS-Kommunikationswarnung"),
}

BARCO_ERRORS: dict[int, tuple[str, str]] = {
    0:  ("LAMP_FAIL",   "Lampenfehler / Lampe nicht gezündet"),
    1:  ("LAMP_TEMP_C", "Lampentemperatur kritisch"),
    2:  ("CASE_TEMP_C", "Gehäusetemperatur kritisch"),
    3:  ("FAN_FAIL",    "Lüfterausfall"),
    4:  ("VOLT_CRIT",   "Spannung außerhalb Bereich"),
    5:  ("LPS_FAIL",    "LPS-Fehler (Netzteil)"),
    6:  ("ICP_FAIL",    "ICP-Kommunikationsfehler"),
    7:  ("LVPS_FAIL",   "LVPS-Fehler (Niederspannung)"),
    8:  ("LAMP_ARC",    "Lichtbogen-Fehler"),
    9:  ("LENS_FAIL",   "Linsenmotor-Fehler"),
    10: ("MIRROR_FAIL", "Spiegel/DMD-Fehler"),
    11: ("COLOR_FAIL",  "Farbrad-Fehler"),
    12: ("ICP_DATA",    "ICP-Datenfehler"),
    13: ("LPS_COMM_E",  "LPS-Kommunikationsfehler"),
    14: ("INTERLOCK",   "Sicherheitsverriegelung ausgelöst"),
    15: ("TEMP_SHUTDN", "Temperatur-Notabschaltung"),
}


def decode_barco_bitmask(
    value: int,
    table: dict[int, tuple[str, str]],
    max_bits: int = 32,
) -> list[str]:
    """
    Dekodiert einen Barco-Bitmask-Wert anhand der Tabelle.
    Gibt eine Liste von Beschreibungsstrings zurück.
    Unbekannte Bits werden als "Bit N (0xXXXXXXXX)" ausgegeben.
    """
    if value == 0:
        return []
    results = []
    for bit in range(max_bits):
        if not (value & (1 << bit)):
            continue
        if bit in table:
            code, desc = table[bit]
            results.append(f"{code}: {desc}")
        else:
            results.append(f"Bit {bit} (0x{1 << bit:08X}) – unbekannter Code")
    return results


def decode_barco_notifications(value: int) -> list[str]:
    return decode_barco_bitmask(value, BARCO_NOTIFICATIONS)


def decode_barco_warnings(value: int) -> list[str]:
    return decode_barco_bitmask(value, BARCO_WARNINGS)


def decode_barco_errors(value: int) -> list[str]:
    return decode_barco_bitmask(value, BARCO_ERRORS)


def build_barco_error_details(
    notifications: int,
    warnings: int,
    errors: int,
) -> list[str]:
    """
    Erstellt eine vollständige Fehlerliste aus allen drei Bitmask-Feldern.
    Fehler zuerst, dann Warnungen, dann Meldungen.
    """
    details: list[str] = []
    for desc in decode_barco_errors(errors):
        details.append(f"🔴 {desc}")
    for desc in decode_barco_warnings(warnings):
        details.append(f"🟡 {desc}")
    for desc in decode_barco_notifications(notifications):
        details.append(f"🔵 {desc}")
    return details
