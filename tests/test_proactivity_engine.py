"""Unit tests for the Proactivity Engine (app/core/proactivity_engine.py, Phase C).

Covers priority, quiet hours, throttling, deduplication/cooldown, snooze and
dismiss-forever - the parts that make proactivity "controlled" rather than a
constant stream of noise (Master-Plan Abschnitt 8.5).
"""

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from proactivity_engine import ProactivityEngine  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    return ProactivityEngine(base_path=tmp_path)


def _rule(priority="information", dedup_key="test_rule", message="Test-Nachricht"):
    def rule(context):
        return [{"priority": priority, "message": message, "reason": "Testgrund", "dedup_key": dedup_key}]
    return rule


def test_disabled_engine_returns_nothing(engine):
    engine.register("r", _rule())
    events = engine.evaluate({}, {"proactivity_enabled": False})
    assert events == []


def test_basic_event_is_returned(engine):
    engine.register("r", _rule(message="Hallo"))
    events = engine.evaluate({}, {})
    assert len(events) == 1
    assert events[0].message == "Hallo"
    assert events[0].reason == "Testgrund"


def test_unknown_priority_falls_back_to_information(engine):
    engine.register("r", _rule(priority="not-a-real-priority"))
    events = engine.evaluate({}, {})
    assert events[0].priority == "information"


def test_failing_rule_does_not_break_evaluation(engine):
    def broken_rule(context):
        raise RuntimeError("boom")

    engine.register("broken", broken_rule)
    engine.register("ok", _rule(message="Ich funktioniere"))
    events = engine.evaluate({}, {})
    assert len(events) == 1
    assert events[0].message == "Ich funktioniere"


def test_cooldown_prevents_immediate_repeat(engine):
    engine.register("r", _rule(dedup_key="same_key"))
    first = engine.evaluate({}, {"proactivity_cooldown_minutes": 60})
    assert len(first) == 1

    second = engine.evaluate({}, {"proactivity_cooldown_minutes": 60})
    assert second == []


def test_zero_cooldown_allows_repeats(engine):
    engine.register("r", _rule(dedup_key="same_key"))
    first = engine.evaluate({}, {"proactivity_cooldown_minutes": 0})
    second = engine.evaluate({}, {"proactivity_cooldown_minutes": 0})
    assert len(first) == 1
    assert len(second) == 1


def test_snooze_suppresses_event_until_expiry(engine):
    engine.register("r", _rule(dedup_key="snoozable"))
    engine.snooze("snoozable", minutes=60)
    events = engine.evaluate({}, {"proactivity_cooldown_minutes": 0})
    assert events == []


def test_dismiss_forever_suppresses_event_permanently(engine):
    engine.register("r", _rule(dedup_key="dismissable"))
    engine.dismiss_forever("dismissable")
    events = engine.evaluate({}, {"proactivity_cooldown_minutes": 0})
    assert events == []


def test_throttle_limits_events_per_hour(engine):
    for index in range(5):
        engine.register(f"r{index}", _rule(priority="information", dedup_key=f"key{index}"))

    events = engine.evaluate({}, {"proactivity_max_per_hour": 2, "proactivity_cooldown_minutes": 0})
    assert len(events) == 2


def test_throttle_never_blocks_kritisch_priority(engine):
    for index in range(3):
        engine.register(f"r{index}", _rule(priority="information", dedup_key=f"key{index}"))
    engine.register("critical", _rule(priority="kritisch", dedup_key="crit"))

    events = engine.evaluate({}, {"proactivity_max_per_hour": 1, "proactivity_cooldown_minutes": 0})
    priorities = [event.priority for event in events]
    assert "kritisch" in priorities


def test_quiet_hours_blocks_non_critical(engine):
    engine.register("r", _rule(priority="relevant", dedup_key="quiet_test"))
    config = {
        "proactivity_quiet_hours_start": "00:00",
        "proactivity_quiet_hours_end": "23:59",
        "proactivity_cooldown_minutes": 0,
    }
    events = engine.evaluate({}, config)
    assert events == []


def test_quiet_hours_still_allows_kritisch_by_default(engine):
    engine.register("r", _rule(priority="kritisch", dedup_key="quiet_critical"))
    config = {
        "proactivity_quiet_hours_start": "00:00",
        "proactivity_quiet_hours_end": "23:59",
        "proactivity_cooldown_minutes": 0,
    }
    events = engine.evaluate({}, config)
    assert len(events) == 1


def test_quiet_hours_can_block_kritisch_too_when_configured(engine):
    engine.register("r", _rule(priority="kritisch", dedup_key="quiet_critical_2"))
    config = {
        "proactivity_quiet_hours_start": "00:00",
        "proactivity_quiet_hours_end": "23:59",
        "proactivity_quiet_hours_allow_kritisch": False,
        "proactivity_cooldown_minutes": 0,
    }
    events = engine.evaluate({}, config)
    assert events == []


def test_recent_history_returns_evaluated_events(engine):
    engine.register("r", _rule(message="Historieneintrag"))
    engine.evaluate({}, {})
    history = engine.recent_history()
    assert len(history) == 1
    assert history[0]["message"] == "Historieneintrag"
