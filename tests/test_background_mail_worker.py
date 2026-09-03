"""Tests fuer app/background_tasks.py::MailBackgroundWorker (bisher ungetestet, siehe
plans/2026-08-09-jarvis-mail-hintergrund-aktivieren.md) - Zeitfenster-Logik, "neu vs.
bekannt"-Erkennung ueber den ID-Cache, Fehlerfall bei nicht erreichbarem Mail.app, und
dass ein Kalender-Vorschlag erst nach ausdruecklicher Bestaetigung wirklich angelegt wird."""

from datetime import datetime
from unittest.mock import patch

import pytest

from background_tasks import MailBackgroundWorker
from mail_client import MailAccessError, MailMessage


def _msg(message_id, sender="a@b.de", subject="Hallo", preview=""):
    return MailMessage(message_id=message_id, sender=sender, subject=subject, received="irrelevant", preview=preview)


class _FakeLLM:
    """Liefert eine feste Zusammenfassung statt eines echten Modellaufrufs -
    _build_summary() ruft das ueber summarize_mail_digest_via_llm() auf, siehe
    plans/2026-08-10-jarvis-mail-update-menschlich.md."""

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False, **kwargs):
        return "Menschliche Zusammenfassung."


@pytest.fixture
def worker(tmp_path):
    config = {
        "background_mail_enabled": True,
        "background_mail_morning_time": "07:00",
        "background_mail_max_messages": 20,
        "auto_calendar_from_mail_enabled": True,
    }
    w = MailBackgroundWorker(config, _FakeLLM(), base_path=tmp_path)
    w.permissions.grant("mail")
    return w


# --- _time_reached --------------------------------------------------------------


@pytest.mark.parametrize(
    "now_hm,target,expected",
    [
        ((7, 0), "07:00", True),
        ((6, 59), "07:00", False),
        ((23, 0), "07:00", True),
        ((7, 0), "not-a-time", False),
    ],
)
def test_time_reached_variants(worker, now_hm, target, expected):
    now = datetime(2027, 1, 1, now_hm[0], now_hm[1])
    assert worker._time_reached(now, target) is expected


# --- _scan: neu vs. bekannt -------------------------------------------------------


def test_first_scan_establishes_baseline_without_reporting_new(worker):
    messages = [_msg("m1"), _msg("m2")]
    with patch("background_tasks.list_inbox_messages", return_value=messages):
        worker._scan(reason="manual", max_messages=20)

    cache = worker._load_cache()
    assert cache["new_messages"] == []
    assert set(cache["known_message_ids"]) == {"m1", "m2"}


def test_second_scan_reports_only_genuinely_new_messages(worker):
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), _msg("m2")]):
        worker._scan(reason="manual", max_messages=20)

    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), _msg("m2"), _msg("m3")]):
        worker._scan(reason="manual", max_messages=20)

    cache = worker._load_cache()
    assert [m["id"] for m in cache["new_messages"]] == ["m3"]


def test_scan_safely_swallows_mail_access_error(worker):
    with patch("background_tasks.list_inbox_messages", side_effect=MailAccessError("Mail.app nicht erreichbar")):
        worker._scan_safely(reason="manual", max_messages=20)

    cache = worker._load_cache()
    assert "nicht erreichbar" in cache["last_error"]


def test_known_message_ids_respect_configured_limit(tmp_path):
    config = {"background_mail_known_id_limit": 2}
    w = MailBackgroundWorker(config, _FakeLLM(), base_path=tmp_path)
    w.permissions.grant("mail")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), _msg("m2"), _msg("m3")]):
        w._scan(reason="manual", max_messages=20)

    cache = w._load_cache()
    assert len(cache["known_message_ids"]) == 2


# --- Kalender-Vorschlaege: propose-then-confirm bleibt auch im Worker gewahrt ------


def test_scan_creates_pending_calendar_action_without_writing_calendar(worker):
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        worker._scan(reason="manual", max_messages=20)  # baseline, kein "neu"

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]), \
         patch("mail_calendar_actions.create_calendar_event") as fake_event, \
         patch("mail_calendar_actions.create_reminder") as fake_reminder:
        worker._scan(reason="manual", max_messages=20)

    fake_event.assert_not_called()
    fake_reminder.assert_not_called()
    pending = worker.pending_calendar_actions()
    assert len(pending) == 1
    assert pending[0]["status"] == "proposed"


# --- Nutzerwunsch 2026-09-02: auto_calendar_from_mail_auto_approve traegt direkt ein --


def test_auto_approve_creates_calendar_entries_without_pending_confirmation(tmp_path):
    config = {
        "background_mail_enabled": True,
        "background_mail_morning_time": "07:00",
        "background_mail_max_messages": 20,
        "auto_calendar_from_mail_enabled": True,
        "auto_calendar_from_mail_auto_approve": True,
    }
    w = MailBackgroundWorker(config, _FakeLLM(), base_path=tmp_path)
    w.permissions.grant("mail")

    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        w._scan(reason="manual", max_messages=20)  # baseline

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]), \
         patch("mail_calendar_actions.create_reminder") as fake_reminder:
        w._scan(reason="manual", max_messages=20)

    fake_reminder.assert_called_once()
    assert w.pending_calendar_actions() == []
    cache = w._load_cache()
    resolved = cache.get("resolved_calendar_actions", [])
    assert len(resolved) == 1
    assert resolved[0]["status"] == "created"


def test_auto_approve_off_by_default_still_proposes(tmp_path):
    """Nichts aendert sich fuer bestehende Konfigurationen ohne den neuen Schluessel -
    Standardverhalten bleibt propose-then-confirm."""
    config = {
        "background_mail_enabled": True,
        "background_mail_max_messages": 20,
        "auto_calendar_from_mail_enabled": True,
    }
    w = MailBackgroundWorker(config, _FakeLLM(), base_path=tmp_path)
    w.permissions.grant("mail")
    assert w.auto_calendar_auto_approve is False


def test_resolve_pending_calendar_action_approve_creates_reminder(worker):
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        worker._scan(reason="manual", max_messages=20)

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]):
        worker._scan(reason="manual", max_messages=20)

    action_key = worker.pending_calendar_actions()[0]["action_key"]
    with patch("mail_calendar_actions.create_reminder") as fake_reminder:
        result = worker.resolve_pending_calendar_action(action_key, approve=True)

    fake_reminder.assert_called_once()
    assert result["ok"] is True
    assert result["action"]["status"] == "created"
    assert worker.pending_calendar_actions() == []


def test_resolve_pending_calendar_action_reject_does_not_create(worker):
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        worker._scan(reason="manual", max_messages=20)

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]):
        worker._scan(reason="manual", max_messages=20)

    action_key = worker.pending_calendar_actions()[0]["action_key"]
    with patch("mail_calendar_actions.create_reminder") as fake_reminder, \
         patch("mail_calendar_actions.create_calendar_event") as fake_event:
        result = worker.resolve_pending_calendar_action(action_key, approve=False)

    fake_reminder.assert_not_called()
    fake_event.assert_not_called()
    assert result["action"]["status"] == "dismissed"
    assert worker.pending_calendar_actions() == []


def test_resolve_pending_calendar_action_unknown_key_returns_not_found(worker):
    result = worker.resolve_pending_calendar_action("does-not-exist", approve=True)
    assert result == {"ok": False, "error": "not_found"}


def test_resolve_pending_calendar_action_second_confirmation_reports_already_done(worker):
    """Live-Bug (Screenshot 2026-09-01): eine erneute proaktive Meldung kann
    pending_mail_calendar_confirmation ein zweites Mal mit denselben action_keys
    setzen, bevor die erste Bestaetigung beantwortet wurde. Die zweite
    Bestaetigung fand die Keys dann nicht mehr in pending_calendar_actions und
    meldete faelschlich "konnte nicht eintragen", obwohl der Termin laengst
    existiert - jetzt erst in resolved_calendar_actions nachschauen."""
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        worker._scan(reason="manual", max_messages=20)

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]):
        worker._scan(reason="manual", max_messages=20)

    action_key = worker.pending_calendar_actions()[0]["action_key"]
    with patch("mail_calendar_actions.create_reminder"):
        first = worker.resolve_pending_calendar_action(action_key, approve=True)
    assert first["ok"] is True
    assert "already_done" not in first

    second = worker.resolve_pending_calendar_action(action_key, approve=True)
    assert second == {"ok": True, "action": first["action"], "already_done": True}


def test_scan_without_auto_calendar_enabled_creates_no_proposals(tmp_path):
    config = {"auto_calendar_from_mail_enabled": False}
    w = MailBackgroundWorker(config, _FakeLLM(), base_path=tmp_path)
    w.permissions.grant("mail")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1")]):
        w._scan(reason="manual", max_messages=20)

    new_message = _msg("m2", sender="shop@example.de", subject="Rechnung", preview="Zahlbar bis zum 15.03.2027, Betrag 49,90 Euro.")
    with patch("background_tasks.list_inbox_messages", return_value=[_msg("m1"), new_message]):
        w._scan(reason="manual", max_messages=20)

    assert w.pending_calendar_actions() == []


# --- _build_summary: menschliche LLM-Zusammenfassung statt "Absender: Betreff" ----
# (Bugreport 2026-08-10: "Mail-Update" las rohe Absender-Adressen und Betreffzeilen
# vor, ohne inhaltliches Verstaendnis. Siehe
# plans/2026-08-10-jarvis-mail-update-menschlich.md.)


def test_build_summary_uses_llm_for_human_summary(worker):
    summary = worker._build_summary([_msg("m1", sender="Indeed <donotreply@jobalert.indeed.com>", subject="Job")], [])

    assert "Menschliche Zusammenfassung." in summary
    assert "donotreply@jobalert.indeed.com" not in summary


def test_build_summary_flattens_category_lines_into_one_paragraph(tmp_path):
    # Regression fuer 2026-08-10: das kleine lokale Modell haelt sich trotz
    # Prompt-Anweisung nicht zuverlaessig an "ein Fliesstext-Absatz" und
    # produziert stattdessen Zeilen wie "Wichtig: ...\nPrivat: ..." -
    # summarize_mail_digest_via_llm() muss das hart nachbearbeiten.
    class _ListyLLM:
        def ask(self, *args, **kwargs):
            return "Wichtig: eine Rechnung.\nPrivat: eine Empfehlung von Pinterest."

    config = {"auto_calendar_from_mail_enabled": False}
    w = MailBackgroundWorker(config, _ListyLLM(), base_path=tmp_path)
    w.permissions.grant("mail")

    summary = w._build_summary([_msg("m1")], [])

    assert "\n" not in summary


def test_build_summary_falls_back_to_mechanical_summary_when_llm_fails(tmp_path):
    class _BrokenLLM:
        def ask(self, *args, **kwargs):
            raise RuntimeError("Modell nicht erreichbar")

    config = {"auto_calendar_from_mail_enabled": False}
    w = MailBackgroundWorker(config, _BrokenLLM(), base_path=tmp_path)
    w.permissions.grant("mail")

    summary = w._build_summary([_msg("m1", sender="a@b.de", subject="Testbetreff")], [])

    assert "Wichtigste Übersicht" in summary
    assert "a@b.de" in summary
    assert "Testbetreff" in summary


def test_build_summary_appends_calendar_proposal_deterministically(worker):
    calendar_actions = [{"title": "Meeting am Montag"}]
    summary = worker._build_summary([_msg("m1")], [], calendar_actions=calendar_actions)

    assert "Meeting am Montag" in summary
    assert "noch nicht angelegt" in summary
