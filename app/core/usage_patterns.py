from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from data_dir import data_root

# Baustein D ("Muster ueber Zeit erkennen"), siehe
# plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md. Bewusst nach demselben
# datensparsamen Vorbild wie voice_performance.py gebaut: gespeichert wird
# NIEMALS der Anfrage-Wortlaut, nur zu welcher Faehigkeit (domain) und WANN
# grob (Wochentag + Tageszeit-Eimer, keine genaue Uhrzeit) eine Anfrage kam -
# aggregiert als "in welchen Kalenderwochen kam das vor", nicht als
# Einzel-Ereignis-Liste. Nur aktiv, wenn die Berechtigung "usage_patterns"
# erteilt ist (siehe permission_manager.py) - Aufrufer sind dafuer
# verantwortlich, record_pattern_event() nur bei erteilter Permission
# aufzurufen, dieses Modul selbst prueft das nicht (kennt den PermissionManager
# nicht, um keine Zirkel-Abhaengigkeit einzufuehren).

TIME_BUCKETS = ("nachts", "morgens", "mittags", "abends")
_WEEKDAY_NAMES = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _restrict_to_owner(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _time_bucket(hour: int) -> str:
    if 0 <= hour < 6:
        return "nachts"
    if 6 <= hour < 12:
        return "morgens"
    if 12 <= hour < 18:
        return "mittags"
    return "abends"


def _week_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _recent_week_keys(count: int, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    return [_week_key(now - timedelta(weeks=offset)) for offset in range(count)]


def _pattern_key(domain: str, weekday: int, time_bucket: str) -> str:
    return f"{domain}:{weekday}:{time_bucket}"


class UsagePatternStore:
    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "usage_patterns.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _restrict_to_owner(temp_path)
        temp_path.replace(self.path)

    def record(self, domain: str, *, at: datetime | None = None, prune_weeks_older_than: int = 12) -> None:
        """Traegt eine Kalenderwoche fuer {domain, weekday, time_bucket} ein - nie
        mehr als einmal pro Woche pro Muster (mehrfaches Fragen am selben Tag zaehlt
        nicht mehrfach), und raeumt Wochen aelter als `prune_weeks_older_than` aktiv
        weg (Design-Entscheidung 5 im Plan: aktiv aufraeumen, nicht nur ausblenden)."""
        at = at or datetime.now()
        weekday = at.weekday()
        bucket = _time_bucket(at.hour)
        key = _pattern_key(domain, weekday, bucket)
        week = _week_key(at)

        # Wichtig: das Aufraeum-Fenster ("welche Wochen behalten wir") muss sich
        # immer nach der tatsaechlichen aktuellen Zeit richten, NICHT nach `at` -
        # sonst wuerden beim Nachtragen aelterer Ereignisse (z.B. in Tests, oder
        # wenn `at` aus einem anderen Grund in der Vergangenheit liegt) bereits
        # gespeicherte, eigentlich noch gueltige neuere Wochen faelschlich
        # herausgefiltert werden (beim Testen konkret so aufgetreten).
        keep_weeks = set(_recent_week_keys(prune_weeks_older_than, now=datetime.now()))

        data = self._load()
        entry = data.get(key)
        weeks: list[str] = list(entry.get("weeks", [])) if isinstance(entry, dict) else []
        if week not in weeks:
            weeks.append(week)
        # Aktives Aufraeumen: nur Wochen behalten, die innerhalb des
        # Aufbewahrungsfensters liegen.
        weeks = [w for w in weeks if w in keep_weeks]

        data[key] = {"domain": domain, "weekday": weekday, "time_bucket": bucket, "weeks": sorted(weeks)}
        self._save(data)

    def recurring_patterns(
        self, *, min_weeks: int = 3, lookback_weeks: int = 4, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Liefert alle Muster, die in mindestens `min_weeks` der letzten
        `lookback_weeks` Kalenderwochen vorkamen."""
        recent_weeks = set(_recent_week_keys(lookback_weeks, now=now or datetime.now()))
        results: list[dict[str, Any]] = []
        for entry in self._load().values():
            if not isinstance(entry, dict):
                continue
            weeks = set(entry.get("weeks", []))
            matching = weeks & recent_weeks
            if len(matching) >= min_weeks:
                results.append(
                    {
                        "domain": str(entry.get("domain") or ""),
                        "weekday": int(entry.get("weekday", 0)),
                        "weekday_name": _WEEKDAY_NAMES[int(entry.get("weekday", 0)) % 7],
                        "time_bucket": str(entry.get("time_bucket") or ""),
                        "week_count": len(matching),
                    }
                )
        return results

    def clear(self) -> None:
        self._save({})


USAGE_PATTERNS = UsagePatternStore()


def record_pattern_event(domain: str, *, at: datetime | None = None) -> None:
    USAGE_PATTERNS.record(domain, at=at)


def recurring_patterns(*, min_weeks: int = 3, lookback_weeks: int = 4) -> list[dict[str, Any]]:
    return USAGE_PATTERNS.recurring_patterns(min_weeks=min_weeks, lookback_weeks=lookback_weeks)


def clear_patterns() -> None:
    USAGE_PATTERNS.clear()
