"""
Gesundheits-Check für Barco Projektoren (Stage 1).

Protokoll: Barco DP Series – TCP/IP Binary Protocol (TDE4313)
  Paket-Aufbau: \xfe [Adresse] [Cmd-Bytes] [Daten] [Checksum] \xff
  Adresse Ethernet: \x00

Status-Abfrage (Cmd \x81\x04\x17):
  Senden:  \xfe \x00 \x81 \x04 \x17 \x9c \xff
  ACK:     \xfe \x00 \x00 \x06 \x06 \xff
  Antwort: \xfe \x00 \x81 \x04 \x17 [notif 4B][warn 4B][error 4B] [chksum] \xff

Farb-Zustände:
  GREEN   – verbunden, keine Meldungen
  BLUE    – Benachrichtigungen (notification_count > 0, kein Fehler/Warnung)
  YELLOW  – Warnungen (warning_count > 0, kein Fehler)
  RED     – verbunden, error_count > 0 → sofortiger Telegram-Alarm!
  OFFLINE – TCP nicht erreichbar (kein Strom oder Netzfehler) → kein Alarm wenn vorher auch offline
"""
import logging
import socket
import struct
from dataclasses import dataclass, field

from .error_codes import build_barco_error_details

logger = logging.getLogger(__name__)


class HealthColor:
    GREEN   = "green"
    BLUE    = "blue"
    YELLOW  = "yellow"
    RED     = "red"
    OFFLINE = "offline"   # Kein Strom / nicht erreichbar – kein echter Fehler


# Barco Protokoll-Konstanten
_START    = 0xFE
_STOP     = 0xFF
_ADDR     = 0x00
_ACK_CMD0 = 0x00
_ACK_CMD1 = 0x06

# Status-Abfrage-Befehl (3 Bytes)
_STATUS_CMD = [0x81, 0x04, 0x17]

_DEFAULT_PORT    = 43728
_DEFAULT_TIMEOUT = 5


def _checksum(address: int, cmd_bytes: list, data_bytes: list = None) -> int:
    """Barco-Checksum: (Adresse + Cmd-Bytes + Daten-Bytes) mod 256."""
    if data_bytes is None:
        data_bytes = []
    return (address + sum(cmd_bytes) + sum(data_bytes)) % 256


def _escape(payload: bytes) -> bytes:
    """Barco Byte-Stuffing: maskiert 0x80/0xFE/0xFF im Payload."""
    out = []
    for b in payload:
        if b == 0x80:
            out += [0x80, 0x00]
        elif b == 0xFE:
            out += [0x80, 0x7E]
        elif b == 0xFF:
            out += [0x80, 0x7F]
        else:
            out.append(b)
    return bytes(out)


def _unescape(payload: bytes) -> bytes:
    """Barco Byte-Stuffing: demaskiert Escape-Sequenzen im empfangenen Payload."""
    out = []
    i = 0
    while i < len(payload):
        b = payload[i]
        if b == 0x80 and i + 1 < len(payload):
            nxt = payload[i + 1]
            out.append({0x00: 0x80, 0x7E: 0xFE, 0x7F: 0xFF}.get(nxt, nxt))
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def _build_status_request() -> bytes:
    """Baut das Status-Abfrage-Paket mit korrekt escaptem Payload zusammen."""
    cs = _checksum(_ADDR, _STATUS_CMD)
    payload = bytes([_ADDR] + _STATUS_CMD + [cs])
    return bytes([_START]) + _escape(payload) + bytes([_STOP])


@dataclass
class HealthResult:
    cinema_id:     str
    cinema_name:   str
    reachable:     bool
    color:         str          # green / blue / yellow / red
    notifications: int = 0
    warnings:      int = 0
    errors:        int = 0
    error_msg:     str = ""
    error_details: list = field(default_factory=list)  # dekodierte Fehlertexte
    temperature_c: float = -1.0                        # Temperatur in °C, -1 = unbekannt
    lamp_on:       object = None                       # True=AN, False=AUS, None=unbekannt
    raw_response:  str = field(default="", repr=False)  # für Debugging


def _parse_counts(data: bytes) -> tuple:
    """
    Wertet die Status-Antwort aus (nach Unescape).
    Gibt (notification_count, warning_count, error_count) oder None bei Fehler zurück.
    """
    if len(data) < 2:
        logger.debug(f"Barco Gesundheit: Antwort zu kurz ({len(data)} Bytes): {data.hex()}")
        return None

    if data[0] != _START or data[-1] != _STOP:
        logger.debug(f"Barco Gesundheit: fehlendes Start/Stop-Byte: {data.hex()}")
        return None

    # Payload demaskieren (alles zwischen Start- und Stop-Byte)
    inner = _unescape(data[1:-1])
    # Erwartet: addr(1) + cmd(3) + data(12) + chksum(1) = 17 Bytes
    if len(inner) < 17:
        logger.debug(f"Barco Gesundheit: innere Nutzlast zu kurz ({len(inner)} B): {inner.hex()}")
        return None

    if inner[1] != _STATUS_CMD[0] or inner[2] != _STATUS_CMD[1] or inner[3] != _STATUS_CMD[2]:
        logger.debug(f"Barco Gesundheit: falsche Cmd-Bytes: {inner.hex()}")
        return None

    # 3 × 4 Bytes ab Position 4, MSB-first (Big-Endian) laut Barco-Protokoll
    payload = inner[4:16]
    if len(payload) < 12:
        logger.debug(f"Barco Gesundheit: Payload zu kurz: {inner.hex()}")
        return None

    try:
        notifications = struct.unpack_from(">I", payload, 0)[0]
        warnings      = struct.unpack_from(">I", payload, 4)[0]
        errors        = struct.unpack_from(">I", payload, 8)[0]
    except struct.error as e:
        logger.debug(f"Barco Gesundheit: struct-Fehler: {e}")
        return None

    return notifications, warnings, errors


def check_health(
    cinema_id:      str,
    cinema_name:    str,
    projector_ip:   str,
    projector_port: int = _DEFAULT_PORT,
    timeout:        int = _DEFAULT_TIMEOUT,
    projector_type: str = "barco",
    snmp_temp_oid:  str = "",
    snmp_temp_div:  float = 1.0,
    snmp_community: str = "public",
    snmp_port:      int = 161,
) -> HealthResult:
    """
    Fragt den Gesundheitsstatus des Projektors ab.
    Unterstützt: barco (Binary TCP) und christie (WebSocket JSON-RPC).

    Gibt GREEN / BLUE / YELLOW / RED / OFFLINE zurück.
    """
    # Christie CineLife+ → separater Checker
    if projector_type.lower() == "christie":
        from .christie_checker import check_christie_health
        return check_christie_health(
            cinema_id=cinema_id,
            cinema_name=cinema_name,
            projector_ip=projector_ip,
            projector_port=projector_port if projector_port != _DEFAULT_PORT else 5004,
            timeout=timeout,
        )

    # Barco Binary Protocol (Standard)
    request = _build_status_request()
    logger.debug(
        f"[GESUNDHEIT] {cinema_name} ({projector_ip}:{projector_port}) – "
        f"Status-Abfrage: {request.hex()}"
    )

    try:
        with socket.create_connection((projector_ip, projector_port), timeout=timeout) as sock:
            sock.sendall(request)

            # ACK lesen (6 Bytes)
            ack = _recv_exact(sock, 6, timeout)
            if not ack or len(ack) < 6:
                logger.warning(
                    f"[GESUNDHEIT] {cinema_name}: ACK zu kurz oder leer: "
                    f"{ack.hex() if ack else 'leer'}"
                )
                return HealthResult(
                    cinema_id=cinema_id, cinema_name=cinema_name,
                    reachable=False, color=HealthColor.OFFLINE,
                    error_msg="ACK nicht empfangen",
                    raw_response=ack.hex() if ack else "",
                )

            if ack[2] != _ACK_CMD0 or ack[3] != _ACK_CMD1:
                logger.warning(f"[GESUNDHEIT] {cinema_name}: Ungültiges ACK: {ack.hex()}")
                return HealthResult(
                    cinema_id=cinema_id, cinema_name=cinema_name,
                    reachable=False, color=HealthColor.OFFLINE,
                    error_msg=f"Ungültiges ACK: {ack.hex()}",
                    raw_response=ack.hex(),
                )

            # Antwort lesen (variable Länge durch Escaping – lese bis Stop-Byte)
            response = _recv_frame(sock, timeout)
            logger.debug(f"[GESUNDHEIT] {cinema_name}: Antwort: {response.hex() if response else 'leer'}")

    except socket.timeout:
        logger.info(
            f"[GESUNDHEIT] {cinema_name}: ⬛ OFFLINE (Timeout – kein Strom oder Netzfehler)"
        )
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg="Timeout – Projektor nicht erreichbar",
        )
    except OSError as e:
        logger.info(
            f"[GESUNDHEIT] {cinema_name}: ⬛ OFFLINE ({e})"
        )
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg=f"Verbindungsfehler: {e}",
        )

    if not response:
        logger.warning(f"[GESUNDHEIT] {cinema_name}: Keine Antwort empfangen")
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg="Keine Antwort auf Status-Abfrage",
        )

    counts = _parse_counts(response)
    if counts is None:
        # Verbunden, aber Antwort nicht lesbar → als OFFLINE werten (Protokollfehler)
        logger.warning(
            f"[GESUNDHEIT] {cinema_name}: Antwort nicht auswertbar – {response.hex()}"
        )
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=True, color=HealthColor.OFFLINE,
            error_msg=f"Antwort nicht auswertbar: {response.hex()}",
            raw_response=response.hex(),
        )

    notifications, warnings, errors = counts
    logger.info(
        f"[GESUNDHEIT] {cinema_name}: "
        f"Meldungen={notifications} Warnungen={warnings} Fehler={errors}"
    )

    # Farbe bestimmen
    if errors > 0:
        color = HealthColor.RED
    elif warnings > 0:
        color = HealthColor.YELLOW
    elif notifications > 0:
        color = HealthColor.BLUE
    else:
        color = HealthColor.GREEN

    error_details = build_barco_error_details(notifications, warnings, errors)

    # Lampenstatus (separate kurze Verbindung – gleicher Port)
    lamp_on = _read_barco_lamp_status(projector_ip, projector_port, timeout)

    # Temperatur via SNMP (optional, nur wenn OID konfiguriert)
    temperature_c = -1.0
    if snmp_temp_oid:
        temperature_c = _read_barco_snmp_temp(
            projector_ip, snmp_temp_oid, snmp_temp_div,
            snmp_community, snmp_port, timeout,
        )

    return HealthResult(
        cinema_id=cinema_id, cinema_name=cinema_name,
        reachable=True, color=color,
        notifications=notifications, warnings=warnings, errors=errors,
        error_details=error_details,
        lamp_on=lamp_on,
        temperature_c=temperature_c,
        raw_response=response.hex(),
    )


def _read_barco_snmp_temp(
    ip: str,
    oid: str,
    divisor: float,
    community: str,
    port: int,
    timeout: int,
) -> float:
    """Liest Barco-Projektortemperatur via SNMP. Gibt °C zurück oder -1.0 bei Fehler."""
    try:
        from .snmp_client import snmp_get
        raw = snmp_get(ip, community, oid, port, timeout)
        if isinstance(raw, int):
            temp = raw / divisor if divisor != 1.0 else float(raw)
            logger.debug(f"[TEMP] {ip}: SNMP {oid} = {raw} → {temp:.1f}°C")
            return temp
    except Exception as e:
        logger.debug(f"[TEMP] {ip}: SNMP-Fehler ({oid}): {e}")
    return -1.0


def _read_barco_lamp_status(ip: str, port: int, timeout: int) -> object:
    """
    Liest den Barco-Lampenstatus via TCP (kurze 2. Verbindung).
    Gibt True (AN), False (AUS) oder None (nicht lesbar) zurück.
    """
    cs = _checksum(_ADDR, [0x76, 0x9A])
    payload = bytes([_ADDR, 0x76, 0x9A, cs])
    request = bytes([_START]) + _escape(payload) + bytes([_STOP])
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.sendall(request)
            ack = _recv_exact(sock, 6, timeout)
            if not ack or len(ack) < 4 or ack[2] != _ACK_CMD0 or ack[3] != _ACK_CMD1:
                return None
            resp = _recv_frame(sock, timeout)
            if resp and len(resp) >= 2 and resp[0] == _START and resp[-1] == _STOP:
                inner = _unescape(resp[1:-1])
                # inner: addr(1) + cmd0(1) + cmd1(1) + lamp_byte(1) + chksum(1)
                if len(inner) >= 4 and inner[1] == 0x76 and inner[2] == 0x9A:
                    if inner[3] == 0x01:
                        return True   # Lampe AN
                    if inner[3] == 0x00:
                        return False  # Lampe AUS
    except Exception:
        pass
    return None


def _recv_exact(sock: socket.socket, n: int, timeout: int) -> bytes:
    """Empfängt exakt n Bytes (oder so viele wie ankommen bis Timeout)."""
    buf = b""
    try:
        sock.settimeout(timeout)
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    return buf


def _recv_frame(sock: socket.socket, timeout: int) -> bytes:
    """Liest ein vollständiges Barco-Frame bis zum Stop-Byte 0xFF.
    Da 0xFF im Payload zu 0x80 0x7F escaped wird, markiert das erste
    echte 0xFF-Byte sicher das Frameende."""
    buf = b""
    sock.settimeout(timeout)
    try:
        while True:
            b = sock.recv(1)
            if not b:
                break
            buf += b
            if b == b"\xff":
                break
    except socket.timeout:
        pass
    return buf
