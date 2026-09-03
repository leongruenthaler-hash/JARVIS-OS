"""Live-Bug 2026-09-03: PrivacyDashboard.status() behauptete "komplett lokal auf
diesem Mac", waehrend tatsaechlich Claude Code oder Gemini (beide Cloud-Provider)
aktiv waren - die cloud_ai-Erkennung kannte nur die API-Anbieternamen "openai"/
"anthropic"/"google", nie die tatsaechlichen ModelManager-Provider-Strings
"claude_code"/"gemini". Live gefunden bei einem 50-Nachrichten-Test der
Gemini/Claude-Code-Rollenaufteilung."""

from unittest.mock import patch

from model_manager import ModelStatus
from privacy_dashboard import PrivacyDashboard


def _status(provider: str, active_model: str = "sonnet") -> ModelStatus:
    return ModelStatus(
        provider=provider,
        active_model=active_model,
        openai_enabled=False,
        ollama_installed=True,
        ollama_running=True,
        installed_models=[],
        missing_models=[],
        openai_key_present=False,
        claude_code_available=True,
        gemini_available=True,
    )


def test_status_reports_cloud_for_claude_code(tmp_path):
    dashboard = PrivacyDashboard({}, base_path=tmp_path)
    with patch("privacy_dashboard.ModelManager.status", return_value=_status("claude_code")):
        text = dashboard.status()
    assert "über die Cloud" in text
    assert "komplett lokal" not in text


def test_status_reports_cloud_for_gemini(tmp_path):
    dashboard = PrivacyDashboard({}, base_path=tmp_path)
    with patch("privacy_dashboard.ModelManager.status", return_value=_status("gemini", "gemini-3.6-flash")):
        text = dashboard.status()
    assert "über die Cloud" in text
    assert "komplett lokal" not in text


def test_status_reports_cloud_for_openai(tmp_path):
    dashboard = PrivacyDashboard({}, base_path=tmp_path)
    with patch("privacy_dashboard.ModelManager.status", return_value=_status("openai", "gpt-5.4-nano")):
        text = dashboard.status()
    assert "über die Cloud" in text
    assert "komplett lokal" not in text


def test_status_reports_local_for_ollama(tmp_path):
    dashboard = PrivacyDashboard({}, base_path=tmp_path)
    with patch("privacy_dashboard.ModelManager.status", return_value=_status("ollama", "phi4-mini")):
        text = dashboard.status()
    assert "komplett lokal auf diesem Mac" in text
    assert "über die Cloud" not in text
