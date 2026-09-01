"""Tests fuer den neuen 'claude_code'-Provider in ModelManager: Claude Code (die
'claude'-CLI) als weiterer KI-Anbieter neben Ollama/OpenAI, damit Jarvis das
bestehende Claude-Abo statt der separat abgerechneten API nutzen kann
(Nutzerwunsch 2026-09-01)."""

from unittest.mock import patch

from model_manager import ModelManager


def test_use_claude_code_activates_when_cli_available(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        result = manager.use_claude_code()
        assert manager.provider == "claude_code"
    assert "Claude Code" in result


def test_use_claude_code_falls_back_to_ollama_when_cli_missing(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=False):
        result = manager.use_claude_code()
        assert manager.provider == "ollama"
    assert "nicht verfuegbar" in result


def test_provider_falls_back_to_ollama_if_cli_disappears_after_activation(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        manager.use_claude_code()
    # CLI verschwindet (z.B. deinstalliert) zwischen Aktivierung und naechster Abfrage -
    # provider muss live neu geprueft werden, nicht nur beim Aktivieren.
    with patch("model_manager.is_claude_code_available", return_value=False):
        assert manager.provider == "ollama"


def test_active_model_uses_configured_claude_code_model(tmp_path):
    config = {"claude_code_model": "opus"}
    manager = ModelManager(config, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        manager.use_claude_code()
        assert manager.active_model == "opus"


def test_work_locally_deactivates_claude_code(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True):
        manager.use_claude_code()
        assert manager.provider == "claude_code"
        manager.work_locally()
        assert manager.provider == "ollama"


def test_status_reports_claude_code_availability(tmp_path):
    manager = ModelManager({}, base_path=tmp_path)
    with patch("model_manager.is_claude_code_available", return_value=True), \
         patch("model_manager.is_ollama_running", return_value=False), \
         patch("model_manager.is_ollama_installed", return_value=False):
        status = manager.status()
    assert status.claude_code_available is True


def test_reload_from_disk_resets_stale_claude_code_provider_when_cli_gone(tmp_path):
    """Bugreport-Muster wie bei OpenAI: falls die claude-CLI zwischen zwei
    Programmstarts verschwindet, darf ein NEU geladener ModelManager nicht
    weiter 'claude_code' als Provider melden."""
    config = {}
    with patch("model_manager.is_claude_code_available", return_value=True):
        first = ModelManager(config, base_path=tmp_path)
        first.use_claude_code()

    with patch("model_manager.is_claude_code_available", return_value=False):
        reloaded = ModelManager(config, base_path=tmp_path)
        assert reloaded.data["provider"] == "ollama"
