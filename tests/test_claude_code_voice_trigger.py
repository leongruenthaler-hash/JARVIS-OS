"""Regressionstest fuer Bugreport 2026-09-02: Live in der App reproduziert - die
Spracherkennung verstand "nutze Claude Code" als "Nutzer Cloud Code". Da
handle_model_command() das nicht erkannte, fiel der Befehl komplett durch bis zu
einem Datei-Suche-Handler, der "cloud" als Suchbegriff interpretierte und mit
"Ich finde im Dateiindex ... nichts Passendes zu cloud" antwortete, statt Claude
Code zu aktivieren. "cloud code" wird jetzt zusaetzlich als Ausloeser akzeptiert."""

from unittest.mock import patch

import jarvis
from model_manager import ModelManager


def test_mishearing_cloud_code_still_activates_claude_code(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        result = jarvis.handle_model_command("Nutzer Cloud Code", model_manager=manager)

    assert result is not None
    assert manager.provider == "claude_code"


def test_cloud_code_aktiv_phrase_also_matches(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        result = jarvis.handle_model_command("Cloud Code aktiv", model_manager=manager)

    assert result is not None
    assert manager.provider == "claude_code"


def test_original_correct_phrase_still_works(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        result = jarvis.handle_model_command("nutze claude code", model_manager=manager)

    assert result is not None
    assert manager.provider == "claude_code"
