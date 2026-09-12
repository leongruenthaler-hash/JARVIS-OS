---
name: bluetooth
description: Verbindet/trennt Bluetooth-Geraete auf dem Mac Mini (z.B. "Jarvis, verbinde dich mit der Denon Soundbar" oder "trenn den Logitech BT Adapter"). Nutze das bei jeder Bitte, ein Bluetooth-Geraet zu verbinden, zu trennen oder aufzulisten.
---

# Bluetooth-Geraete verbinden/trennen

Duenner Wrapper um `blueutil` (Homebrew-CLI fuer macOS-Bluetooth). Steuert
NUR bereits mit diesem Mac gekoppelte Geraete - ein neues Geraet (z.B. ein
frisch angeschlossener Adapter) muss zuerst einmal manuell ueber die
Systemeinstellungen gekoppelt werden, das kann dieses Skill NICHT (kein
automatisches Pairing/PIN-Eingabe per CLI moeglich). Sag Leon das ehrlich,
statt es zu versuchen, wenn `connect` mit "Kein gekoppeltes Geraet gefunden"
fehlschlaegt.

## Befehle

Alle über: `python3 ~/.openclaw/workspace/skills/bluetooth/cli.py <befehl>`

- **`list`** - listet alle gekoppelten Geraete (Name, Adresse, ob gerade
  verbunden) als JSON.
- **`connect <name>`** - sucht per Namens-Teilstring (Groß/Kleinschreibung
  egal) unter den gekoppelten Geraeten und verbindet das erste passende. Der
  Name muss nicht exakt stimmen - "Denon" reicht z.B. für "Denon DHT-S217".
- **`disconnect <name>`** - gleiche Suche, trennt die Verbindung.

## Wichtig

- Bekannte Geraetenamen sind z.B. "Denon DHT-S217" (Soundbar im Wohnzimmer),
  "JBL Charge 4", "AirPods Pro" - `list` zeigt den aktuellen, echten Stand.
- Findet `connect`/`disconnect` mehrere passende Geraete, nimmt es das
  erste - bei Mehrdeutigkeit lieber kurz nachfragen, welches gemeint ist,
  statt zu raten.
- Nach einem `connect` kurz mit `list` gegenchecken, ob `connected: true`
  wirklich stimmt, bevor du Leon Erfolg meldest - eine Verbindung kann auch
  am Geraet selbst scheitern (z.B. Soundbar aus).
