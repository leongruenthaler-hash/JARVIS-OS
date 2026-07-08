# Jarvis Compliance Checklist

Diese Checkliste ist eine technische Arbeitsgrundlage, keine Rechtsberatung.

## Umgesetzt

- [x] Zentrales Permission-System in `app/permission_manager.py`
- [x] Einzelne Berechtigungen fuer Mail, Kalender, Erinnerungen, Kontakte, Dateien, Fotos, Mikrofon, Kamera, Standort, Internet, externe APIs, Cloud-KI und Memory
- [x] Verstaendliche Erklaerung beim ersten Zugriff
- [x] Datenschutz-Dashboard in `app/privacy_dashboard.py`
- [x] Export lokaler Jarvis-Daten
- [x] Loeschen von Verlauf, Logs und lokalen Daten
- [x] Technische Logs ohne sensible Inhalte
- [x] Standardmaessig keine Telemetrie und kein Tracking
- [x] Gespraechsverlauf standardmaessig deaktiviert
- [x] Hintergrund-Mail und Hintergrund-Foto-Scan standardmaessig deaktiviert
- [x] Kalender-/Erinnerungs-Erstellung erst nach Bestaetigung
- [x] Dateien/Mail-Loeschen/Anrufe ueber bestehende Bestaetigungs-Flows
- [x] Hinweis beim Start, dass Jarvis ein KI-System ist
- [x] TODO-Markierung fuer Keychain/Secure Storage

## Offen vor produktiver Nutzung

- [ ] Rechtliche Datenschutzerklaerung erstellen lassen
- [ ] Vollstaendige DPIA/DSFA pruefen, falls sensible Daten dauerhaft verarbeitet werden
- [ ] Altersfreigabe und Zielgruppe definieren
- [ ] App-Store-Privacy-Nutrition-Labels pruefen
- [ ] App Sandbox Entitlements finalisieren
- [ ] Apple Events/Automation-Berechtigungen mit Sandbox testen
- [x] Keychain-Speicherung fuer API-Keys implementieren
- [ ] Cloud-KI-Datenminimierung technisch weiter ausbauen
- [ ] UI fuer Datenschutz-Dashboard bauen, falls Jarvis als App ausgeliefert wird
- [ ] Loesch-/Exportfunktionen in UI sichtbar anbieten
- [ ] Hintergrundaktivitaeten mit sichtbarem Status und Ein/Aus-Schalter versehen
- [ ] E-Mail-Senden nur mit Preview und finaler Bestaetigung implementieren, falls spaeter gewuenscht

## Harte Regeln fuer neue Features

- [ ] Kein Zugriff auf geschuetzte Ressourcen ohne Permission Manager
- [ ] Keine kritische Aktion ohne Action Confirmation
- [ ] Keine sensiblen Inhalte in Exceptions, Logs oder Debug-Ausgaben
- [ ] Keine privaten Apple-APIs
- [ ] Keine heimliche Hintergrundueberwachung
- [ ] Keine Cloud-Anfrage ohne Zustimmung zu `external_api` und gegebenenfalls `cloud_llm`
- [ ] Neue Datenfluesse in `DATA_FLOW.md` dokumentieren


## Secure-Storage-Tests

- [x] CLI zum Setzen des OpenAI API-Keys
- [x] CLI zum Loeschen des OpenAI API-Keys
- [x] CLI zum Pruefen des Secure Storage
- [x] Privacy-Test prueft Klartext-Key-Fundstellen in `config.json` und `.env`
- [x] Privacy-Test prueft Secret-Redaktion
- [ ] Auf final signierter App erneut mit macOS Keychain und Sandbox testen


## Lokale KI und Modelle

- [x] Lokaler Modus ist Standard
- [x] Standardmodell `phi4-mini`
- [x] OpenAI standardmaessig deaktiviert
- [x] OpenAI nur mit Keychain-Key und Zustimmung
- [x] Modellmanager fuer Ollama/OpenAI erstellt
- [x] Sprachbefehle fuer Modellwechsel
- [x] Privacy-Test prueft Ollama, Modelle und Modellwechsel
- [ ] Ollama und Modelle muessen auf dem Zielgeraet installiert werden
