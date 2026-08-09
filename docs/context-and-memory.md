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

Seit dem Phase-B-Folgeschritt "LLM-Fakten unsicherer behandeln" gilt
zusätzlich: `classify_memory_category()` liefert neben der Kategorie auch
eine Standard-`sensitivity` (z. B. Kategorie "Profil" -> `personal`), die an
`remember_fact()`/`upsert_fact()` durchgereicht wird. Fakten aus der
regelbasierten Extraktion (`source="auto"`) werden weiterhin sofort als
`status="confirmed"` gespeichert. Fakten aus der LLM-Extraktion
(`source="auto-llm"`) werden dagegen mit `confidence=0.7` und
`status="pending_confirmation"` gespeichert, weil diese Extraktion
unsicherer ist als die regelbasierte - der Nutzer bestätigt oder lehnt sie
in der Gedächtnis-Ansicht (`MemoryView.swift`) ab, statt dass sie
automatisch als bestätigt gilt.

Fakten, die auf einen `SENSITIVE_FACT_MARKERS`-Treffer laufen (Gesundheit,
Konto, Passwort, ...), werden seither ebenfalls nicht mehr stillschweigend
verworfen, sondern - genauso als `status="pending_confirmation"` - mit
`sensitivity="confidential"` gespeichert, damit sie in der Gedächtnis-Ansicht
klar als sensibel erkennbar sind und der Nutzer selbst entscheidet, ob sie
bleiben. Fakten primär über eine andere, namentlich genannte Person werden
weiterhin komplett verworfen (Datenschutz gegenüber Dritten, keine
Nutzer-Entscheidung möglich).

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

### Gedächtnis-Kern-Ansicht (Phase F-Folgeschritt)

Standardansicht ist seither nicht mehr die Liste, sondern `MemoryCoreView.swift`:
ein pulsierender Zentral-Kern mit konzentrischen Ringen pro Kategorie (größte
Kategorie am nächsten am Kern, siehe `MemoryCoreLayout.swift`), auf denen Fakten
als farblich codierte Knoten sitzen. Ein Umschalter in der Toolbar wechselt
jederzeit zurück zur Liste - beide Ansichten teilen sich dieselbe
`MemoryFactDetailSheet` für Bestätigen/Ablehnen/Löschen.

Zusätzlich zeigt ein gedämpftes, gleichbleibend kleines Punktfeld außerhalb der
Ringe den Fotos-/Dateien-Index an: sobald Jarvis tatsächlich auf ein konkretes
Foto oder eine Datei zugreift (nicht bei bloßem Auflisten/Suchen), meldet
`app/core/activity_log.py` das über `record_activity()` - Hooks sitzen in
`memory.py:touch_fact()`, `photos_client.py` (Foto-Export) und `files_client.py`
(Datei-Verschieben/-Kopieren). Die Swift-Seite pollt `GET
/api/activity/recent?since=...` alle 1,5s, aber ausschließlich solange die
Kern-Ansicht sichtbar ist (`AppState.startActivityPolling()`/
`stopActivityPolling()`), und lässt dafür einen echten, benannten Punkt im Feld
kurz aufleuchten statt jede einzelne Datei dauerhaft als eigenen Knoten zu
führen - bei potenziell zehntausenden Fotos/Dateien wäre Letzteres ein
Performance-Risiko gewesen. Details und Design-Alternativen:
`plans/2026-08-07-jarvis-memory-neural-network-view.md` im CEO-GPT-Repo.

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

## LLM-gestützte Gedächtnis-Extraktion aktiviert (2026-08-09)

Siehe `plans/2026-08-09-jarvis-gedaechtnis-llm-extraktion.md`. Neben der
regelbasierten Fakten-Erkennung (`extract_auto_memory_facts()`, feste
Satzmuster wie "ich bin...") gibt es jetzt einen zweiten, LLM-gestützten Weg
(`auto_memory_llm_extraction_enabled: true`), der auch beiläufig, nicht
exakt vorformuliert erzählte Selbstauskünfte erkennt - läuft nur, wenn die
Regex nichts gefunden hat.

- **Auslöse-Filter geschärft** (`looks_like_memory_candidate()`): vorher
  reichte praktisch jeder Satz mit "ich"/"mein". Jetzt: keine Fragen
  (Fragezeichen oder Fragewort-Anfang), keine Bitten ("gib mir"/"sag mir"/
  ...), und die Selbstauskunft muss ein passendes Aussage-Verb enthalten
  (bin/habe/wohne/arbeite/mag/...). Reduziert unnötige LLM-Aufrufe deutlich,
  ohne echte Kandidaten zu verlieren.
- **Extraktions-Prompt um Beispiele ergänzt** (`_build_memory_extraction_
  messages()`) - dieselbe Lehre wie beim News-Wichtigkeits-Filter
  (`plans/2026-08-09-jarvis-news-baustein.md`): ein kleines lokales Modell
  hält sich an "im Zweifel: false" viel zuverlässiger mit konkreten
  Positiv-/Negativ-Beispielen als nur mit einer abstrakten Regel.
- **JSON-Antwort-Parsing robuster gemacht** (`_parse_llm_fact_response()`):
  live beim Testen aufgefallen, dass das Modell trotz strikter Anweisung
  gelegentlich noch erklärenden Text vor/nach dem JSON stellt - ein
  Regex-Fallback sucht jetzt das erste JSON-Objekt im Text heraus, statt die
  Antwort sofort zu verwerfen (gleiche Technik wie in `core/multistep_
  planner.py::_extract_json_array()`). Schlägt auch das fehl, bleibt es
  beim sicheren Fehlschlagen (kein Fakt wird gespeichert), nie beim Raten.
- **Sicherheitsnetz unverändert:** LLM-erkannte Fakten werden - anders als
  der Regex-Pfad - immer mit `status: "pending_confirmation"` gespeichert,
  nie automatisch als bestätigt übernommen. Der Nutzer sieht und bestätigt/
  lehnt jeden Fund in der Gedächtnis-Ansicht selbst ab.
- **Bekannte Grenze, beim Testen live beobachtet:** die Extraktion kann den
  *Inhalt* eines Fakts gelegentlich falsch wiedergeben (Halluzination),
  auch wenn die Ja/Nein-Entscheidung selbst richtig war (Beispiel: "Ich
  trinke am liebsten Kaffee ohne Zucker" wurde einmal als "bevorzugt
  koffeinhaltigen Tee" gespeichert). Genau dafür ist `pending_confirmation`
  da - kein Fakt gilt, bevor der Nutzer ihn bestätigt hat.
- **Kosten/Performance:** jeder LLM-Aufruf läuft lokal (respektiert
  `force_local`/Privater Modus wie jeder andere Aufruf), fügt aber spürbare
  zusätzliche Wartezeit hinzu, wenn das lokale Modell bereits ausgelastet
  ist (beim Testen auf diesem Rechner teils mehrere Sekunden pro
  Extraktions-Versuch, zusätzlich zur eigentlichen Chat-Antwort).

32 neue Tests (`tests/test_memory_llm_extraction.py`, neu) - insgesamt 242.
Live auf dem echten Mac verifiziert: ein echter, unaufgefordert erzählter
Satz ("Ich wohne seit letztem Jahr in Berlin") landete korrekt als
unbestätigter Fakt im echten Gedächtnis.
