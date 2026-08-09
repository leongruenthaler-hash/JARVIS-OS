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
    rule_calendar_event_starting_soon,
    rule_calendar_events_overlap,
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


CALENDAR_CONFIG = {"proactivity_calendar_event_soon_minutes": 15, "proactivity_calendar_lookahead_hours": 6}


def test_calendar_event_starting_soon_fires_within_window():
    now = datetime.now()
    events = [{"title": "Standup", "start_dt": now + timedelta(minutes=5), "end_dt": now + timedelta(minutes=20), "all_day": False}]
    result = rule_calendar_event_starting_soon({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events})
    assert len(result) == 1
    assert result[0]["priority"] == "wichtig"
    assert "Standup" in result[0]["message"]


def test_calendar_event_starting_soon_silent_outside_window():
    now = datetime.now()
    events = [{"title": "Später", "start_dt": now + timedelta(hours=2), "end_dt": now + timedelta(hours=3), "all_day": False}]
    assert rule_calendar_event_starting_soon({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events}) == []


def test_calendar_event_starting_soon_excludes_all_day():
    now = datetime.now()
    events = [{"title": "Urlaub", "start_dt": now + timedelta(minutes=5), "end_dt": now + timedelta(days=1), "all_day": True}]
    assert rule_calendar_event_starting_soon({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events}) == []


def test_calendar_event_starting_soon_skips_unparseable_events_without_crashing():
    events = [{"title": "Kaputt", "start_dt": None, "end_dt": None, "all_day": False}]
    assert rule_calendar_event_starting_soon({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events}) == []


def test_calendar_events_overlap_fires_for_overlapping_events():
    now = datetime.now()
    events = [
        {"title": "A", "start_dt": now + timedelta(minutes=30), "end_dt": now + timedelta(minutes=90)},
        {"title": "B", "start_dt": now + timedelta(minutes=60), "end_dt": now + timedelta(minutes=120)},
    ]
    result = rule_calendar_events_overlap({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events})
    assert len(result) == 1
    assert result[0]["priority"] == "relevant"
    assert "A" in result[0]["message"] and "B" in result[0]["message"]


def test_calendar_events_overlap_silent_for_non_overlapping_events():
    now = datetime.now()
    events = [
        {"title": "A", "start_dt": now + timedelta(minutes=30), "end_dt": now + timedelta(minutes=60)},
        {"title": "B", "start_dt": now + timedelta(minutes=90), "end_dt": now + timedelta(minutes=120)},
    ]
    assert rule_calendar_events_overlap({"config": CALENDAR_CONFIG, "upcoming_calendar_events": events}) == []
