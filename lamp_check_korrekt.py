"""
Projektor-Lampenstatus-Pruefung fuer Barco-Projektoren.
Prueft einmalig ob die Lampe an oder aus ist, bevor der Server neu gestartet wird.
Nach der Pruefung beendet sich das Skript automatisch.
"""

import socket
import time

# -------------------------------------------------------
# Konfiguration – hier die echten Projektor-IPs eintragen
# -------------------------------------------------------
PROJEKTOREN = [
    {"name": "Saal 1",  "ip": "192.168.10.101"},
    {"name": "Saal 2",  "ip": "192.168.10.102"},
    {"name": "Saal 3",  "ip": "192.168.10.103"},
    {"name": "Saal 4",  "ip": "192.168.10.104"},
    {"name": "Saal 5",  "ip": "192.168.10.105"},
    {"name": "Saal 6",  "ip": "192.168.10.106"},
    {"name": "Saal 7",  "ip": "192.168.10.107"},
    {"name": "Saal 8",  "ip": "192.168.10.108"},
    {"name": "Saal 9",  "ip": "192.168.10.109"},
    {"name": "Saal 10", "ip": "192.168.10.110"},
    {"name": "Saal 11", "ip": "192.168.10.111"},
    {"name": "Saal 12", "ip": "192.168.10.112"},
    {"name": "Saal 13", "ip": "192.168.10.113"},
]

BARCO_PORT    = 43728   # Barco DP-Series Binary Protocol (TCP)
TIMEOUT_SEK   = 5

# Barco-Befehl: Lampenstatus abfragen (DP-Series TDE4313)
LAMP_STATUS_BEFEHL = bytes([0xFE, 0x00, 0x76, 0x9A, 0x10, 0xFF])


def lampe_an(ip: str) -> bool | None:
    """
    Verbindet sich via TCP mit dem Barco-Projektor und fragt den Lampenstatus ab.
    Gibt True (AN), False (AUS) oder None (nicht erreichbar) zurueck.
    """
    try:
        with socket.create_connection((ip, BARCO_PORT), timeout=TIMEOUT_SEK) as sock:
            sock.sendall(LAMP_STATUS_BEFEHL)
            antwort = sock.recv(32)
            if len(antwort) >= 5:
                return antwort[4] == 0x01  # 0x01 = Lampe AN, 0x00 = Lampe AUS
            return None
    except Exception:
        return None


# -------------------------------------------------------
# Hauptprogramm
# -------------------------------------------------------

print(f"[{time.strftime('%H:%M:%S')}] Pruefe Lampenstatus aller Barco-Projektoren...")
print()

lampe_laeuft = []

for proj in PROJEKTOREN:
    status = lampe_an(proj["ip"])
    if status is True:
        print(f"  {proj['name']} ({proj['ip']}):  Lampe AN  – kein Neustart")
        lampe_laeuft.append(proj["name"])
    elif status is False:
        print(f"  {proj['name']} ({proj['ip']}):  Lampe AUS – Neustart wird ausgefuehrt")
    else:
        print(f"  {proj['name']} ({proj['ip']}):  Nicht erreichbar – wird uebersprungen")

print()
if lampe_laeuft:
    print(f"Hinweis: {len(lampe_laeuft)} Projektor(en) wurden uebersprungen (Lampe lief noch):")
    for name in lampe_laeuft:
        print(f"  - {name}")
else:
    print("Alle erreichbaren Projektoren wurden geprueft.")

print()
print("Pruefung abgeschlossen. Programm beendet sich.")
# Kein 'while True', kein 'time.sleep' – das Skript beendet sich hier sauber.
