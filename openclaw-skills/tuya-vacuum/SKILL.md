---
name: tuya-vacuum
description: Steuert Leons Tikom-Staubsaugerroboter ("Staubi") ueber die Tuya-Cloud-API. Nutze das, wenn Leon sagt, Jarvis solle sauber machen/staubsaugen/den Roboter starten/pausieren/zur Ladestation schicken, oder wissen will, wie weit die Reinigung ist oder wie der Akkustand steht.
---

# Tuya-Staubsaugerroboter

Direkte Tuya-Cloud-API-Anbindung (kein Home Assistant, bewusste Nutzerentscheidung
2026-09-12) fuer genau ein Geraet: Leons Tikom-Saugroboter, Tuya-Geraete-ID
`bf23c05c8514c80fccycfj`, ist bereits als Standard-Geraet konfiguriert.

## Wichtige Einschraenkung

**Raumgenaue Reinigung ("nur das Wohnzimmer") ist NICHT moeglich** - dieses
Geraet gibt Raumauswahl nur ueber ein proprietaeres Binaerprotokoll her, das
nicht oeffentlich dokumentiert ist. Sag das Leon ehrlich, wenn er danach fragt,
statt einen Befehl zu senden, der stillschweigend die ganze Wohnung reinigt.
Verfuegbar ist nur die komplette, gespeicherte Karte auf einmal.

## Befehle

Alle Befehle über: `python3 ~/.openclaw/workspace/skills/tuya-vacuum/cli.py <befehl>`

- **`clean`** - startet die komplette Reinigung (Modus "smart", volle Karte).
- **`pause`** - pausiert die laufende Reinigung.
- **`dock`** - schickt den Roboter zurueck zur Ladestation.
- **`status`** - liefert den kompletten Live-Status als JSON, u.a.:
  - `status`: aktueller Zustand (`standby`, `cleaning`, `paused`, `goto_charge`, `charging`, `charge_done`, `sleep`, ...)
  - `electricity_left`: Akkustand in %
  - `clean_area`/`clean_time`: gereinigte Flaeche (m²) / Dauer (Min.) der letzten/laufenden Reinigung
  - `total_clean_area`/`total_clean_count`/`total_clean_time`: Lebenszeit-Statistik
  - `fault`: 0 = kein Fehler, sonst Bitmap mit Fehlercode (z.B. Rad blockiert, Muellbehaelter voll)
- **`specs`** - liefert die volle Geraete-Spezifikation (alle unterstuetzten Funktionen/Datenpunkte) - nur fuer Diagnose/Erweiterung, nicht fuer den Alltag noetig.
- **`command --commands '<JSON-Liste>'`** - Fallback fuer einzelne, seltenere Funktionen (z.B. Saugstaerke aendern: `[{"code":"suction","value":"strong"}]`, Range: gentle/normal/strong).

Antworte Leon nach `clean`/`pause`/`dock` kurz und in normaler Sprache (z.B.
"Staubi ist losgefahren" statt den rohen JSON-Output vorzulesen - siehe
SOUL.md-Regel gegen technisches Kauderwelsch in gesprochenen Antworten).

## Fehlerbilder

- `{"sent": false, "error": "..."}` - Tuya-API-Fehler (z.B. Geraet offline,
  Token abgelaufen und Erneuerung fehlgeschlagen). Nicht selbst reparieren,
  Leon den Fehler kurz mitteilen.
- Ein `status`-Wert `sleep` bedeutet, der Roboter ist im Standby und braucht
  ggf. zuerst `clean`, um "aufzuwachen".
