"""Tests fuer Baustein D (Verhaltensmuster erkennen), siehe
plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md.

Wichtig: alle Zeitangaben relativ zu datetime.now() (nicht ein fest
hinterlegtes Datum) - record()s eigenes Aufraeumen vergleicht immer gegen die
tatsaechliche aktuelle Zeit, ein fest hinterlegtes Test-Datum in der Zukunft
wuerde frisch gespeicherte Eintraege sofort wieder herausfiltern (beim
Entwickeln konkret so aufgetreten).
"""

from datetime import datetime, timedelta

import pytest

from core.usage_patterns import UsagePatternStore


@pytest.fixture
def store(tmp_path):
    return UsagePatternStore(base_path=tmp_path)


def test_recurring_pattern_detected_after_enough_weeks(store):
    now = datetime.now()
    for weeks_ago in range(4):
        store.record("calendar", at=now - timedelta(weeks=weeks_ago))

    patterns = store.recurring_patterns(min_weeks=3, lookback_weeks=4, now=now)
    assert len(patterns) == 1
    assert patterns[0]["domain"] == "calendar"
    assert patterns[0]["week_count"] == 4


def test_pattern_not_detected_below_threshold(store):
    now = datetime.now()
    for weeks_ago in range(2):
        store.record("mail", at=now - timedelta(weeks=weeks_ago))

    patterns = store.recurring_patterns(min_weeks=3, lookback_weeks=4, now=now)
    assert patterns == []


def test_same_day_multiple_requests_count_once_per_week(store):
    now = datetime.now()
    store.record("calendar", at=now)
    store.record("calendar", at=now + timedelta(hours=1))
    store.record("calendar", at=now - timedelta(weeks=1))
    store.record("calendar", at=now - timedelta(weeks=2))

    patterns = store.recurring_patterns(min_weeks=3, lookback_weeks=4, now=now)
    assert len(patterns) == 1
    assert patterns[0]["week_count"] == 3


def test_different_domains_tracked_separately(store):
    now = datetime.now()
    for weeks_ago in range(3):
        store.record("calendar", at=now - timedelta(weeks=weeks_ago))
    store.record("mail", at=now)

    patterns = store.recurring_patterns(min_weeks=3, lookback_weeks=4, now=now)
    assert len(patterns) == 1
    assert patterns[0]["domain"] == "calendar"


def test_old_weeks_outside_retention_are_pruned(store):
    now = datetime.now()
    # record() raeumt bei JEDEM Aufruf anhand der tatsaechlichen aktuellen Zeit auf
    # (nicht anhand von `at`) - ein Ereignis weit ausserhalb des Aufbewahrungs-
    # fensters wird deshalb gar nicht erst dauerhaft gespeichert.
    store.record("calendar", at=now - timedelta(weeks=20), prune_weeks_older_than=4)

    data = store._load()
    assert len(data) == 1
    entry = next(iter(data.values()))
    assert entry["weeks"] == []


def test_recent_weeks_survive_pruning_with_older_entries_present(store):
    now = datetime.now()
    # Direkt manipulierter Ausgangszustand: ein Muster mit einer sehr alten und
    # einer aktuellen Woche, um das Aufraeumen isoliert (ohne den Nebeneffekt
    # unterschiedlicher Wochentag/Zeit-Buckets bei weit auseinanderliegenden
    # `at`-Werten) zu pruefen.
    from core.usage_patterns import _pattern_key, _week_key

    key = _pattern_key("calendar", now.weekday(), "morgens")
    old_week = _week_key(now - timedelta(weeks=20))
    current_week = _week_key(now)
    store._save({key: {"domain": "calendar", "weekday": now.weekday(), "time_bucket": "morgens", "weeks": [old_week, current_week]}})

    store.record("calendar", at=now.replace(hour=9), prune_weeks_older_than=4)

    data = store._load()
    entry = data[key]
    assert old_week not in entry["weeks"]
    assert current_week in entry["weeks"]


def test_clear_removes_all_patterns(store):
    store.record("calendar")
    assert store.recurring_patterns(min_weeks=1) != []
    store.clear()
    assert store.recurring_patterns(min_weeks=1) == []


def test_no_patterns_returns_empty_list_on_fresh_store(store):
    assert store.recurring_patterns(min_weeks=1) == []
