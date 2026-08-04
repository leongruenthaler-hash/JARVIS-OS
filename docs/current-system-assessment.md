# Jarvis – Bestandsaufnahme (Phase A)

Stand: 2026-08-04. Grundlage für den Master-Plan "Jarvis zu einem natürlichen,
persönlichen, proaktiven und visuellen Assistenten weiterentwickeln". Dieses
Dokument beschreibt ausschließlich den **tatsächlichen** Ist-Zustand des
Repositories, keine Annahmen aus der Anforderungsvorlage.

## 1. Repository- und Git-Zustand

- Pfad: `~/Desktop/Projekte/JARVIS-OS`, Git-Repo korrekt im Projektordner verwurzelt
  (wurde am 2026-08-04 repariert, vorher fälschlich unter `~/Desktop` verwurzelt).
- Aktiver Branch: `feature/dashboard-theme`, 17 Commits vor `main`, 0 dahinter
  (sauberer Vorsprung, kein divergenter Branch).
- Weitere Branches: `feature/live-transcription`, `feature/live-voice` (Status nicht
  geprüft, vermutlich abgeschlossene/gemergte Feature-Branches).
- 57 Commits seit 2026-07-08 (~4 Wochen aktive Entwicklung).
- Working Tree ist sauber (Stand nach dem heutigen Security-Audit-Commit).
- Kein automatisierter CI-Workflow gefunden (keine `.github/workflows`).

## 2. Tatsächliche Architektur (vs. Annahmen aus der Vorlage)

Die Aufgabenstellung nennt als möglichen Ausgangspunkt u. a. FastAPI, SQLite,
Server-Sent Events, Tailscale, eine Vektordatenbank und LaunchAgents. **Keines
davon ist im Repository vorhanden.** Der tatsächliche Stack:

| Bereich | Tatsächlich verwendet |
|---|---|
| HTTP-Server | `app/local_server.py` – reiner `http.server.ThreadingHTTPServer`, kein FastAPI/Flask. Seit heute mit Token-Auth gegen CSRF abgesichert. |
| Datenhaltung | Flache JSON-Dateien unter `memory/` (`long_memory.json`, `conversation.json`, `privacy_permissions.json`, `model_settings.json`, `background_mail_cache.json`, `photos_index.json`, `file_index.json`). Keine SQL-Datenbank, keine Migrationen. |
| Streaming | Eigenes NDJSON-Zeilen-Streaming über den HTTP-Response-Body (`/api/chat/stream`), kein SSE-Standardformat. |
| Remote-Zugriff | Kein Tailscale, kein Fernzugriff vorgesehen – Server bindet nur auf `127.0.0.1`. |
| Lokale KI | Ollama (bundled Runtime in der App, Modell `phi4-mini` mitgeliefert) + optional OpenAI. Kein Embedding-/Vektor-Store. |
| macOS-App | SwiftUI, natives Xcode-Projekt (`JarvisApp/JarvisApp.xcodeproj`), spricht ausschließlich mit `local_server.py` über HTTP. |
| Autostart | Kein LaunchAgent gefunden; die Swift-App startet den Python-Server selbst als Subprozess beim App-Start. |
| Tests | Keine pytest-/XCTest-Suite. Es gibt manuelle Diagnose-Skripte (`mic_test.py`, `sound_test.py`, `vad_audio_test.py`, `voice_test.py`, `openai_test.py`) und einen CLI-Selbsttest `python3 app/jarvis.py --privacy-test`, der Permissions, Keychain und Modellstatus prüft. Kein automatisiertes Test-Framework. |
| Codename | Keine Spur von "Friday" im Code oder in Docs – das Projekt heißt intern und extern durchgängig Jarvis. Der Hinweis in der Vorlage trifft hier nicht zu. |

**Konsequenz für den Master-Plan:** Abschnitt 14 ("Datenbank und Migrationen")
und Teile von Abschnitt 15 der Anforderungsvorlage setzen ein SQL-Backend
voraus, das nicht existiert. Neue strukturierte Daten (Memory-Metadaten,
Proactivity-Events, Approvals mit Ablaufdatum) sollten **nicht** ungefragt auf
SQLite umgestellt werden – das wäre ein großer, risikoreicher Umbau. Empfehlung:
zunächst im bestehenden JSON-Dateimuster (mit den bereits vorhandenen
atomaren Schreib-Helfern) weiterbauen und SQLite nur einführen, wenn eine
konkrete Anforderung (z. B. Volltextsuche über viele Erinnerungen) es
zwingend nötig macht.

## 3. Vorhandene Module, gemappt auf die Zielarchitektur

| Zielmodul aus der Vorlage | Entsprechung im Code | Reifegrad |
|---|---|---|
| Conversation Engine | `app/core/conversation_manager.py`, `app/jarvis_personality.py` | Vorhanden, funktional |
| Context Engine | Nicht als eigenes Modul vorhanden. Kontext wird ad hoc in `local_server.py`/`jarvis.py` zusammengebaut (Memory + Kalender + Mail je nach Anfrage) | Fehlt als eigenständige Schicht |
| Memory Engine | `app/memory.py`, `app/core/memory_system.py` (73 Zeilen, schlank) | Vorhanden, aber flach: keine Kategorien/Sensibilität/Ablaufdatum/Quelle wie in Abschnitt 7.3 gefordert |
| Planning Engine | Kein dediziertes Modul. Tool-/Intent-Routing liegt verteilt in `jarvis.py` (sehr groß) und `fast_intent_router.py` | Fehlt als eigenständige Schicht |
| Proactivity Engine | `app/background_tasks.py` (nur Mail-Hintergrundscan mit Zeitfenstern), `app/core/daily_briefing.py` (35 Zeilen, einfache Zusammenfassung) | Rudimentär, kein generisches Regelwerk, keine Prioritätsstufen, keine Ruhezeiten |
| Integration Hub | `mail_client.py`, `calendar_client.py`, `contacts_client.py`, `notes_client.py`, `files_client.py`, `photos_client.py`, `music_client.py`, `desktop_client.py` – alle über AppleScript/Automation, kein zentraler Hub, aber konsistentes Muster | Solide, aber ohne gemeinsame Basisklasse/Statusmodell |
| Vision Engine | Nur `local_vision_service.py`/`photos_client.py` für **vorhandene Fotos** (Bibliothek), **kein** Screenshot-/Bildschirm- oder Kamera-Capture | Praktisch nicht vorhanden |
| Voice Engine | `audio_stream.py`, `stt_engines.py` (4 Engines: Apple Speech, Faster-Whisper, Whisper-4bit, Moonshine-Streaming), `voice_output.py` (Edge-TTS + macOS-Fallback) | Solide Grundlage, aber laut `ARCHITECTURE_REFACTOR_PLAN.md` noch zu stark python-/nicht-swift-seitig, Latenz nicht systematisch gemessen |
| Action/Approval Engine | `app/core/action_engine.py` + `action_confirmation.py`, 27 Aufrufstellen in `jarvis.py` | Funktional vorhanden (propose/resolve, heute zusätzlich mit Lock gegen Race Conditions), aber ohne Parameter-Hash-Bindung, Ablaufzeit oder Replay-Schutz wie in Abschnitt 12.3 gefordert |
| Notification Engine | Keine eigene Instanz gefunden; Hinweise laufen aktuell nur als Chat-Antworten | Fehlt |
| Security/Privacy Layer | `permission_manager.py`, `secure_storage.py`, `privacy_logger.py`, `privacy_dashboard.py` | Der stärkste Teil des Projekts – heute zusätzlich gehärtet (Server-Auth, Race Conditions, Dateirechte, Keychain) |
| Audit/Observability | `privacy_logger.py` protokolliert Events, aber kein Korrelations-ID-System, keine Diagnoseansicht mit CPU/RAM/Queue-Länge | Teilweise |
| UX Layer | SwiftUI-App mit Dashboard, Chat, Mail/Kalender/Dateien/Fotos-Views, Onboarding, Privacy-View | Vorhanden, wirkt bereits wie ein zusammenhängendes Produkt (kein bloßes Debug-Dashboard) |

## 4. Sicherheit und Datenschutz (Ist-Zustand)

Dies ist der am weitesten entwickelte Bereich. Eigene Doku existiert bereits
(`PRIVACY_ARCHITECTURE.md`, `DATA_FLOW.md`, `COMPLIANCE_CHECKLIST.md`) und
deckt sich inhaltlich stark mit Abschnitt 13 der Vorlage: 15 einzelne
Permissions, Zustimmungspflicht vor jeder sensiblen Aktion, kritische Aktionen
nur mit Bestätigung, lokale Verarbeitung als Standard, Keychain statt Klartext.

Heute (2026-08-04) zusätzlich behoben, siehe Commits `92dfff0` und
`45dc902`: Server-Authentifizierung gegen CSRF, Quellpfad-Prüfung beim
Dateiverschieben, Validierung von Berechtigungsnamen, Bestätigungspflicht für
automatisch aus Mails erkannte Kalendereinträge, Dateirechte für gespeicherte
Erinnerungen, Locks gegen Race Conditions, echte Keychain-Anbindung für den
OpenAI-Key, Diagnose-Logging statt stiller Fehler, Bereinigung toten Codes.

**Offene Lücken gegenüber der Vorlage:**
- Kein Prompt-Injection-Schutz für externe Inhalte (E-Mail-Text, Web-Suchergebnisse)
  im Sinne einer expliziten Trennung "Systemregel vs. externer Inhalt" – externe
  Texte fließen aktuell als normaler Kontext in den Prompt.
- Keine Parameter-Hash-Bindung/Replay-Schutz bei Approvals (Abschnitt 12.3/12.4).
- Kein Secret-Scanner für Prompts/Logs über das bestehende `privacy_redact_console`
  hinaus geprüft.
- Sensible-Kategorie-Unterscheidung bei Memory-Einträgen (Abschnitt 7.3/7.4)
  existiert nicht – jede gespeicherte Tatsache landet undifferenziert in
  `long_memory.json`.

## 5. Ressourcen-/Hardwarerisiko (8 GB Apple Silicon)

`requirements.txt` enthält `torch` und `faster-whisper` – beides vergleichsweise
schwergewichtig für 8 GB Unified Memory, besonders wenn gleichzeitig ein
Ollama-Modell geladen ist. Es existiert bereits ein leichteres Apple-Speech-STT
als Alternative (`AppleSpeechEngine`), was in dieselbe Richtung wie die
Ressourcenvorgabe aus Abschnitt 3 der Vorlage geht. Für Phase E (Realtime
Voice) sollte vor größeren Änderungen ein tatsächlicher Speicher-/CPU-Messwert
auf einem 8-GB-Gerät erhoben werden, statt sich auf Annahmen zu verlassen.

## 6. Startfähigkeit (Stabilisierungskriterium Phase A)

- `python3 -m py_compile` über den gesamten `app/`-Baum: **fehlerfrei**.
- Xcode Release-Build (`xcodebuild -scheme JarvisApp -configuration Release`):
  **erfolgreich** (nach Behebung eines vorbestehenden, nicht mit dem
  heutigen Audit zusammenhängenden Pfadfehlers in der `.pbxproj` – die Datei
  verwies auf einen alten, nicht mehr existierenden verschachtelten Ordner).
- Kein automatisierter Testlauf möglich, da keine Testsuite existiert –
  einziger vorhandener Selbsttest ist `--privacy-test` (manuell, nicht in
  CI eingebunden).
- Kalender-Regression von heute (leere Terminliste durch eine fehlerhafte
  AppleScript-"whose"-Filterung) wurde gefunden und behoben (Commit `45dc902`).

## 7. Größte technische Schulden

1. `app/jarvis.py` ist mit weit über 4000 Zeilen die zentrale Monolith-Datei
   (Prompt-Routing, Aktionen, CLI, Kalender-Textverarbeitung u. v. m.) –
   entspricht genau der in `JARVIS_DEVELOPMENT_PLAN.md` selbst beschriebenen
   Gefahr ("Der Kern soll nicht in einer einzigen großen Datei wachsen").
2. Zwei parallele Voice-/Automations-Pfade (CLI `jarvis.py` vs. HTTP
   `local_server.py`) sind teilweise nicht deckungsgleich – z. B. nutzt nur
   der CLI-Pfad den performanteren `fast_intent_router.py`.
3. Kein automatisiertes Test-Framework – jede Regression (siehe Kalender-Bug
   heute) fällt erst im Live-Betrieb auf.
4. Keine Context Engine, keine Planning Engine, keine generische Proactivity
   Engine – das sind die drei größten strukturellen Lücken gegenüber dem
   Master-Ziel.

## 8. Empfohlene Umsetzungsreihenfolge (unverändert zur Vorgabe, jetzt mit Dateibezug)

Phase A gilt hiermit als abgeschlossen (Bestandsaufnahme + Stabilisierung).
Für Phase B (Context/Memory) sind die relevanten Startpunkte:

- Erweiterung von `app/memory.py`/`app/core/memory_system.py` um die in
  Abschnitt 7.3 geforderten Felder (category, scope, confidence, sensitivity,
  retention_policy, expires_at, user_confirmed) – als zusätzliche Felder auf
  dem bestehenden JSON-Format, nicht als DB-Migration.
- Neues Modul `app/core/context_engine.py` als zentrale Zusammenführung statt
  der aktuellen Ad-hoc-Logik in `local_server.py`.
- Memory-UI in der SwiftUI-App (aktuell nicht vorhanden) auf Basis der
  bestehenden `PrivacyView.swift`-Muster.

Dieser Plan wird nicht automatisch ausgeführt – Phase B beginnt erst nach
Rückmeldung, da sie echte neue Funktionalität einführt (kein reiner
Analyse-/Stabilisierungsschritt mehr).
