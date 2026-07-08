# Jarvis Data Flow

Dieses Dokument beschreibt, welche Daten Jarvis verarbeitet, wo sie gespeichert werden und wann Cloud-Dienste genutzt werden.

## Spracheingabe

1. Mikrofon nimmt lokale Audio-Chunks auf.
2. STT transkribiert lokal mit faster-whisper oder der konfigurierten lokalen Engine.
3. Terminalausgabe ist standardmaessig redigiert (`privacy_redact_console=true`).
4. Speicherung von Transkripten erfolgt nicht dauerhaft, ausser `privacy_store_conversation=true` und Permission `memory` ist erlaubt.

Erforderliche Zustimmung: `microphone`, optional `memory`.

## LLM / KI-Antworten

- Lokale KI: keine Cloud-Uebertragung.
- OpenAI/Cloud-KI: Anfrage wird an externen Dienst gesendet, nur nach Permissions `external_api` und `cloud_llm`.
- Webkontext wird nur bei erlaubtem Internetzugriff verwendet.

Erforderliche Zustimmung: `external_api`, `cloud_llm`, optional `internet`.

TODO_COMPLIANCE: Prompts sollten vor Cloud-Versand weiter minimiert oder zusammengefasst werden, besonders bei Mails, Kontakten, Kalendern und Fotos.

## Mail

- Apple Mail wird lokal ueber systemeigene Automation gelesen.
- Gelesen werden Uebersichten/Betreff/Absender/Vorschau, je nach Funktion.
- Mail-Dokumentexport kopiert passende Anhaenge oder lokale Mail-Notizen auf den Schreibtisch.
- Mail-Loeschaktionen werden vorher bestaetigt.

Erforderliche Zustimmung: `mail`, bei Schreibtisch-Export zusaetzlich `files`.

## Kalender und Erinnerungen

- Kalendertermine und Erinnerungen werden ueber Apple Calendar/Reminders erstellt.
- Erstellung erfolgt erst nach Nutzerbestaetigung.
- Automatische Kalenderanlage aus Mails ist standardmaessig deaktiviert.

Erforderliche Zustimmung: `calendar`, `reminders`, bei Mail-Auswertung auch `mail`.

## Kontakte und Anrufe

- Kontakte werden lokal ueber Apple Contacts gelesen.
- Anruf wird vorbereitet und bestaetigt; macOS/iPhone kann weitere Systembestaetigung verlangen.

Erforderliche Zustimmung: `contacts`.

## Dateien und Schreibtisch

- Jarvis liest und veraendert Dateien nur nach Permission `files`.
- Aendernde Aktionen wie Verschieben/Kopieren laufen ueber Bestaetigungsdialog.
- Der Code ist auf lokale Pfade und erlaubte Roots begrenzt.

Erforderliche Zustimmung: `files`.

TODO_COMPLIANCE: In einem Sandbox-App-Build muessen Security Scoped Bookmarks oder explizite File-Picker genutzt werden.

## Fotos

- Fotos werden ueber einen Helper und Apple Photos verarbeitet.
- Fotoindex wird lokal gespeichert.
- OpenAI Vision ist eine Cloud-Funktion und braucht externe Zustimmung.
- Hintergrundscan ist standardmaessig deaktiviert.

Erforderliche Zustimmung: `photos`, fuer OpenAI Vision zusaetzlich `external_api` und `cloud_llm`.

## Notizen

- Apple Notes wird lokal ueber systemeigene Automation gesteuert.
- Notizen werden nur nach Nutzerbefehl erstellt/geaendert.

Erforderliche Zustimmung: `notes`.

## Logs

- Logs enthalten nur Zeitstempel, Modulname, Event und Erfolg/Fehler.
- Sensible Felder werden redigiert.
- Logs koennen ueber Datenschutz-Befehl geloescht werden.

Erforderliche Zustimmung: keine, da technische Minimal-Logs. Logging kann in Config deaktiviert werden.

## Speicherorte

- Permissions: `memory/privacy_permissions.json`
- Langzeitgedaechtnis: `memory/long_memory.json`
- Verlauf: `memory/conversation.json`, standardmaessig nicht neu beschrieben
- Fotoindex: `memory/photos_index.json`
- Mailcache: `memory/background_mail_cache.json`
- Logs: `memory/logs/technical.log`
- Exporte: `memory/exports/`


## API-Keys / Secrets

OpenAI API-Keys werden ueber `app/secure_storage.py` in der macOS Keychain gespeichert. Service-Name: `JarvisOS`, Account: `OPENAI_API_KEY`.

Datenfluss:

1. Nutzer fuehrt `python3 app/jarvis.py --set-openai-key` aus.
2. Der Key wird verdeckt eingegeben und nicht angezeigt.
3. Jarvis speichert den Key in der macOS Keychain.
4. Falls ein alter `.env`-Eintrag existiert, wird er entfernt.
5. OpenAI-Requests lesen den Key zur Laufzeit aus der Keychain.
6. Logs und Terminalausgaben enthalten nur Statusinformationen, niemals den Key.

Pruefung:

- `python3 app/jarvis.py --check-secure-storage`
- `python3 app/jarvis.py --privacy-test`


## Modellverwaltung / Lokale KI

Standarddatenfluss fuer normale Antworten:

1. Sprache wird lokal transkribiert.
2. Jarvis prueft Permissions und Bestaetigungen.
3. Der aktive Provider wird aus `memory/model_settings.json` gelesen.
4. Standard: Anfrage geht lokal an Ollama mit `phi4-mini`.
5. OpenAI wird nur genutzt, wenn der Nutzer OpenAI aktiviert, Keychain-Key vorhanden ist und Cloud-Permissions erlaubt sind.

Lokale Modelle:

- `phi4-mini`
- `gemma3:4b`
- `qwen3:4b`

Installationsbefehle:

```bash
ollama pull phi4-mini
ollama pull gemma3:4b
ollama pull qwen3:4b
```
