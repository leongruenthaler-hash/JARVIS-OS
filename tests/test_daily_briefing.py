"""Tests fuer das ausgebaute Tagesbriefing (Baustein C), siehe
plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md.
"""

from datetime import datetime, timedelta

from calendar_client import events_on_date
from core.daily_briefing import build_daily_briefing


def test_empty_briefing_falls_back_to_default_message():
    briefing = build_daily_briefing()
    assert "nichts Dringendes" in briefing


def test_briefing_lists_multiple_calendar_items_with_time():
    now = datetime.now()
    items = [
        {"title": "Standup", "start_dt": now + timedelta(hours=1)},
        {"title": "Call mit Max", "start_dt": now + timedelta(hours=2)},
    ]
    briefing = build_daily_briefing(calendar_items=items)
    assert "Standup" in briefing
    assert "Call mit Max" in briefing


def test_briefing_limits_calendar_section_to_three_with_remainder_note():
    now = datetime.now()
    items = [{"title": f"Termin {i}", "start_dt": now + timedelta(hours=i)} for i in range(1, 6)]
    briefing = build_daily_briefing(calendar_items=items, max_items_per_section=3)
    assert "Termin 1" in briefing
    assert "Termin 2" in briefing
    assert "Termin 3" in briefing
    assert "Termin 4" not in briefing
    assert "2 weitere" in briefing


def test_briefing_includes_open_tasks():
    tasks = [{"title": "Angebot schreiben", "priority": "hoch"}]
    briefing = build_daily_briefing(tasks=tasks)
    assert "Angebot schreiben" in briefing
    assert "Offene Aufgaben" in briefing


def test_briefing_includes_reminders():
    reminders = [{"title": "Mülltonne rausstellen"}]
    briefing = build_daily_briefing(reminders=reminders)
    assert "Mülltonne rausstellen" in briefing


def test_briefing_single_remaining_item_uses_singular_wording():
    now = datetime.now()
    items = [{"title": f"Termin {i}", "start_dt": now + timedelta(hours=i)} for i in range(1, 5)]
    briefing = build_daily_briefing(calendar_items=items, max_items_per_section=3)
    assert "1 weiterer" in briefing


def test_events_on_date_keeps_only_matching_day():
    now = datetime.now()
    items = [
        {"title": "Heute", "start_dt": now},
        {"title": "Naechste Woche", "start_dt": now + timedelta(days=7)},
    ]
    result = events_on_date(items)
    titles = [item["title"] for item in result]
    assert "Heute" in titles
    assert "Naechste Woche" not in titles


def test_events_on_date_keeps_items_without_start_dt():
    items = [{"title": "Unklar", "start_dt": None}]
    result = events_on_date(items)
    assert len(result) == 1
