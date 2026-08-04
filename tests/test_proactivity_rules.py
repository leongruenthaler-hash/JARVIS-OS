"""Unit tests for the default Proactivity Engine rules (app/core/proactivity_rules.py)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from proactivity_rules import (  # noqa: E402
    rule_low_disk_space,
    rule_new_unread_mail,
    rule_pending_calendar_actions_waiting,
    rule_unconfirmed_memory_facts,
)


def test_low_disk_space_fires_when_below_threshold(monkeypatch):
    class FakeUsage:
        total = 100 * 1024**3
        free = 5 * 1024**3  # 5%

    monkeypatch.setattr("proactivity_rules.shutil.disk_usage", lambda _: FakeUsage())
    events = rule_low_disk_space({"config": {"proactivity_low_disk_percent_threshold": 10}})
    assert len(events) == 1
    assert events[0]["priority"] == "wichtig"


def test_low_disk_space_silent_when_above_threshold(monkeypatch):
    class FakeUsage:
        total = 100 * 1024**3
        free = 50 * 1024**3  # 50%

    monkeypatch.setattr("proactivity_rules.shutil.disk_usage", lambda _: FakeUsage())
    events = rule_low_disk_space({"config": {"proactivity_low_disk_percent_threshold": 10}})
    assert events == []


def test_low_disk_space_critical_below_critical_threshold(monkeypatch):
    class FakeUsage:
        total = 100 * 1024**3
        free = 1 * 1024**3  # 1%

    monkeypatch.setattr("proactivity_rules.shutil.disk_usage", lambda _: FakeUsage())
    events = rule_low_disk_space({
        "config": {"proactivity_low_disk_percent_threshold": 10, "proactivity_critical_disk_percent_threshold": 3}
    })
    assert events[0]["priority"] == "kritisch"


def test_pending_calendar_actions_empty_is_silent():
    assert rule_pending_calendar_actions_waiting({"pending_calendar_actions": []}) == []


def test_pending_calendar_actions_fires_when_old_enough():
    old_proposal = {
        "title": "Zahnarzttermin",
        "proposed_at": (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds"),
    }
    events = rule_pending_calendar_actions_waiting({
        "pending_calendar_actions": [old_proposal],
        "config": {"proactivity_pending_calendar_action_hours": 2},
    })
    assert len(events) == 1
    assert events[0]["priority"] == "relevant"
    assert "Zahnarzttermin" in events[0]["message"]


def test_pending_calendar_actions_silent_when_too_fresh():
    fresh_proposal = {
        "title": "Gerade erst",
        "proposed_at": datetime.now().isoformat(timespec="seconds"),
    }
    events = rule_pending_calendar_actions_waiting({
        "pending_calendar_actions": [fresh_proposal],
        "config": {"proactivity_pending_calendar_action_hours": 2},
    })
    assert events == []


def test_pending_calendar_actions_missing_timestamp_errs_toward_showing():
    legacy_proposal = {"title": "Alt, ohne Zeitstempel"}
    events = rule_pending_calendar_actions_waiting({
        "pending_calendar_actions": [legacy_proposal],
        "config": {"proactivity_pending_calendar_action_hours": 2},
    })
    assert len(events) == 1


def test_unconfirmed_memory_facts_below_minimum_is_silent():
    events = rule_unconfirmed_memory_facts({
        "pending_confirmation_facts": [{}, {}],
        "config": {"proactivity_pending_facts_min_count": 3},
    })
    assert events == []


def test_unconfirmed_memory_facts_fires_at_minimum():
    events = rule_unconfirmed_memory_facts({
        "pending_confirmation_facts": [{}, {}, {}],
        "config": {"proactivity_pending_facts_min_count": 3},
    })
    assert len(events) == 1
    assert events[0]["priority"] == "information"


def test_new_unread_mail_below_minimum_is_silent():
    events = rule_new_unread_mail({
        "new_mail_messages": [{"subject": "A"}],
        "config": {"proactivity_new_mail_min_count": 3},
    })
    assert events == []


def test_new_unread_mail_fires_and_includes_subject():
    events = rule_new_unread_mail({
        "new_mail_messages": [{"subject": "Rechnung"}, {"subject": "B"}, {"subject": "C"}],
        "config": {"proactivity_new_mail_min_count": 3},
    })
    assert len(events) == 1
    assert events[0]["priority"] == "relevant"
    assert "Rechnung" in events[0]["message"]
