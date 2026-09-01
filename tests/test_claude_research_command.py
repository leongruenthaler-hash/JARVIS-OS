"""Tests fuer jarvis.py::handle_claude_research_command() - der Sprachbefehl-Pfad
fuer den Sandbox-Recherche-Modus (Nutzerwunsch 2026-09-02: 'Zugriff auf Dateien/
Code/Internetrecherche'). Deckt: Trigger-Erkennung, Berechtigungs-Gates
(cloud_llm/files/internet), Verhalten wenn Claude Code nicht verfuegbar ist, und
dass Fehler aus dem Sandbox-Aufruf sprechbar durchgereicht werden statt eine
Exception hochzuwerfen."""

from unittest.mock import patch

import jarvis
from claude_code_client import ClaudeCodeError
from memory import Memory


def _memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_returns_none_for_unrelated_text():
    assert jarvis.handle_claude_research_command("Wie spät ist es?") is None


def test_returns_helpful_message_when_claude_code_unavailable():
    with patch("jarvis.is_claude_code_available", return_value=False):
        result = jarvis.handle_claude_research_command("Recherchiere im Internet nach X")

    assert result is not None
    assert "Claude Code" in result


def test_asks_for_cloud_llm_permission_first(tmp_path):
    memory = _memory(tmp_path)
    with patch("jarvis.is_claude_code_available", return_value=True), \
         patch("jarvis.permissions_required", return_value=True), \
         patch("jarvis.ask_claude_code_research") as fake_ask:
        result = jarvis.handle_claude_research_command("Durchsuche meine Dateien nach Rechnungen", memory=memory)

    assert "cloud_llm" in result or "Zustimmung" in result
    fake_ask.assert_not_called()


def test_calls_sandboxed_research_when_permissions_granted(tmp_path):
    memory = _memory(tmp_path)
    with patch("jarvis.is_claude_code_available", return_value=True), \
         patch("jarvis.permissions_required", return_value=False), \
         patch("jarvis.ask_claude_code_research", return_value="Ich habe nichts gefunden.") as fake_ask:
        result = jarvis.handle_claude_research_command("Durchsuche meine Dateien nach Rechnungen", memory=memory)

    assert result == "Ich habe nichts gefunden."
    fake_ask.assert_called_once()
    _, kwargs = fake_ask.call_args
    assert isinstance(kwargs["allowed_dirs"], list)
    assert len(kwargs["allowed_dirs"]) > 0


def test_claude_code_error_becomes_spoken_answer_not_exception(tmp_path):
    memory = _memory(tmp_path)
    with patch("jarvis.is_claude_code_available", return_value=True), \
         patch("jarvis.permissions_required", return_value=False), \
         patch("jarvis.ask_claude_code_research", side_effect=ClaudeCodeError("sandbox-exec fehlt")):
        result = jarvis.handle_claude_research_command("Recherchiere im Internet nach X", memory=memory)

    assert result is not None
    assert "fehlgeschlagen" in result.lower()


def test_matches_various_trigger_phrasings():
    with patch("jarvis.is_claude_code_available", return_value=False):
        for phrase in (
            "Jarvis, recherchiere das mal",
            "Durchsuch meinen Code nach TODO",
            "Schau in meinem Projekt nach der Konfiguration",
            "Such im Internet nach dem Wetter",
        ):
            assert jarvis.handle_claude_research_command(phrase) is not None
