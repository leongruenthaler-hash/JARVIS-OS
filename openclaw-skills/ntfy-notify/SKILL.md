---
name: ntfy-notify
description: Schickt Leon eine Push-Benachrichtigung aufs iPhone ueber die ntfy-App, unabhaengig davon, in welchem Chat/welcher Session gerade gesprochen wird. Nutze das IMMER, wenn eine Nachricht Leon garantiert erreichen soll, auch wenn er gerade nirgendwo mit Jarvis im Gespraech ist - allen voran bei automatisierten/geplanten Aufgaben (z.B. Kalender-Erinnerungen), deren normale Chat-Antwort sonst ins Leere liefe.
---

# Jarvis Push-Benachrichtigungen (ntfy)

Automations/Cron-Aufgaben in OpenClaw liefern per Default nur per "announce"
in die Session, in der sie erstellt wurden - ist diese Session gerade nicht
aktiv, geht die Nachricht klanglos verloren. Dieser Skill loest das: er
verschickt eine echte Push-Benachrichtigung ueber den ntfy-Standard (offener
Push-Dienst, kein Account noetig), die auf Leons iPhone ankommt, egal was
gerade sonst laeuft.

## Voraussetzungen

- Vor dem ersten `send` muss `setup` einmal gelaufen sein (legt ein privates,
  zufaelliges Topic an). Bei `setup` bekommst du eine Abonnier-Anleitung
  zurueck - gib die 1:1 an Leon weiter, damit er die ntfy-App installiert und
  das Topic abonniert.
- Ohne aktives Abonnement in der App kommt eine gesendete Nachricht nirgendwo an
  (kein Fehler, einfach niemand hoert zu) - frag im Zweifel nach, ob er die App
  schon eingerichtet hat.

## Befehle

Alle Befehle über: `python3 ~/Projekte/JARVIS-OS/openclaw-skills/ntfy-notify/cli.py <befehl> ...`

- **`setup`** - legt (falls noch nicht vorhanden) ein privates Topic an und
  gibt Server/Topic/Abonnier-Anleitung als JSON zurueck. Wiederholt aufrufbar,
  aendert ein bestehendes Topic nicht.
- **`status`** - zeigt, ob bereits eingerichtet wurde.
- **`send --title "<Titel>" --message "<Text>" [--priority min|low|default|high|urgent] [--tags "<emoji-namen>"] [--url "<link>"]`**
  - verschickt die Push-Benachrichtigung. `--tags` nutzt ntfy-Emoji-Kurznamen
    (z.B. `calendar`, `bell`, `warning`) - optional, rein kosmetisch.
  - Gibt `{"sent": true}` oder `{"sent": false, "error": "..."}` zurueck. Ein
    `false` ist normal, wenn der ntfy-Server gerade nicht erreichbar ist - kein
    Grund, eine sonst erfolgreiche Aufgabe (z.B. einen erkannten Kalendertermin)
    deswegen als gescheitert zu behandeln.

## Vorgehen

1. Bei jeder Automation/jedem Hintergrund-Task, dessen Ergebnis Leon
   garantiert erreichen soll (nicht nur "falls er gerade zuschaut"): nach dem
   eigentlichen Chat-Schritt zusaetzlich `send` mit einer kurzen, natuerlichen
   Nachricht im Jarvis-Stil aufrufen (sir ansprechen, kein Markdown, ein bis
   zwei Saetze).
2. Noch nicht eingerichtet (siehe `status`)? Erst `setup` ausfuehren und Leon
   die Abonnier-Anleitung mitteilen, bevor du dich auf `send` verlaesst.
3. Kein Ersatz fuer den normalen Chat: wenn Leon gerade aktiv mit dir
   spricht, antworte dort ganz normal - dieser Skill ist der zusaetzliche Weg
   fuer alles, was auch ohne aktiven Chat ankommen muss.
