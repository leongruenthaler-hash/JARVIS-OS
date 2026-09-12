---
name: health
description: Liefert Leons Apple-Health/Watch-Werte (Schlaf, Ruhepuls/HRV, Schritte, Workouts). Nutze das, wenn Leon nach seinem Schlaf, Puls, Aktivitaet, Training oder allgemein "wie geht es mir koerperlich" fragt, oder eine Automation Gesundheitswerte pruefen soll.
---

# Gesundheitswerte (Apple Health)

Liest die zuletzt von JarvisMobile per HealthKit hochgeladenen Werte ab einem
lokalen Proxy auf diesem Mac Mini (scripts/health_proxy_server.py). Kein
direkter HealthKit-Zugriff moeglich - das gibt es nur auf iOS, nicht auf
macOS - JarvisMobile liest die Werte auf dem iPhone aus und schickt sie
hierher.

## Befehl

`python3 ~/.openclaw/workspace/skills/health/cli.py status`

Liefert ein JSON etwa dieser Form:

```json
{
  "updated_at": "2026-09-12T22:10:00+02:00",
  "sleep": { "last_night_hours": 7.2 },
  "heart": { "resting_bpm": 58, "hrv_ms": 42 },
  "activity": { "steps_today": 4231, "active_energy_kcal_today": 210 },
  "workouts_last_7_days": [
    { "type": "Laufen", "start": "2026-09-11T18:03:00+02:00", "duration_min": 32 }
  ]
}
```

## Wichtige Einschraenkungen

- **`updated_at: null`** bedeutet: JarvisMobile hat noch nie Daten hochgeladen
  (App nie im Vordergrund geoeffnet, oder HealthKit-Berechtigung nicht erteilt).
  Sag das Leon ehrlich, statt Werte zu erfinden.
- Ist `updated_at` **aelter als ~24 Stunden**, sag dazu, dass die Werte
  veraltet sein koennten (die App synchronisiert nur, wenn sie im Vordergrund
  ist - kein zuverlaessiger Hintergrund-Sync in dieser Version).
- Keine historischen Trends ueber den letzten Snapshot hinaus - "wie war mein
  Schlaf letzte Woche im Schnitt" kann ehrlich nur mit den in `sleep`
  vorhandenen Feldern beantwortet werden, nicht erfinden.
