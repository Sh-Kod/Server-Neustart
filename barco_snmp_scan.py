"""
Barco SNMP Temperatur-Scanner
Scannt den Barco-Projektor und zeigt alle Werte die wie Temperaturen aussehen.

Ausführen in Windows CMD:
    python barco_snmp_scan.py 172.20.21.21
"""
import socket
import sys


# ── Minimales SNMP v2c GETNEXT (kein externes Paket nötig) ───────────────────

def _enc_len(n):
    if n < 0x80: return bytes([n])
    if n < 0x100: return bytes([0x81, n])
    return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])

def _tlv(tag, value):
    return bytes([tag]) + _enc_len(len(value)) + value

def _enc_int(v):
    if v == 0: return _tlv(0x02, b'\x00')
    parts = []
    while v:
        parts.insert(0, v & 0xFF)
        v >>= 8
    if parts[0] & 0x80: parts.insert(0, 0)
    return _tlv(0x02, bytes(parts))

def _enc_str(s):
    return _tlv(0x04, s.encode() if isinstance(s, str) else s)

def _enc_oid(oid_str):
    p = [int(x) for x in oid_str.split('.')]
    buf = [40 * p[0] + p[1]]
    for n in p[2:]:
        if n < 128:
            buf.append(n)
        else:
            tmp = []
            while n:
                tmp.insert(0, n & 0x7F)
                n >>= 7
            buf += [b | 0x80 for b in tmp[:-1]] + [tmp[-1]]
    return _tlv(0x06, bytes(buf))

def _dec_len(data, off):
    b = data[off]
    if b < 0x80: return b, off + 1
    nb = b & 0x7F
    v = 0
    for i in range(nb): v = (v << 8) | data[off + 1 + i]
    return v, off + 1 + nb

def _dec_tlv(data, off):
    tag = data[off]
    length, off = _dec_len(data, off + 1)
    return tag, data[off:off + length], off + length

def _dec_int(b):
    v = 0
    for x in b: v = (v << 8) | x
    return v

def _dec_oid(b):
    result = []
    first = b[0]
    result += [first // 40, first % 40]
    i, n = 1, 0
    while i < len(b):
        byte = b[i]; i += 1
        n = (n << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            result.append(n); n = 0
    return '.'.join(str(x) for x in result)

def snmp_getnext(host, community, oid, port=161, timeout=3):
    varbind = _tlv(0x30, _enc_oid(oid) + _tlv(0x05, b''))
    pdu = _tlv(0xA1,                           # 0xA1 = GETNEXT
        _enc_int(1) + _enc_int(0) + _enc_int(0) +
        _tlv(0x30, varbind))
    msg = _tlv(0x30, _enc_int(1) + _enc_str(community) + pdu)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(msg, (host, port))
        raw, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    _, msg_val, _ = _dec_tlv(raw, 0)
    off = 0
    _, _, off = _dec_tlv(msg_val, off)   # version
    _, _, off = _dec_tlv(msg_val, off)   # community
    _, pdu_val, _ = _dec_tlv(msg_val, off)

    poff = 0
    _, _, poff = _dec_tlv(pdu_val, poff)  # request-id
    _, es, poff = _dec_tlv(pdu_val, poff) # error-status
    _, _, poff = _dec_tlv(pdu_val, poff)  # error-index
    if _dec_int(es) != 0:
        return None, None

    _, vbl, _ = _dec_tlv(pdu_val, poff)
    _, vb, _  = _dec_tlv(vbl, 0)
    voff = 0
    _, oid_bytes, voff = _dec_tlv(vb, voff)
    tag, val, _ = _dec_tlv(vb, voff)

    next_oid = _dec_oid(oid_bytes)
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46, 0x47):
        return next_oid, _dec_int(val)
    if tag == 0x04:
        return next_oid, val
    return next_oid, f"(typ=0x{tag:02X})"


# ── Haupt-Scan ────────────────────────────────────────────────────────────────

def scan(host, community="public", base_oid="1.3.6.1.4.1.12612"):
    print(f"\nBarco SNMP Scan: {host}  Community: {community}")
    print(f"Basis-OID: {base_oid}\n")
    print(f"{'OID':<50} {'Wert':>10}  Hinweis")
    print("-" * 80)

    current = base_oid
    count = 0
    temp_candidates = []

    while True:
        try:
            next_oid, value = snmp_getnext(host, community, current)
        except Exception as e:
            print(f"  [Fehler: {e}]")
            break

        if next_oid is None or not next_oid.startswith(base_oid):
            break  # Ende des Barco-Baums erreicht

        current = next_oid
        count += 1

        # Temperatur-Hinweis: Integer-Werte zwischen 1500 und 12000 könnten
        # Temperaturen * 100 sein (z.B. 4250 = 42.50°C)
        # Werte zwischen 15 und 120 könnten direkte °C sein
        hint = ""
        if isinstance(value, int):
            if 1500 <= value <= 12000:
                hint = f"  *** mögliche Temp: {value/100:.1f}°C (÷100) ***"
                temp_candidates.append((next_oid, value, value/100, 100))
            elif 1500 <= value*10 <= 12000:
                hint = f"  *** mögliche Temp: {value/10:.1f}°C (÷10) ***"
                temp_candidates.append((next_oid, value, value/10, 10))
            elif 15 <= value <= 120:
                hint = f"  *** mögliche Temp: {value}°C (÷1) ***"
                temp_candidates.append((next_oid, value, float(value), 1))

        val_str = value.hex() if isinstance(value, bytes) else str(value)
        print(f"{next_oid:<50} {val_str:>10}{hint}")

    print(f"\n{'='*80}")
    print(f"Gesamt: {count} OIDs gefunden\n")

    if temp_candidates:
        print("TEMPERATUR-KANDIDATEN:")
        print("-" * 80)
        for oid, raw, celsius, div in temp_candidates:
            print(f"  OID:    {oid}")
            print(f"  Wert:   {raw}  →  {celsius:.1f}°C  (snmp_temp_div: {div})")
            print(f"  Config: snmp_temp_oid: \"{oid}\"")
            print(f"          snmp_temp_div: {div}")
            print()
    else:
        print("Keine offensichtlichen Temperaturwerte gefunden.")
        print("Schau dir die Liste oben an – Werte zwischen 2000-8000 könnten")
        print("Temperaturen in Milli-Celsius oder anderen Einheiten sein.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Verwendung: python barco_snmp_scan.py <IP> [community]")
        print("Beispiel:   python barco_snmp_scan.py 172.20.21.21")
        print("Beispiel:   python barco_snmp_scan.py 172.20.21.21 public")
        sys.exit(1)

    ip        = sys.argv[1]
    community = sys.argv[2] if len(sys.argv) > 2 else "public"
    scan(ip, community)
