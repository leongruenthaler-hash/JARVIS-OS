"""Unit tests for the Voice Performance Log (app/core/voice_performance.py, Phase E)."""

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from voice_performance import VoicePerformanceLog  # noqa: E402


@pytest.fixture
def log(tmp_path):
    return VoicePerformanceLog(base_path=tmp_path)


def test_record_stores_numeric_fields(log):
    entry = log.record({"micReady": 120, "llm": 800.5})
    assert entry is not None
    assert entry["micReady"] == 120
    assert entry["llm"] == 800.5
    assert "recorded_at" in entry


def test_record_drops_non_numeric_fields(log):
    entry = log.record({"micReady": 100, "transcript": "hallo jarvis wie geht es dir"})
    assert entry is not None
    assert "transcript" not in entry
    assert entry["micReady"] == 100


def test_record_returns_none_for_report_without_numeric_fields(log):
    assert log.record({"note": "irrelevant"}) is None
    assert log.record({}) is None


def test_booleans_are_not_treated_as_numeric(log):
    # bool is technically a subclass of int in Python - must not sneak into a
    # "milliseconds" field.
    entry = log.record({"micReady": 50, "someFlag": True})
    assert entry is not None
    assert "someFlag" not in entry


def test_recent_returns_stored_entries_in_order(log):
    log.record({"micReady": 1})
    log.record({"micReady": 2})
    log.record({"micReady": 3})
    recent = log.recent(limit=10)
    assert [entry["micReady"] for entry in recent] == [1, 2, 3]


def test_stats_computes_avg_and_max(log):
    for value in (100, 200, 300):
        log.record({"llm": value})
    stats = log.stats()
    assert stats["count"] == 3
    assert stats["phases"]["llm"]["avg_ms"] == 200.0
    assert stats["phases"]["llm"]["max_ms"] == 300.0
    assert stats["phases"]["llm"]["count"] == 3


def test_stats_empty_when_no_history(log):
    stats = log.stats()
    assert stats == {"count": 0, "phases": {}}


def test_history_is_capped(log):
    for index in range(250):
        log.record({"micReady": index})
    assert len(log.recent(limit=1000)) <= 200


def test_stats_respects_limit(log):
    for index in range(10):
        log.record({"micReady": index})
    stats = log.stats(limit=3)
    assert stats["count"] == 3
