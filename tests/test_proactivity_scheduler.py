"""Unit tests for app/core/proactivity_scheduler.py (Phase 4, "Jarvis proaktiv
machen"-Plan, 2026-09-05)."""

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from proactivity_scheduler import ProactivityScheduler  # noqa: E402


def test_disabled_scheduler_never_starts_a_thread():
    scheduler = ProactivityScheduler({"proactivity_enabled": False}, tick=lambda: None, interval_seconds=1)
    scheduler.start()
    assert scheduler.thread is None


def test_zero_interval_never_starts_a_thread():
    scheduler = ProactivityScheduler({}, tick=lambda: None, interval_seconds=0)
    scheduler.start()
    assert scheduler.thread is None


def test_enabled_scheduler_ticks_repeatedly():
    # interval_seconds ist bewusst int() (Sekunden-Aufloesung reicht fuer den
    # echten Anwendungsfall, Default 300) - kein Bruchteil-Support noetig, daher
    # hier 1s statt Millisekunden testen.
    calls = []
    scheduler = ProactivityScheduler({"proactivity_enabled": True}, tick=lambda: calls.append(1), interval_seconds=1)
    scheduler.start()
    try:
        time.sleep(2.5)
        assert len(calls) >= 2
    finally:
        scheduler.stop()


def test_a_failing_tick_does_not_kill_the_loop():
    calls = []

    def flaky_tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    scheduler = ProactivityScheduler({"proactivity_enabled": True}, tick=flaky_tick, interval_seconds=1)
    scheduler.start()
    try:
        time.sleep(2.5)
        assert len(calls) >= 2
    finally:
        scheduler.stop()


def test_stop_ends_the_loop():
    calls = []
    scheduler = ProactivityScheduler({"proactivity_enabled": True}, tick=lambda: calls.append(1), interval_seconds=1)
    scheduler.start()
    time.sleep(0.2)
    scheduler.stop()
    count_at_stop = len(calls)
    time.sleep(1.5)
    # stop_event.wait() unblocks almost immediately, so at most one more tick
    # can already be mid-flight when stop() is called - never a growing stream.
    assert len(calls) <= count_at_stop + 1
