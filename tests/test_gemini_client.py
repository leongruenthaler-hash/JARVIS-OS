"""Tests fuer app/gemini_client.py: duenner REST-Wrapper um die Google Gemini API
(Nutzerwunsch 2026-09-03: Gemini als schneller Provider fuer Router-Entscheidung +
normale Chat-Antworten, waehrend Claude Code fuer Faehigkeiten/Hintergrund-Aktionen
zustaendig bleibt)."""

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

import gemini_client as gc


@pytest.fixture(autouse=True)
def _reset_availability_cache():
    gc._AVAILABILITY_CACHE = (0.0, False)
    yield
    gc._AVAILABILITY_CACHE = (0.0, False)


def test_is_gemini_available_reflects_key_presence():
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"):
        assert gc.is_gemini_available(force=True) is True
    with patch.object(gc, "get_gemini_api_key", return_value=None):
        assert gc.is_gemini_available(force=True) is False


def test_ask_gemini_raises_when_key_missing():
    with patch.object(gc, "get_gemini_api_key", return_value=None):
        with pytest.raises(gc.GeminiError):
            gc.ask_gemini("Hallo?")


def test_ask_gemini_raises_on_empty_prompt():
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"):
        with pytest.raises(gc.GeminiError):
            gc.ask_gemini("   ")


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_ask_gemini_extracts_text_from_first_candidate():
    payload = {"candidates": [{"content": {"parts": [{"text": "Alles bestens, Sir."}]}}]}
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"), \
         patch.object(gc.urllib.request, "urlopen", return_value=_FakeResponse(payload)) as fake_urlopen:
        answer = gc.ask_gemini("Wie geht's?", system_prompt="Du bist Jarvis.", model="gemini-2.5-flash")

    assert answer == "Alles bestens, Sir."
    request = fake_urlopen.call_args[0][0]
    assert "gemini-2.5-flash:generateContent" in request.full_url
    body = json.loads(request.data.decode("utf-8"))
    assert body["contents"][0]["parts"][0]["text"] == "Wie geht's?"
    assert body["systemInstruction"]["parts"][0]["text"] == "Du bist Jarvis."


def test_ask_gemini_raises_when_no_candidates():
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"), \
         patch.object(gc.urllib.request, "urlopen", return_value=_FakeResponse({"candidates": []})):
        with pytest.raises(gc.GeminiError):
            gc.ask_gemini("Hallo?")


def test_ask_gemini_raises_on_http_error():
    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, BytesIO(b"invalid api key"))

    with patch.object(gc, "get_gemini_api_key", return_value="abc123"), \
         patch.object(gc.urllib.request, "urlopen", side_effect=_raise):
        with pytest.raises(gc.GeminiError, match="401"):
            gc.ask_gemini("Hallo?")


def test_ask_gemini_structured_passes_response_schema_and_parses_json_text():
    schema = {"type": "object", "properties": {"response_type": {"type": "string"}}}
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"response_type": "chat"})}]}}]}
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"), \
         patch.object(gc.urllib.request, "urlopen", return_value=_FakeResponse(payload)) as fake_urlopen:
        result = gc.ask_gemini_structured("Nutzer: hallo", json_schema=schema)

    assert result == {"response_type": "chat"}
    request = fake_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["generationConfig"]["responseSchema"] == schema
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_ask_gemini_structured_raises_on_non_json_text():
    payload = {"candidates": [{"content": {"parts": [{"text": "kein JSON"}]}}]}
    with patch.object(gc, "get_gemini_api_key", return_value="abc123"), \
         patch.object(gc.urllib.request, "urlopen", return_value=_FakeResponse(payload)):
        with pytest.raises(gc.GeminiError):
            gc.ask_gemini_structured("Nutzer: hallo", json_schema={"type": "object"})
