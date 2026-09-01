"""Tests fuer die Sammel-Bestaetigung/-Ablehnung von aus Mails erkannten
Kalender-Vorschlaegen per freiem Chat-Text ("das bestaetige ich nicht"),
siehe plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.

Live-Bug (Screenshot von Leon): die proaktive Meldung "X Kalender-Vorschlaege
aus deinen Mails warten noch auf deine Bestaetigung" wurde ausgeliefert, aber
"das bestaetige ich nicht" im Chat wurde nicht verstanden - weder als
Bestaetigung noch als Ablehnung erkannt, die Anfrage fiel durch zur
verwirrten generischen LLM-Antwort.
"""

from unittest.mock import MagicMock

import pytest

import jarvis
from core.proactivity_rules import rule_pending_calendar_actions_waiting
from memory import Memory


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def _pending_marker(action_keys, set_at=None):
    import time

    return {"action_keys": action_keys, "set_at": set_at if set_at is not None else time.time()}


# --- Proactivity-Regel liefert action_keys mit --------------------------


def test_rule_includes_action_keys_in_data():
    context = {
        "config": {},
        "pending_calendar_actions": [
            {"action_key": "abc123", "title": "Zahnarzt", "proposed_at": ""},
            {"action_key": "def456", "title": "Meeting", "proposed_at": ""},
        ],
    }
    events = rule_pending_calendar_actions_waiting(context)
    assert len(events) == 1
    assert events[0]["data"]["action_keys"] == ["abc123", "def456"]
    # dedup_key traegt seit 2026-08-20 die sortierten action_keys, damit ein
    # neuer/anderer Vorschlag innerhalb des Cooldowns nicht als Duplikat des
    # alten unterdrueckt wird (app/core/proactivity_rules.py:88-96).
    assert events[0]["dedup_key"] == "pending_calendar_actions:abc123,def456"


def test_rule_omits_action_keys_without_key_field():
    context = {
        "config": {},
        "pending_calendar_actions": [{"title": "Ohne Key", "proposed_at": ""}],
    }
    events = rule_pending_calendar_actions_waiting(context)
    assert events[0]["data"]["action_keys"] == []


# --- handle_pending_action_flow: "das bestaetige ich nicht" wird erkannt -


def test_negated_confirmation_recognized_as_cancel():
    settings = {"pending_mail_calendar_confirmation": _pending_marker(["k1", "k2"])}
    memory = MagicMock()
    memory.get.return_value = settings

    mail_worker = MagicMock()
    mail_worker.resolve_pending_calendar_actions.return_value = []

    answer = jarvis.handle_pending_action_flow(
        memory, "das bestätige ich nicht", mail_worker=mail_worker, router_decision="cancel"
    )

    assert answer is not None
    assert "nicht" in answer
    mail_worker.resolve_pending_calendar_actions.assert_called_once_with(["k1", "k2"], approve=False)
    memory.set.assert_called_once()
    saved_settings = memory.set.call_args[0][1]
    assert "pending_mail_calendar_confirmation" not in saved_settings


def test_explicit_confirmation_creates_events():
    settings = {"pending_mail_calendar_confirmation": _pending_marker(["k1"])}
    memory = MagicMock()
    memory.get.return_value = settings

    mail_worker = MagicMock()
    mail_worker.resolve_pending_calendar_actions.return_value = [{"status": "created"}]

    answer = jarvis.handle_pending_action_flow(memory, "ja bitte", mail_worker=mail_worker, router_decision="confirm")

    assert answer is not None
    assert "1" in answer
    mail_worker.resolve_pending_calendar_actions.assert_called_once_with(["k1"], approve=True)


def test_confirmation_of_already_resolved_actions_reports_success_not_failure():
    """Live-Bug (Screenshot 2026-09-01): eine zweite, ueberlappende Bestaetigungs-
    Anfrage fuer dieselben, bereits eingetragenen Termine meldete faelschlich
    "konnte nicht eintragen" statt zu erkennen, dass die Termine schon existieren."""
    settings = {"pending_mail_calendar_confirmation": _pending_marker(["k1", "k2"])}
    memory = MagicMock()
    memory.get.return_value = settings

    mail_worker = MagicMock()
    mail_worker.resolve_pending_calendar_actions.return_value = [
        {"status": "created", "already_done": True},
        {"status": "created", "already_done": True},
    ]

    answer = jarvis.handle_pending_action_flow(memory, "ja", mail_worker=mail_worker, router_decision="confirm")

    assert answer is not None
    assert "bereits erledigt" in answer
    assert "nicht eintragen" not in answer


def test_expired_marker_is_discarded_silently():
    old_marker = _pending_marker(["k1"], set_at=0.0)
    settings = {"pending_mail_calendar_confirmation": old_marker}
    memory = MagicMock()
    memory.get.return_value = settings

    mail_worker = MagicMock()
    answer = jarvis.handle_pending_action_flow(memory, "ja", mail_worker=mail_worker, router_decision="confirm")

    mail_worker.resolve_pending_calendar_actions.assert_not_called()
    assert answer is not None
    assert "nicht mehr aktuell" in answer


def test_no_pending_marker_falls_through():
    memory = MagicMock()
    memory.get.return_value = {}
    answer = jarvis.handle_pending_action_flow(memory, "das bestätige ich nicht", router_decision="cancel")
    assert answer is None


def test_ambiguous_yes_without_marker_still_returns_none():
    memory = MagicMock()
    memory.get.return_value = {}
    answer = jarvis.handle_pending_action_flow(memory, "ja", router_decision="confirm")
    assert answer is None


# --- has_pending_action() erkennt den neuen Schluessel ---------------------


def test_has_pending_action_detects_mail_calendar_confirmation(memory):
    settings = memory.get("settings") or {}
    settings["pending_mail_calendar_confirmation"] = _pending_marker(["k1"])
    memory.set("settings", settings)
    assert jarvis.has_pending_action(memory) is True
