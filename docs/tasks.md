# Aufgabenverwaltung (Phase D)

Stand: 2026-08-05. Setzt Master-Plan Abschnitt 10.4 um: ein eigenständiges
Aufgaben-System, getrennt von Apple Reminders.

## Warum getrennt von Apple Reminders

`app/calendar_client.py` (`list_open_reminders`/`create_reminder`) steuert
bereits systemweite Erinnerungen in Reminders.app. Das neue Aufgaben-System
(`app/core/task_manager.py`) ist bewusst etwas anderes: interne Alltags-/
Projektaufgaben mit Priorität, Abhängigkeiten und Status, die nicht
zwangsläufig als Systembenachrichtigung auftauchen sollen. Wer eine echte
Reminders.app-Erinnerung will, sagt das weiterhin explizit ("erinnere mich
...").

## Datenmodell

Neue `memory`-Bucket `tasks` (`memory/tasks.json`), jeder Eintrag:

```
id            eindeutige ID
title         Aufgabentext
project       optionale Projektzuordnung (freier Text)
priority      niedrig | mittel | hoch | kritisch
deadline      optionales Datum (freier ISO-Text, keine Validierung)
status        vorgeschlagen | offen | in_arbeit | erledigt | abgelehnt
source        manual | conversation | mail
source_reference  optionaler Verweis auf die Quelle
depends_on    Liste anderer Task-IDs
tags          freie Schlagworte
created_at / updated_at
```

## Nicht stillschweigend verbindlich

Master-Plan: *"Jarvis darf erkannte Aufgaben nicht stillschweigend als
verbindlich speichern."* Deshalb zwei getrennte Erstellungswege:

- `create_task()` → sofort `status="offen"` - nur für explizite Nutzeranfragen
  ("erstelle eine Aufgabe ...") oder die manuelle Eingabe in der App.
- `propose_task()` → `status="vorgeschlagen"` - für alles automatisch aus
  Gesprächen oder Mails Erkannte. Wird erst durch `confirm_task()`
  verbindlich, `reject_task()` verwirft den Vorschlag.

**Aktuell nicht angebunden:** Es gibt noch keine automatische
Aufgaben-Erkennung aus Gesprächen oder Mails (`propose_task()` steht bereit,
wird aber noch nirgends automatisch aufgerufen) - das wäre ein sinnvoller,
aber eigenständiger Folgeschritt (vergleichbar mit der Mail-Kalender-Erkennung
aus Phase 5, siehe `app/mail_calendar_actions.py`), der eigene Erkennungs-
Heuristiken und eine bewusste Entscheidung bräuchte, wie aggressiv Jarvis
Aufgaben aus normalem Gesprächstext ableiten soll.

## Abhängigkeiten

`depends_on` ist eine einfache Liste anderer Task-IDs. `blocked_tasks()`
liefert alle nicht erledigten/abgelehnten Aufgaben, deren Abhängigkeit noch
nicht `erledigt` ist - in der App als "Blockiert"-Badge sichtbar. Kein
Zyklen-Check (bei rein manueller Pflege durch den Nutzer aktuell nicht
notwendig, wäre bei automatischer Erkennung ein sinnvoller Zusatz).

## API

Authentifizierte Endpunkte in `app/local_server.py`:

- `GET /api/tasks?status=...&project=...` - Liste/Filter
- `POST /api/tasks/create` - direkt verbindlich
- `POST /api/tasks/update` - Feld(er) bearbeiten
- `POST /api/tasks/confirm` / `.../reject` - Vorschlag auflösen
- `POST /api/tasks/delete` - endgültig entfernen

Swift-Seite: `JarvisApp/Sources/JarvisApp/Views/TasksView.swift`, erreichbar
über Seitenleiste ("Aufgaben") und Dashboard.

## Mail-Antwortentwürfe (ergänzend, Master-Plan Abschnitt 10.3)

`app/mail_client.py:create_reply_draft()` öffnet einen Antwortentwurf in
Mail.app mit vorangestelltem Text - **sendet nichts**. Echtes Senden ist in
diesem Projekt bewusst nicht implementiert (siehe
`PRIVACY_ARCHITECTURE.md`, `TODO_COMPLIANCE`-Eintrag zu E-Mail-Senden) und
wurde hier nicht nachgerüstet - das wäre ein eigener, sicherheitsrelevanter
Schritt mit eigenem Genehmigungsfluss (Empfänger/Betreff/Text/Anhänge vor
Versand anzeigen, siehe Master-Plan 10.3), nicht einfach ein Feature-Zusatz.
Endpunkt: `POST /api/mail/reply-draft {message_id, body}`, hinter der
`mail`-Berechtigung.

## Kontaktauflösung (Master-Plan Abschnitt 10.5)

Bereits vor Phase D vollständig vorhanden in `app/contacts_client.py`
(`find_contacts` mit Levenshtein-Fuzzy-Matching, `call_contact_by_name` fragt
bei mehreren Treffern oder mehreren Telefonnummern gezielt nach). Keine
Änderung nötig.

## Bewusst nicht umgesetzt (Scope-Grenze Phase D)

- Kalenderzeit-basierte Konflikterkennung ("zwei Termine überschneiden
  sich", Terminvorschläge mit freien Zeiträumen) - blockiert weiterhin auf
  derselben AppleScript-Datumsparsing-Einschränkung wie in Phase C
  dokumentiert (`docs/proactivity.md`).
- Kein echtes E-Mail-Senden (siehe oben).
- Keine automatische Aufgaben-Erkennung aus Gesprächen/Mails (siehe oben).
- Keine Zyklen-Erkennung bei `depends_on`.
