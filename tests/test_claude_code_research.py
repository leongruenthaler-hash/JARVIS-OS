"""Tests fuer den Claude-Code-Recherche-Modus (Read/Grep/Glob/WebSearch), IMMER
innerhalb einer sandbox-exec-Sandbox. Bugreport/Sicherheitsbefund 2026-09-02: ohne
echte OS-Sandbox konnte der Prozess trotz --add-dir Dateien AUSSERHALB des
freigegebenen Ordners lesen (live reproduziert mit dem Jarvis-Auth-Token) - das
haerten diese Tests gegen eine kuenftige Regression ab, indem sie erzwingen, dass
_build_sandbox_profile() den Home-Ordner verweigert und nur explizit
freigegebene Unterordner wieder erlaubt, und dass ask_claude_code_research() ohne
sandbox-exec komplett ablehnt statt ungeschuetzt weiterzulaufen."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import claude_code_client as cc


def test_sandbox_profile_denies_home_then_reallows_only_whitelisted_dirs():
    profile = cc._build_sandbox_profile(["/Users/test/Projekte/JARVIS-OS"])

    assert "(deny file-read*" in profile
    # ...und nur der explizit uebergebene Ordner wieder freigegeben.
    assert '(subpath "/Users/test/Projekte/JARVIS-OS")' in profile
    assert "(allow default)" in profile


def test_sandbox_profile_always_reallows_claude_cli_own_config_and_keychain():
    profile = cc._build_sandbox_profile(["/Users/test/Projekte/JARVIS-OS"])

    assert ".claude" in profile
    assert "Library/Keychains" in profile


def test_ask_claude_code_research_rejects_without_sandbox_exec():
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("shutil.which", side_effect=lambda name: "/usr/local/bin/claude" if name == "claude" else None):
        with pytest.raises(cc.ClaudeCodeError, match="sandbox-exec"):
            cc.ask_claude_code_research("Suche etwas", allowed_dirs=["/Users/test/Projekte"])


def test_ask_claude_code_research_rejects_without_any_allowed_dirs():
    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("shutil.which", return_value="/usr/local/bin/sandbox-exec"):
        with pytest.raises(cc.ClaudeCodeError, match="erlaubten Ordner"):
            cc.ask_claude_code_research("Suche etwas", allowed_dirs=[])


def test_ask_claude_code_research_invokes_via_sandbox_exec_with_restricted_tools():
    fake_result = MagicMock(returncode=0, stdout=json.dumps({"is_error": False, "result": "Gefunden: README.md"}), stderr="")

    def fake_which(name):
        return {"claude": "/usr/local/bin/claude", "sandbox-exec": "/usr/bin/sandbox-exec"}.get(name)

    with patch.object(cc, "find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("shutil.which", side_effect=fake_which), \
         patch.object(subprocess, "run", return_value=fake_result) as fake_run:
        answer = cc.ask_claude_code_research(
            "Was steht in README.md?",
            allowed_dirs=["/Users/test/Projekte/JARVIS-OS"],
        )

    assert answer == "Gefunden: README.md"
    args, kwargs = fake_run.call_args
    invoked = args[0]
    assert invoked[0] == "/usr/bin/sandbox-exec"
    assert invoked[1] == "-f"
    assert invoked[3] == "/usr/local/bin/claude"
    assert "--tools" in invoked
    assert invoked[invoked.index("--tools") + 1] == cc.RESEARCH_TOOLS
    assert "--allowedTools" in invoked
    # WebFetch darf NIE im Recherche-Modus stehen - kombiniert mit Read waere das
    # ein Weg, gelesene lokale Daten an eine beliebige externe URL zu schicken.
    assert "WebFetch" not in cc.RESEARCH_TOOLS
    assert "--add-dir" in invoked
    assert "/Users/test/Projekte/JARVIS-OS" in invoked
    # cwd muss innerhalb eines erlaubten Ordners liegen, sonst kann der Prozess
    # nicht einmal starten (live beobachtet: schon "claude --version" schlug fehl,
    # wenn das Arbeitsverzeichnis ausserhalb der Sandbox lag).
    assert kwargs["cwd"] == "/Users/test/Projekte/JARVIS-OS"


def test_ask_claude_code_research_never_includes_webfetch_regardless_of_input():
    assert "WebFetch" not in cc.RESEARCH_TOOLS
