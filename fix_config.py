"""
Einmalig ausführen: korrigiert projector_ip Einträge in config.yaml
"""
import re

with open("config.yaml", encoding="utf-8") as f:
    content = f.read()

# projector_ip Zeilen die am Zeilenanfang stehen (falsche Position)
# werden gelöscht – wir schreiben die komplette korrigierte Version
lines = content.splitlines()

fixed_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # Falsch platzierte projector_ip (kein führendes Leerzeichen)
    if re.match(r'^projector_ip:', line):
        # In die vorherige cinema-Gruppe einfügen (vor dem nächsten - id:)
        # Wert extrahieren
        ip_val = line.split(":", 1)[1].strip().strip('"').strip("'")
        # In fixed_lines rückwärts suchen und nach "enabled:" einfügen
        for j in range(len(fixed_lines) - 1, -1, -1):
            if fixed_lines[j].strip().startswith("enabled:"):
                fixed_lines.insert(j + 1, f"  projector_ip: \"{ip_val}\"")
                break
        i += 1
        continue
    fixed_lines.append(line)
    i += 1

result = "\n".join(fixed_lines) + "\n"

with open("config.yaml", "w", encoding="utf-8") as f:
    f.write(result)

print("config.yaml erfolgreich korrigiert!")

# Schnell-Prüfung
import yaml
try:
    with open("config.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cinemas_with_proj = [c for c in data.get("cinemas", []) if c.get("projector_ip")]
    print(f"YAML OK – {len(cinemas_with_proj)} Projektoren konfiguriert:")
    for c in cinemas_with_proj:
        print(f"  {c['name']}: {c['projector_ip']}")
except Exception as e:
    print(f"YAML-Fehler nach Fix: {e}")
