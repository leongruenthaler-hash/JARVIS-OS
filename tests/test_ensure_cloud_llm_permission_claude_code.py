"""Regressionstest: ensure_cloud_llm_permission() gattete Anfragen nur fuer die
Provider "openai"/"anthropic"/"google" - "claude_code" fehlte, obwohl es genauso
eine Cloud-KI ist. Ergebnis: wer die cloud_llm-Berechtigung widerruft, waere mit
Claude Code als aktivem Provider trotzdem ungeprueft durchgelaufen. Gefunden beim
Einbau des Recherche-Modus, 2026-09-02."""

from unittest.mock import patch

import jarvis
from memory import Memory


def test_claude_code_provider_triggers_cloud_llm_permission_check(tmp_path):
    memory = Memory(base_path=tmp_path)
    with patch("jarvis.ModelManager") as fake_manager_cls, \
         patch("jarvis.permissions_required", return_value=True):
        fake_manager_cls.return_value.provider = "claude_code"
        result = jarvis.ensure_cloud_llm_permission(memory, "Wie spät ist es?")

    assert result is not None
    assert "cloud_llm" in result or "Zustimmung" in result


def test_claude_code_does_not_require_external_api_permission(tmp_path):
    """claude_code laeuft als lokaler CLI-Subprozess, nicht als von Jarvis selbst
    aufgerufener API-Endpunkt - "external_api" (Jarvis macht einen eigenen
    Netzwerkaufruf) passt konzeptionell nicht, nur "cloud_llm" wird geprueft."""
    memory = Memory(base_path=tmp_path)
    with patch("jarvis.ModelManager") as fake_manager_cls, \
         patch("jarvis.permissions_required", return_value=True), \
         patch.object(jarvis.PermissionManager, "is_allowed", side_effect=lambda perm: perm == "cloud_llm"):
        fake_manager_cls.return_value.provider = "claude_code"
        result = jarvis.ensure_cloud_llm_permission(memory, "Wie spät ist es?")

    # cloud_llm ist erlaubt, external_api wird fuer claude_code gar nicht erst
    # geprueft - also darf hier keine Rueckfrage kommen.
    assert result is None


def test_local_provider_never_needs_cloud_llm_permission(tmp_path):
    memory = Memory(base_path=tmp_path)
    with patch("jarvis.ModelManager") as fake_manager_cls:
        fake_manager_cls.return_value.provider = "ollama"
        result = jarvis.ensure_cloud_llm_permission(memory, "Wie spät ist es?")

    assert result is None
