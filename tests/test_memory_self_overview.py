"""Tests fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Gedaechtnis-Bug: "Was weißt du über mich?" (mit Fragezeichen) matchte nicht
den exakten Uebersichts-Vergleich (der kein Satzzeichen erwartete) und fiel
stattdessen in die recall_patterns, die "mich" faelschlich als Such-THEMA
behandelten - Ergebnis: "Dazu habe ich noch nichts im Langzeitgedächtnis: mich".
Siehe docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import MagicMock, patch

import jarvis
from memory import Memory


def _memory_with_facts(tmp_path, facts):
    memory = Memory(base_path=tmp_path)
    for category, subject, content in facts:
        memory.remember(category, subject, content)
    return memory


def test_question_with_trailing_mark_shows_overview(tmp_path):
    memory = _memory_with_facts(tmp_path, [("Vorlieben", "Kaffee", "trinkt Kaffee ohne Zucker")])
    answer = jarvis.handle_memory_command(memory, "Was weißt du über mich?")

    assert "Kaffee ohne Zucker" in answer
    assert "Dazu habe ich noch nichts" not in answer


def test_ueber_mich_recall_pattern_also_shows_overview(tmp_path):
    memory = _memory_with_facts(tmp_path, [("Vorlieben", "Kaffee", "trinkt Kaffee ohne Zucker")])
    answer = jarvis.handle_memory_command(memory, "Was weißt du über mich")

    assert "Kaffee ohne Zucker" in answer
    assert ": mich" not in answer


def test_genuine_topic_recall_still_works(tmp_path):
    memory = _memory_with_facts(tmp_path, [("Projekte", "Fussball", "spielt Fussball am Wochenende")])
    answer = jarvis.handle_memory_command(memory, "Was weißt du über Fussball")

    assert "Fussball am Wochenende" in answer


def test_empty_memory_gives_honest_answer(tmp_path):
    memory = Memory(base_path=tmp_path)
    answer = jarvis.handle_memory_command(memory, "Was weißt du über mich?")

    assert "noch keine Langzeit-Erinnerungen" in answer
