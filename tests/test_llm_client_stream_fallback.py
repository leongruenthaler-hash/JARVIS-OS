"""Tests fuer LLMClient.ask_stream()'s Ruecksturz auf ask() bei leerem
Ollama-Streaming-Ergebnis - live beobachtet (2026-08-12): Ollamas
Streaming-Endpunkt lieferte fuer phi4-mini HTTP 200 mit komplett leerem
Body, obwohl derselbe Prompt ueber den nicht-gestreamten Weg funktionierte.
Siehe docs/current-system-assessment.md, Abschnitt 38."""

from unittest.mock import MagicMock, patch

import jarvis
from model_router import ModelRoute


def _route():
    return ModelRoute(
        provider="ollama",
        model="phi4-mini",
        max_output_tokens=220,
        num_ctx=2048,
        temperature=0.2,
        recent_context_limit=3,
        compact_prompt=True,
        stream=True,
        mode="performance",
    )


def _client():
    client = jarvis.LLMClient.__new__(jarvis.LLMClient)
    client.provider = "ollama"
    client._last_state_refresh = 1e18  # skip _refresh_model_state()'s real work
    return client


def test_falls_back_to_ask_when_ollama_stream_returns_empty():
    client = _client()
    with patch.object(client, "_ask_ollama", return_value="") as fake_stream, \
         patch.object(client, "ask", return_value="Mir geht es gut, Sir.") as fake_ask:
        result = client.ask_stream([{"role": "user", "content": "hi"}], route=_route(), on_chunk=None)

    fake_stream.assert_called_once()
    fake_ask.assert_called_once()
    assert result == "Mir geht es gut, Sir."


def test_uses_stream_result_when_non_empty():
    client = _client()
    with patch.object(client, "_ask_ollama", return_value="Alles bestens.") as fake_stream, \
         patch.object(client, "ask") as fake_ask:
        result = client.ask_stream([{"role": "user", "content": "hi"}], route=_route(), on_chunk=None)

    fake_stream.assert_called_once()
    fake_ask.assert_not_called()
    assert result == "Alles bestens."


def test_fallback_replays_chunks_to_on_chunk():
    client = _client()
    chunks = []
    with patch.object(client, "_ask_ollama", return_value=""), \
         patch.object(client, "ask", return_value="Zwei Woerter"):
        client.ask_stream([{"role": "user", "content": "hi"}], route=_route(), on_chunk=chunks.append)

    assert "".join(chunks) == "Zwei Woerter"
