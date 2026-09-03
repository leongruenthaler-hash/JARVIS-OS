"""Tests fuer den 'gemini'-Dispatch-Pfad in LLMClient.ask()/ask_stream() und fuer
force_provider allgemein: Gemini uebernimmt laut Nutzerwunsch (2026-09-03) die
Intent-Router-Entscheidung und normale Chat-Antworten ("die schnelleren Antworten"),
waehrend Claude Code weiterhin fuer Faehigkeiten/Hintergrund-Aktionen zustaendig
bleibt (siehe core/intent_router.py, app/jarvis.py::answer_message()).
force_provider darf NIE hart scheitern, wenn der gewuenschte Anbieter (noch) nicht
verfuegbar ist (z.B. kein Gemini-Key hinterlegt) - es faellt dann still auf den
tatsaechlich aktiven Provider (self.provider) zurueck."""

from unittest.mock import patch

import jarvis
from model_router import ModelRoute


def _route(provider="gemini"):
    return ModelRoute(
        provider=provider,
        model="gemini-2.5-flash",
        max_output_tokens=400,
        num_ctx=1024,
        temperature=0.3,
        recent_context_limit=4,
        compact_prompt=False,
        stream=False,
        mode="quality",
    )


def _client(provider="ollama"):
    client = jarvis.LLMClient.__new__(jarvis.LLMClient)
    client.provider = provider
    client.config = {}
    client._last_state_refresh = 1e18
    return client


def test_ask_dispatches_to_gemini_when_active_provider():
    client = _client("gemini")
    messages = [
        {"role": "system", "content": "Du bist Jarvis."},
        {"role": "user", "content": "Wie spaet ist es?"},
    ]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.ask_gemini", return_value="Es ist 14 Uhr.") as fake_ask:
        answer = client.ask(messages, route=_route())

    assert answer == "Es ist 14 Uhr."
    fake_ask.assert_called_once()
    _, kwargs = fake_ask.call_args
    assert kwargs["system_prompt"] == "Du bist Jarvis."
    assert "Wie spaet ist es?" in fake_ask.call_args[0][0]


def test_private_mode_never_routes_to_gemini():
    client = _client("gemini")
    with patch.object(client, "_ask_ollama", return_value="Lokale Antwort.") as fake_ollama, \
         patch("llm_client.ask_gemini") as fake_gemini:
        answer = client.ask(
            [{"role": "user", "content": "geheim"}],
            route=_route(provider="ollama"),
            force_local=True,
        )

    assert answer == "Lokale Antwort."
    fake_ollama.assert_called_once()
    fake_gemini.assert_not_called()


def test_gemini_error_is_wrapped_as_runtime_error():
    from gemini_client import GeminiError

    client = _client("gemini")
    with patch.object(client, "_prepare_messages", return_value=[{"role": "user", "content": "hi"}]), \
         patch("llm_client.ask_gemini", side_effect=GeminiError("kein API-Key")):
        try:
            client.ask([{"role": "user", "content": "hi"}], route=_route())
            assert False, "erwartete RuntimeError"
        except RuntimeError as exc:
            assert "kein API-Key" in str(exc)


def test_force_provider_dispatches_to_gemini_regardless_of_active_provider():
    """core/intent_router.py::decide() und der Chat-Fallback in
    jarvis.py::answer_message() rufen ask()/ask_stream() mit force_provider="gemini"
    auf, unabhaengig davon, was self.provider gerade ist (z.B. claude_code)."""
    client = _client("claude_code")
    messages = [{"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.is_gemini_available", return_value=True), \
         patch("llm_client.ask_gemini", return_value="Hi!") as fake_gemini, \
         patch("llm_client.ask_claude_code") as fake_claude:
        answer = client.ask(messages, route=_route(provider="claude_code"), force_provider="gemini")

    assert answer == "Hi!"
    fake_gemini.assert_called_once()
    fake_claude.assert_not_called()


def test_force_provider_falls_back_to_active_provider_when_gemini_unavailable():
    client = _client("claude_code")
    messages = [{"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.is_gemini_available", return_value=False), \
         patch("llm_client.ask_claude_code", return_value="Antwort von Claude Code.") as fake_claude, \
         patch("llm_client.ask_gemini") as fake_gemini:
        answer = client.ask(messages, route=_route(provider="claude_code"), force_provider="gemini")

    assert answer == "Antwort von Claude Code."
    fake_claude.assert_called_once()
    fake_gemini.assert_not_called()


# --- Provider-Selbstauskunft (llm_client.py::_PROVIDER_SELF_NOTICE) ------------------
# Live-Bug 2026-09-03: auf "funktionierst du grad ueber Gemini oder Claude?" antwortete
# Gemini selbst "Ich laufe über Claude" - das Modell wusste nicht, dass es GENAU DIESE
# Antwort generierte. Ein kurzer interner Hinweis im System-Prompt (nicht gemockt hier,
# damit _prepare_messages() ihn wirklich einfuegt) soll das beheben.


def test_gemini_call_includes_self_identity_notice_in_system_prompt():
    client = _client("gemini")
    messages = [
        {"role": "system", "content": "Du bist Jarvis."},
        {"role": "user", "content": "Funktionierst du grad ueber Gemini oder Claude?"},
    ]
    with patch("llm_client.ask_gemini", return_value="Gemini, Sir.") as fake_ask:
        client.ask(messages, route=_route())

    system_prompt = fake_ask.call_args[1]["system_prompt"]
    assert "Google Gemini" in system_prompt
    assert "sag das ehrlich" in system_prompt


def test_claude_code_call_includes_self_identity_notice_in_system_prompt():
    client = _client("claude_code")
    messages = [
        {"role": "system", "content": "Du bist Jarvis."},
        {"role": "user", "content": "Funktionierst du grad ueber Gemini oder Claude?"},
    ]
    with patch("llm_client.ask_claude_code", return_value="Claude, Sir.") as fake_ask:
        client.ask(messages, route=_route(provider="claude_code"))

    system_prompt = fake_ask.call_args[1]["system_prompt"]
    assert "Claude" in system_prompt and "Anthropic" in system_prompt
    assert "sag das ehrlich" in system_prompt


def test_ask_stream_forwards_force_provider_to_ask_fallback():
    """ask_stream() hat fuer gemini/claude_code kein eigenes Streaming - es faellt auf
    self.ask() zurueck, muss force_provider dabei aber weiterreichen, sonst wuerde die
    Streaming-Variante eines Chat-Aufrufs (on_llm_chunk gesetzt) den Gemini-Wunsch
    stillschweigend verlieren."""
    client = _client("claude_code")
    messages = [{"role": "user", "content": "hallo"}]
    with patch.object(client, "_prepare_messages", return_value=messages), \
         patch("llm_client.is_gemini_available", return_value=True), \
         patch("llm_client.ask_gemini", return_value="Hi!") as fake_gemini:
        answer = client.ask_stream(messages, route=_route(provider="claude_code"), force_provider="gemini")

    assert answer == "Hi!"
    fake_gemini.assert_called_once()
