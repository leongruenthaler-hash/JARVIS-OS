"""Duenner REST-Wrapper um die Google Gemini API, damit Jarvis Gemini als schnellen
Cloud-Provider fuer die Intent-Router-Entscheidung und normale Chat-Antworten nutzen
kann (Nutzerwunsch 2026-09-03: "Gemini fuer die schnelleren Antworten, Claude Code
fuer die Hintergrund-Aktionen und die eigentlichen Aufgaben"). Anders als Claude Code
laeuft Gemini nicht ueber ein lokal installiertes CLI/Abo, sondern ueber einen
API-Key (Google AI Studio) - kein zusaetzlicher Prozess, nur ein HTTP-Aufruf ueber
urllib (kein neues Python-Paket noetig, gleiches Muster wie llm_client.py::_ask_ollama).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from secure_storage import SecureStorageError, get_gemini_api_key

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"

_AVAILABILITY_CACHE: tuple[float, bool] = (0.0, False)
_AVAILABILITY_CACHE_SECONDS = 30.0


class GeminiError(RuntimeError):
    """Gemini war nicht erreichbar, hat einen Fehler geliefert oder eine unbrauchbare/
    leere Antwort zurueckgegeben."""


def is_gemini_available(force: bool = False) -> bool:
    global _AVAILABILITY_CACHE
    now = time.time()
    cached_at, cached_value = _AVAILABILITY_CACHE
    if not force and now - cached_at < _AVAILABILITY_CACHE_SECONDS:
        return cached_value
    try:
        available = bool(get_gemini_api_key())
    except SecureStorageError:
        available = False
    _AVAILABILITY_CACHE = (now, available)
    return available


def _require_api_key() -> str:
    try:
        api_key = get_gemini_api_key()
    except SecureStorageError as exc:
        raise GeminiError(str(exc)) from exc
    if not api_key:
        raise GeminiError(
            "Gemini API-Key fehlt. Speichere ihn sicher mit: python3 app/jarvis.py --set-gemini-key"
        )
    return api_key


def _call_gemini(
    prompt: str,
    *,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    timeout: float = 20,
    generation_config: dict | None = None,
) -> dict:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise GeminiError("Leerer Prompt an Gemini uebergeben.")
    api_key = _require_api_key()

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    if generation_config:
        payload["generationConfig"] = generation_config

    url = f"{API_BASE}/{model}:generateContent?key={api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise GeminiError(f"Gemini-Anfrage fehlgeschlagen ({exc.code}): {detail[:300] or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Gemini war nicht erreichbar: {exc.reason}") from exc
    except TimeoutError as exc:
        raise GeminiError(f"Gemini hat innerhalb von {timeout:.0f}s nicht geantwortet.") from exc

    return data


def _extract_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise GeminiError(f"Gemini hat die Anfrage blockiert: {block_reason}")
        raise GeminiError("Gemini hat keine Antwort geliefert.")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text") or "") for part in parts).strip()
    if not text:
        raise GeminiError("Gemini hat eine leere Antwort geliefert.")
    return text


def ask_gemini(
    prompt: str,
    *,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    timeout: float = 20,
) -> str:
    data = _call_gemini(prompt, system_prompt=system_prompt, model=model, timeout=timeout)
    return _extract_text(data)


def ask_gemini_structured(
    prompt: str,
    *,
    json_schema: dict,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    timeout: float = 20,
) -> dict:
    """Wie ask_gemini(), erzwingt aber schema-validierte JSON-Ausgabe ueber Geminis
    natives generationConfig.responseSchema (Gegenstueck zu Claude Codes --json-schema
    bzw. Ollamas format-Feld, siehe llm_client.py::ask_structured())."""
    data = _call_gemini(
        prompt,
        system_prompt=system_prompt,
        model=model,
        timeout=timeout,
        generation_config={"responseMimeType": "application/json", "responseSchema": json_schema},
    )
    text = _extract_text(data)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini lieferte keine valide JSON-Antwort: {text[:200]}") from exc
    if not isinstance(parsed, dict):
        raise GeminiError("Gemini lieferte kein JSON-Objekt.")
    return parsed
