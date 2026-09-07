---
name: jarvis-photos
description: Durchsucht die Apple-Fotos-Bibliothek auf diesem Mac per Vision-Framework-Bildanalyse (Objekte, Szenen, erkannter Text). Nutze das, wenn der Nutzer nach Fotos fragt, z.B. "zeig mir Fotos vom Strand", "finde Bilder mit Hunden", "welche Fotos habe ich letzten Sommer gemacht". Erster Aufruf braucht evtl. einen Scan (kann bei großen Bibliotheken dauern).
---

# Jarvis Fotos-Suche

Eigens für dieses Setup gebauter Skill (wiederverwendet den Foto-Such-Code aus dem früheren JARVIS-OS-Projekt: `photos_client.py` + `photos_helper.swift`, nutzt Apples Photos- und Vision-Framework für rein lokale, On-Device-Bilderkennung).

## Voraussetzungen

- Erster Aufruf von `scan` löst einen macOS-Berechtigungsdialog für Fotos-Zugriff aus - der Nutzer muss diesen einmalig bestätigen.
- Ein Scan kann bei großen Bibliotheken (Tausende Fotos, insbesondere wenn viele nur in iCloud liegen) lange dauern - warne den Nutzer entsprechend, statt lange stumm zu warten.

## Befehle

Alle Befehle über: `python3 ~/Projekte/JARVIS-OS/openclaw-skills/photos/cli.py <befehl> ...`

- **`status`** - zeigt an, wie viele Fotos indexiert sind und wann zuletzt gescannt wurde. Nutze das zuerst, um zu wissen, ob ein Scan nötig ist.
- **`scan [--max N]`** - indexiert (neue/geänderte) Fotos, Standard max. 500 pro Lauf. Erkennt dabei Objekte/Szenen/Text/Gesichter per Vision-Framework.
- **`search "<suchbegriff>" [--max N]`** - durchsucht den bestehenden Index, gibt JSON-Liste mit Dateiname, Erstellungsdatum, erkannten Labels/Texten zurück.

## Vorgehen bei einer Nutzer-Anfrage

1. Falls noch nie gescannt (siehe `status`), dem Nutzer erklären, dass ein einmaliger Scan nötig ist, und fragen ob er jetzt starten soll (kann dauern).
2. Bei `search`-Ergebnissen: die Labels/Texte natürlich in eine Antwort umformulieren, nicht das rohe JSON zeigen.
3. Ein `scan` läuft synchron und blockiert bis fertig - bei sehr großen Bibliotheken lieber mit einem kleinen `--max`-Wert anfangen, um zu testen, ob es überhaupt funktioniert, bevor ein großer Lauf gestartet wird.
