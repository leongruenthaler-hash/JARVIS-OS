"""Tests fuer den 'claude_code'-Dispatch-Pfad in LLMClient.ask(): flacht die
Nachrichtenliste zu System-Prompt + Verlauf-Text ab (die CLI nimmt nur einen
einzelnen Prompt-String), ruft claude_code_client.ask_claude_code() auf, und
"privater Modus" (force_local) darf NIE an Claude Code gehen."""

from unittest.mock import patch

import jarvis
from model_router import ModelRoute


def _route(provider="claude_code"):
    return ModelRoute(
        provider=provider,
        model="sonnet",
        max_output_tokens=500,
        num_ctx=1024,
        temperature=0.3,
        recent_context_limit=4,
        compact_prompt=False,
        stream=False,
        mode="quality",
    )


def _client(provider="claude_code"):
    client = jarvis.LLMClient.__new__(jarvis.LLMClient)
    client.provider = provider
    client.config = {}
    client._last_state_refresh = 1e18
    return client


def test_ask_dispatches_to_claude_code_when_active_provider():
    client = _client("claude_code")
    messages = [
        {"role": "system", "content": "Du bist Jarvis."},
        {"role": "user", "content": "Wie spaet ist es?"},
    ]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.ask_claude_code", return_value="Es ist 14 Uhr.") as fake_ask:
        answer = client.ask(messages, route=_route())

    assert answer == "Es ist 14 Uhr."
    fake_ask.assert_called_once()
    _, kwargs = fake_ask.call_args
    assert kwargs["system_prompt"] == "Du bist Jarvis."
    assert "Wie spaet ist es?" in fake_ask.call_args[0][0]


def test_private_mode_never_routes_to_claude_code():
    """force_local=True (privater Modus) muss IMMER lokal bleiben, auch wenn
    claude_code der konfigurierte Standard-Provider ist - identisches
    Sicherheitsversprechen wie beim bestehenden OpenAI-Pfad."""
    client = _client("claude_code")
    with patch.object(client, "_ask_ollama", return_value="Lokale Antwort.") as fake_ollama, \
         patch("llm_client.ask_claude_code") as fake_claude:
        answer = client.ask(
            [{"role": "user", "content": "geheim"}],
            route=_route(provider="ollama"),
            force_local=True,
        )

    assert answer == "Lokale Antwort."
    fake_ollama.assert_called_once()
    fake_claude.assert_not_called()


def test_claude_code_error_is_wrapped_as_runtime_error():
    from claude_code_client import ClaudeCodeError

    client = _client("claude_code")
    with patch.object(client, "_prepare_messages", return_value=[{"role": "user", "content": "hi"}]), \
         patch("llm_client.ask_claude_code", side_effect=ClaudeCodeError("CLI nicht gefunden")):
        try:
            client.ask([{"role": "user", "content": "hi"}], route=_route())
            assert False, "erwartete RuntimeError"
        except RuntimeError as exc:
            assert "CLI nicht gefunden" in str(exc)
