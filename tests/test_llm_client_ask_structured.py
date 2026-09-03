"""Tests fuer LLMClient.ask_structured(): erzwingt schema-validierte JSON-Ausgabe statt
freien Text - Grundlage des Intent-Routers (core/intent_router.py, Plan
"Jarvis-Intent-Router 2.0", 2026-09-02). Claude Code nutzt dafuer --json-schema, Ollama
das native "format"-Feld von /api/chat."""

from unittest.mock import patch

import pytest

import jarvis
from model_router import ModelRoute

SCHEMA = {"type": "object", "properties": {"response_type": {"type": "string"}}, "required": ["response_type"]}


def _route(provider="claude_code"):
    return ModelRoute(
        provider=provider,
        model="sonnet",
        max_output_tokens=200,
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


def test_ask_structured_dispatches_to_claude_code_and_returns_dict():
    client = _client("claude_code")
    messages = [{"role": "system", "content": "System."}, {"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.ask_claude_code_structured", return_value={"response_type": "chat"}) as fake_ask:
        result = client.ask_structured(messages, json_schema=SCHEMA, route=_route())

    assert result == {"response_type": "chat"}
    _, kwargs = fake_ask.call_args
    assert kwargs["json_schema"] == SCHEMA
    assert kwargs["system_prompt"] == "System."


def test_ask_structured_dispatches_to_ollama_and_parses_json_string():
    client = _client("ollama")
    with patch.object(client, "_ask_ollama", return_value='{"response_type": "capability_call", "capability": "mail"}') as fake_ollama:
        result = client.ask_structured([{"role": "user", "content": "mails?"}], json_schema=SCHEMA, route=_route(provider="ollama"))

    assert result == {"response_type": "capability_call", "capability": "mail"}
    _, kwargs = fake_ollama.call_args
    assert kwargs["response_schema"] == SCHEMA


def test_ask_structured_raises_when_ollama_returns_invalid_json():
    client = _client("ollama")
    with patch.object(client, "_ask_ollama", return_value="das ist kein JSON"):
        with pytest.raises(RuntimeError):
            client.ask_structured([{"role": "user", "content": "hi"}], json_schema=SCHEMA, route=_route(provider="ollama"))


def test_ask_structured_force_local_routes_to_ollama_even_if_claude_code_is_default():
    client = _client("claude_code")
    with patch.object(client, "_ask_ollama", return_value='{"response_type": "chat"}') as fake_ollama, \
         patch("llm_client.ask_claude_code_structured") as fake_claude:
        result = client.ask_structured(
            [{"role": "user", "content": "geheim"}], json_schema=SCHEMA, route=_route(provider="ollama"), force_local=True
        )

    assert result == {"response_type": "chat"}
    fake_ollama.assert_called_once()
    fake_claude.assert_not_called()


def test_ask_structured_wraps_claude_code_error_as_runtime_error():
    from claude_code_client import ClaudeCodeError

    client = _client("claude_code")
    with patch.object(client, "_prepare_messages", return_value=[{"role": "user", "content": "hi"}]), \
         patch("llm_client.ask_claude_code_structured", side_effect=ClaudeCodeError("kaputt")):
        with pytest.raises(RuntimeError, match="kaputt"):
            client.ask_structured([{"role": "user", "content": "hi"}], json_schema=SCHEMA, route=_route())


# --- force_provider="gemini": Grundlage der Rollenaufteilung Gemini (Router-Entscheidung
# + normale Chat-Antworten) / Claude Code (Faehigkeiten, Hintergrund-Aktionen), siehe
# core/intent_router.py::decide() und app/jarvis.py::answer_message() (Nutzerwunsch
# 2026-09-03). ---


def test_ask_structured_force_provider_dispatches_to_gemini_when_available():
    client = _client("claude_code")
    messages = [{"role": "system", "content": "System."}, {"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.is_gemini_available", return_value=True), \
         patch("llm_client.ask_gemini_structured", return_value={"response_type": "chat"}) as fake_ask:
        result = client.ask_structured(messages, json_schema=SCHEMA, route=_route(provider="gemini"), force_provider="gemini")

    assert result == {"response_type": "chat"}
    _, kwargs = fake_ask.call_args
    assert kwargs["json_schema"] == SCHEMA
    assert kwargs["system_prompt"] == "System."


def test_ask_structured_force_provider_falls_back_when_gemini_unavailable():
    """Kein Gemini-Key hinterlegt: force_provider="gemini" darf nie hart scheitern,
    sondern soll still auf den tatsaechlich aktiven Provider zurueckfallen."""
    client = _client("claude_code")
    messages = [{"role": "system", "content": "System."}, {"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.is_gemini_available", return_value=False), \
         patch("llm_client.ask_claude_code_structured", return_value={"response_type": "chat"}) as fake_claude, \
         patch("llm_client.ask_gemini_structured") as fake_gemini:
        result = client.ask_structured(messages, json_schema=SCHEMA, route=_route(), force_provider="gemini")

    assert result == {"response_type": "chat"}
    fake_claude.assert_called_once()
    fake_gemini.assert_not_called()


def test_ask_structured_wraps_gemini_error_as_runtime_error():
    from gemini_client import GeminiError

    client = _client("gemini")
    with patch.object(client, "_prepare_messages", return_value=[{"role": "user", "content": "hi"}]), \
         patch("llm_client.is_gemini_available", return_value=True), \
         patch("llm_client.ask_gemini_structured", side_effect=GeminiError("kaputt")):
        with pytest.raises(RuntimeError, match="kaputt"):
            client.ask_structured([{"role": "user", "content": "hi"}], json_schema=SCHEMA, route=_route(provider="gemini"))
