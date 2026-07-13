# JARVIS-OS

Lokaler macOS-KI-Assistent fuer Sprache, Dateien, Mail, Kalender, Notizen, Fotos und Musik.

## Mindesthardware

- Apple MacBook Air M1 oder Mac mini M1
- 8 GB Unified Memory
- macOS
- Ollama fuer lokale KI

## Empfohlene Hardware

- Apple Silicon M1 oder neuer
- 16 GB Unified Memory fuer groessere lokale Modelle
- SSD mit ausreichend freiem Speicher fuer Ollama-Modelle

## Standard-KI

Jarvis arbeitet standardmaessig lokal mit Ollama und dem Modell:

```bash
phi4-mini
```

OpenAI ist standardmaessig deaktiviert und wird nur genutzt, wenn du es aktivierst, deinen eigenen API-Key in der macOS Keychain speicherst und Cloud-KI/externen APIs zustimmst.

## Unterstuetzte lokale Modelle

- `phi4-mini` Standardmodell, empfohlen fuer M1/8 GB
- `gemma3:4b` optional
- `qwen3:4b` optional

## Installation lokaler Modelle

Installiere Ollama und fuehre dann aus:

```bash
ollama pull phi4-mini
ollama pull gemma3:4b
ollama pull qwen3:4b
```

Falls Ollama nicht laeuft:

```bash
ollama serve
```

## Start

```bash
cd ~/Desktop/JARVIS-OS
source .venv/bin/activate
bash start_jarvis.sh
```

## Modellwechsel per Sprache

- `Jarvis, nutze Standardmodell` -> `phi4-mini`
- `Jarvis, nutze Gemma` -> `gemma3:4b`
- `Jarvis, nutze Qwen` -> `qwen3:4b`
- `Jarvis, nutze OpenAI` -> Cloud-KI aktivieren, nur mit Keychain-Key und Zustimmung
- `Jarvis, arbeite lokal` -> OpenAI deaktivieren
- `Jarvis, welches Modell nutzt du?` -> Modellstatus

## OpenAI optional aktivieren

API-Key sicher in der macOS Keychain speichern:

```bash
python3 app/jarvis.py --set-openai-key
```

Pruefen:

```bash
python3 app/jarvis.py --check-secure-storage
```

Loeschen:

```bash
python3 app/jarvis.py --delete-openai-key
```

## Tests

```bash
python3 app/jarvis.py --privacy-test
```

Der Test prueft Datenschutz, Permissions, Keychain und Modellstatus.

## Native macOS App (SwiftUI)

Jarvis besitzt jetzt zusätzlich eine native SwiftUI-App. Die bestehende Python-Logik bleibt der Jarvis Core. Die App spricht nur mit dem lokalen Jarvis-Server auf `127.0.0.1`.

### Architektur

- `app/` - Jarvis Core mit Python-Logik, Datenschutz, Modellen, Mail, Kalender, Dateien, Fotos und Integrationen
- `app/local_server.py` - lokale Schnittstelle zwischen SwiftUI und Python
- `JarvisApp/` - native macOS-App in SwiftUI

### Lokaler Server

Die SwiftUI-App startet den lokalen Jarvis-Server automatisch, falls er noch nicht läuft. Der manuelle Start ist nur noch zum Debuggen nötig:

```bash
cd ~/Desktop/JARVIS-OS
source .venv/bin/activate
python3 app/jarvis.py --local-server
```

### App starten

Während der Entwicklung:

```bash
cd ~/Desktop/JARVIS-OS/JarvisApp
swift run JarvisApp
```

### App kompilieren

```bash
cd ~/Desktop/JARVIS-OS/JarvisApp
swift build
```

### In Xcode öffnen

```bash
open ~/Desktop/JARVIS-OS/JarvisApp/Package.swift
```

Die App enthält Onboarding, Chat, Modellverwaltung, Datenschutzbereich, OpenAI-Key-Verwaltung über Jarvis Core und Platzhalterseiten für Verlauf, Kalender, Mail, Erinnerungen, Dateien und Fotos. Diese Seiten sind bewusst an den bestehenden Python-Core angebunden vorbereitet, damit keine bestehende Funktionalität entfernt oder neu erfunden werden muss.

