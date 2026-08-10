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
