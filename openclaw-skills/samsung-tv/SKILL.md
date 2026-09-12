---
name: samsung-tv
description: Steuert Leons Samsung-Fernseher ("65\" QLED") ueber die SmartThings-Cloud-API - genau das, was auch die SmartThings-App auf seinem iPhone kann. Nutze das, wenn Leon sagt, Jarvis solle den Fernseher an-/ausschalten, lauter/leiser stellen, stummschalten, den Kanal wechseln oder eine App (Netflix, YouTube etc.) starten.
---

# Samsung-Fernseher (SmartThings)

Direkte SmartThings-Cloud-API-Anbindung (kein Home Assistant, gleiche
Nutzerentscheidung wie bei tuya-vacuum) fuer genau ein Geraet: Leons Samsung
65" QLED, SmartThings-Geraete-ID `652e7d51-cfa9-1ac1-6566-36f32ac36e31`,
bereits als Standard-Geraet konfiguriert.

## Befehle

Alle über: `python3 ~/.openclaw/workspace/skills/samsung-tv/cli.py <befehl>`

- **`status`** - liefert Power-Status, Lautstaerke, Stummschaltung, Eingangsquelle, Kanal als JSON.
- **`on`** / **`off`** - Fernseher an-/ausschalten.
- **`volume-up`** / **`volume-down`** - Lautstaerke um eine Stufe aendern.
- **`set-volume <0-100>`** - Lautstaerke direkt setzen.
- **`mute`** / **`unmute`** - Stummschaltung an/aus.
- **`channel-up`** / **`channel-down`** - Kanal wechseln.
- **`channel <nummer>`** - direkt auf einen Kanal springen.
- **`input <quelle>`** - Eingangsquelle wechseln (z.B. `HDMI1`, `HDMI2`, `digitalTv`).
- **`launch-app <name>`** - eine App starten, z.B. `launch-app Netflix`,
  `launch-app Disney+`, `launch-app "Prime Video"`, `launch-app Spotify`,
  `launch-app "Apple Music"`, `launch-app "Apple TV"`, `launch-app YouTube`.
  Die namensbasierte Aufloesung von SmartThings ist NICHT fuer jede App
  zuverlaessig - nur Netflix funktioniert per reinem Namen, alle anderen oben
  gelisteten Apps NICHT (die API meldet "COMPLETED", startet aber
  tatsaechlich nichts). Fuer diese hat das Skript eine feste
  Namen-zu-App-ID-Tabelle (`KNOWN_APP_IDS` in cli.py), jeder Eintrag einzeln
  live am Fernseher verifiziert (2026-09-12). Startet eine App per Name
  nachweislich nicht wirklich (Leon sagt es dir, oder du kannst es nicht
  selbst am Bildschirm pruefen): sag das ehrlich statt Erfolg zu behaupten,
  und schlage vor, die numerische Samsung-App-ID zu ermitteln und in
  `KNOWN_APP_IDS` zu ergaenzen, statt wild neue IDs zu raten - oeffentlich
  kursierende IDs koennen trotzdem falsch sein (Prime Video brauchte drei
  Versuche, bis die richtige gefunden war).
- **`open-netflix`** - startet Netflix UND waehlt automatisch Leons Profil
  ("Leon Gruenthaler", das oben in der Profilliste fokussierte) aus - nutze
  das statt `launch-app Netflix`, wenn Leon direkt in sein eigenes Profil
  will ("mach Netflix mit meinem Profil an" o.ae.).
- **`keys <TASTE1> <TASTE2> ...`** - sendet eine oder mehrere Fernbedienungs-
  Tasten nacheinander (UP/DOWN/LEFT/RIGHT/OK/BACK/EXIT/MENU/HOME/MUTE/PLAY/
  PAUSE/STOP/REWIND/FF/PLAY_BACK/SOURCE) - fuer alles, was `open-netflix`
  nicht abdeckt (z.B. andere Profile, andere Apps mit In-App-Navigation).
  VORSICHT: die Profilliste in Netflix ist VERTIKAL, nicht horizontal -
  LEFT/RIGHT auf einem bereits fokussierten Profil trifft oft das kleine
  Stift-Icon ("Profil bearbeiten") daneben statt das Profil selbst zu
  waehlen (live beobachtet 2026-09-12) - fuer andere Profile lieber
  UP/DOWN benutzen, niemals blind LEFT/RIGHT + OK auf einem Profil.
- **`play`** / **`pause`** - Medienwiedergabe steuern.

## Wichtige Einschraenkungen

- Der SmartThings-Personal-Access-Token kann ablaufen (je nach Auswahl bei
  der Erstellung unter account.smartthings.com/tokens) - ein 401-Fehler
  bedeutet fast immer "Token abgelaufen", nicht einen Fehler in diesem
  Skript. Sag Leon das ehrlich, falls das passiert - er muss dann einen
  neuen Token erzeugen (kein automatischer Refresh moeglich, PATs haben
  keinen Refresh-Mechanismus wie OAuth).
- `launch-app` braucht exakte oder nahe App-Namen wie auf dem Fernseher
  angezeigt - bei sehr ungewoehnlichen/seltenen Apps kann die Namensaufloesung
  scheitern, dann ehrlich sagen statt zu erfinden, dass es geklappt hat.
