"""Tests fuer jarvis.py::strip_first_name_address()/wants_first_name_permission()
- deterministischer Rueckhalt gegen die Vorname-Verbot-Anweisung im
Personality-Prompt, die das kleinere lokale Modell (phi4-mini) live
gelegentlich ignorierte, siehe docs/current-system-assessment.md, Abschnitt 37."""

import jarvis


def test_strips_vocative_name_with_exclamation():
    result = jarvis.strip_first_name_address("Danke der Nachfrage, Leon!", "Leon")
    assert result == "Danke der Nachfrage!"


def test_strips_vocative_name_with_period():
    result = jarvis.strip_first_name_address("Alles klar, Leon.", "Leon")
    assert result == "Alles klar."


def test_strips_leading_name_greeting():
    result = jarvis.strip_first_name_address("Leon, ich habe das erledigt.", "Leon")
    assert result == "ich habe das erledigt."


def test_leaves_answer_without_name_unchanged():
    result = jarvis.strip_first_name_address("Sir, alles erledigt.", "Leon")
    assert result == "Sir, alles erledigt."


def test_permission_phrase_detected():
    assert jarvis.wants_first_name_permission("Du darfst mich ab jetzt Leon nennen") is True
    assert jarvis.wants_first_name_permission("Nenn mich bei meinem Namen") is True


def test_no_false_positive_permission_detection():
    assert jarvis.wants_first_name_permission("Wie ist das Wetter heute") is False
