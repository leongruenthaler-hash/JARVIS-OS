"""Tests fuer den kritischen Fund aus der Faehigkeits-Simulation (2026-08-13):
"Loesche die Mail von Anthropic" fiel bisher still auf "die zuletzt gelesenen
Mails" zurueck (komplett unbezogene Mails haetten geloescht werden koennen),
weil nur drei fest hinterlegte Absender (Indeed/PayPal/Stepstone) erkannt
wurden. Siehe docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import MagicMock, patch

import jarvis
from mail_client import MailMessage


def test_extracts_sender_name_after_von():
    assert jarvis.extract_mail_delete_target("Lösche die Mail von Anthropic") == "Anthropic"


def test_extracts_sender_name_plural_mails():
    assert jarvis.extract_mail_delete_target("Lösch die Mails von Zenfy bitte") == "Zenfy"


def test_returns_none_without_von_pattern():
    assert jarvis.extract_mail_delete_target("Lösch die Mail") is None


def _message(message_id, sender, subject):
    return MailMessage(message_id=message_id, sender=sender, subject=subject, received="", preview="")


def test_unknown_sender_searches_real_mailbox_not_last_summary():
    memory = MagicMock()
    memory.get.return_value = {
        "last_mail_summary": {
            "message_ids": ["999"],
            "subjects": ["Komplett unrelated"],
            "senders": ["irgendwer"],
        }
    }
    found = [_message("1", "Anthropic <no-reply@anthropic.com>", "Rechnung")]
    with patch.object(jarvis, "search_messages_by_terms", return_value=found) as fake_search:
        answer = jarvis.handle_mail_delete_command("Lösche die Mail von Anthropic", memory=memory)

    fake_search.assert_called_once()
    assert "Anthropic" in answer
    assert "Rechnung" in answer
    # Der vorgeschlagene Loesch-Vorgang muss auf der ECHTEN Suche basieren
    # (message_id "1"), nicht auf der alten, unbezogenen last_mail_summary-ID
    # "999" - das war genau der Kern des Bugs.
    saved_settings = memory.set.call_args[0][1]
    assert saved_settings["pending_mail_delete"]["message_ids"] == ["1"]


def test_unknown_sender_with_no_matches_asks_instead_of_guessing():
    memory = MagicMock()
    memory.get.return_value = {}
    with patch.object(jarvis, "search_messages_by_terms", return_value=[]):
        answer = jarvis.handle_mail_delete_command("Lösche die Mail von Anthropic", memory=memory)

    assert "keine Mails von Anthropic" in answer
    memory.set.assert_not_called()


def test_no_name_at_all_falls_back_to_last_summary_with_honest_wording():
    memory = MagicMock()
    memory.get.return_value = {
        "last_mail_summary": {
            "message_ids": ["42"],
            "subjects": ["Testbetreff"],
            "senders": ["Test Sender"],
        }
    }
    answer = jarvis.handle_mail_delete_command("Lösch die Mail bitte", memory=memory)

    assert "keinen Namen genannt" in answer
    assert "Testbetreff" in answer


def test_known_target_indeed_unaffected_by_new_logic():
    memory = MagicMock()
    memory.get.return_value = {}
    answer = jarvis.handle_mail_delete_command("Lösch die Mails von Indeed", memory=memory)

    assert "Indeed" in answer
    memory.propose.assert_not_called() if hasattr(memory, "propose") else None
