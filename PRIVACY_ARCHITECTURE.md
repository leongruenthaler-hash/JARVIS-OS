# Jarvis Privacy Architecture

Jarvis ist ein lokaler KI-Assistent fuer macOS/iOS-nahe Nutzung. Dieses Dokument beschreibt technische Compliance-Grundlagen fuer DSGVO, EU AI Act und Apple-App-Store-Vorbereitung. Es ist keine Rechtsberatung.

## Grundprinzipien

- Privacy by default: keine Telemetrie, kein Tracking, keine Hintergrundueberwachung ohne Kontrolle.
- Lokale Verarbeitung zuerst: Spracheingabe, Dateizugriff und Apple-App-Integrationen laufen lokal, soweit technisch moeglich.
- Explizite Berechtigungen: sensible Bereiche sind hinter `app/permission_manager.py` gekapselt.
- Human in the loop: kritische Aktionen werden erst nach Nutzerbestaetigung ausgefuehrt.
- Keine privaten Apple-APIs: Apple-Integrationen nutzen AppleScript, systemeigene Apps und sichtbare macOS-Berechtigungen.

## Zentrale Module

- Speech Input: `app/audio_stream.py`, `app/stt_engines.py`
- LLM Engine: `app/llm_client.py`
- Permission Manager: `app/permission_manager.py`
- Action Confirmation: `app/action_confirmation.py` und Pending-Flows in `app/jarvis.py`
- App Integrations: `app/mail_client.py`, `app/calendar_client.py`, `app/contacts_client.py`, `app/notes_client.py`, `app/photos_client.py`, `app/files_client.py`, `app/desktop_client.py`, `app/music_client.py`
- Privacy Dashboard: `app/privacy_dashboard.py`
- Secure Storage: `app/secure_storage.py`
- Logging: `app/privacy_logger.py`

## Berechtigungen

Berechtigungen werden in `memory/privacy_permissions.json` gespeichert. Standard ist deaktiviert. Beim ersten Zugriff erklaert Jarvis, warum die Berechtigung benoetigt wird, und wartet auf Zustimmung.

Aktuelle Berechtigungen:

- microphone
- camera
- location
- mail
- calendar
- reminders
- contacts
- notes
- files
- photos
- music
- internet
- external_api
- cloud_llm
- memory

## Kritische Aktionen mit Bestaetigung

Jarvis bestaetigt vor Ausfuehrung insbesondere:

- Dateien verschieben/kopieren oder sonst veraendern
- Mails loeschen oder Mail-Dokumente exportieren
- Kalendertermine und Erinnerungen erstellen
- Kontakte anrufen
- Cloud-KI oder externe APIs verwenden, wenn noch keine Zustimmung vorliegt

TODO_COMPLIANCE: E-Mail-Senden ist aktuell nicht implementiert. Falls es spaeter eingebaut wird, muss es zwingend ueber Permission `mail` plus Action-Confirmation laufen.

## Speicherung

- `memory/long_memory.json`: explizit erlaubte Langzeiterinnerungen.
- `memory/conversation.json`: Gespraechsverlauf nur, wenn `privacy_store_conversation` aktiv ist und Permission `memory` erlaubt wurde.
- `memory/background_mail_cache.json`: Hintergrund-Mailcache, nur bei erlaubtem Mailzugriff.
- `memory/photos_index.json`: lokaler Fotoindex, nur bei erlaubtem Fotozugriff.
- `memory/logs/technical.log`: technische Logs ohne sensible Inhalte.

## Apple-Kompatibilitaet

Jarvis soll keine macOS/iOS-Sicherheitsmechanismen umgehen. Fuer einen App-Store-Build sind voraussichtlich folgende Apple-Berechtigungen/Entitlements zu pruefen:

- Mikrofonzugriff
- Kontakte
- Kalender
- Erinnerungen
- Fotos
- Dateien/User Selected Files oder App Sandbox Bookmarks
- Netzwerkzugriff, falls Cloud-KI/Websuche aktiv ist
- Automation/Apple Events fuer Mail, Music, Notes, Calendar, Reminders, Contacts

TODO_COMPLIANCE: Fuer App Sandbox muessen Apple Events und Dateizugriffe enger ueber Entitlements, Security Scoped Bookmarks oder dokumentbasierte User-Auswahl abgebildet werden.

## EU-AI-Act-Transparenz

Beim Start weist Jarvis darauf hin, dass es ein KI-System ist. Wichtige Aktionen sollen assistierend vorbereitet und durch den Nutzer bestaetigt werden. Jarvis darf keine finalen wichtigen Entscheidungen autonom treffen.


## Secure Storage / API-Keys

API-Keys werden nicht in `config.json`, `.env`, Logs oder Terminalausgaben gespeichert. Jarvis nutzt `app/secure_storage.py` mit Service-Name `JarvisOS` und speichert den OpenAI API-Key in der macOS Keychain.

CLI-Befehle:

- `python3 app/jarvis.py --set-openai-key`
- `python3 app/jarvis.py --delete-openai-key`
- `python3 app/jarvis.py --check-secure-storage`

`keyring` wird optional unterstuetzt. Wenn es nicht installiert ist, nutzt Jarvis den nativen macOS-Keychain-Zugriff ueber Apples `security`-Tool. Secrets werden niemals ausgegeben oder geloggt.

TODO_COMPLIANCE: Fuer einen signierten App-Store-Build muss der Keychain-Zugriff mit der finalen Bundle-ID, App Sandbox und Entitlements getestet werden.


## Lokale KI / Modellverwaltung

Jarvis ist fuer Apple Silicon M1 mit 8 GB Unified Memory auf lokale, kleine Modelle optimiert. Standard ist `phi4-mini` ueber Ollama. Optional werden `gemma3:4b` und `qwen3:4b` unterstuetzt.

Die Modellverwaltung liegt in `app/model_manager.py` und prueft:

- ob Ollama installiert ist
- ob Ollama erreichbar ist
- welche Modelle installiert sind
- welches Modell aktiv ist
- ob OpenAI aktiv ist

Cloud-KI ist standardmaessig deaktiviert. OpenAI wird nur verwendet, wenn der Nutzer OpenAI aktiviert, ein API-Key in der macOS Keychain liegt und die Permissions `external_api` und `cloud_llm` erlaubt sind.

Performance-Vorgaben fuer M1/8 GB:

- Standardmodell `phi4-mini`
- kurzer Kontext (`recent_context_messages` begrenzt)
- Ollama `num_ctx` begrenzt
- kurze Antwortlaenge (`num_predict` begrenzt)
- keine Modellwechsel ohne Nutzerbefehl
- keine doppelte OpenAI-Client-Initialisierung
