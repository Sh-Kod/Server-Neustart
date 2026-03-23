import asyncio
from puresnmp import Client
from puresnmp.credentials import V2C

IP = "172.20.23.21"

oids = [
    ("Runtime (Stunden)",  "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.0"),
    ("Max 100% (Stunden)", "1.3.6.1.4.1.12612.220.11.2.2.4.8.1.2.1"),
]

async def main():
    print(f"\nSNMP-Test Projektor {IP}")
    print("=" * 40)
    client = Client(IP, V2C("public"), port=161)
    for label, oid in oids:
        try:
            result = await client.get(oid)
            print(f"{label}: {result}")
        except Exception as e:
            print(f"{label}: FEHLER – {e}")
    print("=" * 40)

asyncio.run(main())
