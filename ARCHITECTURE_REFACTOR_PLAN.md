# Jarvis Architecture Refactor Plan

Stand: 2026-07-08

## Zielbild

Jarvis soll sich wie eine native macOS-App anfühlen:

- SwiftUI übernimmt UI, Audioaufnahme, Status, Berechtigungen und Apple-Integrationen.
- Python bleibt für LLM, Tool-Routing, Datenschutzlogik, bestehende Prototypen und den lokalen Server zuständig.
- Die App spricht über eine stabile lokale API mit dem Core.
- Audio und Voice-State sollen nicht mehr vom Python-Prozess abhängen.

## Aktuelle Lage

### SwiftUI-App

- `JarvisMacApp` startet die App und bindet `AppState` ein.
- `AppState` steuert UI, Modellwechsel, Voice-State, Chat, Scan-Stati und die Verbindung zum lokalen Server.
- `LocalServerController` startet den lokalen Core und ruft die Python-Bridge für TTS an.
- `JarvisAPIClient` spricht mit `http://127.0.0.1:8765`.
- `TTSService` nutzt aktuell `app/tts_bridge.py` indirekt.

### Python-Core

- `app/jarvis.py` enthält Hauptlogik, Prompt-Routing, Mail-/Datei-/Foto-/Kalender-/Notiz-Automationen und Fallbacks.
- `app/local_server.py` exponiert dieselben Funktionen als lokale HTTP-API.
- `app/audio_stream.py` übernimmt derzeit die Aufnahme, VAD und teilweise Transkriptions-Workflow.
- `app/stt_engines.py` enthält mehrere STT-Backends.
- `app/llm_client.py`, `app/model_manager.py`, `app/model_router.py` regeln LLM und Modellwahl.

### Beobachtung

- Die UI hängt noch zu stark an Python, wenn es um Audio-Start, Voice-Status und Reaktionszeit geht.
- Der Python-Core macht mehr als nur KI: Audio, TTS-Koordination und mehrere App-nahe Zustände liegen noch dort.
- Die lokale API ist schon brauchbar, aber der Swift-Client braucht klarere Zustände, Timeouts und robustere Retry-Pfade.

## Refactor-Prinzipien

1. Kein Big Bang Rewrite.
2. Erst die Audio-Hot-Path-Migration, dann die Integrationen.
3. Bestehende Funktionen bleiben aktiv und werden nur umgehängt.
4. Legacy-Pfade bleiben vorerst erhalten und werden nur markiert.
5. UI-Status und Mikrofonlogik sollen in Swift leben.
6. Python soll nur dann laufen, wenn wirklich Kernlogik gebraucht wird.

## Zielaufteilung

### Swift soll übernehmen

- Mikrofonaufnahme
- Voice-State-Machine
- Permission-Dialoge und Nutzerstatus
- Verbindungsstatus zur lokalen API
- Chat-UI und Streaming-Anzeige
- TTS-Playback-Koordination
- Apple-nahe Services als native Platzhalter oder echte Services

### Python soll behalten

- LLM-Aufrufe
- Prompt-Verarbeitung
- Intent-Routing
- Datenschutzlogik
- Automationen und bestehende Tool-Logik
- Legacy-Audio nur als Fallback

## Phasenplan

### Phase 1: Audio aus Python herauslösen

Ziel:

- Native Audioaufnahme in Swift über `AVFoundation`.
- Sofortiges Starten der Aufnahme ohne Blockierung der UI.
- Swift hält den Voice-State und reicht Audio oder Transkripte an den Core weiter.

Geplante Schritte:

1. Neue Swift-Services anlegen:
   - `AudioCaptureService.swift`
   - `VoiceStateManager.swift` oder Erweiterung von `AppState`
   - `PermissionService.swift`
2. Mikrofonstatus, Fehler und `idle / listening / transcribing / thinking / speaking / error` in Swift abbilden.
3. Python-Audioaufnahme vorerst als Legacy-Fallback behalten.
4. Streaming-Transkription vorbereiten, aber noch nicht vollständig umstellen.

### Phase 2: Swift ↔ Core stabilisieren

Ziel:

- Eine kleine, robuste API-Schicht mit klaren Endpunkten.
- Kein eingefrorener UI-Thread.

Geplante Schritte:

1. `JarvisAPIClient` härten:
   - Timeouts
   - Retry
   - eindeutige Fehlermeldungen
   - Verbindungsstatus
2. Endpunkte klar trennen:
   - `/health`
   - `/chat`
   - `/chat/stream`
   - `/models`
   - `/voice/status`
   - `/permissions`
3. Streaming-Events sauber normalisieren.

### Phase 3: Python-Core verschlanken

Ziel:

- Python wird stärker zum reinen KI- und Automations-Kern.

Geplante Schritte:

1. Audio-Start, UI-nahe Statuslogik und TTS-Koordination aus Python herausziehen.
2. Apple-nahe Aufgaben schrittweise in Swift-Services spiegeln.
3. Legacy-Pfade mit Warnhinweis behalten, bis Swift-Variante stabil ist.

### Phase 4: Apple-Integrationen nativ vorbereiten

Ziel:

- Die App bekommt klare Swift-Service-Grenzen für Apple-Features.

Geplante Platzhalter/Services:

- `CalendarService.swift`
- `ReminderService.swift`
- `MailService.swift`
- `PhotoService.swift`
- `FileService.swift`
- `PermissionService.swift`

### Phase 5: Logging und Debugging vereinheitlichen

Ziel:

- Swift und Python loggen sauber, ohne sensible Inhalte.

Geplante Schritte:

1. Swift-Logger nach Bereich trennen:
   - App
   - Audio
   - API
   - Permissions
2. Python-Logger nach Bereich trennen:
   - Core
   - LLM
   - Tools
3. UI-Debugansicht ergänzen.

## Konkrete Umbau-Reihenfolge

1. Native AudioCaptureService in Swift bauen.
2. Mikrofonbutton und Voice-State auf Swift umstellen.
3. API-Client robuster machen.
4. Python-Audio als Fallback markieren.
5. Mail/Kalender/Dateien/Fotos in native Service-Skelette überführen.
6. Danach Python-Core weiter verkleinern.

## Risiken

- Zu frühes Entfernen der Python-Audio-Pfade würde Voice-Funktionen brechen.
- Doppelte Zustandsquellen zwischen Swift und Python können Race Conditions erzeugen.
- Apple-Integrationen müssen sauber mit Berechtigungen und Sandbox zusammenarbeiten.

## Erfolgskriterien

- Das Mikrofon startet in Swift schnell und zuverlässig.
- Die UI friert nicht mehr beim Sprechen ein.
- Der lokale Core bleibt für KI-Aufgaben erreichbar.
- Legacy-Funktionen laufen weiter, bis die Swift-Variante wirklich fertig ist.

## Nächster sinnvoller Schritt

1. Swift-nativen Audio-Service bauen.
2. AppState auf diesen Audio-Service umstellen.
3. Python-Audio-Flow als Legacy-Fallback belassen.
4. Danach die Apple-Integrations-Services als echte Swift-Dateien vorbereiten.

