# Sprachsystem / Realtime Voice (Phase E)

Stand: 2026-08-05. Setzt Master-Plan Abschnitt 6 um. Vor dieser Phase wurde
die bestehende Sprachpipeline gründlich untersucht (siehe unten) - vieles war
bereits solide gebaut und wurde bewusst **nicht** verändert, um nichts
Funktionierendes zu riskieren.

## Was bereits vor Phase E existierte und unverändert blieb

- **Streaming-Sprachausgabe**: `StreamingSpeechPlayer.swift` +
  `IncrementalSentenceSplitter.swift` synthetisieren und sprechen Sätze, sobald
  sie aus dem Antwort-Stream fertig sind (Prefetch-Pipeline, nächster Satz
  wird synthetisiert während der aktuelle spielt).
- **Streaming-Antworttext**: `/api/chat/stream` liefert die LLM-Antwort als
  NDJSON-Chunks, sobald sie entstehen.
- **Live-Transkription**: `AppState.attemptLiveTranscription()` steuert die
  `apple_speech --live`-Hilfsbinary direkt aus Swift, liefert echte,
  inkrementell wachsende Teiltranskripte (nicht nur Batch-Ergebnisse).
- **Manuelles Unterbrechen**: `stopCurrentSpeech()`/`stopAutoListening()`
  brechen laufende Sprachausgabe und offene Zuhör-Anfragen sauber ab
  (`/api/voice/cancel-listening`, `/api/voice/speaking`).
- **Echo-Unterdrückung**: `AudioCaptureService` ignoriert eigene Aufnahmen,
  während Jarvis spricht (`isSpeaking`-Flag).

## Was in Phase E neu dazukam

### Gesprächsmodi (Master-Plan 6.4)

`app/core/voice_modes.py` (neu), fünf Modi:

| Modus | Wirkung |
|---|---|
| kurz | Erzwingt knappen Prompt + Anweisung "extrem knapp antworten" |
| standard | Bisheriges Verhalten, unverändert |
| fokus | Ausführliche, technische Antworten (kein Kompakt-Prompt) |
| diskret | Erzwingt knappen Prompt + **keine Sprachausgabe** (nur Text) |
| privat | Deaktiviert Websuche für diesen Zug; Anweisung, keine Cloud-Fähigkeiten vorauszusetzen |

Wird in `memory/settings.json` (`voice_mode`) gespeichert, per
`GET/POST /api/settings/voice-mode` gelesen/gesetzt, in `app/jarvis.py`s
`build_input()` in den System-Prompt eingespeist. Auswahl in der App:
Segmented Picker in `SettingsView.swift`.

**Diskreter Modus** wird Swift-seitig direkt anhand des bereits bekannten
`appState.voiceMode` durchgesetzt (nicht erst nach Abschluss der Antwort) -
`sendStreamingChatMessage` überspringt `StreamingSpeechPlayer.enqueue(...)`
komplett, wenn `voiceMode == "diskret"`. Der Server liefert zusätzlich ein
`voice_output_suppressed`-Feld in der Chat-Antwort (informativ/zur
Absicherung, aber nicht der primäre Durchsetzungsweg).

**"Privater Modus" ist bewusst unvollständig**: Er deaktiviert Websuche für
den aktuellen Zug (`app/local_server.py`, `_answer_with_core`), erzwingt aber
**nicht** den LLM-Provider selbst (Ollama statt OpenAI, falls Cloud-KI
aktiviert ist). Eine korrekte Provider-Erzwingung pro Zug hätte tiefere,
ungetestete Eingriffe in `app/model_router.py`/`ModelRoute` gebraucht, die
ich ohne Möglichkeit, Modellrouting live zu testen, nicht riskieren wollte.
Folgeschritt, kein aktueller Bug.

### Latenzmessung (Master-Plan 6.5)

`app/core/voice_performance.py` (neu): `VoicePerformanceLog` persistiert
**ausschließlich numerische Millisekunden-Werte** (nie Text oder Audio) in
`memory/voice_performance.json`, mit Aggregation (Durchschnitt/p95/Maximum
pro Phase). Vorher landete `AppState.swift`s bereits vorhandene
`printVoicePerformanceReportIfVoiceRun()`-Berechnung nur als `print()`-Zeile
in der Xcode-Konsole - keine Historie, kein Weg zu prüfen, ob die
Latenzziele aus Abschnitt 6.5 tatsächlich erreicht werden.

Jetzt zusätzlich: nach jedem Sprach-Turn sendet die App die schon
berechneten Werte (micReady, recordingStart, transcription, llmFirstToken,
llm, tts, playback) per Fire-and-forget-POST an
`/api/voice/performance-report`. `GET /api/voice/performance-stats?limit=N`
liefert Durchschnitt/p95/Maximum je Phase über die letzten N Züge - damit
lässt sich tatsächlich nachschauen, ob z. B. "Unterbrechen unter einer
Sekunde" (Abschnitt 6.5) real erreicht wird, statt es zu vermuten.

## Bewusst nicht umgesetzt (Scope-Grenze Phase E)

- **Automatisches Unterbrechen (Barge-in)**: Der Nutzer kann Jarvis heute nur
  manuell unterbrechen (Stopp-Aktion), nicht automatisch dadurch, dass er
  einfach anfängt zu sprechen, während Jarvis redet. Eine echte
  Auto-Barge-in-Erkennung bräuchte zuverlässige akustische Echo-Unterdrückung
  (z. B. `AVAudioEngine`-Voice-Processing), damit Jarvis nicht ständig seine
  eigene Stimme als Nutzereingabe missversteht - das ist reines
  Audio-Hardware-Verhalten, das ich in dieser Umgebung nicht durch Zuhören
  verifizieren kann. Ein blind implementierter, falsch kalibrierter
  Auto-Barge-in könnte die App unbenutzbar machen (ständiges
  Selbst-Unterbrechen). Bewusst nicht riskiert - Folgeschritt, der echtes
  Testen auf einem Gerät braucht.
- **Echtes Streaming-STT**: Keine der vier STT-Engines (`app/stt_engines.py`)
  liefert echte inkrementelle Teiltranskripte während der Aufnahme - trotz
  des Namens transkribiert auch `MoonshineStreamingEngine` nur blockweise am
  Ende. Nur der separate Apple-Speech-`--live`-Pfad liefert echte Partials
  (bereits vorher vorhanden, siehe oben). Ein echtes Streaming-Backend für
  die übrigen Engines wäre ein größerer, eigenständiger Umbau.
- Mobile Sprachsteuerung (Master-Plan 6.3) - kein iPhone-Client existiert,
  außerhalb des Projektumfangs bisher.
- "Privater Modus" erzwingt noch nicht den LLM-Provider (siehe oben).
