"""
Barco Projektor – Lampenstatus lesen (NUR LESEN, kein Schalten!).

Protokoll: Barco DP Series – TCP/IP Binary Protocol (TDE4313)
  Paket-Aufbau: \xfe [Adresse] [Cmd-Bytes] [Daten] [Checksum] \xff
  Adresse Ethernet: \x00
  Checksum = (Adresse + Cmd-Bytes + Daten) mod 256
  TCP Port Series 2: 43728  (Standard)
  TCP Port Series 1: 43680

Lampe lesen (Cmd \x76\x9a):
  Senden:  \xfe \x00 \x76 \x9a \x10 \xff
  ACK:     \xfe \x00 \x00 \x06 \x06 \xff
  Antwort: \xfe \x00 \x76 \x9a [0x00=AUS / 0x01=AN] [Checksum] \xff

WICHTIG: Dieses Modul schaltet die Lampe NICHT.
         Es liest nur den Status und gibt True (AN) oder False (AUS) zurück.
"""
import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)

# Barco DP Binary Protokoll – Konstanten
_START  = 0xFE
_STOP   = 0xFF
_ACK_CMD0 = 0x00
_ACK_CMD1 = 0x06

# Lamp-Read-Befehl (kein Datenbyte notwendig)
_LAMP_READ_CMD0 = 0x76
_LAMP_READ_CMD1 = 0x9A

# Antwort-Datenbytes
_LAMP_OFF = 0x00
_LAMP_ON  = 0x01

_DEFAULT_PORT    = 43728   # Series 2
_DEFAULT_TIMEOUT = 5       # Sekunden


def _checksum(address: int, cmd_bytes: list[int], data_bytes: list[int] = []) -> int:
    """Barco-Checksum: (Adresse + Cmd-Bytes + Daten-Bytes) mod 256."""
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


def _build_lamp_read_request(address: int = 0x00) -> bytes:
    """Baut das Lamp-Read-Paket mit korrekt escaptem Payload zusammen."""
    cmd = [_LAMP_READ_CMD0, _LAMP_READ_CMD1]
    cs  = _checksum(address, cmd)
    payload = bytes([address] + cmd + [cs])
    return bytes([_START]) + _escape(payload) + bytes([_STOP])


def _parse_lamp_response(data: bytes) -> Optional[bool]:
    """
    Wertet die Lampen-Antwort aus (nach Unescape).
    Gibt True (Lampe AN), False (Lampe AUS) oder None bei Parse-Fehler zurück.
    """
    if len(data) < 2:
        logger.debug(f"Barco Lampen-Antwort zu kurz: {data.hex()}")
        return None
    if data[0] != _START or data[-1] != _STOP:
        logger.debug(f"Barco Antwort: fehlendes Start/Stop-Byte: {data.hex()}")
        return None
    inner = _unescape(data[1:-1])
    # inner: addr(1) + cmd0(1) + cmd1(1) + lamp_byte(1) + chksum(1)
    if len(inner) < 4:
        logger.debug(f"Barco Antwort: innerer Payload zu kurz: {inner.hex()}")
        return None
    if inner[1] != _LAMP_READ_CMD0 or inner[2] != _LAMP_READ_CMD1:
        logger.debug(f"Barco Antwort: unerwartete Cmd-Bytes: {inner.hex()}")
        return None
    lamp_byte = inner[3]
    if lamp_byte == _LAMP_ON:
        return True
    if lamp_byte == _LAMP_OFF:
        return False
    logger.debug(f"Barco Antwort: unbekannter Lampen-Status-Byte: {lamp_byte:#04x}")
    return None


def _recv_frame(sock, timeout: int) -> bytes:
    """Liest ein vollständiges Barco-Frame bis zum Stop-Byte 0xFF."""
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


def read_lamp_on(
    projector_ip: str,
    projector_port: int = _DEFAULT_PORT,
    timeout: int = _DEFAULT_TIMEOUT,
    address: int = 0x00,
) -> Optional[bool]:
    """
    Liest den Lampenstatus des Barco Projektors via TCP.

    Gibt zurück:
      True  → Lampe AN  (Vorstellung läuft vermutlich)
      False → Lampe AUS (kein Film)
      None  → Verbindungsfehler / Antwort nicht auswertbar (Projektor ggf. offline)

    WICHTIG: Schaltet die Lampe NICHT. Nur lesen!
    """
    request = _build_lamp_read_request(address)
    logger.debug(
        f"Barco Projektor {projector_ip}:{projector_port} – "
        f"Lamp-Read senden: {request.hex()}"
    )

    try:
        with socket.create_connection(
            (projector_ip, projector_port), timeout=timeout
        ) as sock:
            sock.sendall(request)

            # Zuerst ACK lesen (6 Bytes – ACK enthält keine Escape-Sequenzen)
            ack = sock.recv(6)
            logger.debug(f"Barco ACK empfangen: {ack.hex()}")

            if len(ack) < 6 or ack[2] != _ACK_CMD0 or ack[3] != _ACK_CMD1:
                logger.warning(
                    f"Barco Projektor {projector_ip}: "
                    f"Kein gültiges ACK erhalten: {ack.hex()}"
                )
                return None

            # Antwort lesen bis Stop-Byte (variable Länge durch Escaping)
            response = _recv_frame(sock, timeout)
            logger.debug(f"Barco Lampen-Antwort: {response.hex() if response else 'leer'}")

    except socket.timeout:
        logger.warning(
            f"Barco Projektor {projector_ip}:{projector_port} – "
            "Timeout beim Verbindungsaufbau."
        )
        return None
    except OSError as e:
        logger.warning(
            f"Barco Projektor {projector_ip}:{projector_port} – "
            f"Verbindungsfehler: {e}"
        )
        return None

    result = _parse_lamp_response(response)
    if result is True:
        logger.info(f"Barco Projektor {projector_ip}: Lampe AN 🔆")
    elif result is False:
        logger.info(f"Barco Projektor {projector_ip}: Lampe AUS ⬛")
    else:
        logger.warning(
            f"Barco Projektor {projector_ip}: Antwort nicht auswertbar – {response.hex()}"
        )
    return result
