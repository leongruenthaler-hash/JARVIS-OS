"""Tests fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Notizen-Bug: "Was steht auf meinem Einkaufszettel?" wurde nicht als
Lese-Anfrage erkannt (nur "was steht IN" war hinterlegt, nicht "was steht
AUF"), startete stattdessen einen Notiz-ergaenzen-Vorgang - und die naechste,
voellig unabhaengige Nachricht wurde automatisch als Notiz-Inhalt geschluckt.
Live bestaetigt: landete in Leons echter Einkaufszettel-Notiz. Siehe
docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import MagicMock

import jarvis


def test_was_steht_auf_recognized_as_read_request():
    assert jarvis._looks_like_notes_read_request("Was steht auf meinem Einkaufszettel?") is True


def test_was_steht_in_still_recognized_as_read_request():
    assert jarvis._looks_like_notes_read_request("Was steht in meinen Notizen?") is True


def test_create_verb_still_wins_over_read_trigger():
    assert jarvis._looks_like_notes_read_request("Erstelle eine Notiz über meine Notizen") is False


def test_notiere_verb_does_not_get_swallowed_into_stale_pending_note():
    """Live-Bug 2026-09-03 (50-Nachrichten-Test der Gemini/Claude-Code-
    Rollenaufteilung): "Notiere bitte kurz: Auto zur Inspektion bringen" waehrend
    einer noch offenen, unabhaengigen Notiz-Rueckfrage wurde faelschlich als deren
    Inhalt uebernommen (an die alte "Einkaufsliste"-Notiz angehaengt) statt eine
    neue, eigenstaendige Notiz anzulegen. Ursache: weder DOMAIN_TERMS["notes"] noch
    COMMAND_SHAPE_PREFIXES kannten die Verbform "notiere" (nur "notiz"/"notizen"
    als Substantive) - beide Bail-outs griffen deshalb nicht."""
    memory = MagicMock()
    memory.get.return_value = {
        "pending_note": {"state": "awaiting_body", "title": "Einkaufsliste", "append": True}
    }
    answer = jarvis.handle_pending_note_flow(memory, "Notiere bitte kurz: Auto zur Inspektion bringen")

    assert answer is None
    memory.set.assert_called_once()
    saved_settings = memory.set.call_args[0][1]
    assert "pending_note" not in saved_settings


def test_unrelated_question_does_not_get_swallowed_as_note_content():
    # "Welche Aufgaben sind noch offen?" enthaelt "aufgaben" (tasks-Domaene) -
    # der domaenen-basierte Bail-out (app/jarvis.py:3231-3235, 2026-08-20)
    # greift VOR dem aelteren Frage-Form-Guard weiter unten: die offene Notiz
    # wird verworfen (nicht als Inhalt gespeichert) und None zurueckgegeben,
    # damit die echte tasks-Domaene die Frage beantwortet - keine "eigenen
    # Frage"-Ausweichantwort mehr fuer Saetze mit erkennbarer Domaene.
    memory = MagicMock()
    memory.get.return_value = {
        "pending_note": {"state": "awaiting_body", "title": "Einkaufszettel", "append": True}
    }
    answer = jarvis.handle_pending_note_flow(memory, "Welche Aufgaben sind noch offen?")

    assert answer is None
    # Die offene Notiz MUSS verworfen werden, nicht als Inhalt gespeichert.
    memory.set.assert_called_once()
    saved_settings = memory.set.call_args[0][1]
    assert "pending_note" not in saved_settings


def test_plausible_note_content_still_saved(monkeypatch):
    memory = MagicMock()
    memory.get.return_value = {
        "pending_note": {"state": "awaiting_body", "title": "Einkaufszettel", "append": True}
    }
    monkeypatch.setattr(jarvis, "save_note_or_append", lambda title, body, append: f"Erledigt. {title} ist ergänzt.")
    answer = jarvis.handle_pending_note_flow(memory, "Milch und Butter")

    assert "ergänzt" in answer
    memory.set.assert_called_once()
    saved_settings = memory.set.call_args[0][1]
    assert "pending_note" not in saved_settings


def test_abbrechen_still_works_with_guard_in_place():
    memory = MagicMock()
    memory.get.return_value = {
        "pending_note": {"state": "awaiting_body", "title": "Einkaufszettel", "append": True}
    }
    answer = jarvis.handle_pending_note_flow(memory, "abbrechen")

    assert "verworfen" in answer
