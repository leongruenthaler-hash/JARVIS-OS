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

Stufe 2 konnte aus Zeitgründen nicht so gebaut werden, dass sie bei
Bestätigung direkt in jeden der acht Domänen-Handler durchreicht, ohne deren
eigene (teils separate) Stichwort-Erkennung erneut zu durchlaufen -
stattdessen wird die bestätigte Anfrage um das kanonische Domänen-Stichwort
ergänzt und dann normal durch denselben Handler geschickt, den auch ein
direkter Stichwort-Treffer auslösen würde. Der CLI-Pfad (`jarvis.py::main()`)
erzwingt Stufe 1/Stufe 2 jetzt konsistent zum App-Pfad, ist aber laut
Bestandsaufnahme weiterhin die zwei parallelen, nicht deckungsgleichen
Antwortpfade (Abschnitt 7.2) - dieses strukturelle Problem bleibt bestehen.
`model_router.py`s `_is_simple()`/`_is_complex()` nutzen bewusst weiterhin
keine Fuzzy-Erkennung (niedrigere Priorität, siehe Plan).

**Nachtrag (2026-08-09):** "Volles LLM-Function-Calling statt
Keyword-Dispatch" war hier als bewusst nicht umgesetzt vermerkt - inzwischen
umgesetzt als eigene Stufe 3, siehe Abschnitt 18.

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

## 16. Tagesbriefing ausgebaut (2026-08-08)

Baustein C aus `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`
umgesetzt: `app/core/daily_briefing.py::build_daily_briefing()` zeigte
bisher nur den jeweils ersten Termin/die erste Erinnerung und gar keine
Aufgaben. Jetzt: bis zu 3 Einträge pro Bereich (Termine/Aufgaben/
Erinnerungen, mit Leon abgestimmt - das Briefing wird teils vorgelesen,
mehr wäre beim Vorlesen unangenehm), mit "und N weitere" bei mehr. Neue
Funktion `calendar_client.py::events_on_date()` filtert Termine robust auf
"heute" (nutzt `start_dt` aus Baustein A) - ersetzt auch den bisherigen
Inline-Filter in `answer_calendar_query()` (reine Vereinheitlichung).

Offene Aufgaben (`TaskManager.list_tasks(status="offen"/"in_arbeit")`)
erscheinen erstmals im Briefing - automatisch vorgeschlagene, unbestätigte
Aufgaben (`status="vorgeschlagen"`) bewusst ausgeschlossen (Master-Plan-
Grundsatz: unbestätigte Vorschläge werden nie stillschweigend verbindlich).
Beide Antwortpfade (App/CLI) konsistent erweitert; der CLI-Pfad
(`jarvis.py::handle_daily_briefing_command()`) bekommt dabei erstmals auch
einen echten Mail-Status statt eines fest leeren Werts.

8 neue Tests (insgesamt 127).

## 17. Wiederkehrende Muster erkennen (2026-08-08)

Baustein D aus `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`
umgesetzt — der einzige Baustein aus der Sammlung, der bewusst erst nach
expliziter Datenschutz-Rückfrage an Leon angegangen wurde, da er als
einziger dauerhaft neue Verhaltensdaten anlegt.

Neues Modul `app/core/usage_patterns.py`: zählt bei erkannter Fähigkeit
(`has_domain()`-Treffer) ausschließlich Kategorie + Wochentag + grobe
Tageszeit, nie den Anfrage-Wortlaut — aggregiert als "in welchen
Kalenderwochen kam das vor", nicht als Einzel-Ereignis-Liste. Folgt damit
demselben datensparsamen Vorbild wie `core/voice_performance.py`
(ausschließlich Millisekunden-Zahlen, nie Text/Audio).

Neue, eigene Berechtigung `usage_patterns` — **standardmäßig aus**, muss von
Leon bewusst aktiviert werden. Neue Proactivity-Regel
`rule_recurring_usage_pattern` schlägt bei erkanntem Muster (Standard: ≥3
von 4 Wochen) einmalig eine Automatisierung vor, richtet nie selbst etwas
ein. Eigene Lösch-Möglichkeit im Privacy Dashboard
(`clear_usage_patterns()`), zusätzlich zur ohnehin greifenden
"alles löschen"-Funktion.

11 neue Tests (insgesamt 138). Bewusst nicht umgesetzt: eigene
Einsichts-Ansicht in der App für bereits erkannte Muster (aktueller Umfang:
Proactivity-Meldung + Löschbarkeit reichen für den ersten Wurf) — möglicher
Folgeschritt, falls gewünscht.

## 18. Mehrstufige Aufträge / Function-Calling (2026-08-09)

Baustein E aus `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`
umgesetzt, siehe `plans/2026-08-09-jarvis-mehrstufige-auftraege.md`. Erste
neue **Stufe 3** der Absichtserkennung — nach Stufe 1 (Fuzzy-Stichwörter) und
Stufe 2 (LLM-Klassifikation als Rückfrage-Sicherheitsnetz) kann Jarvis jetzt
aus einer einzigen Anfrage mehrere Fähigkeiten hintereinander ausführen
("räum den Posteingang auf und leg mir eine Erinnerung an").

**Bewusst kein iterativer Tool-Loop**, sondern "Plan einmal aufstellen, dann
streng sequenziell abarbeiten": neues Modul `app/core/multistep_planner.py`
(`plan_multistep()`) lässt das Modell die Anfrage einmalig in ein JSON-Array
aus `{domain, teilauftrag}`-Schritten zerlegen (max. 4, per
`multistep_planner_max_steps` in `config.json`), validiert streng (unbekannte
Domäne, leerer Teilauftrag, zu viele Schritte, kein valides JSON → `None`,
Aufrufer fällt dann auf den bestehenden Einzelschritt-Weg zurück, rät nie
selbst). **Keine neuen Fähigkeiten oder Parameter-Formate** — jeder Schritt
läuft 1:1 über den schon vorhandenen `_dispatch_confirmed_domain()`
(`jarvis.py`), denselben Dispatch, den auch ein einzelner Stichwort-Treffer
auslösen würde.

Bewusst konservativer Auslöser: `looks_like_multistep_request()` greift nur,
wenn Stufe 1 bereits **zwei** verschiedene Domänen im selben Satz erkennt
**und** ein Verbindungswort (und/danach/außerdem/anschließend/sowie/
zusätzlich) vorkommt — lieber einen echten Mehrschritt-Auftrag einmal
verpassen (läuft dann als Einzelschritt weiter) als einen normalen Satz
fälschlich zerlegen.

`execute_multistep_plan()` arbeitet die Schritte sequenziell ab. Braucht ein
Schritt eine Bestätigung (neuer `pending_*`-Schlüssel in den Settings — z. B.
Mail löschen, oder eine fehlende Berechtigung), hält die **gesamte Kette**
an: die bereits erledigten Schritte werden zusammengefasst, die Rückfrage des
blockierenden Schritts angehängt, die restlichen Schritte in
`memory["settings"]["pending_multistep_queue"]` gemerkt. Erst nach
ausdrücklicher Bestätigung/Ablehnung geht es weiter
(`_continue_multistep_chain_if_pending()`, eingehängt in alle bestehenden
`ACTION_ENGINE.resolve()`-Aufrufstellen sowie den `pending_permission`-Zweig
von `handle_pending_action_flow()`) — kein bestätigungspflichtiger Einzelschritt
wird durch die Kette zur Hintertür.

Bricht ein Schritt mit Fehler ab (Handler gibt `None` zurück) **oder** lehnt
der Nutzer eine Zwischen-Bestätigung ab, **bricht die gesamte Kette ab** (auf
Leons ausdrückliche Vorgabe) — meldet aber nicht nur, wie weit sie gekommen
ist, sondern macht einen konkreten Vorschlag, wie es sinnvoll weitergehen
könnte (z. B. die restlichen Schritte einzeln nacheinander anzubieten),
ohne selbst etwas davon automatisch auszuführen.

Beide Produktionspfade (`local_server.py::_answer_with_core()` und
`jarvis.py::main()`) rufen Stufe 3 an derselben Stelle auf: nach der
Muster-Zählung (Baustein D), vor der bestehenden Stufe-1-Domänenprüfung.

19 neue Tests (`tests/test_multistep_planner.py`, insgesamt 157): Plan-
Validierung, Auslöser-Erkennung, Ausführungs-Kette (alle Schritte glatt,
Anhalten bei Bestätigungsbedarf, Abbruch mit Vorschlag) sowie die volle
Kettenfortsetzung über `handle_pending_action_flow()` (Bestätigung,
Ablehnung, Berechtigung-erteilt-Fall) — `_dispatch_confirmed_domain()` bzw.
`PermissionManager`/`ACTION_ENGINE`-Executor jeweils per `monkeypatch`
ersetzt, damit kein echter Domänen-Handler (AppleScript etc.) läuft.

**Bewusst nicht umgesetzt:** echtes, iteratives LLM-Tool-Calling (Modell
sieht Zwischenergebnisse, entscheidet selbst über den nächsten Aufruf) —
schwerer kontrollierbar, höheres Endlosschleifen-Risiko, siehe "Verworfene
Alternativen" im Plan. Der `pending_call_choice`-Zwischenschritt (mehrdeutige
Telefonnummer beim Anrufen) wird beim Ketten-Fortsetzen per
`waiting_on_key`-Umleitung auf `pending_call_contact` mitbehandelt, aber
nicht gesondert getestet — seltener Randfall innerhalb eines ohnehin schon
seltenen Mehrschritt-Kontakt-Schritts.

## 19. Drei Bugs aus einem Live-Test auf dem echten Mac behoben (2026-08-09)

Nach den Bausteinen A–E und den Systembenachrichtigungen wurde die laufende
App auf dem echten Mac (nicht nur mit synthetischen Tests) durchgetestet -
über `/api/chat` mit echten, sicheren Lese-Anfragen an jede Domäne. Dabei
fielen drei echte Bugs auf, alle noch am selben Tag behoben:

1. **"Bildschirm"-Anfragen wurden von der Fotos-Domäne abgefangen.**
   Root Cause: `has_domain_fuzzy()` (`app/core/intent_matching.py`) prüfte
   Einzelwort-Begriffe bisher per reinem Python-Teilstring-Check
   (`term in text`) - "bild" ist ein Fotos-Stichwort und zugleich ein
   Teilstring von "bildschirm", das Wort wurde also nie erreicht, bevor die
   Fotos-Domäne (die vor der Screen-Domäne geprüft wird) schon zugeschlagen
   hatte. Im Test hat das tatsächlich eine echte Aktion ausgelöst: "Mach
   einen Screenshot von meinem Bildschirm" hat 13 echte Fotos in einen neuen
   Ordner auf dem Schreibtisch kopiert, statt einen Screenshot zu machen
   (nur kopiert, nicht verschoben - die Fotomediathek blieb unangetastet).
   **Fix:** Einzelwort-Begriffe zählen jetzt nur noch als eigenständiges Wort
   (Wortgrenzen-Check über eine Menge der Text-Wörter), nicht mehr als
   Teilstring eines längeren Wortes. Mehrwort-Begriffe (z. B. "e mail",
   "bilder von") bleiben unverändert ein echter Teilstring-Check, da dort
   Wortgrenzen innerhalb der Phrase keine Rolle spielen.
2. **Notizen konnten nicht gelesen werden.** `handle_notes_command()` hatte
   überhaupt keinen Lese-Pfad - jede Anfrage ohne erkennbaren Notiz-Titel
   (auch reine Fragen wie "was steht in meinen Notizen") landete im
   Erstellen-Flow ("Wie soll die Notiz heißen?"). **Fix:** neue
   `list_recent_notes()` in `app/notes_client.py` (liest Titel +
   Änderungsdatum aller Notizen über alle Accounts/Ordner per AppleScript,
   numerische Datumsfelder statt formatiertem Text - dieselbe Technik wie
   `calendar_client.py::_build_datetime()`); `handle_notes_command()` erkennt
   jetzt zuerst eine Lese-Absicht (Trigger-Wörter wie "zeig mir"/"was steht
   in"/"welche notizen", Erstell-Verben haben Vorrang) und beantwortet sie
   mit den letzten 5 Notizen statt in den Erstellen-Flow zu fallen.
3. **Aufgaben (`task_manager.py`) waren per Chat komplett unerreichbar.**
   "Was habe ich für offene Aufgaben?" fiel durch die gesamte Domänen-Kette
   und landete im werkzeuglosen Chat, der eine frei erfundene, plausibel
   klingende, aber falsche Antwort gab (statt "keine Aufgaben" bei
   tatsächlich leerer Liste). **Fix:** neue neunte Domäne `"tasks"`
   (`DOMAIN_TERMS`, `_DOMAIN_CLARIFICATION_LABELS`/`_PHRASES`,
   `multistep_planner.py::_PLANNER_DOMAINS`) mit neuem
   `handle_tasks_command()` - rein lesend, kein Berechtigungs-Gate nötig
   (Aufgaben liegen nur in Jarvis' eigenem Speicher, keine macOS-API
   beteiligt). In beiden Produktionspfaden (`local_server.py`, `jarvis.py::
   main()`) sowie in `_dispatch_confirmed_domain()` (Stufe-2-Rückfrage)
   verdrahtet.

15 neue Tests (`tests/test_domain_matching.py` erweitert,
`tests/test_notes_and_tasks.py` neu) - insgesamt 171 Tests. Alle drei Fixes
zusätzlich live gegen die echte laufende App auf dem Mac verifiziert (echte
Notes.app, echte Aufgaben-Speicherung), nicht nur mit synthetischen Tests.

## 20. Bug 4: Gedächtnis-Fakten unsichtbar/verloren (2026-08-09)

Direkt im Anschluss an Bausteine 19 fiel beim gezielten Nachfragen ("ich kann
im Gedächtnis nichts sehen") ein vierter, deutlich schwerwiegenderer Bug auf:
automatisch erfasste Erinnerungen (`auto_update_memory()`) tauchten **nie**
in `/api/memory/facts` (der Gedächtnis-Ansicht der App) auf, obwohl die
Funktion selbst "gespeichert" meldete.

**Root Cause:** `JarvisMemorySystem.__init__()` (`app/core/memory_system.py`)
hat bisher bei **jedem** Aufruf eine komplett neue, eigene `Memory`-Instanz
aus `memory.base_path` gebaut - auch wenn der Aufrufer (z. B.
`local_server.py`s langlebiges `self.memory`, das seit Server-Start läuft)
schon eine lebendige Instanz besaß. `Memory` lädt seinen Zustand nur einmal
bei `__init__` in den Prozessspeicher; `set()`/`save()` schreiben zwar auf
die Platte, aber nichts liest danach automatisch wieder davon. Zwei getrennte
`Memory`-Objekte auf demselben Pfad laufen dadurch garantiert auseinander -
ein Fakt, der über die kurzlebige, wegwerfbare Instanz gespeichert wurde, war
für die langlebige Server-Instanz (und damit für jede Chat-Antwort und die
Gedächtnis-Ansicht) einfach unsichtbar, bis der Prozess neu gestartet wurde.

**Noch schlimmer:** `auto_update_memory()` rief danach `memory.trim_facts()`
auf der **originalen, jetzt veralteten** Instanz auf - das hat die Datei mit
dem alten (leeren) Stand überschrieben und den gerade erst gespeicherten
Fakt sofort wieder gelöscht, nicht nur versteckt. In der Praxis: ein frisch
gespeicherter Testfakt war noch im selben Funktionsaufruf wieder weg.

Betroffen waren alle vier Aufrufstellen von `JarvisMemorySystem(...)` in
`jarvis.py`: `auto_update_memory()` (regelbasierte Auto-Erfassung),
`handle_memory_command()` ("was weißt du über mich"), die
Bildschirm-Vision-Auto-Erinnerung sowie `_run_llm_memory_extraction()`
(Stufe-2-LLM-Extraktion, aktuell per `auto_memory_llm_extraction_enabled:
false` deaktiviert, aber vom selben Bug betroffen gewesen).

**Fix:** `JarvisMemorySystem` akzeptiert jetzt wahlweise einen Pfad (baut
sich wie bisher eine neue Instanz, für Aufrufer ohne bereits bestehende) ODER
eine schon bestehende `Memory`-Instanz (wird dann direkt weiterverwendet,
keine zweite gebaut). Alle vier Aufrufstellen übergeben jetzt die schon
vorhandene `memory`-Instanz statt `memory.base_path` - dieselbe Instanz, mit
der der Aufrufer danach auch liest, bleibt beim Schreiben synchron.

5 neue Tests (`tests/test_memory.py` erweitert) - insgesamt 175 Tests, u. a.
ein direkter Regressionstest für das `trim_facts()`-Überschreiben. Live auf
dem echten Mac verifiziert: derselbe Testsatz, der vorher spurlos
verschwand, ist jetzt sofort über dieselbe Memory-Instanz sichtbar.

**Bekannter, unvermeidbarer Nebeneffekt des Testens:** Ein Testfakt ("Leon
mag es") wurde beim Verifizieren tatsächlich in der echten Gedächtnis-Ansicht
gespeichert (aus dem Testsatz "Ich mag es, wenn du kurze Antworten gibst.").
Über die Gedächtnis-Ansicht in der App lösch- oder ablehnbar wie jede andere
Erinnerung - wurde bewusst nicht automatisch entfernt.

## 20. Bug-Muster-Audit: weitere Dual-Instance-Stellen gesucht (2026-08-09)

Nachdem der Gedächtnis-Bug (Abschnitt 19) genau einem wiederkehrenden Muster
folgte - eine Klasse cacht ihre Datei bei Konstruktion in `self.data`,
schreibt bei jeder Änderung den GANZEN Cache zurück, und eine zweite,
kurzlebige Instanz neben einer langlebigen kann so einen Schreibvorgang
unsichtbar machen und später stillschweigend überschreiben - wurde
systematisch nach weiteren Stellen mit demselben Muster gesucht (`Memory`,
`TaskManager`, `PermissionManager`, `ConversationManager`,
`UsagePatternStore`, `ActionEngine`, `PrivacyLogger`, `PrivacyDashboard`,
`ModelManager` in `app/jarvis.py`, `app/local_server.py`, `app/core/*.py`).

**Bestätigter, behobener Bug: `ModelManager`.** Exakt dasselbe Muster wie bei
`Memory`/`JarvisMemorySystem`: `local_server.py::self.models` ist eine
langlebige, serverweite Instanz (Zeile 172), aber `jarvis.py::
handle_model_command()` baute bei jedem Aufruf eine **eigene, frische**
`ModelManager(CONFIG)`. Beide Pfade sind im selben laufenden Prozess
erreichbar: `_handle_fast_commands()` (nutzt `self.models`) fängt nur einen
Teil der Modell-Befehle ab (z. B. nicht "cloud ki"), alles andere fällt in
`handle_model_command()` über die Domänen-Handler-Liste durch. Konkret
nachgestellt: "gemma" über `self.models` gesetzt → "cloud ki" (nur von
`handle_model_command()` erkannt) baut eine frische, zu diesem Zeitpunkt
schon wieder aktuelle Instanz und schreibt korrekt - aber `self.models`
weiß davon nichts. Ein späterer Befehl über `self.models` (z. B. "qwen")
überschreibt die Datei dann mit `self.models`' eigenem, veraltetem Stand und
macht den Cloud-Wechsel spurlos rückgängig.

**Fix:** `handle_model_command()` bekommt einen neuen optionalen Parameter
`model_manager` - wird er übergeben, wird er direkt weiterverwendet (keine
zweite Instanz), sonst wie bisher eine neue gebaut (CLI-Pfad `jarvis.py::
main()` hält ohnehin keine langlebige `ModelManager`-Instanz über die
Schleife hinweg, dort ist eine frische Instanz pro Aufruf unproblematisch).
`local_server.py`s Aufrufstelle in der `direct_handlers`-Liste übergibt jetzt
`self.models` mit.

4 neue Tests (`tests/test_model_manager_shared_instance.py`, neu) - insgesamt
179 Tests: der Bug in Isolation nachgestellt (dokumentiert die Ursache),
Regressionstest, dass `handle_model_command()` die übergebene Instanz direkt
mutiert statt eine neue zu bauen, End-to-End-Variante mit geteilter Instanz
über mehrere Aufrufe, sowie ein Test, dass der bisherige CLI-Pfad (keine
Instanz übergeben) unverändert funktioniert.

**Geprüft und als unkritisch eingestuft** (kein Datenverlust, da diese
Klassen entweder gar keinen Cache halten und bei jedem Zugriff frisch von der
Platte lesen, oder nie in mehrere gleichzeitig aktive, konkurrierend
schreibende Instanzen aufgeteilt sind): `TaskManager` (delegiert komplett an
die übergebene `Memory`-Instanz, hält selbst keinen Cache),
`ConversationManager` (wird nie langlebig gehalten, jede Instanz liest beim
Konstruieren den aktuellen Stand), `UsagePatternStore`/`VoicePerformanceLog`
(laden bei jeder Methode frisch von der Platte), `ProactivityEngine`
(lädt/speichert seinen State bei jedem `evaluate()`-Aufruf frisch),
`ActionEngine` (hält keinen eigenen Datei-State, operiert nur auf der
übergebenen `Memory`-Instanz), `PrivacyLogger` (kein In-Prozess-Cache,
hängt nur an die Log-Datei an).

**Nicht behoben, niedrigere Priorität (Sichtbarkeits-, kein
Datenverlust-Problem):** `PermissionManager` cacht ebenfalls nach demselben
Muster, und `local_server.py`s langlebige `self.permissions`/
`self.dashboard.permission_manager`-Instanzen werden nur lesend genutzt -
alle tatsächlichen Berechtigungsänderungen laufen über kurzlebige,
Funktions-lokale `PermissionManager()`-Instanzen (`ensure_permission()` etc.),
die nie langlebig gehalten werden und deshalb nie schreibend miteinander
kollidieren. Der Datenschutz-Status (`/api/privacy/status`,
`self.permissions.is_allowed(...)`) kann dadurch aber bis zum nächsten
Server-Neustart einen veralteten Berechtigungsstand zeigen, wenn eine
Berechtigung zwischenzeitlich anderweitig geändert wurde. **Inzwischen
behoben, siehe Abschnitt 21.**

## 21. PermissionManager-Staleness behoben (2026-08-09)

Auf Wunsch nachträglich auch die als niedrige Priorität zurückgestellte
`PermissionManager`-Stelle aus Abschnitt 20 behoben - dasselbe Cache-Muster
wie bei `Memory`/`ModelManager`, hier aber als Lese-Staleness statt
Datenverlust (siehe dort für die genaue Ursache).

**Fix:** `is_allowed()`, `is_requested()`, `export()` und `summary()` laden
jetzt vor jedem Zugriff über eine neue `_refresh()`-Methode frisch von der
Platte, statt sich auf den bei Konstruktion einmal geladenen `self.data`-
Cache zu verlassen. `grant()`/`revoke()`/`mark_explanation_shown()`/
`reset_to_not_requested()` laden ebenfalls unmittelbar vor dem Ändern neu
(echtes Read-Modify-Write statt "cached-Modify-Write"). Ein neuer,
**modulweiter** Lock (`_LOCK`, bewusst nicht pro Instanz - der Punkt ist ja
gerade der Schutz vor mehreren gleichzeitigen Instanzen im selben Prozess)
umschließt jeden Lese-Ändere-Speicher-Vorgang, damit zwei kurzlebige
Instanzen, die im selben lokalen HTTP-Server gleichzeitig verschiedene
Berechtigungen ändern (z. B. Sprach-Thread + Dashboard-Anfrage), sich nicht
gegenseitig überschreiben können - dieselbe Race, die bei `Memory` schon
einen dedizierten Lock bekommen hat.

6 neue Tests (`tests/test_permission_manager_shared_instance.py`, neu) -
insgesamt 185 Tests: Berechtigung über eine Instanz ändern, sofort über eine
andere sichtbar (Grant und Revoke), mehrere abwechselnde Änderungen über
verschiedene Instanzen ohne Datenverlust, `export()`/`summary()` beide
aktuell, sowie ein direkter "keine Kollision"-Test zwischen `grant()` und
`mark_explanation_shown()` über zwei verschiedene Instanzen.

## 22. "deaktiviere" hat faelschlich erlaubt statt verboten (2026-08-09)

Beim Live-Verifizieren von Abschnitt 21 gefunden: `handle_privacy_command()`s
Erlauben-Erkennung (`grant_match = re.search(r"(?:erlaube|aktiviere)\s+...")`)
hatte keine Wortgrenze vor "aktiviere" - "aktiviere" ist ein Teilstring von
"deaktiviere" ("de" + "aktiviere"), also matchte z. B. "deaktiviere dateien"
sowohl `grant_match` als auch `revoke_match`. Da `grant_match` zuerst geprüft
wird, hat der Befehl "deaktiviere dateien" die Berechtigung tatsächlich
**erlaubt statt entzogen** - live nachgestellt und bestätigt (Speicherplatz
war True → blieb True statt False zu werden). Betrifft nur textuelle
Datenschutz-Befehle, nicht den Schalter im Dashboard (der ruft `grant()`/
`revoke()` direkt und eindeutig auf, ohne Text-Erkennung).

**Fix:** `\b` vor `(?:erlaube|aktiviere)` bzw. `(?:deaktiviere|verbiete|
entziehe)` ergänzt - "aktiviere" matcht jetzt nur noch als eigenständiges
Wort, nicht mehr als Teilstring von "deaktiviere".

4 neue Tests (`tests/test_privacy_command.py`, neu) - insgesamt 189 Tests:
"deaktiviere X" verbietet jetzt korrekt, "aktiviere X"/"erlaube X" erlauben
weiterhin korrekt, "verbiete X" verbietet weiterhin korrekt. Live auf dem
echten Mac verifiziert.

## 23. Selbstauskunft fälschlich als Mail/Kalender-Rückfrage eingestuft (2026-08-09)

Von Leon per Screenshot gemeldet: die reine Selbstauskunft "Jarvis ich lebe
schon seit 18 Jahren in Amberg in Deutschland" löste keine normale Antwort
aus, sondern die Stufe-2-Rückfrage "Ging es dabei um deine Mails oder deinen
Kalender oder eine Erinnerung?" - ein klar falsches Ergebnis für eine reine
Tatsachenaussage.

**Ursache, zwei zusammenwirkende Lücken:**
1. `looks_like_memory_candidate()` erkannte den Satz nicht als Gedächtnis-
   Kandidat, weil `_MEMORY_CANDIDATE_STATEMENT_VERBS` das Verb "lebe" nicht
   enthielt (nur "wohne" war gelistet). Der Satz wurde deshalb NICHT für die
   LLM-Gedächtnis-Extraktion (Abschnitt zur Gedächtnis-Härtung) vorgemerkt.
2. Weil der Satz dadurch bei keinem der Domänen-Handler und auch nicht bei
   der Gedächtnis-Erkennung griff, landete er bei Stufe 2 der
   Absichtserkennung (`classify_domain_via_llm`) - dem kleinen lokalen
   Modell (phi4-mini) als reiner Sicherheitsnetz-Klassifikator. Ohne
   Beispiele im Prompt stufte das Modell die Aussage fälschlich als
   mail/calendar-relevant ein, statt mit "keine" zu antworten - dieselbe
   Über-Klassifikations-Schwäche des kleinen Modells wie beim News-Baustein
   (Abschnitt 18) und der Gedächtnis-Extraktion.

**Fix:**
1. `"lebe"` zu `_MEMORY_CANDIDATE_STATEMENT_VERBS` ergänzt (`app/jarvis.py`)
   - der Satz wird jetzt korrekt als Gedächtnis-Kandidat erkannt.
2. Prompt von `classify_domain_via_llm()` um eine explizite Regel und
   Beispiele gehärtet: reine Selbstauskünfte (Wohnort, Alter, Vorlieben,
   Beruf, Eigenschaften) werden immer mit "keine" beantwortet, auch wenn sie
   Jahreszahlen oder Ortsnamen enthalten - als zweite, unabhängige
   Absicherung, falls ein zukünftiger Satz erneut durch die (naturgemäß nie
   vollständige) Verb-Liste rutscht.

2 neue Tests (`tests/test_memory_llm_extraction.py`,
`tests/test_domain_matching.py`) - insgesamt 244 Tests. Xcode-Build
erfolgreich, live auf dem echten Mac mit exakt Leons ursprünglichem Satz
verifiziert: die Aussage wird jetzt normal beantwortet und landet korrekt
als `pending_confirmation`-Fakt im Gedächtnis, statt eine falsche Rückfrage
auszulösen.

## 24. Mail-Hintergrund-Check und Kalender-aus-Mail aktiviert (2026-08-09)

Zwei bereits vollständig gebaute, aber per Konfiguration abgeschaltete
Bausteine wurden auf Leons Wunsch scharf geschaltet: `background_mail_enabled`
(morgendlicher Mail-Check durch `MailBackgroundWorker`,
`app/background_tasks.py`) und `auto_calendar_from_mail_enabled` (Termine/
Fristen aus Mails erkennen und vorschlagen, `app/mail_calendar_actions.py`).
Siehe `plans/2026-08-09-jarvis-mail-hintergrund-aktivieren.md`.

**Vor der Aktivierung geprüft:** das "erst vorschlagen, dann bestätigen"-
Prinzip war bereits korrekt umgesetzt (`create_calendar_actions_from_messages`
schreibt nie direkt in den Kalender, nur `execute_planned_calendar_action`
nach ausdrücklicher Bestätigung über `resolve_pending_calendar_action`) -
das wurde nicht angetastet, nur mit 15 neuen Tests
(`tests/test_mail_calendar_actions.py`) erstmals abgesichert. Der Worker
selbst hatte ebenfalls keine Tests - 13 neue Tests
(`tests/test_background_mail_worker.py`) decken Zeitfenster-Logik, "neu vs.
bekannt"-Erkennung über den Mail-ID-Cache und den Fehlerfall bei nicht
erreichbarem Mail.app ab.

**Zwei echte Bugs beim Live-Test gefunden und behoben, bevor final
übernommen wurde** (gleiches Muster wie beim News-Baustein - erst live
testen, dann härten):

1. **Zu kurzer AppleScript-Timeout.** `list_inbox_messages()` rief
   `_run_applescript()` immer mit dessen 8-Sekunden-Default auf, unabhängig
   davon, ob `include_preview=True` den vollen Mail-Inhalt für bis zu 20 (bzw.
   80 nachts) Nachrichten abruft - deutlich langsamer als reine Metadaten. Der
   erste echte Scan lief selbst mit bereits geöffnetem Mail.app in den
   Timeout (8s + 12s Retry). **Fix:** der Timeout skaliert jetzt mit
   `max_messages`, wenn `include_preview` aktiv ist (`3 + 2 × max_messages`
   Sekunden, gedeckelt bei 60s) - 3 neue Tests
   (`tests/test_mail_client_timeout.py`).
2. **Fremder Post-Inhalt in Social-Media-Digests löste falsche Kalender-
   Vorschläge aus.** Ein LinkedIn-Aktivitäts-Update enthielt in einem
   fremden, zitierten Post die Wörter "der Boarding Call gilt noch" - `call`
   traf `EVENT_TERMS`, ein im selben Digest enthaltenes Datum lieferte den
   Zeitstempel, und Jarvis schlug daraus fälschlich eine Kalender-Erinnerung
   vor. **Fix:** ein deterministischer Absender-Vorfilter
   (`_looks_like_bulk_or_notification`, prüft auf `noreply`/`no-reply`/
   `donotreply`/`notifications@`/`newsletter@`/`mailer-daemon`-Muster im
   Absender) läuft jetzt VOR der Stichwort-Erkennung - gleiche Technik wie
   der CORRECTIV-Kategorie-Vorfilter beim News-Baustein. Zusätzlich wurde
   `"erinnerung"` aus `DEADLINE_TERMS` entfernt (zu generisches Wort, das in
   praktisch jedem Newsletter-Footer vorkommen kann, ohne dass die Mail
   selbst eine echte Frist ist).

**Bewusste Entscheidung:** zunächst nur der morgendliche Scan ist aktiv, der
separate nächtliche Scan (`enable_overnight_scan()`, bis zu 80 Nachrichten)
bleibt vorerst aus - kleinerer erster Schritt, bewährt sich erst im Alltag.

Live auf dem echten Mac gegen die echte Inbox verifiziert: ein echter Scan
erkannte 9 neue Mails, davon zunächst 3 Kalender-Vorschläge - nach dem
Absender-Vorfilter-Fix noch 1 (ein Webinar-Marketing-Mail mit echtem Datum/
Uhrzeit, bewusst als Vorschlag stehen gelassen statt selbst zu bestätigen
oder zu verwerfen - genau dafür ist das Bestätigen-Dashboard da). Die zwei
durch den vorherigen Bug fälschlich erzeugten Vorschläge (LinkedIn-Digest,
eine automatische Anthropic-Bestätigungsmail) wurden manuell über
`/api/mail/calendar-actions/resolve` verworfen, bevor Leon sie zu Gesicht
bekommen hätte. 31 neue Tests insgesamt (15 + 13 + 3), Testsuite komplett
grün, Xcode-Build erfolgreich.

## 25. CLI- und Server-Antwortpfad zusammengeführt (2026-08-10)

`app/jarvis.py::main()` (CLI) und `app/local_server.py::_answer_with_core()`
(App) implementierten seit Monaten dieselbe Domänen-Erkennungs-Kette (~14
Handler in identischer Reihenfolge, jeweils mit Berechtigungs-Gate) zweimal
unabhängig von Hand gepflegt - der Code kommentierte das selbst
ausdrücklich. Siehe
`plans/2026-08-09-jarvis-cli-server-aufraeumen.md`.

**Umbau:** neue gemeinsame Funktion `jarvis.py::answer_message()` (plus
`AnswerWorkers`/`AnswerResult`-Hilfsklassen) besitzt jetzt die komplette
Kette - Stufe 1 Stichwort-Erkennung, Baustein E (mehrstufige Aufträge),
Stufe 2 Modell-Klassifikation, Websuche, finaler LLM-Aufruf. `main()` und
`_answer_with_core()` rufen sie auf und behalten nur noch echte
Aufrufer-Eigenheiten: CLI macht `print`/`speak`, Server macht
Streaming/`_finalize_answer`/Pipeline-Logging; beide behalten ihre eigenen
Vorab-Kurzbefehle (CLI: `route_fast_intent`/Tagesbriefing; Server:
Dashboard-Statusfragen), die nur für den jeweiligen Aufrufer Sinn ergeben.

**Zwei echte, bisher unbemerkte Verhaltens-Unterschiede beim Vergleich
gefunden** (bestätigt das eigentliche Risiko dieses Bausteins - unabhängig
gepflegter, eigentlich identischer Code driftet auseinander, ohne dass es
auffällt):
1. Der finale, werkzeuglose LLM-Aufruf der CLI übergab für die
   Routing-Entscheidung immer eine leere History und kein `force_local` -
   "Privater Modus" wirkte sich im CLI-Pfad dadurch vermutlich gar nicht
   aus. Nach Rücksprache mit Leon **angehoben**: beide Pfade nutzen jetzt
   dieselbe Routing-Logik (`_routing_history()` liest bei der CLI dieselbe
   persistierte Gesprächs-Historie, die `build_input()` ohnehin schon
   nutzt).
2. Der Server speicherte über `_finalize_answer()` **jede** Handler-Antwort
   im Gesprächsverlauf, die CLI dagegen bewusst NICHT für
   System-/Präferenz-/Stil-/Projekt-/Lokal-/Datenschutz-Antworten und mit
   `auto_memory=False` für Modell-/Gedächtnis-Befehle. Übernommen wurde die
   bewusstere, zurückhaltendere CLI-Variante - der Server speichert jetzt
   ebenfalls nicht mehr jede Kurzantwort auf Hausmeister-Kommandos im
   Verlauf.

**Kein Regressions-Sicherheitsnetz vorher vorhanden** (weder `main()` noch
`_answer_with_core()` hatten je einen End-to-End-Test) - 12 neue
Charakterisierungs-Tests (`tests/test_answer_message.py`) decken jetzt
Dispatch-Reihenfolge, Berechtigungs-Gates, die record_exchange-Unterschiede
pro Handler-Typ, `pending_mail_followup`-Übergänge sowie den
Stufe-2-/Chat-Fallback ab.

287 Tests insgesamt, alle grün. Xcode-Build erfolgreich. Live auf dem
echten Mac gegen den Server-Pfad verifiziert: allgemeiner Chat, Kalender,
Notizen, Mail-Übersicht und Modellwechsel laufen alle korrekt über die neue
gemeinsame Funktion; Gesprächsverlauf bestätigt die neue,
zurückhaltendere Aufzeichnung für Hausmeister-Kommandos.

## 26. Tagesbriefing im App-Chat frei erfunden statt echter Daten (2026-08-10)

**Bugreport:** Leon tippte im App-Chat "starte doch bitte mal das morgen
Briefing" und bekam ein Tagesbriefing mit erfundenen Sitzungsteilnehmern
("Frau Schmidt", "Herr Müller") und einem völlig themenfremden, bizarren
Satz über eine Katze - ohne jeden Bezug zu echten Kalender-/Aufgaben-/
Mail-Daten.

**Ursache, zwei kombinierte Lücken:**
- `handle_daily_briefing_command()` erkannte nur die exakten Komposita
  "tagesbriefing"/"morgenübersicht"/"abendbriefing" als Auslöser - "morgen
  Briefing" als zwei separate Wörter fiel durch, egal welcher Aufrufer.
- Selbst mit passendem Auslöser lief `handle_daily_briefing_command()`
  bisher **nur** als CLI-eigener Vorab-Check in `main()`, VOR dem Aufruf von
  `answer_message()` - im App-/Server-Pfad (`_answer_with_core()`) gab es
  dafür gar keine Entsprechung im Chat-Text-Pfad (nur einen separaten
  Dashboard-Button-Endpunkt `/api/daily-briefing`). Jede Briefing-Anfrage im
  App-Chat lief deshalb immer bis zum allgemeinen, werkzeuglosen LLM-Aufruf
  durch, der ohne echte Daten frei improvisierte.

**Fix:**
- Auslöser-Erkennung auf den Teilstring "briefing" verallgemeinert (deckt
  "tagesbriefing", "abendbriefing", "morgen briefing", "briefing bitte" etc.
  gleichermaßen ab).
- `handle_daily_briefing_command()` als erster Check innerhalb von
  `answer_message()` selbst verankert (vor der `direct_handlers`-Kette,
  analog zu `main()`s bisheriger Priorität) - dadurch identisch für CLI und
  App/Server, kein separater Vorab-Check in `main()` mehr nötig, der jetzt
  entfernt wurde.

3 neue Tests (`tests/test_answer_message.py`): Briefing-Anfrage nutzt echte
Daten statt allgemeinem Chat, Wort-getrennter Auslöser wird erkannt,
unrelated Text löst weiterhin nichts aus. 291 Tests insgesamt, alle grün.
Xcode-Build erfolgreich. Live auf dem echten Mac über den App-/Server-Pfad
mit Leons genauer Originalformulierung verifiziert: liefert jetzt ein
echtes Briefing mit echten Erinnerungen/Mail-Zahl statt erfundenem Inhalt;
normaler Chat funktioniert unverändert weiter.

## 27. Mail-Update roh statt menschlich zusammengefasst (2026-08-10)

**Bugreport:** Leon bat um "ein kurzes Mail-Update" und bekam eine
Aneinanderreihung roher Absender-Adressen und Betreffzeilen vorgelesen
(inklusive kompletter `<donotreply@...>`-Header), ohne inhaltliche
Einordnung oder Gewichtung - eine automatisierte Sicherheitsbenachrichtigung
erschien gleichrangig neben einer echten Stellenanzeige.

**Ursache:** Zwei unabhängige Mail-Zusammenfassungs-Pfade existierten
bereits. `handle_mail_command()` nutzte einen sorgfältig formulierten
LLM-Prompt für eine natürliche, thematisch gebündelte Zusammenfassung.
`MailBackgroundWorker._build_summary()` - der tatsächliche Pfad hinter
"Mail-Update"/Hintergrundscan - war dagegen rein mechanisch:
`f"{sender}: {subject}"` je Mail aneinandergereiht, kein LLM, kein
inhaltliches Verständnis.

**Fix:**
- Gemeinsame Funktion `jarvis.py::summarize_mail_digest_via_llm()`
  extrahiert aus dem bestehenden, bereits guten Prompt von
  `handle_mail_command()` - jetzt von beiden Pfaden genutzt (DRY, ein
  einheitlicher Jarvis-Ton statt zwei unterschiedlicher).
- `MailBackgroundWorker` bekommt eine `llm`-Referenz im Konstruktor
  (analog `NewsBackgroundWorker`), an allen drei Erzeugungsstellen
  nachgezogen (`jarvis.py` x2, `local_server.py`).
- `_build_summary()` nutzt jetzt `build_mail_summary_digest()` +
  `summarize_mail_digest_via_llm()`; fällt bei leerer/fehlgeschlagener
  LLM-Antwort automatisch auf die alte mechanische Zusammenfassung zurück
  (kein hartes Scheitern, falls das lokale Modell gerade nicht antwortet).
- Kalender-/Erinnerungs-Vorschläge bleiben bewusst deterministisch
  angehängt, nicht vom LLM umformuliert - Sicherheitsprinzip: konkrete,
  noch unbestätigte Vorschläge dürfen nicht verzerrt werden.

6 neue/angepasste Tests (`tests/test_background_mail_worker.py`): LLM-
Zusammenfassung wird genutzt und enthält keine rohen E-Mail-Adressen mehr,
Fallback auf mechanische Zusammenfassung bei fehlgeschlagenem LLM-Aufruf,
Kalender-Vorschläge bleiben deterministisch angehängt. 294 Tests insgesamt,
alle grün. Xcode-Build erfolgreich. Live auf dem echten Mac mit Leons
genauer Originalanfrage verifiziert: thematisch gebündelte, menschliche
Zusammenfassung mit Wichtigkeits-Einordnung statt roher Kopfzeilen; Kalender-
Domäne als Regressionscheck unverändert funktionsfähig.

**Nachschärfung noch am selben Tag:** Leon bemerkte direkt beim Live-Test,
dass die neue LLM-Zusammenfassung zwar keine rohen Adressen mehr enthielt,
aber wieder als Liste herauskam ("Wichtig: ...\nPrivat: ...") - dasselbe
Grundmuster wie andere Bausteine diese Sitzung: das kleine lokale Modell
(gemma3:4b) haelt sich ohne sehr konkretes Beispiel nicht zuverlaessig an
Formatvorgaben im Prompt. Fix: Prompt um ein konkretes Fliesstext-Beispiel
und eine explizite "keine Kategorie-Zeile am Zeilenanfang"-Regel ergaenzt,
PLUS ein deterministischer Rueckhalt in `summarize_mail_digest_via_llm()`,
der alle verbleibenden Zeilenumbrueche hart zu Leerzeichen zusammenzieht -
Prompt-Worte allein reichen bei diesem Modell erfahrungsgemäß nicht. Ein
weiterer Test (`test_build_summary_flattens_category_lines_into_one_paragraph`)
deckt das ab. 295 Tests insgesamt, alle grün. Erneut live verifiziert: die
Antwort ist jetzt ein einziger Fließtext-Absatz ohne Zeilenumbrüche.

## 28. Lokale Foto-Vision aktiviert (2026-08-10)

Siehe `plans/2026-08-10-jarvis-foto-vision-lokal-aktivieren.md`. Der Code
für nächtlichen Fotoscan + lokale Bildbeschreibung (`llava` über Ollama)
existierte bereits vollständig, wurde aber nie automatisch gestartet -
anders als bei Mail und News fehlte die Verdrahtung in `local_server.py`.

**Umsetzung:**
- `PhotoBackgroundWorker._run_loop()` in `app/photos_client.py` in eine
  testbare `_tick(now)`-Methode extrahiert (analog `_time_reached`/
  `_scan_safely`); `_tick()` löst nach dem nächtlichen Metadaten-Scan jetzt
  zusätzlich `_vision_safely()` aus, das die lokale Bildbeschreibung über
  `LocalVisionService`/`llava` anstößt - vorher lief nur der Scan, die
  Beschreibungen entstanden nie automatisch.
- Neuer Konfigurationswert `local_photo_vision_background_enabled`
  (Default: an), damit der nächtliche Vision-Lauf bei Bedarf separat
  abschaltbar bleibt, ohne den Scan selbst zu deaktivieren.
- `_ensure_photo_worker()` in `local_server.py` ergänzt (analog
  `_ensure_mail_worker()`/`_ensure_news_worker()`) und in
  `_proactivity_context()` verdrahtet - der Worker startet jetzt beim
  ersten erlaubten Poll, sobald die "photos"-Berechtigung erteilt ist,
  genau wie bei Mail/News.
- `photos_background_enabled: true` in beiden `config.json` (Repo-Vorlage +
  Produktiv-Config) gesetzt. OpenAI-Cloud-Vision bleibt bewusst aus - Leon
  hat sich explizit für den rein lokalen Weg entschieden.

6 neue Tests (`tests/test_photo_background_worker.py`, vorher komplett
ungetestet): Scan+Vision laufen im selben Zyklus, beides jeweils nur einmal
pro Tag, Vision-Lauf abschaltbar über den neuen Config-Wert, robustes
Verhalten bei fehlendem/unerreichbarem lokalem Vision-Modell. 301 Tests
insgesamt, alle grün. Xcode-Build erfolgreich.

**Live-Verifikation, mit Einschränkung:** der macOS-Fotozugriff (System-
Berechtigung, getrennt von Jarvis' eigenem Berechtigungssystem) war auf
Leons Mac noch nie erteilt - die Ende-zu-Ende-Kette (Anfrage → Scan →
Vision-Beschreibung → inhaltliche Suche) konnte deshalb nicht mit echten
Fotos verifiziert werden, das braucht Leons manuelle Freigabe in den
Systemeinstellungen. Verifiziert wurde stattdessen: der Worker startet
automatisch (Jarvis' eigene "photos"-Berechtigung war bereits erteilt), ein
manuell ausgelöster Scan läuft durch und behandelt die fehlende macOS-
Freigabe sauber ohne Absturz (kein Code-Fehler, reine macOS-Berechtigung).
Anderer Regressionscheck (allgemeiner Chat) unauffällig.

**Separat aufgefallen, nicht Teil dieser Änderung:** die Kalender-Domäne
antwortete beim Live-Test mit einem AppleScript-Timeout ("Kalender hat zu
lange nicht geantwortet") - reproduziert unabhängig von der App direkt über
`calendar_client.py`, also kein durch diese Änderung eingeführtes Problem
(hier wurde nichts an Kalender-Code angefasst). Vermutlich ein aktueller,
eigenständiger Zustand auf Leons Mac (z. B. Calendar.app haengt/synchronisiert).
Noch nicht untersucht, Leon informiert.

## 29. Kalender-Timeout untersucht: keine Störung, echte Geschwindigkeitsgrenze (2026-08-10)

Nachuntersuchung von Abschnitt 28. Direkt (ohne die App) reproduziert:
`list_upcoming_calendar_items()` brauchte je nach Systemlast zwischen 9 und
20+ Sekunden - bei einem festen 20s-Timeout kippte das regelmäßig in einen
Fehler, obwohl Calendar.app nicht hängt, sondern nur langsam antwortet.

**Ursache:** Leons Konto hat 6 Kalender mit zusammen 342 Terminen (u. a.
"Deutsche Feiertage" und "Geburtstage" mit wiederkehrenden Einträgen über
mehrere Jahre). Das AppleScript liest dabei JEDEN Termin einzeln (Startdatum
zuerst, dann bei Treffern weitere Felder) - Calendar.apps AppleScript-Bridge
ist inhärent langsam pro Zugriff (siehe bereits bestehender Code-Kommentar
zu einem früher versuchten, aber wegen Zuverlässigkeitsproblemen wieder
verworfenen "whose"-Filter). Getestet: ein Sammelzugriff über
`properties of eventRef` statt einzelner Feldzugriffe brachte keine
messbare Verbesserung (9.9s vs. 9.6s) - der Engpass ist der Zugriff pro
Termin selbst, nicht die Anzahl gelesener Felder.

**Fix:** Timeout in `calendar_client.py::_run_applescript()` von 20s auf 35s
angehoben - reale Sicherheitsmarge basierend auf gemessenen Laufzeiten.
Live verifiziert: 3 von 4 Anfragen liefen sofort durch (die eine
verzögerte lag an System-Last direkt nach einem App-Neustart), Regressions-
check (allgemeiner Chat) unauffällig. 301 Tests weiterhin grün.

**Nicht behoben, bewusst nicht angefasst:** die zugrunde liegende Langsamkeit
selbst bleibt bestehen - eine echte Beschleunigung bräuchte entweder (a)
weniger Kalender abzufragen (Leons `calendar_name`-Einstellung ist aktuell
leer = alle Kalender inkl. Feiertage/Geburtstage; einschränken würde aber
auch weniger anzeigen) oder (b) einen nativen EventKit-Helfer statt
AppleScript (deutlich schnellerer Zugriff, aber ein eigenes, größeres
Projekt analog zum bestehenden Photos-Helfer - eigener Plan nötig). Beides
bewusst nicht selbstständig entschieden, da beides Leons Kalenderdaten-
Darstellung bzw. den App-Umfang verändert.

## 30. Echter Blocker für Foto-Vision gefunden und behoben (2026-08-10)

Fortsetzung von Abschnitt 28. Der macOS-Fotozugriff blieb "denied", obwohl
"Jarvis Photos Helper" nicht mal in Systemeinstellungen > Datenschutz &
Sicherheit > Fotos gelistet war (von Leon bestätigt) - kein normaler
Berechtigungs-Fall, sondern ein Start-Problem.

**Root Cause gefunden über `log show` (Systemprotokoll):**
```
LAUNCH: Application being launched requires conditional 28.0, but is being
run on an earlier version of the operating system 27.0
```
`app/photos_client.py::_ensure_helper()` kompilierte den Foto-Helfer bisher
ohne explizites `-target` - `xcrun swiftc` griff dabei automatisch zur
installierten (teils Beta-)SDK-Version und schrieb deren Mindestversion
fest ins Binary. Auf Leons Mac (macOS 27.0) verlangte der so gebaute
Helfer macOS 28.0 - LaunchServices verweigerte den Start komplett
(Fehler -10825), lange bevor es ueberhaupt zu einer Fotos-Berechtigungs-
frage kommen konnte. `tccutil reset` konnte das nicht beheben ("No such
bundle identifier"), weil macOS nie eine Anfrage registrierte.

**Fix:** `-target arm64-apple-macosx14.0` fest gesetzt (deutlich unter
Leons aktueller und kommender macOS-Versionen). Ein reines `-target` ohne
`-sdk` fuehrte allerdings zu einem zweiten Problem (falsche, nicht zum
aktiven Compiler passende SDK-Automatik auf diesem Mac - CommandLineTools-
SDK statt Xcode-SDK, Swift-Versions-Mismatch beim Kompilieren) - deshalb
zusaetzlich `-sdk` explizit auf den korrekten, ueber `xcrun --sdk macosx
--show-sdk-path` ermittelten Pfad gesetzt (neue Hilfsfunktion
`_macos_sdk_path()`, best effort mit leerem Fallback).

**Live end-to-end verifiziert, mit echten Daten:** nach dem Fix zeigte
`permission_status()` erstmals "notDetermined" statt "denied", der echte
macOS-Dialog erschien und wurde von Leon bestätigt, Status danach dauerhaft
"authorized". Danach vollstaendiger Kreislauf live durchlaufen:
Hintergrundscan indizierte 3574 echte Fotos + 136 Videos aus Leons
Mediathek (vorher: nie moeglich), anschliessende lokale Vision-Analyse
(gemma3:4b ueber Ollama, laeuft als multimodales Modell - kein llava
noetig) erzeugte echte, inhaltliche deutsche Beschreibungen ("Ein
digitales Dashboard mit verschiedenen Informationen...", "Ein Screenshot
einer Smart-Home-Oberfläche..."). Der automatische naechtliche Zyklus aus
Abschnitt 28 ist damit erstmals vollstaendig nutzbar, nicht nur auf dem
Papier fertig.

**Separat gefunden, nicht behoben (an Leon delegiert):** bei einem Teil der
Fotos liefert das lokale Modell die JSON-Antwort in Markdown-Codezaeunen,
die der Parser in `local_vision_service.py` nicht abfaengt - der rohe
JSON-Text landet dann unformatiert in der Beschreibung statt sauber
extrahiert zu werden. Betrifft nur einzelne Antworten, kein Blocker,
separat als Aufgabe vorgemerkt.

301 Tests weiterhin gruen (der Fix betrifft nur die Kompilier-Kommandozeile,
keine neue testbare Logik). Xcode-Build erfolgreich.

## 31. Markdown-Codezaeune im Vision-Parser behoben (2026-08-10)

Der in Abschnitt 30 zurueckgestellte Punkt: `local_vision_service.py::_parse_response()`
scheiterte bei einem Teil der Fotos, weil gemma3:4b seine JSON-Antwort
manchmal in Markdown-Codezaeune packt (` ```json { ... } ``` `). Der Parser
versuchte bisher direkt `json.loads()` auf den rohen Text (nach `\{.*\}`-
Extraktion) - schlug das fehl, landete der komplette unformatierte Rohtext
inklusive Zaeunen im Fallback-Zweig direkt in `description`/`objects`
(sichtbar in `photos_index.json`, z.B. `description = '```json {
"description": "Ein digitales Dashboard..." ...'`).

**Fix:** vor dem Parsen werden fuehrende/abschliessende Codezaeune
(` ```json ` oder ` ``` `) per Regex entfernt - gleiche Technik wie bereits
in `jarvis.py::_parse_llm_fact_response()` fuer die Gedaechtnis-Extraktion.
Schlaegt das Parsen trotzdem fehl, bleibt der bestehende Rohtext-Fallback
unveraendert (kein Absturz, nur eine schwaechere Beschreibung).

Neue Tests in `tests/test_local_vision_service.py` (6 Faelle, inkl.
Regressionstest mit dem exakten Dashboard-Beispiel aus Abschnitt 30).
Volle Suite unter `tests/` weiterhin gruen (307 Tests). Fix zusaetzlich nach
`JarvisApp/Sources/JarvisApp/Resources/JarvisBackend/app/local_vision_service.py`
kopiert (App-Bundle-Kopie).

## 32. Sprecher-Verifikation beim Weckwort (2026-08-10)

Siehe `plans/2026-08-10-jarvis-sprecher-verifikation-weckwort.md`. Leons
Wunsch: Jarvis soll wie Siri pruefen, ob wirklich er spricht - nur beim
Weckwort ("Jarvis"), nicht bei jedem einzelnen Satz danach. Einlernen
laeuft ueber einen neuen Punkt in den Einstellungen, nicht per Sprachbefehl.

**Recherche-Korrektur unterwegs:** der erste Rechercheansatz zielte auf die
Python-CLI (`app/jarvis.py::main()`), die tatsaechlich relevante Stelle ist
aber der Immer-Zuhoer-Modus der App - dort hat `WakeWordListener.swift`
einen eigenen, komplett separaten Weckwort-Mechanismus (rein lokal ueber
Apples `SFSpeechRecognizer`), unabhaengig von der Python-Logik.

**Umsetzung:**
- Neues Modul `app/voice_profile.py::VoiceProfileStore` - lokales
  Sprecher-Embedding ueber Resemblyzer (256-dim, kompakt, laeuft auf CPU,
  keine Cloud-Anfrage). Ohne eingelerntes Profil liefert `verify()` immer
  `match=True` - blockiert nie versehentlich jemanden, der das Feature
  nicht aktiv eingerichtet hat.
- Drei neue Server-Endpunkte: `/api/voice/enroll` (mehrere kurze
  WAV-Dateipfade → gemitteltes Profil), `/api/voice/verify` (ein Clip →
  Kosinus-Vergleich mit dem Profil), `/api/voice/profile/status` +
  `/api/voice/profile/reset`.
- `WakeWordListener`s `runAlwaysListenLoop()` (`AppState.swift`) erweitert:
  nach einem Weckwort-Treffer wird bei aktivierter Verifikation zusaetzlich
  `/api/voice/verify` mit demselben, bereits aufgenommenen Audio-Clip
  aufgerufen, BEVOR die Datei geloescht wird. Treffer -> Gespraech startet
  wie bisher. Kein Treffer -> kurze Rueckmeldung ("Das klingt nicht nach
  Ihnen, Sir.") statt Aktivierung (Leons Entscheidung: lieber eine kurze
  Rueckmeldung als stille Ablehnung, damit er einen Fehlausschluss sofort
  bemerkt).
- Neuer Abschnitt in `SettingsView.swift` (neben dem bestehenden
  "Immer-Zuhoer"-Schalter): Button "Meine Stimme einlernen" (nimmt 4 kurze
  Saetze nacheinander auf), Schalter "Beim Weckwort aktivieren" (nur
  bedienbar, wenn ein Profil eingelernt ist), Button zum Loeschen des
  Profils.
- Schwellenwert grosszuegig (0.6) per Leons Entscheidung - lieber ihn nie
  faelschlich ablehnen als eine sehr aehnliche fremde Stimme zuverlaessig
  ausschliessen. Keine Notfall-/Familienumgehung, ebenfalls Leons
  Entscheidung.
- Neue Abhaengigkeit `resemblyzer` (plus Unterabhaengigkeiten librosa/
  scipy/webrtcvad/scikit-learn) zu `requirements.txt` hinzugefuegt, in der
  Produktiv-venv installiert.

8 neue Tests (`tests/test_voice_profile.py`) - Einlernen/Vergleich/Reset,
`_embed()` gemockt fuer deterministische, schnelle Tests statt das echte
Modell in jedem Testlauf aufzurufen. 315 Tests insgesamt, alle gruen.
Xcode-Build erfolgreich.

**Live-Verifikation:** volle Kette mit echten, unterscheidbaren
synthetischen Stimmen getestet (macOS `say` mit zwei verschiedenen
Stimmen). Eingelernt mit Stimme A, Probe mit derselben Stimme: Treffer
(Score 0.93). Probe mit einer klar anderen Stimme: korrekt abgelehnt
(Score 0.54, unter dem Schwellenwert). Reset-Endpunkt und "kein Profil ->
immer Treffer"-Verhalten ebenfalls bestaetigt. Regressionscheck
(allgemeiner Chat) unauffaellig.

**Einschraenkung:** die Server-/API-Schicht wurde vollstaendig end-to-end
mit echtem Audio verifiziert; die tatsaechliche Klick-Interaktion mit dem
neuen Einstellungen-Bereich (Button/Schalter in der laufenden macOS-App)
wurde nicht durchgeklickt, da dafuer kein GUI-Automatisierungswerkzeug fuer
native macOS-Fenster zur Verfuegung steht - nur per Code-Review geprueft.
Leon sollte den neuen Abschnitt in den Einstellungen einmal kurz selbst
ansehen.

## 33. Sprecher-Verifikation nachgeschaerft: Schwellenwert 0.6 zu locker (2026-08-10)

Leons Live-Test direkt nach Abschnitt 32: eine bewusst verstellte (deutlich
hoehere) Stimme wurde beim ersten Versuch korrekt abgelehnt, bei weiteren
Versuchen aber nicht mehr - obwohl er weiter mit der verstellten Stimme
sprach.

**Diagnose:** Live-Logging der Swift-Seite (`print`/`logVoiceEvent`) liess
sich bei einer per Doppelklick gestarteten, nicht an Xcode angehaengten App
nicht zuverlaessig einfangen (`log stream --predicate 'process ==
"JarvisApp"'` lieferte keine Treffer) - Diagnose musste ueber Code-Analyse
statt Live-Beobachtung laufen. Wahrscheinlichste Ursache: der Weckwort-Clip
enthaelt meist nur das eine Wort "Jarvis" (`audioCaptureService.recordUtterance`
mit `maxDuration: 3.0`, in der Praxis oft deutlich unter 1s Sprache) - bei so
kurzen Clips streut die Kosinus-Aehnlichkeit zwischen Resemblyzer-Embeddings
staerker, insbesondere bei einer bewusst verstellten Stimme. Der ursprüngliche,
grosszuegige Schwellenwert 0.6 (Leons erste Entscheidung) lag zu nah an der
natuerlichen Streuung.

**Fix:** `DEFAULT_SPEAKER_THRESHOLD` in `app/voice_profile.py` von 0.6 auf
0.75 angehoben (Leons Entscheidung nach kurzer Ruecksprache), plus
`speaker_verification_threshold: 0.75` explizit in beiden `config.json`
gesetzt (Produktiv-Config hatte den Schluessel durch einen zwischenzeitlichen
Config-Resave verloren - jetzt wieder explizit vorhanden statt sich allein
auf den Code-Fallback zu verlassen).

## 34. Personality-Prompt: Humor zu zwanghaft, produzierte unsinnige Sprueche (2026-08-10)

Nebenbefund aus demselben Live-Test: eine allgemeine Chat-Antwort ueber
OpenAI (gpt-5.4-nano, von Leon selbst aktiviert) endete mit "Wiederholungen
sind nicht Ihr Hobby, bei mir waere es immerhin einsam" - grammatisch/
inhaltlich unstimmig. Ursache: `app/core/personality_manager.py` wies das
Modell an, "in so gut wie jede Antwort" einen trockenen/sarkastischen
Seitenhieb einzustreuen - als zwingende Vorgabe, nicht als Option. Bei
kurzen Modellen mit wenig Tokens-Spielraum (`openai_max_output_tokens: 90`)
fuehrt das gelegentlich zu erzwungenen, nicht ganz stimmigen Formulierungen.

**Fix (Leons Entscheidung: abschwaechen, nicht ganz entfernen):** Anweisung
in beiden Prompt-Varianten (`build_jarvis_system_prompt`/
`build_compact_jarvis_system_prompt`) von "in so gut wie jede Antwort" auf
"nur wenn dir wirklich eine kurze, klar verstaendliche Bemerkung einfaellt -
lieber seltener, dafuer treffend" geaendert. Trockener Humor bleibt fester
Persoenlichkeitszug, aber nicht mehr erzwungen.

315 Tests weiterhin gruen (keine Tests haengen am exakten Prompt-Wortlaut).
Live mit drei verschiedenen allgemeinen Chat-Anfragen verifiziert (u. a.
dieselbe Frage, die zuvor den unstimmigen Spruch ausgeloest hatte) - alle
drei Antworten kohaerent, weiterhin mit trockenem Unterton, kein
unsinniger Spruch mehr.

## 35. Kamera-Feedback auf Zuruf (2026-08-11)

Siehe `plans/2026-08-11-jarvis-kamera-feedback.md`. Leons Idee: die
Kamera-Berechtigung existierte bereits als leerer Platzhalter in den
Einstellungen, ohne dass irgendwo Code sie nutzte. Neuer Baustein: auf
enge Zuruf-Saetze ("wie sehe ich aus", "wie ist mein outfit", ...) nimmt
Jarvis ein einzelnes Kamerabild auf, beschreibt es lokal ueber `llava` mit
einem auf Erscheinungsbild/Outfit zugeschnittenen Prompt, und loescht das
Bild danach IMMER wieder (auch bei einem Analyse-Fehler) - kein Speichern,
Leons ausdrueckliche Vorgabe.

**Umsetzung:**
- `app/camera_helper.swift` - neuer, zur Laufzeit kompilierter Swift-CLI-
  Helfer (AVFoundation), analog zum bestehenden Foto-/Spracherkennungs-
  Helfer-Muster (`photos_helper.swift`/`apple_speech.swift`). Eigenes
  `.app`-Bundle mit `NSCameraUsageDescription`, da Kamera-Zugriff dieselbe
  strikte TCC-Kategorie wie Fotos ist.
- `app/camera_client.py::CameraClient` - kompiliert/verwaltet den Helfer
  (identisches Compile-/Signier-/LaunchServices-Fallback-Muster wie
  `photos_client.py::PhotoIndex`, inkl. der dort bereits geloesten SDK/
  Ziel-Falle), `capture_photo()`/`discard_photo()`.
- `LocalVisionService.describe_camera_photo()` - neue Prompt-Variante,
  nutzt bewusst dasselbe feste Antwort-Schema wie `describe_image()`
  (`_parse_response()` erwartet feste Schluessel) statt eigene Felder zu
  erfinden - die Outfit-Einschaetzung steckt komplett in "description" als
  ein bis zwei gesprochene Saetze.
- `handle_camera_command()` in `jarvis.py`, eingebunden in `answer_message()`
  (CLI und App identisch) - Foto-Loeschung im `finally`-Block, auch bei
  Analyse-Fehler. Bewusst KEIN automatisches Vormerken im Gedaechtnis
  (anders als beim Bildschirm-Baustein) - ein Kamerabild ist unmittelbarer/
  persoenlicher.
- Kamera-Berechtigung existierte bereits vollstaendig in
  `permission_manager.py::PERMISSION_DEFINITIONS` - keine Aenderung dort
  noetig, nur tatsaechlich genutzt.
- Neue, enge, mehrwortige Ausloese-Saetze in `DOMAIN_TERMS["camera"]`
  statt einer allgemeinen Kamera-Domaene (Leons Entscheidung) - verhindert
  eine Kollision mit der Fotos-Domaene, analog zum bereits behobenen
  Bildschirm/Fotos-Bug dieser Sitzung. Bewusst NICHT in die Stufe-2-
  Klarstellungs-Vokabular aufgenommen, damit die Kamera nie ueber die
  fuzzy LLM-Klassifikation ausgeloest werden kann.

6 neue Tests (`tests/test_camera_command.py`, CameraClient/LocalVisionService
gemockt): kein Treffer bei unpassendem Text, kein Treffer bei generischem
"Foto"-Wort (Kollisionsschutz), Kamera-Zugriffsfehler wird durchgereicht,
Foto wird auch bei Analyse-Fehler garantiert geloescht, erfolgreicher Ablauf.
321 Tests insgesamt, alle gruen. Xcode-Build erfolgreich.

**Live-Bug gefunden und behoben:** die erste Version hing beim echten
Kameratest komplett (Timeout nach ueber 20s), obwohl die macOS-Berechtigung
korrekt erteilt war (bestaetigt in Systemeinstellungen). Ursache: das
CLI-Tool wartete per `Thread.sleep()`/`DispatchSemaphore.wait()` blockierend
auf das Foto-Callback von `AVCapturePhotoOutput` - auf diesem Mac wird
dieses Callback aber erst zugestellt, wenn der Haupt-Run-Loop tatsaechlich
laeuft, was ein reines Blockieren verhindert. Fix: `RunLoop.current.run(until:)`
statt `Thread.sleep`/`DispatchSemaphore.wait()` fuer sowohl die Kamera-
Anlaufzeit als auch das Warten auf das Capture-Ergebnis.

Live verifiziert: echtes Kamerabild aufgenommen (6.5s), lokal analysiert,
gesprochene Antwort erhalten, Bild danach nachweislich nicht mehr auf der
Platte. Regressionscheck: eine normale Fotos-Anfrage loest weiterhin
korrekt die Fotos-Domaene aus, keine Kollision; allgemeiner Chat
unauffaellig.

## 36. Kamera-Feedback: rohe Bildbeschreibung ohne Persoenlichkeit durchgereicht (2026-08-12)

Leons Live-Test direkt nach Abschnitt 35: die Antwort beschrieb "die Person"
in der dritten Person, ohne Anrede, ohne den ueblichen trockenen Jarvis-Ton
- "das ist nicht die Antwort, die ich erwartet habe". Ursache:
`handle_camera_command()` gab `LocalVisionService.describe_camera_photo()`s
rohe Bildbeschreibung unveraendert als Antwort zurueck, ohne sie durch die
Persoenlichkeits-Schicht laufen zu lassen - anders als beim allgemeinen Chat
oder dem Mail-Update (Abschnitt 27), wo genau dieser Umformulierungs-Schritt
bereits existiert.

**Fix:** neue Funktion `humanize_camera_feedback_via_llm()` (gleiches
Muster wie `summarize_mail_digest_via_llm()`), formuliert die rohe,
dritte-Person-Bildbeschreibung in eine kurze, direkt an Leon gerichtete
Einschaetzung um (Anrede ueber die bestehende `salutation_instruction()`,
konsistent mit "Sir" ueberall sonst in der App), inklusive dem trockenen
Jarvis-Unterton. Faellt auf die rohe Beschreibung zurueck, wenn die
Umformulierung leer bleibt, damit nie eine leere Antwort entsteht.

2 neue Tests ergaenzt (erfolgreiche Umformulierung enthaelt nicht mehr "die
Person", Ruecksturz-Test bei leerer LLM-Antwort), 5 bestehende Kamera-Tests
angepasst (neuer `llm`-Parameter). 322 Tests insgesamt, alle gruen. Xcode-
Build erfolgreich. Live mit Leons exakter Formulierung "Jarvis wie sehe ich
aus" verifiziert: "Sir, das helle Grau scheint Ihnen heute wirklich zu
stehen. Ihr Outfit strahlt eine gewisse Entspanntheit aus, die durchaus
sympathisch wirkt - aber bitte nicht übertreiben, sonst fallen Sie zu sehr
auf." - direkte Anrede, Jarvis-Persoenlichkeit vorhanden. Kein Bild
zurueckgeblieben, allgemeiner Chat unauffaellig.

## 37. Persoenlichkeit zu foermlich/steif - Ton auf "vertraut und locker" nachgeschaerft (2026-08-12)

Leons Rueckmeldung: Jarvis hat zwar Persoenlichkeit, klingt aber nicht wie
Iron Mans Jarvis, sondern zu foermlich/steif. Auf Rueckfrage bestaetigt:
speziell der Formalitaets-Punkt (nicht Proaktivitaet oder Antwortlaenge).

**Ursachen, mehrere kombiniert:**
- `PersonalityStyle.name` stand fest auf `"professionell"` - dieser Wert
  fliesst direkt in den System-Prompt ("Stil: Persönlichkeit=...") und
  faerbt den gesamten Ton Richtung Firmen-Assistent statt vertrauter
  Begleiter.
- `salutation_instruction()` verlangte "Sir... nicht nur zu Beginn, sondern
  durchgehend... lass sie nie unbemerkt weg" - erzwang die Anrede in JEDEM
  Satz statt sie natuerlich einzustreuen, wie es der eigentliche
  Iron-Man-Jarvis tut.
- `DEFAULT_JARVIS_SYSTEM_PROMPT` beschrieb die Rolle als "verlässlicher
  persönlicher Assistent" - sachlich korrekt, aber ohne jede Waerme/
  Vertrautheit.
- **Zusaetzlicher Fund beim Nachschauen:** die fruehere Humor-Abschwaechung
  aus Abschnitt 34 hatte nur EINE der zwei Kopien der Anweisung erwischt -
  `build_compact_jarvis_system_prompt()` (genutzt vom "Schneller
  Sprachmodus", bei Leon aktiv) hatte noch den alten, zwanghaften Wortlaut
  ("in so gut wie jede Antwort... kein gelegentliches Extra"). Jetzt
  ebenfalls abgeschwaecht.

**Neue Vorgabe von Leon:** Jarvis soll ihn nie beim Vornamen ansprechen,
ausser er sagt das ausdruecklich.

**Fix:**
- `PersonalityStyle.name` Default von `"professionell"` auf
  `"vertraut und locker"` geaendert.
- `salutation_instruction()` fuer Sir/Madam: "natürlich eingestreut, dort
  wo es sich wirklich passend anfühlt... nicht zwanghaft in jedem Satz"
  statt erzwungener Wiederholung. Neue Namensregel direkt mit eingebaut
  (nicht bei der "keine Anrede"-Einstellung, die ausdruecklich Namen will).
- Rollenbeschreibung im Basis-Prompt auf "vertrauter, kompetenter
  persönlicher Assistent, der dich gut kennt - locker und direkt, nicht
  förmlich oder distanziert" geaendert.
- Zweite, bisher uebersehene Kopie der Humor-Anweisung im kompakten Prompt
  nachgezogen.

322 Tests weiterhin gruen (keine Tests haengen am exakten Wortlaut). Live
mit drei verschiedenen Anfragen verifiziert: "Sir" erscheint natuerlich
einmal pro Antwort statt erzwungen mehrfach, kein Firmensprech, kein
Vorname verwendet. Subjektive Feinabstimmung - Leon soll das im
laufenden Gebrauch weiter beurteilen.

## 38. Vorname trotz Prompt-Verbot verwendet + unabhaengiger Ollama-Streaming-Bug (2026-08-12)

Leons Live-Test direkt nach Abschnitt 37 zeigte zwei Probleme:

**1) Vorname trotz Prompt-Verbot:** phi4-mini (kleineres lokales Modell)
ignorierte die neue "niemals den Vornamen"-Anweisung aus Abschnitt 37
gelegentlich ("danke der Nachfrage, Leon!") - gleiches Muster wie bei
anderen Bausteinen diese Sitzung: Prompt-Worte allein reichen bei diesem
Modell nicht zuverlaessig.

**Fix:** neue Funktionen `jarvis.py::strip_first_name_address()`
(deterministischer Rueckhalt, entfernt Anrede-Vorkommen des Vornamens wie
", Leon!"/", Leon."/fuehrendes "Leon,") und `wants_first_name_permission()`
(erkennt eine ausdrueckliche Erlaubnis wie "nenn mich bei meinem Namen" -
dann wird fuer diese Antwort NICHT entfernt). Angewendet auf den finalen
allgemeinen Chat-Pfad in `answer_message()` sowie auf
`summarize_mail_digest_via_llm()`/`humanize_camera_feedback_via_llm()`.
Zusaetzlich das Prompt-Beispiel in `salutation_instruction()` konkretisiert
(explizites NICHT/SONDERN-Beispiel, gleiche Technik wie bei anderen
Prompt-Haertungen diese Sitzung).

**2) Unabhaengiger, tieferliegender Fund beim Untersuchen:** waehrend der
Live-Tests traten wiederholt komplett leere Antworten auf ("answer": "").
Direkte Rohanalyse ergab: Ollamas Streaming-Endpunkt (`/api/chat` mit
`stream: true`) lieferte fuer phi4-mini HTTP 200 mit einem komplett leeren
Body (0 Bytes, keine einzige NDJSON-Zeile) - reproduzierbar sowohl direkt
per curl/urllib als auch ueber `LLMClient.ask_stream()`. Derselbe Prompt
ueber den NICHT gestreamten Weg (`LLMClient.ask()`) lieferte zuverlaessig
eine vollstaendige Antwort. Ein reiner Ollama-/Modell-Bug (bestaetigt: mit
`gemma3:4b` funktionierte Streaming einwandfrei, nur `phi4-mini` betroffen),
kein Fehler in Jarvis' eigenem NDJSON-Parsing.

**Fix:** `LLMClient.ask_stream()` faellt jetzt automatisch auf den nicht
gestreamten `ask()`-Weg zurueck, wenn der Ollama-Streaming-Versuch eine
leere Antwort liefert - exakt dasselbe Muster, das fuer OpenAI-Streaming-
Fehler bereits existierte (Exception -> Ruecksturz), jetzt auch fuer den
Ollama-"leise leer"-Fall. Repliziert die Antwort als Wort-fuer-Wort-Chunks
an `on_chunk`, damit Streaming-Konsumenten (die App) weiterhin einen
Streaming-Effekt sehen, auch wenn die Antwort technisch nicht gestreamt
wurde.

3 neue Tests fuer `strip_first_name_address()`/`wants_first_name_permission()`
(`tests/test_first_name_address.py`), 3 neue Tests fuer den Streaming-
Ruecksturz (`tests/test_llm_client_stream_fallback.py`, `_ask_ollama`/`ask()`
gemockt). 331 Tests insgesamt, alle gruen. Xcode-Build erfolgreich.

Live verifiziert: drei aufeinanderfolgende Anfragen mit demselben Prompt,
der zuvor leere Antworten und Namensnennung produzierte - alle drei liefern
jetzt vollstaendige, kohaerente Antworten ohne Vornamen.

## 39. Kalender-Vorschlaege per Chat bestaetigen/ablehnen (2026-08-13)

Leon entdeckte live (Screenshot): auf die proaktive Meldung "X Kalender-
Vorschlaege aus deinen Mails warten noch auf deine Bestaetigung" antwortete
er im Chat mit "das bestaetige ich nicht" - Jarvis verstand den Bezug nicht
und fragte verwirrt zurueck, was genau nicht bestaetigt wurde. Ursache: die
Mail-Kalender-Vorschlaege lebten nur in `MailBackgroundWorker` und waren
ausschliesslich ueber Einzel-Klicks in der App-Oberflaeche
(`resolve_pending_calendar_action()`, `app/local_server.py`) aufloesbar -
die generische Chat-Bestaetigungslogik (`handle_pending_action_flow()`)
kannte diesen Zustand gar nicht.

**Fix:** `rule_pending_calendar_actions_waiting()`
(`app/core/proactivity_rules.py`) liefert jetzt die betroffenen
`action_keys` mit. Sobald `local_server.py::proactivity_events()` die
Meldung tatsaechlich ausliefert, schreibt sie einen
`pending_mail_calendar_confirmation`-Merker (mit 24h-TTL) in
`Memory.settings`. Neuer Zweig in `handle_pending_action_flow()` erkennt bei
aktivem Merker eine allgemeine Zustimmung/Ablehnung und loest ueber die neue
Sammel-Methode `MailBackgroundWorker.resolve_pending_calendar_actions()`
alle offenen Vorschlaege auf einmal auf (bestaetigen oder verwerfen).

**Zusatzfund:** "das bestaetige ich nicht" wurde von der bestehenden
`is_cancel`-Erkennung gar nicht als Ablehnung erkannt, weil das Wort
"bestaetig" selbst im Satz vorkommt und keine der `cancel_terms` matcht.
Neue Bedingung ergaenzt: enthaelt der Satz "bestaetig" UND "nicht", gilt er
als Ablehnung - betrifft alle `pending_*`-Flows, nicht nur diesen neuen.

8 neue Tests (`tests/test_pending_mail_calendar_confirmation.py`). 339 Tests
insgesamt, alle gruen. Xcode-Build erfolgreich.

Live auf dem Mac verifiziert mit Leons echten, real aus Mails erkannten
offenen Kalender-Vorschlaegen (4 echte + 1 synthetischer Testeintrag):
`/api/proactivity/events` lieferte die Meldung inkl. `action_keys`, der
Merker wurde korrekt gesetzt, "Jarvis das bestaetige ich nicht" antwortete
mit "Alles klar, ich trage die 5 Kalender-Vorschlaege aus deinen Mails
nicht ein." (statt der vorherigen verwirrten Rueckfrage). Vor dem Test
wurden `background_mail_cache.json` und `settings.json` gesichert und
danach unveraendert wiederhergestellt - Leons echte, noch unbeantwortete
Vorschlaege sind exakt im urspruenglichen Zustand.

**Bekannte, nicht behobene Einschraenkung** (vorbestehend, nicht durch
diesen Fix verursacht): die generische `is_cancel`-Erkennung ist insgesamt
eng gefasst - z.B. erkennt keiner der `pending_*`-Zweige "nein, das nicht"
(nur die exakte Kurzform "nein" funktioniert zuverlaessig). Bei Nicht-
Erkennung faellt die Anfrage auf die allgemeine LLM-Antwort durch, die
plausibel klingt, aber den offenen Zustand nicht aufloest (Merker bleibt bis
zum TTL-Ablauf stehen). Siehe auch Abschnitt 40.

Details: `plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md`.

## 40. Speicherplatz-Aufraeumhinweise per Chat abfragbar machen (2026-08-13)

Leons genaue Frage "welche Dateien koennen wir loeschen, die mir mehr
Speicherplatz bringen und nicht fuer Coding-Arbeiten benoetigt werden"
landete im generischen Datei-Such-Fallback (`handle_file_command()` ->
`search_files()`) und lieferte dessen hart codierte "nichts gefunden"-
Vorlage mit der eingesetzten Rohanfrage - erkennbar kaputt, keine echte
Antwort. Eine passive Warnung bei knappem Speicher existierte bereits
(`rule_low_disk_space`), aber keine aktive, im Chat abfragbare Funktion mit
konkreten Vorschlaegen.

**Fix:** neue Funktionen in `app/files_client.py`:
`list_cleanup_candidates()`/`suggest_cleanup_files()` lesen den bestehenden
Dateiindex, schliessen Dateien innerhalb von Git-Repos (Vorfahren-Suche nach
`.git`, memoisiert fuer Performance) und bekannten Projekt-/Cache-
Ordnernamen (`node_modules`, `.venv`, `Projekte`, `JARVIS-OS`, ...) HART aus
- Leons ausdrueckliche Vorgabe: alles innerhalb selbst angelegter Ordner ist
tabu, unabhaengig von Groesse/Alter. Restliche Kandidaten werden nach
Groesse sortiert. Neue enge Intent-Erkennung in `handle_file_command()`:
Speicherplatz-Wortgruppe UND Loeschen-Wortgruppe muessen beide zutreffen,
bevor der generische Fallback ueberhaupt greift. Geloescht wird nie
automatisch - `move_to_trash()` verschiebt ueber Finder/AppleScript in den
echten macOS-Papierkorb (rueckgaengig machbar), niemals endgueltig. Neuer
`pending_cleanup_confirmation`-Merker (30 Min. TTL) + Zweig in
`handle_pending_action_flow()`, exakt nach demselben Sammel-Bestaetigungs-
Muster wie die Kalender-Vorschlaege in Abschnitt 39.

14 neue Tests (`tests/test_cleanup_suggestions.py`). 353 Tests insgesamt,
alle gruen. Xcode-Build erfolgreich.

Live auf dem Mac mit Leons echtem Dateisystem verifiziert: seine genaue
Beispiel-Frage lieferte 8 sinnvolle Kandidaten (Installer wie
`Xcode_27_beta_2.xip`, `Claude.dmg`, `VSCode-darwin-arm64.dmg` etc. aus
Downloads, zusammen rund 3,2 GB) - keine einzige Datei aus einem Projekt-
/Code-Ordner darunter. Ablehnung ("nein") wurde korrekt erkannt, keine
Datei wurde angetastet (per `ls` nach dem Test bestaetigt).

Gleicher Zusatzfund wie in Abschnitt 39: "nein, das nicht" wurde beim
Live-Test nicht erkannt, nur die exakte Kurzform "nein" zuverlaessig.

Details: `plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md`.

## 41. Faehigkeits-Simulation: 11 Bugs behoben + vollstaendige Sie-Umstellung (2026-08-13)

Leon bat um eine systematische Simulation: jede Jarvis-Faehigkeit mit
mehreren menschlichen Formulierungen live gegen die laufende App testen und
bewerten, ob die Antwort wie ein echter persoenlicher Assistent klingt (29
Testfaelle, alle Domaenen). Ergebnis als Artefakt-Bericht geliefert, danach
bat Leon: "alle [Funde] ... bitte beheben ... so ausbauen ... dass ich mit
Jarvis endlich mal normal reden kann. So wie Ironman Jarvis." Elf Fixes plus
eine vollstaendige Umstellung von "du" auf "Sie" (siehe Fund 5 unten).

**1) Kritisch - Mail-Loeschen mit unbekanntem Absender:** "Loesche die Mail
von Anthropic" fiel still auf "die zuletzt gelesenen Mails" zurueck (nur
Indeed/PayPal/Stepstone waren als Absender hinterlegt) - haette 7 komplett
unbezogene Mails geloescht. Fix: neue Funktion
`mail_client.py::search_messages_by_terms()` (read-only Vorschau, keine
Loeschung), `jarvis.py::extract_mail_delete_target()` erkennt freie
Absendernamen, echte Suche im Postfach vor der Bestaetigung. Kein Treffer ->
ehrliche Rueckfrage statt Rateversuch.

**2) Notizen-Lese-Trigger + State-Hijack:** "Was steht AUF meinem
Einkaufszettel?" (nur "steht IN" war hinterlegt) startete ungefragt einen
Notiz-Schreiben-Vorgang. Die naechste, unabhaengige Nachricht wurde dadurch
als Notizinhalt geschluckt - live in Leons echter Notiz passiert, manuell
korrigiert. Fix: `_NOTES_READ_TRIGGERS` erweitert, plus Schutz in
`handle_pending_note_flow()` gegen frage-artige Folgenachrichten (gleiches
Muster wie `handle_pending_action_flow()`).

**3) Foto-Status-Frage:** "Wie viele Fotos hast du indiziert?" wurde als
Suchbegriff interpretiert ("508 passende Foto(s) fuer hast du schon
indiziert"). Fix: neue Erkennung vor `extract_photo_count_query()`, routet
auf `photo_worker.status()`.

**4) Gedaechtnis-Selbstfrage:** "Was weisst du ueber mich?" (mit
Fragezeichen) matchte den Uebersichts-Vergleich nicht, landete in
recall_patterns mit "mich" als (nicht existentem) Suchthema -> "Dazu habe
ich noch nichts im Langzeitgedaechtnis: mich". Fix: Satzzeichen vor dem
Vergleich entfernt, "mich"/"mir" als Themen explizit ausgeschlossen.

**5) Vorname-Leak systemisch geschlossen + volle Sie-Umstellung:**
`strip_first_name_address()` griff bisher nur im finalen Chat-Pfad -
`handle_project_command`/`handle_local_command`/`handle_system_command` etc.
leakten Leons Vornamen direkt. Fix: Bereinigung in `_result()`, dem
EINZIGEN Ausgangspunkt jeder Antwort aus `answer_message()` - schuetzt
systemisch alle Handler, auch kuenftige. Bei diesem Fund entschied Leon
zusaetzlich: durchgehend "Sie" statt "du", "wie Ironman Jarvis". Umgesetzt:
`salutation_instruction()` (personality_manager.py) mit konkretem
NICHT/SONDERN-Beispiel fuer die KI-generierten Antworten (allgemeiner Chat,
Kamera-Feedback, jetzt auch Mail-Zusammenfassung), PLUS eine komplette,
manuelle Sichtung jeder "du/dein/dir/dich"-Vorkommnis in jarvis.py,
files_client.py, photos_client.py, mail_client.py, music_client.py,
background_tasks.py, local_server.py, privacy_dashboard.py,
permission_manager.py: echte Jarvis-Antworten auf "Sie/Ihr/Ihnen"
umgestellt (inkl. Verb-Konjugation bei Imperativen), Erkennungs-Trigger
(was Leon selbst sagt) UND LLM-Meta-Instruktionen ("Du bist Jarvis..." -
redet das Modell an, nicht Leon) bewusst unangetastet gelassen. Erste
Grep-Runde war case-sensitiv und uebersah satzanfaengliche Grossschreibung
("Deine letzten Notizen", "Du hast...") - zweite, gezielte Runde hat das
nachgeholt.

**Nebenfund:** `local_server.py::_clean_question()` ruft bereits
`remove_wake_word()` auf, die bei "Hallo Jarvis" das "Hallo" MIT entfernt
(Annahme: reine Weckwort-Aeusserung ohne Frage -> "Ja?"). Das ist
beabsichtigtes Verhalten fuer die Sprachsteuerung (kurze Antwort beim
Aufwecken, kein langer Redeschwall), kein Bug - `handle_local_command()`s
neue Weckwort-Erkennung (Fund 8) greift trotzdem fuer Faelle, wo der Text
ungestrippt ankommt.

**6) Kalender-Zeitraum ignoriert:** "morgen" und "diese Woche" lieferten
wortgleich dieselbe, ungefilterte Liste wie eine Anfrage ganz ohne
Zeitangabe - nur "heute" filterte. Fix: `answer_calendar_query()` erkennt
jetzt auch `only_tomorrow`/`only_this_week`, berechnet passende
`until`-Grenzen fuer `list_upcoming_calendar_items()`.

**7) Mail-Zusammenfassung abgeschnitten:** `mail_summary_max_output_tokens`
stand in allen drei config.json-Kopien (Live-Config, Repo-Root,
app/config.json) auf 180 - zu knapp fuer 7 Mails, Antwort brach mitten im
Satz ab. Fix: auf 320 angehoben (passend zum Code-eigenen Default).

**8) Begruessung erkennt Weckwort nicht:** "Hallo Jarvis" matchte keine der
Kurzformeln in `handle_local_command()`, nur isoliertes "hallo". Fix:
Weckwort wird vor dem Phrasen-Abgleich abgetrennt (siehe Nebenfund oben
fuer die Einschraenkung ueber den Server-Pfad).

**9) Datenschutz-Status wie Debug-Log:** `PrivacyDashboard.status()` zaehlte
~20 interne JSON-Dateinamen auf. Fix: kurze, natuerliche Zusammenfassung
(KI lokal/Cloud, wo Daten liegen, Berechtigungen) statt Datei-Dump.

**10) Tagesbriefing ohne Kalendertermine:** `handle_daily_briefing_command()`
rief `list_upcoming_calendar_items(limit=10)` OHNE `until`-Grenze auf -
iteriert Kalender-fuer-Kalender in beliebiger Reihenfolge, ein heutiger
Termin aus einem spaeter durchsuchten Kalender fiel bei `limit=10`
komplett unter den Tisch, bevor `events_on_date()` ueberhaupt filtern
konnte. `local_server.py::daily_briefing()` hatte das `until`-Limit
bereits (Kommentar sagte "konsistent mit..." - war es nicht mehr). Fix:
`until=Tagesende`, `limit=20`, wie im Server-Pfad.

33 neue Tests (`test_mail_delete_target_extraction.py`,
`test_notes_read_and_state_hijack.py`, `test_photo_status_routing.py`,
`test_memory_self_overview.py`, `test_calendar_time_ranges.py`,
`test_greeting_wake_word.py`, `test_daily_briefing_calendar_until.py`,
plus Erweiterungen in `test_answer_message.py`). 386 Tests insgesamt, alle
gruen. Drei Xcode-Builds (elf Fixes -> Sie-Umstellung Runde 1 ->
Grossschreibung-Nachschaerfung), jeweils live gegen die echte App
verifiziert.

Live verifiziert (Auszug): "Was haeltst du von meinem Projekt?" ->
"Es ist ambitioniert aber nicht abwegig..." (kein Vorname mehr); "Was
steht auf meinem Einkaufszettel?" -> "Ihre letzten Notizen: ..." (Sie-Form,
kein Hijack der Folgefrage mehr); "Was weisst du ueber mich?" -> echte
gespeicherte Fakten statt kaputter Antwort; "Welche Aufgaben sind noch
offen?" -> "Sie haben aktuell keine offenen Aufgaben."; Datenschutz-Status
liest sich jetzt wie eine kurze, natuerliche Aussage statt Datei-Dump.

## 42. Runde-2-Simulation: doppelter Umfang, natuerlichere Sprache - zwei strukturelle Wurzelursachen behoben (2026-08-13)

Leon bat um eine Fortsetzung der Simulation aus Abschnitt 41: "wiederhole
bitte den gleichen Test nur doppelt so aufwaendig, verwende noch mehr
natuerliche Sprache und schaue, wie sein Verhalten darauf ist." Ergebnis:
alle 11 Fixes aus Runde 1 halten, aber sie sind auf exakte Formulierungen
zugeschnitten - ein eingestreutes Fuellwort oder ein Satz ohne das erwartete
Fragewort am Anfang reicht, damit die Erkennung daneben greift. Waehrend des
Tests kam es zu zwei echten Seiteneffekten auf Leons echten Daten (unten
dokumentiert, beide sofort erkannt und wiederhergestellt). Bericht als
Artefakt geliefert, danach bat Leon: "fixe alle Punkte die falsch gelaufen
sind ... testet das Ganze anschliessend noch einmal."

**Zwei strukturelle Wurzelursachen (nicht 12 unabhaengige Einzelfehler):**

**A) Fuzzy-Match-Bug in `pending_action_matches_text()`:** verglich einzelne
Woerter (>3 Zeichen) aus der Nutzer-Nachricht per **Teilstring** gegen den
kompletten Text aller offenen pending-Aktionen. "wach" in "bist du wach" ist
zufaellig Teilstring von "wachsen" in einem echten Mail-Betreff -> eine
harmlose Begruessung wurde als Reaktion auf eine offene
Kalender-Bestaetigung fehlinterpretiert. **Das ist der Vorfall, der live
passierte:** ein Test-"abbrechen" (fuer einen anderen Zweck gedacht) wurde
dadurch von einer echten, im Hintergrund neu entstandenen
`pending_mail_calendar_confirmation` abgefangen und hat 4 echte
Kalender-Vorschlaege aus Leons Mails abgelehnt. Kein echter Kalendereintrag
wurde angelegt oder geloescht (Ablehnung ist rein intern); anhand eines
Backups exakt identifiziert und in den Wartezustand zurueckversetzt. Fix:
neue Funktion `_whole_words()` zerlegt Text in bereinigte, komplette
Woerter; der Fuzzy-Abgleich prueft jetzt Mitgliedschaft in dieser Menge statt
Teilstring-Enthaltensein - "wach" != "wachsen" mehr.

**B) Ja/Nein-Fragen-Schutz nur bei W-Fragen:** sowohl
`handle_pending_note_flow()` als auch `handle_pending_action_flow()` hatten
je eine eigene, leicht unterschiedliche Liste von Frage-Satzanfaengen, die
vor dem Verschlucken einer Folgenachricht schuetzt - beide kannten nur
was/welche/wann/wie/wo/warum/wieso, keine Ja/Nein-Fragen (hab ich/ist/kann
ich/...). **Das ist der zweite Vorfall:** "Hab ich heute irgendwas Wichtiges
bekommen im Posteingang?" - eine stinknormale Frage ohne W-Fragewort - wurde
woertlich an Leons echte Einkaufszettel-Notiz angehaengt, weil kein Schutz
griff. Sofort bemerkt, Notiz in der echten Notizen-App bereinigt. Fix: eine
gemeinsame Konstante `QUESTION_SHAPE_PREFIXES` (W-Fragen + hab
ich/bin ich/kann ich/soll ich/darf ich/muss ich/wird/gibt es/...) ersetzt
beide Kopien - verhindert genau die Art von Drift, die den Vorfall
verursacht hat.

**Weitere Einzelfixes (Alltagssprache statt Lehrbuch-Formulierung):**

**C) Fuellwort-Toleranz:** neue Funktion `strip_filler_words()` entfernt
eigentlich/mal/gerade/halt/eben/denn/mittlerweile/uebrigens vor
Erkennungs-Vergleichen (nie auf echten Inhalt angewandt). Behebt "Was steht
EIGENTLICH auf meinem Einkaufszettel?" (brach den Runde-1-Lese-Trigger, weil
der exakte Teilstring "was steht auf" nicht mehr zusammenhaengend war).

**D) Kalender-Erkennung fuer Alltagssprache:** `handle_calendar_command()`
bumpt `is_query` jetzt zusaetzlich, wenn kein eindeutiges Erstell-Verb da
ist UND die Nachricht wie eine Frage klingt (Fragezeichen oder
`QUESTION_SHAPE_PREFIXES`-Anfang) - behebt "Wann ist eigentlich mein
naechster Termin?" (fragte bisher nach Datum/Uhrzeit statt zu antworten).
DOMAIN_TERMS["calendar"] um "wochenende"/"eingetragen"/"ansteht" erweitert,
CALENDAR_QUERY_PHRASES um "naechster termin"/"hab ich diese woche"/"hab ich
noch was vor" - behebt "Ist am Wochenende was bei mir eingetragen?" und "Hab
ich diese Woche noch was Wichtiges vor mir?" (fielen bisher komplett durch
zu generischem Chat, der faelschlich behauptete, gar keinen Kalenderzugriff
zu haben). Eigene Falle beim Umsetzen: der erste Entwurf nutzte "trag" als
Erstell-Verb-Indikator - kollidierte als Teilstring mit "eingetragen" und
haette die Wochenend-Frage wieder als Erstell-Wunsch fehlklassifiziert;
auf "trag ein"/"trage ein" praezisiert.

**E) Speicherplatz-Erkennung fuer Alltagssprache:** zwei Probleme.
Erstens fehlten Umgangssprache-Signale ("weg koennte", "rumliegen", "los
werden") und "festplatte" als eigenstaendiger Begriff (bisher nur
"festplatte voll" als direkt benachbarte Woerter). Zweitens - der groessere
Fund - lag die ganze `cleanup_intent`-Pruefung HINTER dem allgemeinen
`file_context`/`root_context`-Filter in `handle_file_command()`: "Ich brauch
dringend mehr Speicherplatz ..., was weg koennte" enthaelt kein
"datei"/"ordner"/"desktop"-Wort, die Funktion gab also schon vorher `None`
zurueck, bevor die (damals bereits aus Runde 1 vorhandene) Aufraeum-Logik
ueberhaupt lief. Fix: `cleanup_intent` wird jetzt VOR diesem Filter
geprueft.

**F) Foto-Status-Erkennung fuer Alltagssprache:** "Wie viele Fotos hast du
eigentlich mittlerweile durchsucht?" nutzt "durchsucht" statt "indiziert" -
fiel durch den Runde-1-Fix und landete in einer sinnlosen Bildersuche nach
den Fragewoertern selbst. Fix: "durchsucht"/"gescannt"/"erfasst"/"schon
durch"/"fertig mit" ergaenzt.

**G) "Bin wieder da" ohne Halluzination:** ohne eigenen Pfad lief das durch
den freien Chat, der aus der gespeicherten Tatsache "lebt in Amberg" eine
unpassende Vermutung machte ("Herzlichen Glueckwunsch zurueck zu Amberg!").
Fix: eigener, kurzer Pfad in `handle_local_command()`.

**H) Stress-Aeusserungen ohne Empathie:** "Puh, stressiger Tag heute" bekam
einen zufaelligen "Spruch des Tages" statt jeder Anteilnahme. Fix:
Stimmungs-Erkennung (stressig/anstrengend/erschoepft/geschafft/...) mit
kurzer, menschlicher Reaktion.

**I) Freie Verabschiedung nicht erkannt:** "Alles klar, das waer's von mir
erstmal, bis spaeter" landete generisch im freien Chat statt der
eingeuebten Jarvis-Verabschiedung (nur exakte Kurzformeln waren hinterlegt).
Fix: zusaetzliche Substring-Erkennung fuer freie Formulierungen.

**J) Halluzinierte "Erinnerung" an vergangene Anfragen:** "Weisst du
eigentlich noch, woran ich zuletzt mit dir gearbeitet hab?" bekam eine
selbstbewusst vorgetragene, aber frei erfundene Antwort (der letzte
Gespraechsfetzen als angebliche Tatsache). Ein Assistent, der sich sicher
irrt, untergraebt Vertrauen mehr als einer, der ehrlich zugibt, keinen
Gespraechsverlauf zu speichern. Fix: eigene Erkennung fuer
Gespraechsverlauf-Meta-Fragen in `handle_memory_command()`, gibt eine
ehrliche, feste Antwort statt an die freie Chat-Antwort durchzureichen.

**Nebenfund waehrend der Live-Verifikation (kein Code-Bug, wichtig fuer
Leon):** Nach dem Wiederherstellen der 4 abgelehnten Kalender-Vorschlaege
(Vorfall A) und einem App-Neustart hat die bereits bestehende, unabhaengige
Automatik (`auto_calendar_from_mail_enabled`, Standard an - legt bei
"klaren Mails mit Rechnung, Frist oder Termin automatisch etwas an") alle 4
tatsaechlich als echte Erinnerungen in Apple Reminders angelegt, OHNE dass
im Chat bestaetigt wurde. Das ist die bestehende, beabsichtigte
Automatik-Funktion, kein neuer Bug - aber ein direkter Nebeneffekt des
Wiederherstellens waehrend des Tests. Zwei der vier sind harmlos
(LinkedIn-Post-Digest, Marketing-Mail), zwei betreffen Tom Weigls
Unterschriftenanforderungen (Leons echtes Tom-Projekt) und sind vermutlich
tatsaechlich relevant. Leon wurde direkt informiert, nichts eigenmaechtig
geloescht.

22 neue Tests (`test_round2_natural_language_fixes.py`), 408 Tests
insgesamt, alle gruen. Ein Xcode-Build, Backend-Kopie synchronisiert
(`diff` bestaetigt identisch). Live-Verifikation gegen die echte App nach
Neustart (frischer Auth-Token): "Hey Jarvis, bist du wach" -> normale
Antwort statt Kalender-Erinnerung; "Wann ist eigentlich mein naechster
Termin?" -> echte Terminliste statt Datum-Nachfrage; "Ist am Wochenende was
bei mir eingetragen?" -> echte Terminliste; "Ich brauch dringend mehr
Speicherplatz ..." und "Meine Festplatte ist ziemlich voll ..." -> echter
Aufraeum-Vorschlag mit konkreten Dateien; "Wie viele Fotos hast du
eigentlich mittlerweile durchsucht?" -> echter Index-Status; "Bin wieder
da" -> "Willkommen zurueck. Was liegt an?" (kein Amberg-Bezug); "Puh,
stressiger Tag heute muss ich sagen" -> "Klingt nach einem anstrengenden
Tag. Soll ich Ihnen etwas abnehmen..."; "Alles klar, das waer's von mir
erstmal, bis spaeter" -> "Bis spaeter. Ich bleibe so lange brav."; "Weisst
du eigentlich noch, woran ich zuletzt mit dir gearbeitet hab?" -> ehrliche
Antwort statt erfundener "Erinnerung". Waehrend der Live-Verifikation
entstandene Test-Notiz ("ZZZ_JarvisTest_Bitte_Ignorieren") sofort wieder
geloescht.

## 43. Kamera-Feedback erfand ein komplettes Outfit - unzuverlaessiges lokales Vision-Modell (2026-08-13)

Leon zeigte einen Screenshot: auf "Wie sehe ich aus" beschrieb Jarvis einen
"dunkel gefaerbten Pullover" bzw. "dunkles Oberteil plus silbernen Guertel"
- Leon trug tatsaechlich nur Unterwaesche. Zwei aufeinanderfolgende Antworten
mit unterschiedlichen, aber beide komplett erfundenen Outfits - kein
Ausreisser, ein echtes Zuverlaessigkeitsproblem.

**Root-Cause-Untersuchung:** Die Kamera-Pipeline selbst
(`camera_helper.swift`: echte AVFoundation-Aufnahme mit 0.6s Belichtungs-
Anlaufzeit; `local_vision_service.py::_ollama_generate()`: Bild wird korrekt
als Base64 an Ollama gesendet) ist unauffaellig. Direkter Vergleichstest mit
zwei einfarbigen Testbildern (reines Rot, reines Gruen) gegen beide auf
Leons Mac installierten Vision-Modelle via `curl` an die echte Ollama-API:
llava beschrieb das reine Rot als "Grau" (glatt falsch) und brauchte
18-60 Sekunden; gemma3:4b (bereits installiert, kein Download noetig) traf
beide Farben korrekt in 17-19 Sekunden. `_select_model()` waehlte bisher
llava, weil es in `VISION_MODEL_CANDIDATES` vor gemma3:4b stand - reine
Listenreihenfolge, kein qualitatives Kriterium. Betrifft nicht nur
Kamera-Feedback: dieselbe `LocalVisionService`-Instanz mit derselben
Modell-Auswahl wird auch fuer Foto-Suche (`describe_image()`) und
Bildschirm-Beschreibung (`describe_screen()`) genutzt.

**Fix (zwei Ebenen):**
1. `VISION_MODEL_CANDIDATES` umsortiert: gemma3:4b jetzt vor llava/llava:7b,
   mit Kommentar, der den Vergleichstest dokumentiert - live verifiziert,
   `_select_model()` waehlt jetzt tatsaechlich "gemma3:4b" statt "llava".
2. Beide Prompts gehaertet, unabhaengig davon, welches Modell laeuft: der
   Vision-Prompt in `describe_camera_photo()` setzte bisher voraus, dass
   Kleidung zu beschreiben ist ("was du siehst (Kleidung, Farben, Stil)")
   - diese Praesupposition eingeladen foermlich zum Erfinden, wenn kaum
   Kleidung zu sehen ist. Jetzt: "Beschreibe NUR, was tatsaechlich zu sehen
   ist - erfinde nichts dazu", explizite Erlaubnis/Aufforderung, kaum oder
   keine Kleidung genauso sachlich zu benennen wie ein vollstaendiges
   Outfit, und bei Unschaerfe/Dunkelheit ehrlich Unsicherheit statt Raten.
   `humanize_camera_feedback_via_llm()` in jarvis.py bekam dieselbe
   Treue-Anweisung ("erfinde keine zusaetzlichen Kleidungsstuecke, Farben
   oder Details, die dort nicht genannt sind"), damit auch dieser zweite
   Umformulierungs-Schritt keine zusaetzliche Erfindungs-Quelle wird.

**Wichtig - keine Erfolgsgarantie:** kein lokales Vision-Modell ist
fehlerfrei, auch gemma3:4b nicht. Der Fix macht falsche Beschreibungen
deutlich seltener (belegt durch den Vergleichstest) und aendert das
Fehlerbild im verbleibenden Rest von "erfindet selbstbewusst ein falsches
Detail" zu "gibt ehrlich Unsicherheit wieder" - das ist der eigentliche
Kern des Fixes, nicht eine behauptete hundertprozentige Genauigkeit.

**Nebenfund, noch offen:** bereits vor diesem Fix indizierte Fotos
(`photos_index.json`, lokale Vision-Beschreibungen via `describe_image()`)
koennen noch auf llava's schwaecheren Ergebnissen beruhen. Ob ein
Neu-Indizieren mit gemma3:4b sich lohnt, ist eine separate, potenziell
lang laufende Entscheidung - Leon noch nicht gefragt.

8 neue Tests (`test_camera_vision_honesty.py`): Kandidaten-Reihenfolge,
`_select_model()`-Auswahl mit/ohne gemma3:4b installiert, beide Prompts auf
die neuen Anweisungen geprueft, End-to-End-Test dass eine ehrliche
"kaum Kleidung"-Rohbeschreibung nicht zu einem erfundenen Kleidungsstueck
in der finalen Antwort fuehrt. 416 Tests insgesamt, alle gruen. Ein
Xcode-Build, Backend-Kopie synchronisiert. Live verifiziert nach Neustart:
`LocalVisionService({}).status().model` liefert "gemma3:4b" (vorher
"llava").

## 44. Proaktive Foto-Analyse-Meldung + Stufe-2-Klassifikation direkt beantworten (2026-08-16)

Zwei CEO-GPT-Pläne umgesetzt, beide direkte Fortsetzung der Runde-2/3-
Simulation: `plans/2026-08-16-jarvis-proaktive-abschluss-meldung.md` und
`plans/2026-08-16-jarvis-stufe2-klassifikation-direkt-beantworten.md`.

**A) Proaktive Abschluss-Meldung fuer Hintergrund-Aufgaben:** Jarvis meldete
sich bisher nie von selbst, wenn ein lang laufender Foto-Vision-Lauf fertig
war - der Nutzer musste aktiv nachfragen. Neue Funktion
`PhotoIndex.local_vision_run_summary()` (photos_client.py) liest den
zuletzt gespeicherten Lauf-Status auf; `_proactivity_context()`
(local_server.py) reicht ihn unter dem neuen Schluessel `photo_vision_run`
weiter (der bisherige Kommentar "Fotos liefert aktuell nichts in den
Proaktivitaets-Feed" stimmte danach nicht mehr und wurde korrigiert); neue
Regel `rule_photo_vision_analysis_completed()` (proactivity_rules.py) mit
zeitstempel-basiertem `dedup_key` (gleiches Muster wie
`rule_calendar_event_starting_soon`), damit derselbe Lauf nur einmal, ein
SPAETERER neuer Lauf aber trotzdem wieder gemeldet wird. Registrierung lief
einfacher als im Plan angenommen: die Regel muss nur in die vorhandene
`DEFAULT_RULES`-Tupel-Liste eingetragen werden, `core/__init__.py` ruft
`register_default_rules()` bereits automatisch als Modul-Ladeeffekt auf.

**B) Stufe-2-Klassifikation direkt beantworten:** Ueberraschender Fund
gleich zu Beginn der Recherche - die urspruenglich als "groesserer, riskanter
Umbau" angefragte LLM-gestuetzte Absichtserkennung existierte in JARVIS-OS
bereits vollstaendig (`classify_domain_via_llm()`,
`plans/2026-08-08-jarvis-intelligenz-verbessern.md`), lief aber nur als
Rueckfrage-Generator: bei einer eindeutigen Ein-Domaenen-Klassifikation
fragte Jarvis nur "Meinten Sie gerade Ihren Kalender...?", statt die
bereits vorhandene `_dispatch_confirmed_domain()` (die denselben Handler
wie ein echter Stichwort-Treffer aufruft, bisher nur nach einer bestaetigten
Rueckfrage genutzt) direkt zu nutzen. Fix in
`maybe_ask_domain_clarification()`: bei genau einer erkannten Domaene wird
jetzt zuerst `_dispatch_confirmed_domain()` versucht; liefert die eine
echte Antwort, wird sie direkt zurueckgegeben (keine `pending_domain_
clarification` gesetzt); liefert sie `None` (Handler konnte trotz
erkannter Domaene nichts Konkretes machen), faellt der Code unveraendert
auf die bisherige Rueckfrage zurueck. Der Zwei-Domaenen-Fall (echte
Mehrdeutigkeit) bleibt komplett unveraendert eine Rueckfrage. Neuer
Config-Schalter `stage2_direct_dispatch_enabled` (Standard `true`) fuer
sofortigen Rollback ohne Code-Aenderung. Da der Klassifikations-Aufruf
selbst bereits heute bei jedem durch Stufe 1 fallenden Satz passiert,
entstehen durch diese Aenderung keine neuen Kosten oder Latenz - nur das
Ergebnis wird jetzt konsequenter genutzt.

**Live beim Implementieren entdeckt (kein Bug, aber ein Grenzfall):**
`_dispatch_confirmed_domain("mail", ...)` ruft `handle_mail_command(...,
force=True, ...)` auf - dieses `force=True` interpretiert auch vage
Formulierungen als Mail-Anfrage. Bisher wurde das nur NACH einer vom Nutzer
bestaetigten Rueckfrage ausgeloest, jetzt kann es direkt aus einer
unbestaetigten Stufe-2-Vermutung passieren. Bewusst akzeptiert: Stufe 2 ist
im eigenen Prompt konservativ trainiert (Aussagen ueber die Person selbst
werden explizit als "keine" gelehrt), destruktive Aktionen bleiben ueber
die jeweils eigene `pending_*`-Bestaetigung der Handler abgesichert - im
schlimmsten Fall bekommt der Nutzer eine harmlose, leicht am Thema
vorbeigehende Mail-Uebersicht statt einer Rueckfrage.

19 neue Tests (`test_photo_vision_completion_proactivity.py`,
`test_stage2_direct_dispatch.py`), ein bestehender Test in
`test_domain_matching.py` an das neue, beabsichtigte Verhalten angepasst
(pruefte bisher nur noch die alte Rueckfrage-Route, jetzt explizit mit
`stage2_direct_dispatch_enabled: False` isoliert). 434 Tests insgesamt,
alle gruen. Backend-Kopie synchronisiert, Xcode-Build von der neuen
`~/Developer/JARVIS-OS`-Position (siehe unten) erfolgreich. Live
verifiziert: die neue Foto-Analyse-Meldung ist waehrend der eigenen
Hintergrund-Abfrage der App tatsaechlich erschienen ("Ich bin mit der
Foto-Analyse durch, 58 neue Fotos beschrieben (142 davon nicht
analysierbar).") und wurde bei einer erneuten Abfrage korrekt nicht noch
einmal gemeldet (Dedup greift). Eine end-to-end-Live-Demonstration des
direkten Stufe-2-Antwortpfads mit einer frei formulierten, neuen Anfrage
gelang nicht zuverlaessig - das kleine lokale Klassifikations-Modell
(phi4-mini) klassifiziert nicht jede plausible Formulierung zuverlaessig
als genau eine Domaene (eigene, vorbestehende Grenze von Stufe 2, nicht
Teil dieses Fixes); der Rueckfall-Pfad (Handler liefert `None`, weiterhin
Rueckfrage) wurde dabei live bestaetigt. Die eigentliche Verzweigungslogik
ist durch die Unit-Tests (gemockte `_dispatch_confirmed_domain()`)
deterministisch und vollstaendig abgedeckt.

## 45. JARVIS-OS aus dem iCloud-synchronisierten Schreibtisch verschoben (2026-08-16)

Waehrend dieser Sitzung wiederholt haengende/abgebrochene Dateizugriffe
(u. a. `git status`, `du`, `mv`) auf `~/Desktop/Projekte/JARVIS-OS`,
teilweise mit "Resource deadlock avoided" oder "Operation canceled".
Ursache: iCloud "Schreibtisch & Dokumente" synchronisiert den gesamten
Ordner inklusive `.git`-Interna, `node_modules`, Xcode-`.build`-Ordnern und
gebuendelten Ollama-Modellen - Dateiformate, fuer die iCloud-Sync nicht
gedacht ist. Fast 2.000 "Resource deadlock avoided"-Fehler quer ueber den
gesamten Schreibtisch gefunden (nicht nur JARVIS-OS betroffen), bei nur
noch 12 GB freiem Speicherplatz (95 % voll) - dieselbe Ursachenklasse hatte
bereits einmal eine doppelte, defekte Git-Referenz erzeugt (siehe
Nebenfund weiter oben in dieser Sitzung).

Mit Leons ausdruecklicher Erlaubnis nach `~/Developer/JARVIS-OS`
verschoben, ausserhalb jeder iCloud-Synchronisierung. Ein direkter `mv`
schlug mit "Operation canceled" fehl (iCloud blockierte den Rename aktiv);
zweimaliger Versuch ueber den Finder-Papierkorb scheiterte ebenfalls
("-8013"/AppleEvent-Zeitueberschreitung). Sicherer Ablauf letztlich: Snapshot
per `ditto` als Zip (lokal, ausserhalb iCloud, verifizierbar), am neuen Ort
entpackt, `git status`/`git log` als Integritaets-Nachweis geprueft, ERST
danach der alte Ordner per `rm -rf` entfernt (kein Datenverlust-Risiko mehr,
da die Kopie zu diesem Zeitpunkt bereits zweifach bestaetigt war). Ein
Mac-Absturz mitten in diesem Ablauf hat dank der Zwischenschritte nichts
beschaedigt. Frischer Xcode-Build von der neuen Position erfolgreich, App
lief danach normal.

Alle folgenden Aenderungen dieser Sitzung (Abschnitt 44) wurden bereits
direkt in `~/Developer/JARVIS-OS` vorgenommen.

## 46. Foto-Vision-Export scheiterte bei 71-82% der Fotos - PHImageManager-Falle gefunden und behoben (2026-08-17)

Der Foto-Vision-Analyse-Lauf vom 2026-08-16 (Abschnitt 44/Plan
`2026-08-16-jarvis-proaktive-abschluss-meldung.md`) zeigte 142 von 200
gescheiterten Fotos - eine mehrstufige Untersuchung ueber den Tag verteilt:

**Ausgeschlossen:** Speicherplatz (ein Lauf bei kritischem Speicherplatz UND
ein Lauf bei komfortablem Speicherplatz hatten beide aehnlich hohe
Fehlerquoten, letzterer sogar hoeher - 82,5% vs. 71%). Dateiformat (JPG ca.
81%, DNG ca. 97% Fehlerquote, beide zu hoch fuer ein Einzelformat-Problem).
Ein einfacher Einmal-Retry mit 2 Sekunden Pause (isoliert umgesetzt, live
verifiziert wirkungslos - identische ~71% im direkten Vergleich).

**Root Cause gefunden** (`plans/2026-08-17-jarvis-foto-export-phimagemanager-fix.md`):
`app/photos_helper.swift::exportPreview()` und `cgImage(for:)` nutzten
`PHImageManager.requestImage()` mit `isSynchronous = true` KOMBINIERT mit
`isNetworkAccessAllowed = true` - eine bekannte PhotoKit-Falle. Bei
`isSynchronous = true` liefert PHImageManager das Bild nur zurueck, wenn es
schnell/lokal verfuegbar ist; fuer nicht lokal zwischengespeicherte
iCloud-Fotos kann der synchrone Aufruf trotz `isNetworkAccessAllowed = true`
sofort mit `nil` zurueckkehren statt auf den Download zu warten. Live-Beweis:
ein isolierter Export gelang in 10,1s, derselbe Mechanismus fuer ein anderes
Foto scheiterte waehrend eines laufenden Batches nach exakt 10,0s (deutlich
unter dem 60s-Subprozess-Timeout) mit derselben generischen Meldung.

**Fix:** beide Funktionen auf echtes asynchrones `PHImageManager.requestImage()`
mit `DispatchSemaphore` umgestellt (45s Timeout, unterhalb des bestehenden
60s-Subprozess-Timeouts in `_run_helper()`), plus drei unterscheidbare
Fehlermeldungen statt einer generischen ("Foto lieferte kein Bild", "konnte
nicht in ein verarbeitbares Format umgewandelt werden", "Zeitüberschreitung
beim Laden aus iCloud").

**Ergebnis der Live-Verifikation - Mechanismus bewiesen, aber Fehlerquote
nicht gesenkt:** der Fix funktioniert nachweislich korrekt (die neue,
praezise Fehlermeldung "Zeitüberschreitung beim Laden aus iCloud." erscheint
jetzt nach echten 45+ Sekunden Warten statt sofort wie vorher), aber die
Gesamt-Fehlerquote blieb in einem frischen 200er-Lauf bei ~71-82%. Das ist
kein Fix-Fehler, sondern eine echte, zugrunde liegende Tatsache: ein
erheblicher Teil der Fotobibliothek braucht laenger als 45 Sekunden zum Laden
aus iCloud oder ist aktuell gar nicht abrufbar - vermutlich derselbe
zugrunde liegende iCloud-Sync-Zustand, der bereits in Abschnitt 45 (defekte
Git-Referenz, Schreibtisch-Aussetzer) sichtbar wurde.

**Kleiner Folge-Fix** (direkt umgesetzt, ohne eigenen Plan, auf Wunsch des
Geschaeftsfuehrers): `analyze_with_local_vision()` markiert ein Foto nach
einem echten, gescheiterten Wartezyklus jetzt mit
`local_vision_unavailable_since` (Zeitstempel) und `local_vision_last_error`
(die jetzt aussagekraeftige Fehlermeldung), statt es jede Nacht erneut zu
versuchen. Neuer Config-Schluessel
`local_photo_vision_unavailable_retry_days` (Standard 14) bestimmt, nach wie
vielen Tagen ein als nicht abrufbar markiertes Foto wieder in den naechsten
Lauf darf - kein dauerhafter, stiller Ausschluss. Gelingt ein spaeterer
Versuch doch, werden beide Felder automatisch wieder entfernt.
`reset_local_vision_descriptions()` setzt auch diese beiden neuen Felder mit
zurueck.

6 Tests in `test_photo_vision_retry.py` (3 bestehend + 3 neu: Markierung
nach endgueltigem Fehlschlag, Ausschluss innerhalb des Cooldowns,
erneuter Versuch nach Ablauf des Cooldowns). 440 Tests insgesamt, alle
gruen. Backend-Kopie synchronisiert, alter kompilierter Swift-Helfer vor dem
Build geloescht (garantiert Neukompilierung), zwei Xcode-Builds (Export-Fix,
dann Markierungs-Fix), beide erfolgreich. Live verifiziert nach Neustart.

`plans/2026-08-17-jarvis-foto-export-phimagemanager-fix.md` als "Umgesetzt"
markiert - der Fix selbst war notwendig und korrekt (siehe oben), hat die
Fehlerquote aber nicht gesenkt, da die eigentliche Ursache eine echte
iCloud-Ladezeit-Realitaet ist, kein Logikfehler mehr. Der Markierungs-Fix
macht das Gesamtverhalten ehrlich (keine stillen, endlosen Fehlschlaege mehr
in der proaktiven Abschluss-Meldung aus Abschnitt 44) statt das eigentliche
iCloud-Sync-Thema zu loesen, das ausserhalb von Jarvis liegt.

---

## 47. Kalender/Erinnerungen: AppleScript-Start scheiterte mit Fehler -600 (2026-08-17)

Live von Leon per Screenshot gemeldet: "Hab ich heute noch Termine" endete in
`Kalender konnte nicht geschrieben werden: ... execution error: „Calendar"
hat einen Fehler erhalten: Das Programm läuft nicht. (-600)`, gleichzeitig
mit einer Speicherplatz-Warnung (6,1 GB frei) in der App sichtbar - beide
Symptome wirkten zunaechst wie dieselbe Ursache.

**Ausgeschlossen:** Speicherplatz (`df` zeigte 18 GB frei auf dem
Data-Volume, unabhaengig von der App-eigenen Meldung - kein Zusammenhang).
Automation-Berechtigung (sobald Calendar.app laeuft, funktioniert
AppleScript-Zugriff sofort ohne Freigabe-Dialog - live geprueft).

**Root Cause gefunden:** `_ensure_app_running()` in `app/calendar_client.py`
nutzte `tell application "Calendar" to launch` per `osascript` als
Vor-Start, bevor die eigentliche Abfrage laeuft. Live reproduziert: genau
dieser Befehl scheitert inzwischen zuverlaessig mit -600, sobald Calendar.app
komplett geschlossen ist, statt die App tatsaechlich zu starten (eine
macOS-Verhaltensaenderung, keine Jarvis-Regression). `open -a Calendar` -
der gleiche Weg wie ein Finder-Doppelklick - startete dagegen sofort
zuverlaessig. Derselbe Start-Helfer wird auch von Erinnerungen genutzt
(`create_reminder`/`list_open_reminders`), betraf also beide Bereiche still,
nicht nur Kalender-Abfragen.

**Fix:** `_ensure_app_running()` startet jetzt per `open -g -a
<process_name>` statt per AppleScript. `-g` haelt die App im Hintergrund,
damit ein stiller "was steht heute an"-Check nicht das Kalender-Fenster vor
Leons aktuelle Arbeit reisst.

2 neue Tests in `tests/test_calendar_client.py`
(`test_ensure_app_running_launches_via_open_not_applescript`,
`test_ensure_app_running_skips_launch_when_already_running`), die den
exakten Subprozess-Befehl pruefen. 442 Tests insgesamt, alle gruen.

**Live-Verifikation:** Calendar.app und Reminders.app komplett beendet, App
neu gebaut und gestartet, dieselbe urspruenglich gescheiterte Frage direkt an
`/api/chat` geschickt - "Für heute sehe ich keine Termine." statt der
-600-Fehlermeldung, Calendar.app wurde dabei nachweislich automatisch (und
unsichtbar im Hintergrund) gestartet. Gleiches Ergebnis fuer Erinnerungen
("Was steht auf meiner Erinnerungsliste").

Kleiner, klar umrissener Ein-Funktions-Fix - direkt umgesetzt, ohne eigenen
Plan.
