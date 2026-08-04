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

**Bewusst nicht umgesetzt:** "Termin beginnt bald" und "zwei Termine
überschneiden sich" (Master-Plan 8.4). `calendar_client.py` liefert
Kalenderzeiten aktuell nur als lokal-formatierte Datums*strings* (macOS/
AppleScript, sprachabhängig), nicht als robust parsbare Zeitstempel - genau
die AppleScript-Abfrage, die heute schon einmal durch eine unvorsichtige
Änderung kaputtging (siehe Commit `45dc902`). Ein zuverlässiger Fix (Datum in
numerischen Komponenten statt als String ausgeben) ist ein sinnvoller, aber
eigenständiger Folgeschritt, der nicht ungetestet in derselben Änderung wie
die neue Proactivity Engine laufen sollte.

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
- Kalender-basierte Trigger (siehe oben) - blockiert auf einer sichereren
  Änderung an `calendar_client.py`.
- Keine macOS-Systembenachrichtigungen (`UNUserNotificationCenter`) - Hinweise
  erscheinen aktuell nur als Chat-Nachricht, wenn die App offen ist.
