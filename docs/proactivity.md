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
- Keine macOS-Systembenachrichtigungen (`UNUserNotificationCenter`) - Hinweise
  erscheinen aktuell nur als Chat-Nachricht, wenn die App offen ist.
- Reisezeit vor einem Termin oder ein automatischer Abgleich mit aus Mails
  erkannten Terminvorschlägen (Baustein B aus
  `plans/2026-08-08-jarvis-proaktiver-wie-iron-man.md`) - bewusst nicht Teil
  der Kalender-Nudges, könnte aber jetzt auf denselben `start_dt`/`end_dt`-
  Feldern aufbauen.
