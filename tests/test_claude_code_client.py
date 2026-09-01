"""Tests fuer app/claude_code_client.py: duenner subprocess-Wrapper um die
'claude'-CLI, damit Jarvis Claude ueber das bestehende Abo statt ueber die
separat abgerechnete API nutzen kann (Nutzerwunsch 2026-09-01)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import claude_code_client as cc


@pytest.fixture(autouse=True)
def _reset_availability_cache():
    cc._AVAILABILITY_CACHE = (0.0, False)
    yield
    cc._AVAILABILITY_CACHE = (0.0, False)


def test_is_claude_code_available_reflects_binary_presence():
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"):
        assert cc.is_claude_code_available(force=True) is True
    with patch.object(cc, "find_claude_binary", return_value=None):
        assert cc.is_claude_code_available(force=True) is False


def test_find_claude_binary_falls_back_to_common_install_paths_when_which_fails(tmp_path, monkeypatch):
    """Bugreport 2026-09-02: JarvisApp wird ueber Finder/LaunchServices gestartet,
    dessen geerbtes PATH enthaelt nicht ~/.local/bin - shutil.which() fand 'claude'
    dort live nicht, obwohl interaktiv im Terminal sofort auffindbar."""
    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".local" / "bin"
    fake_bin.mkdir(parents=True)
    fake_claude = fake_bin / "claude"
    fake_claude.write_text("#!/bin/sh\necho fake\n")
    fake_claude.chmod(0o755)
    monkeypatch.setenv("HOME", str(fake_home))

    with patch.object(cc.shutil, "which", return_value=None):
        found = cc.find_claude_binary()

    assert found == str(fake_claude)


def test_find_claude_binary_returns_none_when_nowhere_found():
    with patch.object(cc.shutil, "which", return_value=None), \
         patch.object(cc.Path, "is_file", return_value=False):
        assert cc.find_claude_binary() is None


def test_ask_claude_code_raises_when_binary_missing():
    with patch.object(cc, "find_claude_binary", return_value=None):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code("Hallo?")


def test_ask_claude_code_raises_on_empty_prompt():
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code("   ")


def test_ask_claude_code_parses_result_field_from_json_output():
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": False, "result": "Alles bestens, Sir."}), stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result) as fake_run:
        answer = cc.ask_claude_code("Wie geht's?", system_prompt="Du bist Jarvis.", model="sonnet")

    assert answer == "Alles bestens, Sir."
    args = fake_run.call_args[0][0]
    assert args[0] == "/usr/local/bin/claude"
    assert "-p" in args
    assert "Wie geht's?" in args
    assert "--tools" in args
    # Leerer String direkt nach --tools deaktiviert ALLE Werkzeuge - Jarvis'
    # Cloud-Anfragen duerfen nie Datei-/Bash-Zugriff bekommen.
    assert args[args.index("--tools") + 1] == ""
    assert "--system-prompt" in args
    assert "Du bist Jarvis." in args
    assert "--model" in args
    assert "sonnet" in args


def test_ask_claude_code_raises_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="", stderr="OAuth session expired")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        with pytest.raises(cc.ClaudeCodeError, match="OAuth session expired"):
            cc.ask_claude_code("Hallo?")


def test_ask_claude_code_raises_when_json_result_field_missing():
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": False}), stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code("Hallo?")


def test_ask_claude_code_raises_on_is_error_flag():
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": True, "result": "kaputt"}), stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code("Hallo?")


def test_ask_claude_code_falls_back_to_raw_text_on_bad_json():
    fake_result = MagicMock(returncode=0, stdout="Ich bin die rohe Antwort.", stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        answer = cc.ask_claude_code("Hallo?")

    assert answer == "Ich bin die rohe Antwort."


def test_ask_claude_code_raises_on_timeout():
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=90)):
        with pytest.raises(cc.ClaudeCodeError, match="90"):
            cc.ask_claude_code("Hallo?", timeout=90)


# --- ask_claude_code_structured(): Grundlage des Intent-Routers (core/intent_router.py) --


def test_ask_claude_code_structured_passes_json_schema_flag():
    schema = {"type": "object", "properties": {"response_type": {"type": "string"}}}
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": False, "structured_output": {"response_type": "chat"}}), stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result) as fake_run:
        result = cc.ask_claude_code_structured("Nutzer: hallo", json_schema=schema)

    assert result == {"response_type": "chat"}
    args = fake_run.call_args[0][0]
    assert "--json-schema" in args
    assert json.loads(args[args.index("--json-schema") + 1]) == schema
    # Der strukturierte Pfad darf, genau wie der normale, NIE Werkzeuge freigeben.
    assert args[args.index("--tools") + 1] == ""


def test_ask_claude_code_structured_falls_back_to_result_field_json_string():
    """Manche CLI-Versionen liefern das Schema-Objekt evtl. nur im "result"-Textfeld
    statt im separaten "structured_output"-Feld - lieber selbst parsen als zu scheitern."""
    fake_result = MagicMock(
        returncode=0,
        stdout=json.dumps({"is_error": False, "result": json.dumps({"response_type": "capability_call", "capability": "mail"})}),
        stderr="",
    )
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        result = cc.ask_claude_code_structured("Nutzer: mails?", json_schema={"type": "object"})

    assert result == {"response_type": "capability_call", "capability": "mail"}


def test_ask_claude_code_structured_raises_when_neither_field_has_a_dict():
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": False, "result": "kein JSON"}), stderr="")
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch.object(subprocess, "run", return_value=fake_result):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code_structured("Nutzer: hallo", json_schema={"type": "object"})


def test_ask_claude_code_structured_raises_when_binary_missing():
    with patch.object(cc, "find_claude_binary", return_value=None):
        with pytest.raises(cc.ClaudeCodeError):
            cc.ask_claude_code_structured("Nutzer: hallo", json_schema={"type": "object"})
