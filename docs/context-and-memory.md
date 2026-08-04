# Context Engine und Memory (Phase B)

Stand: 2026-08-04. Ergänzt `PRIVACY_ARCHITECTURE.md` und `DATA_FLOW.md` um die
in Phase B eingeführte strukturierte Erinnerungs- und Kontext-Verwaltung.

## Was sich geändert hat

Vor Phase B bestand ein gespeicherter Fakt nur aus `content`, `category`,
`created_at`, `updated_at`, `source`. Beim Aufbau eines Prompts wurden einfach
die N zuletzt aktualisierten Fakten angehängt (`build_memory_summary()` in
`app/jarvis.py`) - unabhängig davon, ob sie zur aktuellen Frage passten.

Seit Phase B trägt jeder Fakt zusätzlich:

```
id                 eindeutige, stabile ID (für Bearbeiten/Löschen/Bestätigen)
scope              private | business | project | conversation | temporary-session
source_type        manual | auto | auto-llm | ...
source_reference   optionaler Verweis auf die Quelle (z. B. Mail-ID)
last_used_at       wann der Fakt zuletzt tatsächlich in einem Prompt landete
confidence         0.0-1.0, aktuell meist 1.0 (regelbasierte Extraktion)
sensitivity        normal | personal | confidential | highly-sensitive
retention_policy   until_deleted | session | expires
expires_at         optionales Ablaufdatum
user_confirmed     ob der Nutzer den Fakt explizit bestätigt hat
status             confirmed | pending_confirmation | rejected
tags               freie Schlagworte, u. a. für Context Packs
related_entities   vorbereitet für spätere Verknüpfungen (aktuell ungenutzt)
```

Alte Einträge werden beim ersten Lesen automatisch (verlustfrei) auf dieses
Schema angehoben (`_ensure_fact_fields()` in `app/memory.py`) - keine
Migration nötig, kein Datenverlust.

## Context Engine

`app/core/context_engine.py` ersetzt `build_memory_summary()`:

1. Nimmt alle aktiven Fakten (`status != rejected`, nicht abgelaufen, nicht
   `pending_confirmation`).
2. Filtert optional nach aktivem Context Pack (Kategorie/Tag).
3. Sortiert nach (Relevanz zur aktuellen Frage, Aktualität) - ein Fakt, der
   inhaltlich zur Frage passt, gewinnt gegen einen bloß neueren Fakt. Bei
   keiner Übereinstimmung verhält es sich wie vorher (nur nach Aktualität).
4. Füllt bis zu einem Zeichen-/Anzahl-Budget (`memory_summary_max_facts` in
   `config.json`, wie zuvor).
5. Markiert verwendete Fakten als `last_used_at` (sichtbar in der
   Gedächtnis-Ansicht der App).

Eingebunden in `app/jarvis.py:build_input()`, das für sowohl den CLI- als auch
den HTTP-Chat-Pfad (`local_server.py`) genutzt wird - keine doppelte Logik.

## Speicherregeln (unverändert, jetzt mit Metadaten sichtbar)

Die bestehende, bereits vor Phase B vorhandene Klassifizierung in
`app/jarvis.py` (`should_skip_auto_memory`, `extract_auto_memory_facts`,
`SENSITIVE_FACT_MARKERS`, optionale LLM-Extraktion mit
Selbstbezug-/Sensibilitäts-Filter) bleibt unverändert die Instanz, die
entscheidet, *ob* etwas automatisch gespeichert wird. Phase B ändert nur,
*was* beim Speichern zusätzlich mitgeschrieben wird, und macht das Ergebnis
in der App einsehbar und korrigierbar - sie lockert die bestehenden
Sensibilitätsfilter nicht.

## Memory-Verwaltung (Gedächtnis-Ansicht)

Neue authentifizierte Endpunkte in `app/local_server.py`:

- `GET /api/memory/facts?search=...&category=...` - Liste/Suche
- `POST /api/memory/facts/update` - Feld(er) bearbeiten
- `POST /api/memory/facts/confirm` / `.../reject` - Status setzen
- `POST /api/memory/facts/delete` - endgültig entfernen

Diese Endpunkte sind absichtlich **nicht** hinter der `memory`-Berechtigung
versteckt: Diese Berechtigung steuert, ob Jarvis *weiter* speichern darf,
nicht ob der Nutzer sehen darf, was bereits gespeichert ist.

Swift-Seite: `JarvisApp/Sources/JarvisApp/Views/MemoryView.swift`, erreichbar
über die Seitenleiste ("Gedächtnis") und als Dashboard-Kachel wie jede andere
bestehende Ansicht (kein Platzhalter).

## Context Packs

`config.json` kennt `active_context_pack` (Name oder leer = deaktiviert) und
`context_packs` (benannte Filter aus `categories`/`tags`). Ist ein Pack aktiv,
sieht die Context Engine nur passende Fakten. Standardmäßig ist kein Pack
aktiv - Verhalten bleibt wie zuvor, bis der Nutzer das bewusst umstellt.

## Bewusst nicht umgesetzt (Scope-Grenze Phase B)

- Keine Umstellung auf eine echte Datenbank (siehe Bestandsaufnahme, Abschnitt 2)
  - weiterhin JSON-Dateien mit atomaren Schreibvorgängen.
- Kein Kontextbudget in Tokens (nur Zeichen/Anzahl) - eine echte
  Tokenizer-basierte Zählung wäre ein sinnvoller Folgeschritt, sobald der
  Provider-Wechsel (Ollama/OpenAI) das rechtfertigt.
- Keine automatische Ablauf-Bereinigung (abgelaufene Fakten werden nur aus dem
  *Kontext* ausgeblendet, nicht automatisch gelöscht - der Nutzer sieht und
  löscht sie bewusst in der Gedächtnis-Ansicht).
- `related_entities` ist im Schema vorbereitet, aber ungenutzt - kein
  Beziehungsgraph in dieser Phase.
