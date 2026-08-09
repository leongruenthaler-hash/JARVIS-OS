# Proactivity Engine (Phase C)

Stand: 2026-08-04. Setzt Master-Plan Abschnitt 8 um: deterministische,
regelbasierte Hinweise statt eines LLM, das "von sich aus" etwas sagt.

## Grundprinzip

Kein Hinweis entsteht durch ein Sprachmodell. Jede Regel ist eine reine
Python-Funktion, die einen Kontext (Kalender-Vorschläge, ungelesene Mails,
unbestätigte Erinnerungen, Speicherplatz) prüft und - falls zutreffend -
einen `ProactiveEvent` mit **Pflichtfeld `reason`** zurückgibt: eine
nachvollziehbare, reproduzierbare Begründung, keine Vermutung.

`app/core/proactivity_engine.py`:

```
ProactivityEngine.evaluate(context, config) -> list[ProactiveEvent]
```

Ablauf pro Aufruf:

1. Alle registrierten Regeln laufen gegen den übergebenen Kontext. Eine
   fehlschlagende Regel stoppt nicht die anderen (Fehler wird geloggt).
2. Dauerhaft ausgeblendete (`dismiss_forever`) und aktuell zurückgestellte
   (`snooze`) Hinweise werden entfernt.
3. Abkühlzeit (`proactivity_cooldown_minutes`, Standard 60 Minuten): derselbe
   Hinweis (per `dedup_key`) wird nicht wiederholt gemeldet, solange er noch
   "frisch" ist.
4. Ruhezeiten (`proactivity_quiet_hours_start`/`_end` in `config.json`,
   standardmäßig leer = deaktiviert): außerhalb der erlaubten Zeit werden nur
   `kritisch`-Hinweise durchgelassen (abschaltbar über
   `proactivity_quiet_hours_allow_kritisch`).
5. Drosselung (`proactivity_max_per_hour`, Standard 4): begrenzt normale
   Hinweise pro Stunde, `kritisch` umgeht das Limit nicht künstlich.
6. Jeder tatsächlich gezeigte Hinweis wird in `memory/proactivity_events.json`
   protokolliert (Audit-Trail: Trigger, Daten, Priorität, wann gezeigt).

## Prioritätsstufen

`information` < `relevant` < `wichtig` < `kritisch` (siehe Master-Plan 8.3).

## Eingebaute Regeln (`app/core/proactivity_rules.py`)

| Regel | Priorität | Bedingung |
|---|---|---|
| `low_disk_space` | wichtig/kritisch | Freier Speicherplatz unter Schwellenwert (Standard 10% / kritisch 3%) |
| `pending_calendar_actions_waiting` | relevant | Aus Mails erkannte Kalender-Vorschläge (Phase 5/B) seit ≥2h unbestätigt |
| `unconfirmed_memory_facts` | information | ≥3 Erinnerungen mit Status `pending_confirmation` |
| `new_unread_mail` | relevant | ≥3 neue Mails seit letztem Hintergrundscan |
| `calendar_event_starting_soon` | wichtig | Ein nicht-ganztägiger Termin beginnt innerhalb von `proactivity_calendar_event_soon_minutes` (Standard 15) |
| `calendar_events_overlap` | relevant | Zwei Termine innerhalb von `proactivity_calendar_lookahead_hours` (Standard 6h) überschneiden sich zeitlich |
| `mail_matches_upcoming_event` | relevant | Absendername einer neuen Mail passt zum Titel eines anstehenden Termins (Baustein B, "Connect the dots") |
| `recurring_usage_pattern` | information | Dieselbe Anfrage-Kategorie kam an ≥`proactivity_pattern_min_weeks` (Standard 3) der letzten `proactivity_pattern_lookback_weeks` (Standard 4) Kalenderwochen zum selben Wochentag/derselben Tageszeit vor (Baustein D) |
| `important_news` | wichtig | Neue, als wichtig eingestufte Meldung(en) von CORRECTIV seit dem letzten Check |

**Nachtrag (2026-08-08):** "Termin beginnt bald" und "zwei Termine
überschneiden sich" sind jetzt umgesetzt, siehe
`plans/2026-08-08-jarvis-termin-nudges.md`. Die zuvor fehlende Grundlage
(vergleichbare Zeitstempel statt lokal-formatierter Text) wurde **additiv**
in `calendar_client.py::list_upcoming_calendar_items()` ergänzt: das
AppleScript liefert jetzt zusätzlich zu den bestehenden Text-Feldern
numerische Datumsbestandteile über AppleScripts eigene
Datumsobjekt-Eigenschaften (`year of`/`month of`/`day of`/`hours of`/
`minutes of` - sprachunabhängig, kein String-Parsing nötig), aus denen
`start_dt`/`end_dt` gebaut werden. Die bereits einmal problematische
`whose`-Filterung (Commit `45dc902`) wurde dabei bewusst nicht wieder
angefasst - die bestehende prozedurale Schleife blieb unverändert, nur die
Ausgabe pro Termin wurde um Felder ergänzt. Beide Regeln lesen
`context["upcoming_calendar_events"]`, befüllt in
`local_server.py::_proactivity_context()` - permission-gated wie der
bestehende Mail-Block, liest also nie Kalenderdaten, bevor die Kalender-
Permission erteilt wurde.

Als Nebeneffekt der neuen `start_dt`-Zeitstempel wurde auch ein gemeldeter
Bug behoben: "was steht heute an" zeigte teils Termine aus dem ganzen Jahr
statt nur von heute, vermutlich weil die bisherige Filterung allein auf
einem locale-formatierten AppleScript-Datumsvergleich beruhte.
`jarvis.py::answer_calendar_query()` filtert den `only_today`-Fall jetzt
zusätzlich anhand des robusten `start_dt` in Python nach.

**Nachtrag (2026-08-08, Baustein B):** `mail_matches_upcoming_event` verknüpft
erstmals zwei Datenquellen statt nur eine ("Connect the dots", siehe
`plans/2026-08-08-jarvis-mail-kalender-verknuepfen.md`) - vergleicht den
Absendernamen jeder neuen Mail (`context["new_mail_messages"]`) gegen den
Titel jedes anstehenden Termins im Lookahead-Fenster
(`context["upcoming_calendar_events"]`), per Fuzzy-Wortvergleich
(`core/intent_matching.py`, dieselbe Technik wie bei der Absichtserkennung).

**Bewusste Einschränkung:** der Abgleich läuft gegen den Termin-**Titel**,
nicht gegen echte Termin-**Teilnehmer** - Calendar.app's AppleScript-Zugriff
auf Teilnehmerdaten wurde bewusst nicht zusätzlich erschlossen, um nicht kurz
nach der vorsichtigen Baustein-A-Erweiterung eine weitere, riskantere
Änderung an derselben, historisch fragilen Abfrage vorzunehmen (siehe
Commit `45dc902`). Funktioniert gut, wenn Termine wie im Alltag üblich einen
Namen im Titel tragen ("Call mit Max"), erkennt aber keine Verbindung, wenn
der Name nur als Teilnehmer hinterlegt ist. Ein Teilnehmer-basierter Abgleich
bleibt ein möglicher, separat zu planender Folgeschritt.

Beim Testen fiel ein Falsch-Positiv-Risiko auf: generische
Absender-Bezeichnungen wie "Info" oder "Support" (automatisierte
Firmen-Postfächer) matchten zufällig Termine mit ähnlichen Wörtern im Titel
(z. B. "Info-Abend"). Behoben über eine eigene `_GENERIC_SENDER_WORDS`-
Ausnahmeliste, analog zur bereits bestehenden `_GENERIC_TITLE_WORDS`-Liste.

**Nachtrag (2026-08-08, Baustein D):** `recurring_usage_pattern` ist der
einzige proaktive Baustein, der dauerhaft neue Verhaltensdaten anlegt -
deshalb mit einer eigenen, bewusst datensparsamen Architektur und einer
eigenen, standardmäßig **deaktivierten** Berechtigung `usage_patterns`
(siehe `permission_manager.py`), die Leon explizit einschalten muss.

- **Was gespeichert wird:** ausschließlich Kategorie (z. B. "calendar") +
  Wochentag + grobe Tageszeit (`nachts`/`morgens`/`mittags`/`abends`),
  **niemals der Anfrage-Wortlaut** - nach demselben Vorbild wie
  `voice_performance.py` (persistiert ausschließlich Millisekunden-Zahlen).
  Aggregiert als "in welchen Kalenderwochen kam dieses Muster vor"
  (`app/core/usage_patterns.py`), nicht als Liste einzelner Ereignisse.
- **Wann gezählt wird:** direkt bei jedem erfolgreichen `has_domain()`-
  Treffer in `_answer_with_core()`/`jarvis.py::main()` - nur wenn die
  `usage_patterns`-Berechtigung erteilt ist, sonst passiert gar nichts.
- **Aktives Aufräumen:** alte Wochen außerhalb des Aufbewahrungsfensters
  werden bei jedem Schreibvorgang aktiv entfernt, nicht nur ausgeblendet.
- **Löschbar:** `PrivacyDashboard.clear_usage_patterns()` (zusätzlich zur
  ohnehin greifenden `delete_all_data()`, die jede `*.json` in `memory/`
  erfasst).
- **Vorschlag, nie Automatisierung:** ein erkanntes Muster löst genau eine
  Proactivity-Meldung aus ("soll ich dir das automatisch zeigen?"), richtet
  nie selbst etwas ein - folgt demselben Grundsatz wie
  `task_manager.py::propose_task()`.

11 neue Tests (8 in `tests/test_usage_patterns.py`, neu; 3 weitere in
`tests/test_proactivity_rules.py`) - insgesamt 138 Tests. Details:
`plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md`.

**Nachtrag (2026-08-09):** echte macOS-Systembenachrichtigungen sind jetzt
umgesetzt (siehe `plans/2026-08-09-jarvis-systembenachrichtigungen.md`) - rein
SwiftUI-seitig, kein Backend-Code geändert, da `GET /api/proactivity/events`
bereits alle nötigen Felder liefert. `AppState.refreshProactivityEvents()`
(`JarvisApp/Sources/JarvisApp/Core/AppState.swift`) plant für jedes neue
Ereignis zusätzlich zur bestehenden Chat-Nachricht eine lokale
`UNNotificationRequest` - `dedup_key` dient dabei als Notification-Identifier,
verhindert also doppelte Zustellung bei wiederholtem Polling auf dieselbe
Weise, wie es auch Snooze/Dismiss schon nutzen.

- **Ton nur bei `kritisch`** (z. B. wenig Speicherplatz, Termin startet
  gleich) - alle anderen Prioritätsstufen bleiben lautlos.
- **`.active`/`.passive` statt `.timeSensitive`/`.critical`:** Letztere
  bräuchten ein von Apple genehmigtes Entitlement, das ohne zahlendes
  Developer-Team (das Projekt ist ad hoc signiert, `CODE_SIGN_IDENTITY = "-"`)
  nicht ausgestellt werden kann. `.active` ist die höchste realistisch
  nutzbare Stufe hier.
- **Berechtigung wird genau einmal angefragt** (`NotificationPermissionManager`,
  neu, `JarvisApp/Sources/JarvisApp/Core/NotificationPermissionManager.swift`)
  - beim ersten tatsächlichen Proactivity-Ereignis, nicht pauschal beim
  App-Start. Eine Ablehnung wird dauerhaft respektiert, es wird nicht erneut
  gefragt.
- **Klick auf die Benachrichtigung** bringt Jarvis in den Vordergrund
  (`JarvisAppDelegate` implementiert jetzt `UNUserNotificationCenterDelegate`,
  `JarvisApp/Sources/JarvisApp/App/JarvisMacApp.swift`) - nutzt dieselbe
  Aktivierungslogik wie ein normaler App-Start.
- Als Nebeneffekt wurde dabei auch ein fehlendes App-Icon ergänzt (das Projekt
  hatte bis dahin gar keinen Asset-Katalog, `ASSETCATALOG_COMPILER_APPICON_NAME`
  war leer) - ein einfacher, funktionaler Platzhalter (`Assets.xcassets/
  AppIcon.appiconset`), jederzeit später ohne Code-Änderung durch ein
  finales Design ersetzbar.

**Nachtrag (2026-08-09): Jarvis spricht proaktive Hinweise.** Siehe
`plans/2026-08-09-jarvis-proaktiv-sprechen.md`. Bisher landete ein Hinweis
nur still im Chat und als (meist lautlose) Systembenachrichtigung - jetzt
spricht Jarvis ihn zusätzlich unaufgefordert aus, während die App läuft, mit
derselben Sprachausgabe, die auch normale Chat-Antworten vorliest
(`TTSService`/`ttsService.speak()`, kein Backend-Code geändert).

- **Bewusst keine eigene Prioritäts-Schwelle** - auf Leons ausdrücklichen
  Wunsch werden alle vier Stufen (`information`/`relevant`/`wichtig`/
  `kritisch`) gesprochen, auch Kleinigkeiten mit Mehrwert. Die bestehende
  serverseitige Drosselung (Abkühlzeit, max. 4/Stunde, Ruhezeiten) hält die
  Menge trotzdem im Rahmen, weil ein Ereignis nur überhaupt ankommt, wenn
  diese Filter es schon durchgelassen haben - keine Dopplung nötig.
- **Nie eine laufende Konversation unterbrechen:** `AppState.
  isConversationInProgress()` prüft `isJarvisSpeaking`/`activeSpeechPlayer`
  und `voiceState` (blockierend bei `.userSpeaking`/`.liveTranscribing`/
  `.transcribing`/`.thinking`/`.listening`/`.jarvisSpeaking`/
  `.preparingMicrophone`). Kann ein Ereignis nicht sofort gesprochen werden,
  landet es in `pendingProactiveSpeech` (neue Warteschlange) und wird
  automatisch nachgeholt, sobald `voiceState` wieder auf `.idle` wechselt
  (Hook in `setVoiceState()`) - nichts wird stillschweigend verschluckt.
- **Mail→Kalender-Vorschläge bleiben unverändert Vorschläge**, die Sie
  mündlich bestätigen - kein automatisches Eintragen, bewusst kein Bruch mit
  dem bestehenden "immer erst bestätigen"-Prinzip.
- Live auf dem echten Mac verifiziert: ein frisches, echtes
  `low_disk_space`-Ereignis kam beim App-Start an, direkt danach lief eine
  Audiowiedergabe an.

**Nachtrag (2026-08-09): Baustein "Wichtige Nachrichten" umgesetzt.** Siehe
`plans/2026-08-09-jarvis-news-baustein.md`. Neue Quelle: CORRECTIV
(`correctiv.org/feed/`) - gemeinnützig, spendenfinanziert, nicht
regierungsfinanziert, investigativer Journalismus (Leons ausdrücklicher
Wunsch). Neuer `NewsBackgroundWorker` (`app/news_background_worker.py`,
nach dem Vorbild von `MailBackgroundWorker`) prüft alle
`news_check_interval_minutes` (Standard 4h) auf neue Schlagzeilen.

- **Wichtigkeits-Einstufung passiert im Worker, nicht in der Regel** -
  `rule_important_news` (`core/proactivity_rules.py`) liest nur die bereits
  fertig klassifizierte Liste aus `context["important_news"]`, ruft selbst
  nie ein Sprachmodell auf und bleibt damit wie jede andere Regel eine reine,
  deterministische Funktion.
- **Zweistufiger Filter**, live beim Testen so entwickelt: ein reiner
  Modell-Klassifikator (`classify_headline_importance()`, Vorbild
  `jarvis.py::classify_domain_via_llm`) stufte anfangs 9-12 von 15
  Schlagzeilen fälschlich als "wichtig" ein, darunter mehrere Faktenchecks
  (Richtigstellungen von Gerüchten) und interne Redaktions-Meldungen - trotz
  expliziter Gegenbeispiele im Prompt hält sich das kleine lokale Modell
  (phi4-mini) nicht zuverlässig daran. Deshalb zusätzlich ein
  deterministischer Vorfilter (`_is_excluded_by_category()`): CORRECTIV
  kennzeichnet Faktenchecks und interne Meldungen eindeutig über den
  URL-Pfad (`/faktencheck/`, `/in-eigener-sache/`) - diese werden schon vor
  der Modell-Anfrage aussortiert, nicht erst danach. Ergebnis nach dem Fix:
  5-6 von 15 Schlagzeilen, alle davon tatsächlich substanzielle Meldungen.
- **`internet`-Berechtigung** (bereits vorhanden, wird auch für die Websuche
  genutzt) gated sowohl den Hintergrund-Check selbst als auch das Befüllen
  von `context["important_news"]` in `_proactivity_context()` - dieselbe
  "nie der erste stille Auslöser für eine Berechtigung"-Regel wie bei
  Mail/Kalender/Nutzungsmuster.
- **Jede Meldung wird genau einmal weitergereicht:**
  `NewsBackgroundWorker.drain_important_news()` leert die Warteliste beim
  Lesen - anders als z. B. `low_disk_space` (ein anhaltender Zustand, der
  absichtlich wiederholt gemeldet werden darf) ist eine einzelne
  Nachrichtenmeldung ein einmaliges Ereignis.
- Läuft automatisch mit durch die bereits bestehende Zustellung (Chat,
  Systembenachrichtigung, gesprochene Ausgabe) - kein zusätzlicher Code an
  diesen Stellen nötig.

22 neue Tests (`tests/test_news_source.py`, `tests/test_news_background_
worker.py`, neu; `tests/test_proactivity_rules.py` erweitert) - insgesamt
210 Tests. Live gegen den echten CORRECTIV-Feed und das echte lokale Modell
getestet, inklusive des gefundenen und behobenen Über-Klassifizierungs-
Problems.

## Wo Hinweise ankommen

- `GET /api/proactivity/events` - wertet aus und markiert als gezeigt (mit
  allen Regeln oben, siehe Cooldown).
- `GET /api/proactivity/history` - letzte gezeigte Hinweise, ohne erneut
  auszuwerten (genutzt vom Tagesbriefing, damit zwei Aufrufer sich nicht
  gegenseitig die Benachrichtigung "wegschnappen").
- `POST /api/proactivity/snooze {dedup_key, minutes}` - vorübergehend stumm.
- `POST /api/proactivity/dismiss {dedup_key}` - dauerhaft stumm ("Nie wieder
  für diesen Fall", Master-Plan 8.5).
- Tagesbriefing (`daily_briefing()`) fasst die letzten 30 Minuten an
  gezeigten Hinweisen mit ein.
- SwiftUI-App: `AppState.startProactivityPollingLoop()` fragt alle 5 Minuten
  ab, solange die App online ist, und zeigt neue Hinweise als System-Chat-
  Nachricht (💡-Präfix). Kein Popup/keine harte Unterbrechung.

## Bewusst nicht umgesetzt (Scope-Grenze Phase C)

- Kein Evening Review (Master-Plan 8.8) - eigenständiger Folgeschritt.
- Keine dedizierte Ruhezeiten-Einstellung in der SwiftUI-Oberfläche - aktuell
  nur über `config.json` (`proactivity_quiet_hours_start`/`_end`) steuerbar,
  wie die meisten anderen Zeitfenster-Einstellungen im Projekt
  (`background_mail_morning_time` etc.) auch nur über `config.json` laufen.
- Reisezeit vor einem Termin oder ein automatischer Abgleich mit aus Mails
  erkannten Terminvorschlägen (Baustein B aus
  `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`) - bewusst nicht Teil
  der Kalender-Nudges, könnte aber jetzt auf denselben `start_dt`/`end_dt`-
  Feldern aufbauen.
