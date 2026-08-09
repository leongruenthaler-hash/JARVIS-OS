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

## 9. Phase-B-Status (2026-08-04)

Phase B (Context/Memory) ist umgesetzt: strukturiertes Fakten-Schema mit
Sensibilität/Ablauf/Status in `app/memory.py`, neue `ContextEngine`
(`app/core/context_engine.py`) ersetzt die alte, rein rekenz-basierte
`build_memory_summary()`, authentifizierte Memory-CRUD-Endpunkte in
`local_server.py`, eine neue Gedächtnis-Ansicht in der SwiftUI-App
(`MemoryView.swift`, erreichbar über Seitenleiste und Dashboard), Context
Packs über `config.json`, 22 automatisierte Unit-Tests (`tests/`, `pytest`)
für Memory-Schema und Context Engine. Details: `docs/context-and-memory.md`.

Bewusst nicht umgesetzt: Umstellung auf eine echte Datenbank, Token-basiertes
statt zeichenbasiertes Kontextbudget, automatische Löschung abgelaufener
Fakten (nur Ausblendung aus dem Kontext), Beziehungsgraph über
`related_entities`. Siehe `docs/context-and-memory.md`, letzter Abschnitt.

## 10. Phase-C-Status (2026-08-04)

Phase C (Briefing/Proaktivität) ist umgesetzt: deterministische
`ProactivityEngine` (`app/core/proactivity_engine.py`) mit vier Prioritätsstufen,
Ruhezeiten, Drosselung, Abkühlzeit/Deduplizierung, Snooze und dauerhaftem
Ausblenden, protokolliert in `memory/proactivity_events.json`. Vier
eingebaute Regeln (`app/core/proactivity_rules.py`): Speicherplatz knapp,
unbestätigte Mail-Kalender-Vorschläge, unbestätigte Erinnerungen, neue
ungelesene Mails. Authentifizierte API (`/api/proactivity/...`), Einbindung
ins Tagesbriefing, periodisches Abfragen (alle 5 Minuten) in der SwiftUI-App
mit Anzeige als System-Chat-Nachricht. 25 neue automatisierte Tests. Details:
`docs/proactivity.md`.

Bewusst nicht umgesetzt: kalenderzeit-basierte Trigger ("Termin beginnt
bald", Terminüberschneidungen) - blockiert auf einer sichereren,
eigenständigen Änderung an `calendar_client.py`s AppleScript-Datumsausgabe,
die nicht ungetestet in derselben Änderung wie die neue Engine laufen sollte
(siehe die heute bereits einmal aufgetretene Kalender-Regression, Commit
`45dc902`). Evening Review, macOS-Systembenachrichtigungen, dedizierte
Ruhezeiten-Einstellung in der App-Oberfläche. Siehe `docs/proactivity.md`,
letzter Abschnitt.

## 11. Phase-D-Status (2026-08-05)

Phase D (Kalender/E-Mail/Aufgaben) ist umgesetzt: neues, eigenständiges
Aufgaben-System (`app/core/task_manager.py`) mit Priorität, Abhängigkeiten,
Status und dem Grundsatz "automatisch erkannte Aufgaben werden nie
stillschweigend verbindlich" (Vorschlag/Bestätigung wie bei Phase B/C).
Authentifizierte API, neue `TasksView.swift` in Seitenleiste und Dashboard.
Mail-Antwortentwürfe (`create_reply_draft()` in `app/mail_client.py`) - öffnet
einen Entwurf in Mail.app, sendet nichts. Kontaktauflösung bei Mehrdeutigkeit
war bereits vollständig vorhanden (`app/contacts_client.py`), keine Änderung
nötig. 12 neue Tests (insgesamt 59). Details: `docs/tasks.md`.

Bewusst nicht umgesetzt: kalenderzeit-basierte Konflikterkennung (dieselbe
Einschränkung wie in Phase C), echtes E-Mail-Senden (bewusste
Projekt-Entscheidung, siehe `PRIVACY_ARCHITECTURE.md`), automatische
Aufgaben-Erkennung aus Gesprächen/Mails (Infrastruktur `propose_task()`
steht bereit, aber noch nicht angebunden). Siehe `docs/tasks.md`, letzter
Abschnitt.

**Nebenbefund während dieser Phase:** Das Projekt lag zwischenzeitlich wieder
unter iCloud-Sync (`~/Desktop/Projekte/JARVIS-OS` mit aktivem "Desktop &
Dokumente"-Sync), was zu stundenlangen Zugriffsblockaden führte (System-Load
>200, `Operation not permitted` auf den gesamten Desktop-Ordner). Nutzer hat
iCloud-Sync für Desktop daraufhin deaktiviert. Siehe Memory-Eintrag
`project-icloud-desktop-sync-risk` für Details - bei zukünftigen "zufälligen"
Hängern von Datei-Tools zuerst `fileproviderd`/`bird`-CPU-Last prüfen.

## 12. Phase-E-Status (2026-08-05)

Phase E (Realtime Voice) ist umgesetzt, nach gründlicher Untersuchung der
bestehenden Sprachpipeline (siehe `docs/voice-system.md`) - vieles war
bereits solide vorhanden (Streaming-TTS, Streaming-Antworttext,
Live-Transkription via Apple Speech, manuelles Unterbrechen) und wurde
bewusst nicht angefasst.

Neu: fünf Gesprächsmodi (`app/core/voice_modes.py` - kurz/standard/fokus/
diskret/privat), eingespeist in den System-Prompt und Swift-seitig
durchgesetzt (diskreter Modus unterdrückt Sprachausgabe direkt beim
Streaming, nicht erst nachträglich). Persistente Latenzmessung
(`app/core/voice_performance.py`) statt reiner Konsolen-Ausgabe, mit
Durchschnitt/p95/Maximum je Phase über die letzten Sprach-Turns. 21 neue
Tests (insgesamt 80). Details: `docs/voice-system.md`.

Bewusst nicht umgesetzt: automatisches akustisches Unterbrechen (Barge-in) -
bräuchte echte Akustik-Echo-Unterdrückung, die ich ohne physisches Testen auf
einem Gerät nicht blind riskieren wollte (Gefahr: Jarvis unterbricht sich
ständig selbst). Echtes Streaming-STT für die batch-basierten Engines (nur
der bereits vorhandene Apple-Speech-`--live`-Pfad liefert echte
Teiltranskripte). Mobile Sprachsteuerung (kein iPhone-Client vorhanden). Siehe
`docs/voice-system.md`, letzter Abschnitt.

**Nachtrag (2026-08-08):** "Privater Modus" erzwingt inzwischen tatsächlich
den lokalen LLM-Provider (nicht mehr nur eine Prompt-Anweisung) - behoben im
Rahmen eines umfassenden Security-Audits, siehe Commit `6ee7550` und
`app/core/voice_modes.py::forces_local_only()`.

## 13. Robustere Absichtserkennung (2026-08-08)

Ausgangspunkt: Rückmeldung, dass Jarvis eine Anweisung nicht mehr erkennt,
sobald sie leicht anders formuliert ist oder der Nutzer sich verspricht.
Ursache: `app/jarvis.py::has_domain()`/`DOMAIN_TERMS` akzeptierten bisher nur
exakte Teilstring-Treffer gegen feste Stichwortlisten - ein einziger
Tippfehler oder ein leicht falsch verstandenes Wort (Spracherkennung) reichte,
um eine ganze Fähigkeit (Mail/Kalender/Dateien/...) unerreichbar zu machen;
die Anfrage fiel dann still in den werkzeuglosen Chat-Zweig.

Neu: gemeinsames Fuzzy-Matching-Modul `app/core/intent_matching.py`
(Editierdistanz-Wortvergleich - dieselbe Technik, die für die
Kontaktnamen-Suche in `contacts_client.py` bereits bewährt war, jetzt dorthin
ausgelagert und zusätzlich von `jarvis.py`/`fast_intent_router.py` genutzt -
plus automatische Umlaut-Normalisierung). `has_domain()` und
`fast_intent_router.py` nutzen das jetzt für Tippfehler-/Verhaspel-Toleranz,
mit einer bewusst kurzen Stopword-Liste (siehe Modul-Kommentar), die häufige
Füllwörter wie "mal" davon ausschließt, versehentlich als Domänen-Treffer zu
zählen (beim Testen konkret aufgefallen: "spiel mal Musik" hätte sonst als
Mail-Anfrage gezählt, weil "mal" Editierdistanz 1 zu "mail" hat).

Als Sicherheitsnetz für den Rest-Fall (Stufe 2): erkennt Stufe 1 keine
Domäne, fragt Jarvis über eine kurze, günstige Klassifikationsanfrage ans
ohnehin geladene lokale Modell aktiv nach, was gemeint war
(`maybe_ask_domain_clarification()`/`handle_pending_domain_clarification_flow()`
in `jarvis.py`), statt zu raten oder stillschweigend in den Chat-Zweig zu
fallen - auf ausdrücklichen Wunsch immer nachfragen, nie automatisch
entscheiden. Zusätzlich: Antwort-Budgets angehoben
(`ollama_num_predict`/`phi4_mini_num_predict`/`openai_max_output_tokens` in
`config.json`, `num_ctx` in `model_router.py`), damit Antworten nicht mehr
mitten im Satz abgeschnitten werden. 20 neue Tests (insgesamt 100). Details:
`plans/2026-08-08-jarvis-intelligenz-verbessern.md`.

Bewusst nicht umgesetzt: volles LLM-Function-Calling statt
Keyword-Dispatch (größerer, eigener Umbau, siehe Plan-Notizen). Stufe 2
konnte aus Zeitgründen nicht so gebaut werden, dass sie bei Bestätigung
direkt in jeden der acht Domänen-Handler durchreicht, ohne deren eigene
(teils separate) Stichwort-Erkennung erneut zu durchlaufen - stattdessen wird
die bestätigte Anfrage um das kanonische Domänen-Stichwort ergänzt und dann
normal durch denselben Handler geschickt, den auch ein direkter
Stichwort-Treffer auslösen würde. Der CLI-Pfad (`jarvis.py::main()`) erzwingt
Stufe 1/Stufe 2 jetzt konsistent zum App-Pfad, ist aber laut Bestandsaufnahme
weiterhin die zwei parallelen, nicht deckungsgleichen Antwortpfade (Abschnitt
7.2) - dieses strukturelle Problem bleibt bestehen. `model_router.py`s
`_is_simple()`/`_is_complex()` nutzen bewusst weiterhin keine Fuzzy-Erkennung
(niedrigere Priorität, siehe Plan).

## 14. Proaktive Kalender-Nudges (2026-08-08)

Baustein A aus `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`
umgesetzt: zwei neue, deterministische Proactivity-Regeln
(`rule_calendar_event_starting_soon`, `rule_calendar_events_overlap` in
`app/core/proactivity_rules.py`) - der zuvor im Code selbst als bewusst
zurückgestellter Folgeschritt vermerkte Fall (siehe Abschnitt 7 dieser Datei,
"Größte technische Schulden" #4, jetzt teilweise erledigt für den
Kalender-Teil). Details, Konfigurationswerte und Design-Entscheidungen:
`docs/proactivity.md`, `plans/2026-08-08-jarvis-termin-nudges.md`.

Voraussetzung dafür war eine additive Erweiterung von
`app/calendar_client.py::list_upcoming_calendar_items()` um numerische,
sprachunabhängige Datumsfelder (statt nur locale-formatiertem Text) - dabei
wurde die schon einmal riskante `whose`-AppleScript-Filterung (Commit
`45dc902`) bewusst nicht wieder angefasst, nur die Ausgabe pro Termin
erweitert.

**Nebenbefund und behoben:** ein vom Nutzer gemeldeter Bug, bei dem "was
steht heute an" Termine aus dem ganzen Jahr statt nur von heute zeigte -
behoben durch eine zusätzliche, robuste Python-seitige Filterung anhand der
neuen numerischen Zeitstempel in `jarvis.py::answer_calendar_query()`.

13 neue Tests (insgesamt 113). Bewusst nicht umgesetzt: Reisezeit vor einem
Termin, automatischer Abgleich mit aus Mails erkannten Terminvorschlägen
(Baustein B) - siehe `docs/proactivity.md`, letzter Abschnitt.

## 15. Mail und Kalender verknüpfen (2026-08-08)

Baustein B aus `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`
umgesetzt: neue Regel `rule_mail_matches_upcoming_event` in
`app/core/proactivity_rules.py` - erste Proactivity-Regel, die zwei
Datenquellen (neue Mails + anstehende Termine) gemeinsam auswertet statt
isoliert. Vergleicht den Absendernamen jeder neuen Mail per Fuzzy-
Wortvergleich (`app/core/intent_matching.py`) gegen die Titel anstehender
Termine im Lookahead-Fenster aus Baustein A.

**Bewusste Einschränkung:** Abgleich läuft gegen den Termin-Titel, nicht
gegen echte Termin-Teilnehmer - Letzteres bräuchte eine weitere Erweiterung
der Calendar.app-AppleScript-Abfrage, die bewusst nicht direkt im Anschluss
an die vorsichtige Baustein-A-Änderung vorgenommen wurde. Details, gefundene
Falsch-Positiv-Fälle (generische Absender wie "Info"/"Support") und deren
Behebung: `docs/proactivity.md`.

6 neue Tests (insgesamt 119). Bewusst nicht umgesetzt: Teilnehmer-basierter
Abgleich (siehe oben), Reisezeit vor einem Termin.
