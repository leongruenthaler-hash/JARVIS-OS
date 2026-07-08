# Jarvis macOS App in Xcode

Öffne ab jetzt diese Datei in Xcode:

`JarvisApp/JarvisApp.xcodeproj`

Nicht mehr nur `Package.swift` öffnen, wenn du die echte macOS-App testen willst.

## Starten

1. Xcode öffnen.
2. `JarvisApp/JarvisApp.xcodeproj` öffnen.
3. Oben als Scheme `JarvisApp` auswählen.
4. Ziel: `My Mac`.
5. Run drücken.

## App-Identität

Die App hat jetzt einen echten Bundle Identifier:

`com.leon.jarvis`

Dadurch sollte die Warnung `Cannot index window tabs due to missing main bundle identifier` verschwinden oder deutlich seltener auftreten.

## Datenschutz-Beschreibungen

Die App enthält jetzt eigene macOS-Beschreibungen für:

- Mikrofon
- Fotos
- Kontakte
- Kalender
- Erinnerungen
- Apple Events / Automation

## Wichtig

Die bestehende Python-Logik bleibt unverändert. Die SwiftUI-App spricht weiterhin über die bestehende lokale Python-Bridge mit Jarvis.

Für eine spätere App-Store-Version müssen Signing, Sandbox, Notarization und die finalen Apple-Entitlements noch einmal sauber geprüft werden.
