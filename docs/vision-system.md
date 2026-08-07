# Vision Engine / Bildschirm-Verständnis (Phase F)

Stand: 2026-08-06. Erster Ausbauschritt der in `docs/current-system-assessment.md`
(Phase A) als "praktisch nicht vorhanden" markierten Vision Engine - bisher gab
es nur `local_vision_service.py`/`photos_client.py` für vorhandene Fotos in der
Mediathek, keinen Zugriff auf den aktuellen Bildschirminhalt.

## Was neu dazukam

- `app/screen_client.py` - Screenshot des **aktiven Fensters** (nicht des ganzen
  Bildschirms) über das macOS-eigene `screencapture`-CLI. Das aktive Fenster wird
  vorher per AppleScript (`System Events`) ermittelt; schlägt das fehl (z. B.
  fehlende Bedienungshilfen-Berechtigung), fällt der Aufruf automatisch auf eine
  Ganzbildschirm-Aufnahme zurück, statt die Anfrage scheitern zu lassen.
- `LocalVisionService.describe_screen()` (`app/local_vision_service.py`) - wie
  `describe_image()`, aber mit einem auf Bildschirminhalte statt Fotos
  zugeschnittenen Prompt (App/Fenster/sichtbarer Text statt Motiv/Farben).
- Neue Berechtigung `screen` (`app/permission_manager.py`), sichtbar in der App
  unter "Datenschutz" (`JarvisApp/Sources/JarvisApp/Views/PrivacyView.swift`) -
  wird wie jede andere Domäne (Mail, Fotos, ...) vor der ersten Nutzung explizit
  abgefragt (`ensure_privacy_domain_permission`).
- `handle_screen_command()` (`app/jarvis.py`) - Einstiegspunkt für Fragen wie
  "was siehst du gerade auf meinem Bildschirm" oder "schau dir meinen
  Bildschirm an", eingehängt in sowohl den CLI- als auch den HTTP-Chat-Pfad
  (`app/local_server.py`), analog zum bestehenden Foto-/Mail-Muster.

## Was automatisch passiert - und was nicht

- **Kein Speichern des Bildes.** Der Screenshot landet in einer Temp-Datei
  außerhalb von `data_root()`, wird sofort nach der Analyse gelöscht
  (`discard_screenshot()`) und nie in `memory/` abgelegt.
- **Der Befund wird automatisch als Fakt vorgemerkt**, ohne dass der Nutzer
  extra "merk dir das" sagen muss (frühere Zwischenstufe dieses Schritts,
  seither geändert: Nutzer will sich nicht bei jeder Bildschirmanalyse erneut
  bestätigend äußern müssen). Genau wie bei der LLM-Auto-Extraktion aus
  `docs/context-and-memory.md` (`source="auto-llm"`) landet das Ergebnis mit
  `source="auto-vision"`, `confidence=0.6` und `status="pending_confirmation"`
  im Gedächtnis - eine einzelne Bildbeschreibung kann ebenso danebenliegen wie
  eine LLM-Extraktion, deshalb kein `status="confirmed"` auf Verdacht. Der
  Nutzer sieht, bestätigt oder verwirft das Ergebnis in der Gedächtnis-Ansicht
  (`MemoryView.swift`), statt es vorher mündlich freigeben zu müssen.
- Wie jeder andere Fakt läuft der Befund vorher durch
  `classify_memory_category()` (Kategorie + `sensitivity`).

## Bewusst nicht umgesetzt (Scope-Grenze Phase F)

- Kein dauerhaftes/proaktives Mitschauen - jede Aufnahme ist weiterhin eine
  einzelne, vom Nutzer ausgelöste Anfrage für das jeweils aktive Fenster, kein
  Hintergrunddienst. Bewusst so entschieden: Dauer-Analyse würde ein lokales
  Vision-Modell (Ollama) praktisch permanent auslasten - spürbarer Akku-/
  Lüfter-Mehrverbrauch für vergleichsweise geringen Zusatznutzen gegenüber
  ereignisgesteuerten Einzelabfragen.
- Kein Speichern des Screenshot-Bildes selbst als Erinnerung, nur die
  Text-Beschreibung.
- Keine Erkennung mehrerer/aller offenen Fenster gleichzeitig, nur des
  aktuell aktiven.
