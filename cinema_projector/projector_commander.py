"""
Projektor-Steuerungsbefehle für Barco DP2K und Christie CP4435-RGB.

WICHTIG:
  Alle Befehle erfordern eine explizite Bestätigung im Telegram-Menü,
  bevor sie ausgeführt werden. Die Cinema-ID wird bei jedem Schritt
  mitgeführt – ein falscher Zugriff auf einen anderen Saal ist nicht möglich.

Barco DP2K – TCP Binary Protocol (Port 43728):
  Douser/Shutter ÖFFNEN:  \xFE\x00\x22\x42\x00\x64\xFF  (bestätigt)
  Douser/Shutter SCHLIESSEN: \xFE\x00\x23\x42\x00\x65\xFF (bestätigt)
  Lampe EIN:  \xFE\x00\x28\x42\x01\x6B\xFF  (cmd 0x28, data 0x01)
  Lampe AUS:  \xFE\x00\x29\x42\x00\x6B\xFF  (cmd 0x29, data 0x00)

Christie CP4435-RGB – TCP ASCII (Port 3002):
  Laser EIN:  (LSR1)
  Laser AUS:  (LSR0)
  Douser AUF: (SHU1)
  Douser ZU:  (SHU0)
  Abfrage:    (LSR?), (SHU?)
"""
import logging
import socket
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_BARCO_DEFAULT_PORT   = 43728
_CHRISTIE_DEFAULT_PORT = 3002
_DEFAULT_TIMEOUT      = 8   # Sekunden


# ── Barco Protokoll-Konstanten ────────────────────────────────────────────────

_START = 0xFE
_STOP  = 0xFF
_ADDR  = 0x00


def _barco_checksum(address: int, cmd_bytes: list, data_bytes: list = None) -> int:
    if data_bytes is None:
        data_bytes = []
    return (address + sum(cmd_bytes) + sum(data_bytes)) % 256


# Barco Douser/Shutter – verifizierte Befehle (TDE4313 + Community-Quellen)
_CMD_DOUSER_OPEN  = bytes([_START, _ADDR, 0x22, 0x42, 0x00, 0x64, _STOP])
_CMD_DOUSER_CLOSE = bytes([_START, _ADDR, 0x23, 0x42, 0x00, 0x65, _STOP])

# Barco Lampe EIN/AUS – basierend auf Protokoll-Analyse (cmd 0x28/0x29, data 0x01/0x00)
_CMD_LAMP_ON  = bytes([
    _START, _ADDR, 0x28, 0x42, 0x01,
    _barco_checksum(_ADDR, [0x28, 0x42], [0x01]),
    _STOP,
])
_CMD_LAMP_OFF = bytes([
    _START, _ADDR, 0x29, 0x42, 0x00,
    _barco_checksum(_ADDR, [0x29, 0x42], [0x00]),
    _STOP,
])


@dataclass
class CommandResult:
    success:  bool
    message:  str
    raw_resp: str = ""


def _barco_send_command(
    ip: str,
    port: int,
    command: bytes,
    timeout: int = _DEFAULT_TIMEOUT,
    expect_ack: bool = True,
) -> CommandResult:
    """Sendet einen Barco-Binärbefehl und liest das ACK."""
    logger.info(f"[CMD] Barco {ip}:{port} → {command.hex()}")
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.sendall(command)
            if expect_ack:
                ack = b""
                sock.settimeout(timeout)
                try:
                    ack = sock.recv(16)
                except socket.timeout:
                    pass
                logger.info(f"[CMD] Barco ACK: {ack.hex() if ack else 'leer'}")
                if ack and ack[0] == _START and len(ack) >= 4:
                    # Fehlermeldung im ACK?
                    if ack[2] == 0x01:  # NACK
                        return CommandResult(
                            success=False,
                            message=f"Barco NACK empfangen: {ack.hex()}",
                            raw_resp=ack.hex(),
                        )
                return CommandResult(
                    success=True,
                    message="Befehl gesendet",
                    raw_resp=ack.hex() if ack else "",
                )
    except socket.timeout:
        msg = f"Timeout – Projektor nicht erreichbar ({ip}:{port})"
        logger.warning(f"[CMD] {msg}")
        return CommandResult(success=False, message=msg)
    except OSError as e:
        msg = f"Verbindungsfehler: {e}"
        logger.warning(f"[CMD] {msg}")
        return CommandResult(success=False, message=msg)


def _christie_send_command(
    ip: str,
    port: int,
    command: str,
    timeout: int = _DEFAULT_TIMEOUT,
) -> CommandResult:
    """Sendet einen Christie ASCII-Befehl via TCP und liest die Antwort."""
    cmd_bytes = f"{command}\r\n".encode("ascii")
    logger.info(f"[CMD] Christie {ip}:{port} → {command}")
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.sendall(cmd_bytes)
            resp = b""
            sock.settimeout(timeout)
            try:
                resp = sock.recv(256)
            except socket.timeout:
                pass
            resp_str = resp.decode("ascii", errors="replace").strip()
            logger.info(f"[CMD] Christie Antwort: {resp_str!r}")
            return CommandResult(
                success=True,
                message=f"Antwort: {resp_str}" if resp_str else "Befehl gesendet",
                raw_resp=resp_str,
            )
    except socket.timeout:
        msg = f"Timeout – Projektor nicht erreichbar ({ip}:{port})"
        logger.warning(f"[CMD] {msg}")
        return CommandResult(success=False, message=msg)
    except OSError as e:
        msg = f"Verbindungsfehler: {e}"
        logger.warning(f"[CMD] {msg}")
        return CommandResult(success=False, message=msg)


# ── Öffentliche Steuerungs-API ────────────────────────────────────────────────

def cmd_douser_open(
    projector_ip: str,
    projector_port: Optional[int] = None,
    projector_type: str = "barco",
    timeout: int = _DEFAULT_TIMEOUT,
) -> CommandResult:
    """Douser/Shutter öffnen."""
    if projector_type.lower() == "christie":
        port = projector_port or _CHRISTIE_DEFAULT_PORT
        return _christie_send_command(projector_ip, port, "(SHU1)", timeout)
    port = projector_port or _BARCO_DEFAULT_PORT
    return _barco_send_command(projector_ip, port, _CMD_DOUSER_OPEN, timeout)


def cmd_douser_close(
    projector_ip: str,
    projector_port: Optional[int] = None,
    projector_type: str = "barco",
    timeout: int = _DEFAULT_TIMEOUT,
) -> CommandResult:
    """Douser/Shutter schließen."""
    if projector_type.lower() == "christie":
        port = projector_port or _CHRISTIE_DEFAULT_PORT
        return _christie_send_command(projector_ip, port, "(SHU0)", timeout)
    port = projector_port or _BARCO_DEFAULT_PORT
    return _barco_send_command(projector_ip, port, _CMD_DOUSER_CLOSE, timeout)


def cmd_lamp_on(
    projector_ip: str,
    projector_port: Optional[int] = None,
    projector_type: str = "barco",
    timeout: int = _DEFAULT_TIMEOUT,
) -> CommandResult:
    """Lampe / Laser einschalten."""
    if projector_type.lower() == "christie":
        port = projector_port or _CHRISTIE_DEFAULT_PORT
        return _christie_send_command(projector_ip, port, "(LSR1)", timeout)
    port = projector_port or _BARCO_DEFAULT_PORT
    return _barco_send_command(projector_ip, port, _CMD_LAMP_ON, timeout)


def cmd_lamp_off(
    projector_ip: str,
    projector_port: Optional[int] = None,
    projector_type: str = "barco",
    timeout: int = _DEFAULT_TIMEOUT,
) -> CommandResult:
    """Lampe / Laser ausschalten."""
    if projector_type.lower() == "christie":
        port = projector_port or _CHRISTIE_DEFAULT_PORT
        return _christie_send_command(projector_ip, port, "(LSR0)", timeout)
    port = projector_port or _BARCO_DEFAULT_PORT
    return _barco_send_command(projector_ip, port, _CMD_LAMP_OFF, timeout)
