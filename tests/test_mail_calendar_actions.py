"""Tests fuer app/mail_calendar_actions.py (bisher ungetestet, siehe
plans/2026-08-09-jarvis-mail-hintergrund-aktivieren.md) - Datum/Uhrzeit-
Erkennung aus Mail-Text und das Propose-then-confirm-Verhalten: plan_calendar_action()/
create_calendar_actions_from_messages() duerfen NIEMALS direkt einen Kalendereintrag
anlegen, das darf ausschliesslich execute_planned_calendar_action() nach expliziter
Bestaetigung."""

from datetime import datetime
from unittest.mock import patch

import pytest

from mail_calendar_actions import (
    create_calendar_actions_from_messages,
    execute_planned_calendar_action,
    plan_calendar_action,
)
from mail_client import MailMessage


def _msg(subject="Rechnung fällig", preview="Bitte begleichen Sie den Betrag.", sender="rechnung@shop.de", message_id="m1"):
    return MailMessage(message_id=message_id, sender=sender, subject=subject, received="irrelevant", preview=preview)


@pytest.fixture
def config():
    return {"auto_calendar_default_time": "09:00", "auto_calendar_event_duration_minutes": 60}


# --- plan_calendar_action: Erkennung ------------------------------------------


def test_plan_calendar_action_none_without_keyword(config):
    message = _msg(subject="Newsletter", preview="Hier die neuesten Angebote der Woche.")
    assert plan_calendar_action(message, config) is None


def test_plan_calendar_action_none_without_date(config):
    message = _msg(subject="Rechnung", preview="Bitte zeitnah begleichen.")
    assert plan_calendar_action(message, config) is None


def test_plan_calendar_action_invoice_becomes_reminder(config):
    message = _msg(subject="Rechnung Nr. 123", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    plan = plan_calendar_action(message, config)
    assert plan is not None
    assert plan["kind"] == "reminder"
    assert plan["when"] == datetime(2027, 3, 15, 9, 0)


def test_plan_calendar_action_event_with_time_becomes_event(config):
    message = _msg(sender="praxis@zahnarzt.de", subject="Termin beim Zahnarzt", preview="Ihr Termin ist am 20.09.2027 um 14:30 Uhr.")
    plan = plan_calendar_action(message, config)
    assert plan is not None
    assert plan["kind"] == "event"
    assert plan["when"] == datetime(2027, 9, 20, 14, 30)


def test_plan_calendar_action_relative_date_morgen(config):
    message = _msg(subject="Meeting", preview="Unser Meeting ist morgen um 10 Uhr.")
    plan = plan_calendar_action(message, config)
    assert plan is not None
    from datetime import timedelta
    expected_day = (datetime.now() + timedelta(days=1)).date()
    assert plan["when"].date() == expected_day
    assert plan["when"].hour == 10


def test_plan_calendar_action_deadline_without_time_uses_default(config):
    message = _msg(subject="Frist", preview="Frist zur Rückmeldung bis zum 01.12.2027.")
    plan = plan_calendar_action(message, config)
    assert plan is not None
    assert plan["when"] == datetime(2027, 12, 1, 9, 0)


def test_plan_calendar_action_uses_configured_default_time():
    message = _msg(subject="Frist", preview="Frist bis zum 01.12.2027.")
    plan = plan_calendar_action(message, {"auto_calendar_default_time": "18:30"})
    assert plan is not None
    assert plan["when"] == datetime(2027, 12, 1, 18, 30)


def test_plan_calendar_action_ignores_bulk_notification_sender(config):
    # Live gefunden: ein LinkedIn-Aktivitaets-Digest mit fremdem Post-Inhalt
    # ("...der Boarding Call gilt noch...") loeste faelschlich einen
    # Kalender-Vorschlag aus - der Absender-Vorfilter muss das jetzt vor der
    # Stichwort-Erkennung abfangen.
    message = _msg(
        sender="Jonas Mündner auf LinkedIn <notifications-noreply@linkedin.com>",
        subject="Jonas Mündner hat Folgendes gepostet",
        preview="Der Boarding Call gilt noch am 15.03.2027 um 14:00 Uhr.",
    )
    assert plan_calendar_action(message, config) is None


def test_plan_calendar_action_ignores_received_date_for_extraction(config):
    # message.received selbst enthaelt ein Datumsformat (deutsches Wochentag+Datum) -
    # das darf NICHT als das erkannte Datum verwendet werden, nur Inhalt aus
    # sender/subject/preview zaehlt (siehe Kommentar in _combined_text()).
    message = MailMessage(
        message_id="m2",
        sender="shop@example.de",
        subject="Rechnung ohne Datum im Text",
        received="Donnerstag, 7. August 2025 um 21:15:00",
        preview="Bitte Betrag begleichen, kein Datum genannt.",
    )
    assert plan_calendar_action(message, config) is None


# --- create_calendar_actions_from_messages: nur Vorschlaege, kein Direkt-Schreiben ---


def test_create_calendar_actions_never_calls_calendar_client(config):
    messages = [_msg(preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")]
    with patch("mail_calendar_actions.create_calendar_event") as fake_event, \
         patch("mail_calendar_actions.create_reminder") as fake_reminder:
        proposed, keys = create_calendar_actions_from_messages(messages, config)

    assert len(proposed) == 1
    assert proposed[0]["status"] == "proposed"
    assert len(keys) == 1
    fake_event.assert_not_called()
    fake_reminder.assert_not_called()


def test_create_calendar_actions_skips_existing_keys(config):
    messages = [_msg(preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")]
    _, keys = create_calendar_actions_from_messages(messages, config)
    proposed_again, keys_again = create_calendar_actions_from_messages(messages, config, existing_keys=set(keys))
    assert proposed_again == []
    assert keys_again == []


def test_create_calendar_actions_skips_messages_without_plan(config):
    messages = [_msg(subject="Newsletter", preview="Nichts Relevantes hier.")]
    proposed, keys = create_calendar_actions_from_messages(messages, config)
    assert proposed == []
    assert keys == []


# --- execute_planned_calendar_action: einzige Stelle, die wirklich schreibt ---------


def test_execute_planned_calendar_action_creates_event(config):
    action = {
        "kind": "event",
        "title": "Termin: Zahnarzt",
        "when": datetime(2027, 9, 20, 14, 30).isoformat(timespec="minutes"),
        "notes": "Automatisch erkannt.",
    }
    with patch("mail_calendar_actions.create_calendar_event") as fake_event:
        result = execute_planned_calendar_action(action, config)

    fake_event.assert_called_once()
    assert result["status"] == "created"


def test_execute_planned_calendar_action_creates_reminder(config):
    action = {
        "kind": "reminder",
        "title": "Erinnerung: Rechnung",
        "when": datetime(2027, 3, 15, 9, 0).isoformat(timespec="minutes"),
        "notes": "Automatisch erkannt.",
    }
    with patch("mail_calendar_actions.create_reminder") as fake_reminder:
        result = execute_planned_calendar_action(action, config)

    fake_reminder.assert_called_once()
    assert result["status"] == "created"


def test_execute_planned_calendar_action_handles_calendar_access_error(config):
    from calendar_client import CalendarAccessError

    action = {
        "kind": "event",
        "title": "Termin",
        "when": datetime(2027, 9, 20, 14, 30).isoformat(timespec="minutes"),
        "notes": "",
    }
    with patch("mail_calendar_actions.create_calendar_event", side_effect=CalendarAccessError("Calendar.app nicht erreichbar")):
        result = execute_planned_calendar_action(action, config)

    assert result["status"] == "error"
    assert "error" in result


def test_execute_planned_calendar_action_handles_corrupted_when(config):
    action = {"kind": "event", "title": "Termin", "when": "nicht-parsebar", "notes": ""}
    result = execute_planned_calendar_action(action, config)
    assert result["status"] == "error"
