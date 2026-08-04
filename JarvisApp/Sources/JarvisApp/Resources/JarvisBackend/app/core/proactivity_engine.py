from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from data_dir import data_root

# See docs/proactivity.md and Master-Plan Abschnitt 8.
PRIORITIES = ("information", "relevant", "wichtig", "kritisch")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}

RuleFunc = Callable[[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class ProactiveEvent:
    id: str
    trigger: str
    priority: str
    message: str
    reason: str
    data: dict[str, Any] = field(default_factory=dict)
    dedup_key: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "priority": self.priority,
            "message": self.message,
            "reason": self.reason,
            "data": self.data,
            "dedup_key": self.dedup_key,
            "created_at": self.created_at,
        }


def _restrict_to_owner(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class ProactivityEngine:
    """Deterministic, rule-based proactivity (Master-Plan Abschnitt 8). No rule here
    ever calls an LLM - a proactive nudge always has a traceable, reproducible reason
    (see `reason` on every ProactiveEvent), matching the "Begruendungspflicht"
    requirement. Rules are plain functions registered via register(); the engine only
    handles priority, quiet hours, throttling, deduplication and the audit trail.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.base_path / "proactivity_events.json"
        self._rules: list[tuple[str, RuleFunc]] = []

    def register(self, name: str, rule: RuleFunc) -> None:
        self._rules.append((name, rule))

    def _load_state(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {"history": [], "last_shown": {}, "dismissed_forever": [], "snoozed_until": {}}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"history": [], "last_shown": {}, "dismissed_forever": [], "snoozed_until": {}}
        data.setdefault("history", [])
        data.setdefault("last_shown", {})
        data.setdefault("dismissed_forever", [])
        data.setdefault("snoozed_until", {})
        return data

    def _save_state(self, state: dict[str, Any]) -> None:
        state["history"] = state["history"][-200:]
        temp_path = self.cache_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        _restrict_to_owner(temp_path)
        temp_path.replace(self.cache_path)

    def evaluate(self, context: dict[str, Any], config: dict[str, Any] | None = None) -> list[ProactiveEvent]:
        config = config or {}
        if not bool(config.get("proactivity_enabled", True)):
            return []

        now = datetime.now()
        state = self._load_state()

        candidates: list[ProactiveEvent] = []
        for rule_name, rule in self._rules:
            try:
                raw_events = rule(context) or []
            except Exception as exc:
                # A single misbehaving rule (e.g. a data source that's temporarily
                # unavailable) must never take down the whole evaluation pass.
                print(f"Proactivity-Regel '{rule_name}' fehlgeschlagen: {type(exc).__name__}")
                continue
            for raw in raw_events:
                priority = raw.get("priority") if raw.get("priority") in PRIORITIES else "information"
                dedup_key = str(raw.get("dedup_key") or f"{rule_name}:{raw.get('message', '')}")
                candidates.append(
                    ProactiveEvent(
                        id=uuid.uuid4().hex[:12],
                        trigger=rule_name,
                        priority=priority,
                        message=str(raw.get("message") or ""),
                        reason=str(raw.get("reason") or ""),
                        data=dict(raw.get("data") or {}),
                        dedup_key=dedup_key,
                        created_at=now.isoformat(timespec="seconds"),
                    )
                )

        dismissed_forever = set(state.get("dismissed_forever", []))
        snoozed_until = state.get("snoozed_until", {})
        candidates = [event for event in candidates if event.dedup_key not in dismissed_forever]
        candidates = [
            event
            for event in candidates
            if not self._is_snoozed(event.dedup_key, snoozed_until, now)
        ]

        cooldown_minutes = int(config.get("proactivity_cooldown_minutes", 60))
        last_shown = state.get("last_shown", {})
        candidates = [
            event
            for event in candidates
            if not self._within_cooldown(event.dedup_key, last_shown, now, cooldown_minutes)
        ]

        candidates = self._apply_quiet_hours(candidates, config, now)
        candidates.sort(key=lambda event: PRIORITY_RANK.get(event.priority, 0), reverse=True)
        candidates = self._apply_throttle(candidates, state, config, now)

        for event in candidates:
            last_shown[event.dedup_key] = now.isoformat(timespec="seconds")
            state["history"].append(event.to_dict())
        state["last_shown"] = last_shown
        if candidates:
            self._save_state(state)

        return candidates

    @staticmethod
    def _is_snoozed(dedup_key: str, snoozed_until: dict[str, str], now: datetime) -> bool:
        until = snoozed_until.get(dedup_key)
        if not until:
            return False
        try:
            return datetime.fromisoformat(until) > now
        except ValueError:
            return False

    @staticmethod
    def _within_cooldown(dedup_key: str, last_shown: dict[str, str], now: datetime, cooldown_minutes: int) -> bool:
        last = last_shown.get(dedup_key)
        if not last or cooldown_minutes <= 0:
            return False
        try:
            return datetime.fromisoformat(last) + timedelta(minutes=cooldown_minutes) > now
        except ValueError:
            return False

    @staticmethod
    def _apply_quiet_hours(events: list[ProactiveEvent], config: dict[str, Any], now: datetime) -> list[ProactiveEvent]:
        start_text = str(config.get("proactivity_quiet_hours_start") or "").strip()
        end_text = str(config.get("proactivity_quiet_hours_end") or "").strip()
        if not start_text or not end_text:
            return events

        try:
            start_hour, start_minute = (int(part) for part in start_text.split(":"))
            end_hour, end_minute = (int(part) for part in end_text.split(":"))
        except ValueError:
            return events

        start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        in_quiet_hours = now >= start or now < end if start > end else start <= now < end
        if not in_quiet_hours:
            return events

        allow_critical = bool(config.get("proactivity_quiet_hours_allow_kritisch", True))
        if allow_critical:
            return [event for event in events if event.priority == "kritisch"]
        return []

    @staticmethod
    def _apply_throttle(
        events: list[ProactiveEvent], state: dict[str, Any], config: dict[str, Any], now: datetime
    ) -> list[ProactiveEvent]:
        max_per_hour = int(config.get("proactivity_max_per_hour", 4))
        if max_per_hour <= 0:
            return events

        one_hour_ago = now - timedelta(hours=1)
        recent_count = 0
        for entry in state.get("history", []):
            try:
                created_at = datetime.fromisoformat(str(entry.get("created_at")))
            except ValueError:
                continue
            if created_at >= one_hour_ago:
                recent_count += 1

        allowed = max(0, max_per_hour - recent_count)
        kept: list[ProactiveEvent] = []
        for event in events:
            if event.priority == "kritisch" or len(kept) < allowed:
                kept.append(event)
        return kept

    def snooze(self, dedup_key: str, minutes: int = 60) -> None:
        state = self._load_state()
        state.setdefault("snoozed_until", {})[dedup_key] = (
            datetime.now() + timedelta(minutes=minutes)
        ).isoformat(timespec="seconds")
        self._save_state(state)

    def dismiss_forever(self, dedup_key: str) -> None:
        state = self._load_state()
        dismissed = set(state.get("dismissed_forever", []))
        dismissed.add(dedup_key)
        state["dismissed_forever"] = sorted(dismissed)
        self._save_state(state)

    def recent_history(self, limit: int = 20) -> list[dict[str, Any]]:
        state = self._load_state()
        return list(state.get("history", []))[-limit:]


PROACTIVITY_ENGINE = ProactivityEngine()
