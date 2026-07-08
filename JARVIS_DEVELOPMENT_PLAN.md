# Jarvis Entwicklungsplan

Stand: 2026-07-06

## Zielbild

Jarvis soll sich klar von ChatGPT, Siri und Apple Intelligence unterscheiden:

- lokal zuerst
- privacy-first
- handlungsfähig statt nur gesprächig
- proaktiv, aber kontrollierbar
- macOS-tief integriert
- später iPhone-erweiterbar

Der Kern soll nicht in einer einzigen großen Datei wachsen, sondern in klar getrennten Modulen mit sauberem Zuständigkeitsbereich.

---

## 1. Zielarchitektur

### A. Python-Core

Der Python-Core bleibt die fachliche Wahrheit für:

- LLM-Routing
- Memory
- lokale Datenquellen
- macOS-Aktionen
- Kalender, Mail, Dateien, Fotos
- Automationen
- Proaktivität
- Sicherheits- und Datenschutzlogik

### B. Lokaler App-Server

Die SwiftUI-App spricht ausschließlich mit einem lokalen Server.

Aufgaben:

- API für Chat, Status, Modelle, Berechtigungen
- Streaming-Antworten
- Scan- und Index-Status
- sichere Aktionsfreigaben
- keine UI-Logik

### C. SwiftUI-App

Die App ist die Bedienoberfläche:

- Chat
- Home
- Aktionszentrale
- Mail
- Kalender/Erinnerungen
- Dateien
- Fotos
- Datenschutz
- Modelle
- Einstellungen

---

## 2. Empfohlene Ordnerstruktur

### Python

```text
app/
  core/
    action_router.py
    automation_engine.py
    conversation_manager.py
    daily_briefing.py
    document_index.py
    memory_system.py
    personality_manager.py
    proactive_engine.py
    provider_router.py
    safety_dashboard.py
    screen_understanding.py
    plugin_manager.py

  services/
    calendar_service.py
    contacts_service.py
    file_service.py
    mail_service.py
    photo_service.py
    stt_service.py
    tts_service.py
    system_service.py
    llm_service.py

  storage/
    memory.db
    automation.db
    document_index.db
    photo_index.db
    settings.json
```

### SwiftUI

```text
JarvisApp/Sources/JarvisApp/
  Core/
    AppState.swift
    JarvisAPIClient.swift
    LocalServerController.swift
    JarvisModels.swift
    JarvisPersonality.swift

  Views/
    HomeView.swift
    ChatView.swift
    ActionCenterView.swift
    MailView.swift
    CalendarRemindersView.swift
    FilesView.swift
    PhotosView.swift
    PrivacyView.swift
    ModelsView.swift
    SettingsView.swift
    OnboardingView.swift

  Components/
    JarvisVoiceOrb.swift
    SuggestionChipRow.swift
    ScanProgressCard.swift
    LiquidGlassBackground.swift
```

---

## 3. Priorisierung

### MVP

1. `action_router`
2. `memory_system`
3. `personality_manager`
4. `conversation_manager`
5. `daily_briefing`
6. einfache `automation_engine`

### Beta

1. `proactive_engine`
2. `document_index`
3. `screen_understanding`
4. `plugin_system`
5. `safety_dashboard`

### Später

1. iPhone-Anbindung
2. Multi-Device-Sync
3. Plugin-Store
4. semantische Suche über alle Quellen
5. ausgefeilter Tagesassistent

---

## 4. Konkrete Arbeitspakete

### Arbeitspaket 1: Architektur festziehen

Ziel:

- Modulgrenzen fixieren
- Provider-Struktur festlegen
- Sicherheitsregeln klar definieren

Ergebnis:

- ein technisches Architektur-Dokument
- einheitliche Dateinamen und Zuständigkeiten

### Arbeitspaket 2: Personality und Conversation

Ziel:

- eine einzige Quelle für Tonalität und Systemprompt
- ein stabiler Gesprächsverlauf
- klare Rollen für user/assistant/system

Ergebnis:

- Jarvis klingt konsistent
- Textchat und Voicechat nutzen dieselbe Persönlichkeit

### Arbeitspaket 3: Memory-System

Ziel:

- lokales Nutzerprofil
- Vorlieben
- Projekte
- exportier- und löschbar

Ergebnis:

- persistentes lokales Memory
- transparente Steuerung

### Arbeitspaket 4: Action Router

Ziel:

- alle macOS-Aktionen durch einen sicheren Router
- riskante Aktionen nur mit Bestätigung

Ergebnis:

- ein zentraler Platz für Ausführen, Prüfen, Bestätigen

### Arbeitspaket 5: Daily Briefing

Ziel:

- morgens und abends automatisch relevante Zusammenfassungen

Ergebnis:

- kompakte Tagesübersichten

### Arbeitspaket 6: Basic Automation

Ziel:

- einfache Regeln mit Triggern und Aktionen

Ergebnis:

- wiederkehrende Aufgaben lokal ausführbar

### Arbeitspaket 7: Proactive Engine

Ziel:

- nur relevante Hinweise, keine Dauerbeschallung

Ergebnis:

- Mail, Termine, Akku, Wetter, Fahrzeit

### Arbeitspaket 8: Dokumente und Fotos

Ziel:

- lokale Suche und semantische Indizierung

Ergebnis:

- bessere Treffer
- lokale Analyse

### Arbeitspaket 9: Bildschirmverständnis

Ziel:

- mit Zustimmung Screenshot und UI-Verständnis

Ergebnis:

- Hilfe bei Fehlermeldungen und Klickpfaden

### Arbeitspaket 10: Plugins und Dashboard

Ziel:

- Plugin-System
- Sicherheitsdashboard
- klare Berechtigungen

Ergebnis:

- erweiterbar, aber kontrolliert

---

## 5. Empfohlene Implementierungsreihenfolge

1. `personality_manager`
2. `conversation_manager`
3. `memory_system`
4. `action_router`
5. `daily_briefing`
6. `automation_engine`
7. `proactive_engine`
8. `document_index`
9. `photo_index`
10. `screen_understanding`
11. `plugin_manager`
12. `safety_dashboard`

Das ist die Reihenfolge mit dem besten Verhältnis aus Nutzen, Risiko und sichtbarem Fortschritt.

---

## 6. Sicherheitsregeln

- Keine gefährlichen Aktionen ohne Bestätigung
- Keine heimliche Datenerfassung
- Kein Cloud-Upload ohne Zustimmung
- Alles lokal speichern, wenn möglich
- Berechtigungen sichtbar machen
- Logs ohne sensible Inhalte
- Export und Löschung immer möglich

---

## 7. Konkrete Dateien für die ersten Schritte

### Python neu

- `app/core/personality_manager.py`
- `app/core/conversation_manager.py`
- `app/core/memory_system.py`
- `app/core/action_router.py`
- `app/core/daily_briefing.py`

### Python erweitern

- `app/jarvis.py`
- `app/local_server.py`
- `app/settings.py`
- `app/privacy_dashboard.py`

### SwiftUI neu/erweitert

- `JarvisApp/Sources/JarvisApp/Core/JarvisAPIClient.swift`
- `JarvisApp/Sources/JarvisApp/Core/AppState.swift`
- `JarvisApp/Sources/JarvisApp/Views/HomeView.swift`
- `JarvisApp/Sources/JarvisApp/Views/ChatView.swift`
- `JarvisApp/Sources/JarvisApp/Views/ActionCenterView.swift`
- `JarvisApp/Sources/JarvisApp/Views/SettingsView.swift`

---

## 8. MVP-Definition

Jarvis ist MVP-ready, wenn Folgendes stabil läuft:

- konsistente Persönlichkeit
- stabiler Chatverlauf
- lokales Memory
- Aktionen mit Bestätigung
- tägliche Briefings
- einfache Automationen
- saubere Berechtigungen

---

## 9. Beta-Definition

Jarvis ist Beta-tauglich, wenn zusätzlich Folgendes vorhanden ist:

- proaktive Hinweise
- Dokumentensuche
- Fotosuche
- Bildschirmhilfe
- Plugin-Grundsystem
- Sicherheitsdashboard

---

## 10. Nächster sinnvoller Schritt

Als nächstes würde ich mit dem **MVP-Kern** beginnen:

1. `personality_manager`
2. `conversation_manager`
3. `memory_system`
4. `action_router`

Danach kommen Daily Briefing und Automation.
