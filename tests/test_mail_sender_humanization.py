"""Regressionstest fuer Bugreport 2026-09-01: Jarvis las beim Vorlesen/Zusammenfassen
von Mails Absender wortwoertlich mit "<name@domain>", spitzen Klammern und anderen
Sonderzeichen aus der rohen Apple-Mail-Kopfzeile vor, statt einen sprechbaren Namen zu
nennen. humanize_mail_sender() macht daraus einen reinen Namen, und
build_mail_summary_digest() (Grundlage fuer summarize_mail_digest_via_llm()) nutzt das
jetzt, damit die rohe Adresse gar nicht erst in den LLM-Kontext gelangt."""

from jarvis import build_mail_summary_digest, humanize_mail_sender
from mail_client import MailMessage


def test_humanize_sender_strips_display_name_from_bracketed_address():
    assert humanize_mail_sender("Indeed <donotreply@jobalert.indeed.com>") == "Indeed"


def test_humanize_sender_strips_quotes_around_display_name():
    assert humanize_mail_sender('"Max Mustermann" <max@example.de>') == "Max Mustermann"


def test_humanize_sender_falls_back_to_local_part_for_bare_address():
    assert humanize_mail_sender("julia.schmidt@example.de") == "Julia Schmidt"


def test_humanize_sender_handles_address_only_in_brackets():
    assert humanize_mail_sender("<newsletter@shop.de>") == "Newsletter"


def test_humanize_sender_returns_unbekannt_for_empty_input():
    assert humanize_mail_sender("") == "Unbekannt"
    assert humanize_mail_sender(None) == "Unbekannt"


def test_humanize_sender_passes_through_plain_names_unchanged():
    assert humanize_mail_sender("Julia Schmidt") == "Julia Schmidt"


def _msg(sender, subject="Hallo", preview=""):
    return MailMessage(message_id="", sender=sender, subject=subject, received="irrelevant", preview=preview)


def test_digest_never_contains_raw_email_address_or_angle_brackets():
    messages = [_msg("Indeed <donotreply@jobalert.indeed.com>", subject="Neuer Job")]

    digest = build_mail_summary_digest(messages)

    assert "<" not in digest
    assert ">" not in digest
    assert "donotreply@jobalert.indeed.com" not in digest
    assert "Von: Indeed" in digest
