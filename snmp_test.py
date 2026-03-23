from pysnmp.hlapi import *

IP = "172.20.23.21"

oids = [
    ("Runtime (Stunden)",  "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.0"),
    ("Max 100% (Stunden)", "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.1"),
]

print(f"\nSNMP-Test Projektor {IP}")
print("=" * 40)
for label, oid in oids:
    ei, es, eI, vb = next(getCmd(
        SnmpEngine(),
        CommunityData("public"),
        UdpTransportTarget((IP, 161), timeout=5),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    ))
    if ei:
        print(f"{label}: FEHLER – {ei}")
    else:
        print(f"{label}: {vb[0].prettyPrint()}")
print("=" * 40)
