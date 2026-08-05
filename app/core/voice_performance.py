from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from data_dir import data_root

# Master-Plan Abschnitt 6.5: "Erfasse dafuer internes Performance-Logging ohne
# Speicherung sensibler Audioinhalte." Before this, VoicePerformanceReport data
# (AppState.swift's printVoicePerformanceReportIfVoiceRun) only ever went to the
# Xcode console via print() - no history, no way to check "are we actually hitting
# the latency targets" without eyeballing individual console lines. This persists
# just the timing numbers (milliseconds per phase), nothing else.

MAX_HISTORY = 200


def _restrict_to_owner(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class VoicePerformanceLog:
    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "voice_performance.json"

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        _restrict_to_owner(temp_path)
        temp_path.replace(self.path)

    def record(self, report: dict[str, Any]) -> dict[str, Any] | None:
        """Persists only numeric duration fields (milliseconds) from `report` - any
        text/string field (which could theoretically carry transcript content by a
        caller's mistake) is silently dropped, not stored. Returns the stored entry,
        or None if nothing numeric was in the report."""
        numeric_fields = {
            key: value
            for key, value in report.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if not numeric_fields:
            return None

        entry = {"recorded_at": datetime.now().isoformat(timespec="seconds"), **numeric_fields}
        entries = self._load()
        entries.append(entry)
        self._save(entries[-MAX_HISTORY:])
        return entry

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._load()[-limit:]

    def stats(self, limit: int = 50) -> dict[str, Any]:
        entries = self.recent(limit)
        if not entries:
            return {"count": 0, "phases": {}}

        phase_keys: set[str] = set()
        for entry in entries:
            phase_keys.update(key for key in entry if key != "recorded_at")

        phases: dict[str, Any] = {}
        for key in sorted(phase_keys):
            values = sorted(entry[key] for entry in entries if key in entry)
            if not values:
                continue
            p95_index = min(len(values) - 1, int(len(values) * 0.95))
            phases[key] = {
                "avg_ms": round(sum(values) / len(values), 1),
                "p95_ms": round(values[p95_index], 1),
                "max_ms": round(max(values), 1),
                "count": len(values),
            }

        return {"count": len(entries), "phases": phases}


VOICE_PERFORMANCE_LOG = VoicePerformanceLog()
