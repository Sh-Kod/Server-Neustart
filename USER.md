# USER.md — Nutzerprofil

## Wer
Shervin — arbeitet im Kino-IT-Bereich (Projektionstechnik, Doremi/GDC-Server). Entwickelt und betreibt dieses Tool selbst.

## Technisches Profil
- Python-Entwickler (kein Anfänger)
- Windows-Umgebung (Windows 10, NSSM als Dienst-Manager)
- Vertraut mit: Git, Telegram Bot API, YAML-Konfiguration, SNMP
- Projekt läuft produktiv auf echten Kino-Servern — Fehler haben reale Konsequenzen

## Arbeitsweise
- Erwartet einen **Plan vor jeder Codeänderung** und gibt explizit Freigabe
- Kommuniziert knapp und zielgerichtet — keine langen Erklärungen nötig wenn die Sache klar ist
- Trifft Entscheidungen selbst, will aber Optionen und Begründungen kennen
- Bevorzugt Feature-Branches und saubere Commits

## Kontext
- Projekt läuft auf einem dedizierten Windows-Rechner im Kino
- Deployment via NSSM-Dienst + VBS-Startskript
- Telegram-Bot ist primäre Steuerungsschnittstelle (kein Web-UI)
- Kein automatisches Test-Framework — Tests manuell via `--dry-run`
