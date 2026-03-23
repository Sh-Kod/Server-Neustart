"""
Liest Lampenstatus eines Barco-Projektors via SNMP und berechnet den Prozentwert.

OIDs (BARCO-ME-DCP-MIB, lampRunTimeTable):
  Index 1 = aktuelle Laufzeit (Stunden)   → Communicator: "RunTime"
  Index 2 = Max-Lebensdauer (= 100%)      → Communicator: "RunTime + Remaining"

Formel: percent = runtime / max_life * 100
"""
import logging
from dataclasses import dataclass
from typing import Optional

from .snmp_client import snmp_get

logger = logging.getLogger(__name__)

_OID_BASE    = "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2"
_OID_RUNTIME = f"{_OID_BASE}.1"   # aktuelle Laufzeit (Stunden)
_OID_MAX     = f"{_OID_BASE}.2"   # Gesamt-Lebensdauer (= 100%)


@dataclass
class LampResult:
    cinema_id: str
    cinema_name: str
    projector_ip: str
    runtime_hours: Optional[int]
    max_hours: Optional[int]
    percent: Optional[float]
    error: Optional[str]

    @property
    def ok(self) -> bool:
        return self.error is None and self.percent is not None


def check_lamp(
    cinema_id: str,
    cinema_name: str,
    projector_ip: str,
    community: str = "public",
    port: int = 161,
    timeout: int = 5,
) -> LampResult:
    """Liest Laufzeit und Basis vom Projektor, gibt LampResult zurück."""
    try:
        runtime  = snmp_get(projector_ip, community, _OID_RUNTIME, port, timeout)
        max_life = snmp_get(projector_ip, community, _OID_MAX,     port, timeout)
    except Exception as e:
        logger.warning(f"[LAMPE] {cinema_name} ({projector_ip}): SNMP-Fehler – {e}")
        return LampResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            projector_ip=projector_ip,
            runtime_hours=None, max_hours=None,
            percent=None, error=str(e),
        )

    if not isinstance(runtime, int) or not isinstance(max_life, int) or max_life == 0:
        err = f"Ungültige SNMP-Werte: runtime={runtime!r}, max={max_life!r}"
        logger.warning(f"[LAMPE] {cinema_name}: {err}")
        return LampResult(
            cinema_id=cinema_id, cinema_name=cinema_name,
            projector_ip=projector_ip,
            runtime_hours=runtime if isinstance(runtime, int) else None,
            max_hours=max_life if isinstance(max_life, int) else None,
            percent=None, error=err,
        )

    percent = runtime / max_life * 100
    logger.info(
        f"[LAMPE] {cinema_name}: {runtime}h / {max_life}h = {percent:.1f}%"
    )
    return LampResult(
        cinema_id=cinema_id, cinema_name=cinema_name,
        projector_ip=projector_ip,
        runtime_hours=runtime, max_hours=max_life,
        percent=percent, error=None,
    )
