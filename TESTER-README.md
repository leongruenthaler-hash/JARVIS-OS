# Jarvis Beta - Setup

Kurzanleitung, um Jarvis auf einem neuen Mac zum Laufen zu bringen. Dauert
beim ersten Mal ca. 10-15 Minuten (hauptsächlich Download der Python-Pakete).
Das Standard-KI-Modell (phi4-mini) ist schon in der App enthalten, kein
separater Download nötig.

Voraussetzungen: macOS 14 oder neuer, ca. 6-8 GB freier Speicherplatz.

## 1. Repo-Ordner an den richtigen Ort legen

Wichtig: Der Ordner `JARVIS-OS` muss genau unter `~/Desktop/JARVIS-OS`
liegen (also im Schreibtisch-Ordner, mit exakt diesem Namen) - die App
sucht dort nach dem Python-Backend.

Entpacke das Zip und verschiebe den `JARVIS-OS`-Ordner an diese Stelle,
falls er nicht schon dort liegt.

## 2. Python-Umgebung einmalig einrichten

Terminal öffnen (Spotlight -> "Terminal") und einfügen:

```bash
cd ~/Desktop/JARVIS-OS
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Das dauert ein paar Minuten (lädt u. a. PyTorch und Whisper herunter).

## 3. KI-Modell (nichts zu tun, aber gut zu wissen)

Die App bringt ihre eigene, abgeschottete Ollama-Instanz und das Modell
phi4-mini schon mit - kein separates Ollama-Installer, kein `ollama pull`
im Terminal nötig. Falls du zusätzlich schon eine eigene Ollama-Installation
hast: die läuft unabhängig auf ihrem üblichen Port weiter, kein Konflikt.

Zwei weitere, stärkere lokale Modelle (gemma3:4b, qwen3:4b) lassen sich
später direkt in der App unter "Modelle" mit einem Klick nachladen (je
2,5-3,5 GB Download).

**Alternative - OpenAI statt lokal:** eigenen API-Key hinterlegen:

```bash
cd ~/Desktop/JARVIS-OS
.venv/bin/python3 app/jarvis.py --set-openai-key
```

## 4. App installieren

**`JarvisApp.app` nach `/Applications` ziehen - das ist ein Pflichtschritt,
kein optionaler.** Die App bringt ein rund 2,5 GB großes KI-Modell mit; wenn
sie stattdessen im Schreibtisch-Ordner liegen bleibt und dieser bei dir mit
iCloud Drive synchronisiert wird ("Desktop & Dokumente" in den iCloud-
Einstellungen), kann macOS Teile davon zwischendurch auslagern, während die
App noch darauf zugreift - das führt zu einem harten Absturz. Erst nach
`/Applications` verschieben, dann starten.

**Beim allerersten Start:** Rechtsklick auf `JarvisApp.app` -> **Öffnen**
(nicht per Doppelklick). macOS zeigt eine Warnung, weil die App nicht über
den App Store verteilt wird - im Dialog auf "Öffnen" bestätigen. Das ist
nur beim ersten Start nötig.

## 5. Berechtigungen erlauben

Die App fragt beim ersten Gebrauch nach Mikrofonzugriff und danach, ob sie
macOS-Apps wie Kalender, Erinnerungen, Mail, Kontakte, Notizen, Musik oder
Fotos steuern darf - das erscheint erst dann, wenn du eine passende Anfrage
stellst, und jedes Mal einzeln bestätigbar (nichts läuft automatisch ohne
Rückfrage).

Tipp: Falls du Kalender.app auf diesem Mac noch nie geöffnet hast (z. B.
frisch eingerichteter iCloud-Account), öffne sie einmal manuell und schließe
ein eventuelles Konto-Setup ab, bevor du Jarvis nach Terminen fragst - das
erspart einen "hat zu lange nicht geantwortet"-Fehler beim allerersten Mal.

## 6. Loslegen

App starten, "Jarvis" sagen oder tippen. Feedback (was funktioniert nicht,
was ist komisch/unpassend) gerne direkt zurückmelden.

---

**Datenschutz-Hinweis für Tester:** Die App verarbeitet Anfragen je nach
gewähltem Modus lokal (Ollama) oder über OpenAI. Es werden keine
Konfigurationsdaten von diesem Rechner an mich (den Entwickler) geschickt -
alles bleibt lokal bei dir.
