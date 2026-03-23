"""
Minimaler SNMP v2c GET – nur Python Standard-Bibliothek, keine extra Pakete.
"""
import socket


def _enc_len(n):
    if n < 0x80:
        return bytes([n])
    elif n < 0x100:
        return bytes([0x81, n])
    return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])


def _tlv(tag, value):
    return bytes([tag]) + _enc_len(len(value)) + value


def _enc_int(v):
    if v == 0:
        return _tlv(0x02, b'\x00')
    parts = []
    while v:
        parts.insert(0, v & 0xFF)
        v >>= 8
    if parts[0] & 0x80:
        parts.insert(0, 0)
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
    if b < 0x80:
        return b, off + 1
    nb = b & 0x7F
    v = 0
    for i in range(nb):
        v = (v << 8) | data[off + 1 + i]
    return v, off + 1 + nb


def _dec_tlv(data, off):
    tag = data[off]
    length, off = _dec_len(data, off + 1)
    return tag, data[off:off + length], off + length


def _dec_int(b):
    v = 0
    for x in b:
        v = (v << 8) | x
    return v


def snmp_get(host, community, oid, port=161, timeout=5):
    varbind = _tlv(0x30, _enc_oid(oid) + _tlv(0x05, b''))
    pdu = _tlv(0xA0,
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

    # parse: Sequence { version, community, GetResponse-PDU }
    _, msg_val, _ = _dec_tlv(raw, 0)
    off = 0
    _, _, off = _dec_tlv(msg_val, off)  # version
    _, _, off = _dec_tlv(msg_val, off)  # community
    _, pdu_val, _ = _dec_tlv(msg_val, off)  # PDU

    poff = 0
    _, _, poff = _dec_tlv(pdu_val, poff)   # request-id
    _, es, poff = _dec_tlv(pdu_val, poff)  # error-status
    _, _, poff = _dec_tlv(pdu_val, poff)   # error-index
    if _dec_int(es) != 0:
        raise RuntimeError(f"SNMP error-status={_dec_int(es)}")

    _, vbl, _ = _dec_tlv(pdu_val, poff)   # VarBindList
    _, vb, _  = _dec_tlv(vbl, 0)          # first VarBind
    voff = 0
    _, _, voff = _dec_tlv(vb, voff)        # OID
    tag, val, _ = _dec_tlv(vb, voff)       # Value

    # Numeric types: Integer, Counter32, Gauge32, TimeTicks, Counter64
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46, 0x47):
        return _dec_int(val)
    return val  # bytes for OctetString etc.


# ── Test ──────────────────────────────────────────────────────────────────────
IP = "172.20.23.21"

oids = [
    ("Runtime (Stunden)",  "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.0"),
    ("Max 100% (Stunden)", "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.1"),
]

print(f"\nSNMP-Test Projektor {IP}")
print("=" * 40)
for label, oid in oids:
    try:
        value = snmp_get(IP, "public", oid)
        print(f"{label}: {value}")
    except Exception as e:
        print(f"{label}: FEHLER – {e}")
print("=" * 40)
