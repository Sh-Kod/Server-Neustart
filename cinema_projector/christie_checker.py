"""
Gesundheits-Check für Christie CP4435-RGB Projektoren (CineLife+).

Protokoll: WebSocket auf Port 5004 (kein Login nötig im LAN)
           JSON-RPC 2.0 – Server sendet StatusItems als XML automatisch nach Verbindungsaufbau.

StatusItem.alarmstate:
  0 = Normal (OK)
  1 = Warnung
  2+ = Fehler / Kritisch

Zustandsermittlung:
  GREEN  – alle alarmstate == 0
  YELLOW – mind. 1 alarmstate == 1, kein alarmstate >= 2
  RED    – mind. 1 alarmstate >= 2
  OFFLINE – Verbindung fehlgeschlagen (kein Strom / Netzfehler)
"""
import json
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_DEFAULT_PORT  = 5004
_DEFAULT_TIMEOUT = 10
_MAX_MESSAGES  = 20   # Maximal so viele Nachrichten lesen bevor Abbruch


def check_christie_health(
    cinema_id:      str,
    cinema_name:    str,
    projector_ip:   str,
    projector_port: int = _DEFAULT_PORT,
    timeout:        int = _DEFAULT_TIMEOUT,
):
    """
    Verbindet zu Christie CineLife+ WebSocket, liest StatusItems und
    bestimmt den Gesundheitszustand.

    Gibt HealthResult zurück (GREEN / YELLOW / RED / OFFLINE).
    """
    from .health_checker import HealthColor, HealthResult

    try:
        import websocket as _ws_lib
    except ImportError:
        logger.error(
            "[GESUNDHEIT] Christie: 'websocket-client' nicht installiert. "
            "Bitte: pip install websocket-client"
        )
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg="websocket-client nicht installiert",
        )

    ws_url = f"ws://{projector_ip}:{projector_port}/"
    logger.debug(f"[GESUNDHEIT] Christie {cinema_name}: Verbinde zu {ws_url}")

    try:
        ws = _ws_lib.create_connection(ws_url, timeout=timeout)
    except OSError as e:
        logger.info(f"[GESUNDHEIT] Christie {cinema_name}: ⬛ OFFLINE ({e})")
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg=f"Verbindungsfehler: {e}",
        )
    except Exception as e:
        logger.info(f"[GESUNDHEIT] Christie {cinema_name}: ⬛ OFFLINE ({e})")
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=False, color=HealthColor.OFFLINE,
            error_msg=str(e),
        )

    # Server schickt StatusItems automatisch – warte auf method 2011
    xml_str = None
    try:
        ws.settimeout(timeout)
        for _ in range(_MAX_MESSAGES):
            try:
                raw  = ws.recv()
                data = json.loads(raw)
                if data.get("method") == 2011:
                    props = data.get("result", {}).get("properties", [])
                    if props:
                        xml_str = props[0].get("value", "")
                        break
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception as e:
        logger.warning(f"[GESUNDHEIT] Christie {cinema_name}: Lesefehler – {e}")
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if not xml_str:
        logger.warning(f"[GESUNDHEIT] Christie {cinema_name}: Keine Status-Daten empfangen")
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=True, color=HealthColor.OFFLINE,
            error_msg="Keine StatusItems empfangen (method 2011 nicht erhalten)",
        )

    return _parse_status_xml(cinema_id, cinema_name, xml_str)


def _parse_status_xml(cinema_id: str, cinema_name: str, xml_str: str):
    """Parst die Christie StatusItems XML und bestimmt den Farbzustand."""
    from .health_checker import HealthColor, HealthResult

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        logger.warning(f"[GESUNDHEIT] Christie {cinema_name}: XML-Fehler – {e}")
        return HealthResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            reachable=True, color=HealthColor.OFFLINE,
            error_msg=f"XML-Fehler: {e}",
        )

    errors        = 0
    warnings      = 0
    notifications = 0
    alarm_items   = []   # für Debugging

    for item in root.findall("StatusItem"):
        try:
            alarm = int(item.findtext("alarmstate", "0") or "0")
        except ValueError:
            alarm = 0

        if alarm >= 2:
            errors += 1
            name = item.findtext("name", "?")
            val  = item.findtext("value", "")
            alarm_items.append(f"{name}={val}(alarm={alarm})")
        elif alarm == 1:
            warnings += 1
            name = item.findtext("name", "?")
            alarm_items.append(f"{name}(warn)")

    log_level = logging.INFO if not alarm_items else logging.WARNING
    logger.log(
        log_level,
        f"[GESUNDHEIT] Christie {cinema_name}: "
        f"Fehler={errors} Warnungen={warnings}"
        + (f" | {', '.join(alarm_items)}" if alarm_items else "")
    )

    if errors > 0:
        color = HealthColor.RED
    elif warnings > 0:
        color = HealthColor.YELLOW
    else:
        color = HealthColor.GREEN

    return HealthResult(
        cinema_id=cinema_id, cinema_name=cinema_name,
        reachable=True, color=color,
        notifications=notifications,
        warnings=warnings,
        errors=errors,
    )
