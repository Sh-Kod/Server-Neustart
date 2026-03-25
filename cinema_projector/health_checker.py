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


def _build_status_request() -> bytes:
    """Baut das Status-Abfrage-Paket zusammen."""
    cs = _checksum(_ADDR, _STATUS_CMD)
    return bytes([_START, _ADDR] + _STATUS_CMD + [cs, _STOP])


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
    raw_response:  str = field(default="", repr=False)  # für Debugging


def _parse_counts(data: bytes) -> tuple:
    """
    Wertet die Status-Antwort aus.
    Erwartet: \xfe \x00 \x81 \x04 \x17 [notif 4B] [warn 4B] [error 4B] [chksum] \xff
    Gibt (notification_count, warning_count, error_count) oder None bei Fehler zurück.
    """
    if len(data) < 2:
        logger.debug(f"Barco Gesundheit: Antwort zu kurz ({len(data)} Bytes): {data.hex()}")
        return None

    if data[0] != _START or data[-1] != _STOP:
        logger.debug(f"Barco Gesundheit: fehlendes Start/Stop-Byte: {data.hex()}")
        return None

    # Erwartete Mindestlänge: start(1) + addr(1) + cmd(3) + data(12) + chksum(1) + stop(1) = 19
    if len(data) < 19:
        logger.debug(f"Barco Gesundheit: Antwort zu kurz ({len(data)} Bytes, erwartet ≥19): {data.hex()}")
        return None

    # Cmd-Bytes prüfen (Positionen 2, 3, 4)
    if data[2] != _STATUS_CMD[0] or data[3] != _STATUS_CMD[1] or data[4] != _STATUS_CMD[2]:
        logger.debug(f"Barco Gesundheit: falsche Cmd-Bytes: {data.hex()}")
        return None

    # Daten-Bytes lesen (12 Bytes ab Position 5, 3 × 4 Bytes Little-Endian)
    payload = data[5:17]
    if len(payload) < 12:
        logger.debug(f"Barco Gesundheit: Payload zu kurz: {data.hex()}")
        return None

    try:
        notifications = struct.unpack_from("<I", payload, 0)[0]
        warnings      = struct.unpack_from("<I", payload, 4)[0]
        errors        = struct.unpack_from("<I", payload, 8)[0]
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
) -> HealthResult:
    """
    Fragt den Gesundheitsstatus des Barco Projektors ab.

    Gibt GREEN / BLUE / YELLOW / RED zurück.
    RED = sofortiger Alarm erforderlich (nicht erreichbar ODER Fehler > 0).
    """
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

            # Antwort lesen (19 Bytes: start+addr+3cmd+12data+chksum+stop)
            response = _recv_exact(sock, 19, timeout)
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

    return HealthResult(
        cinema_id=cinema_id, cinema_name=cinema_name,
        reachable=True, color=color,
        notifications=notifications, warnings=warnings, errors=errors,
        raw_response=response.hex(),
    )


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
