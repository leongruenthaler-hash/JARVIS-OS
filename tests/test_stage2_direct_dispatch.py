"""Tests fuer plans/2026-08-16-jarvis-stufe2-klassifikation-direkt-beantworten.md:
eine eindeutige Stufe-2-Klassifikation (classify_domain_via_llm liefert genau eine
Domaene) soll jetzt zuerst versuchen, direkt ueber _dispatch_confirmed_domain() zu
antworten, statt in jedem Fall nur eine Rueckfrage zu stellen. _dispatch_confirmed_domain
selbst wird gemockt (analog zum Muster in test_camera_command.py), damit die Tests
weder einen echten Mail-/Kalender-/... Zugriff noch ein echtes Modell brauchen und
sich ausschliesslich auf die neue Verzweigungslogik konzentrieren."""

from unittest.mock import patch

import pytest

from memory import Memory
import jarvis


class _FakeLLM:
    def __init__(self, response: str):
        self._response = response

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, raw_system_prompt=False, **kwargs):
        return self._response


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_single_domain_with_real_answer_skips_clarification(memory):
    llm = _FakeLLM("calendar")
    with patch.object(jarvis, "_dispatch_confirmed_domain", return_value="Ihre nächsten Termine: ...") as dispatch:
        answer = jarvis.maybe_ask_domain_clarification(llm, memory, "was steht bei mir so an")

    assert answer == "Ihre nächsten Termine: ..."
    dispatch.assert_called_once_with("calendar", "was steht bei mir so an", memory, photo_worker=None)

    settings = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings


def test_single_domain_handler_returns_none_falls_back_to_clarification(memory):
    llm = _FakeLLM("calendar")
    with patch.object(jarvis, "_dispatch_confirmed_domain", return_value=None):
        answer = jarvis.maybe_ask_domain_clarification(llm, memory, "was steht bei mir so an")

    assert answer is not None
    assert "Meinten Sie gerade" in answer

    settings = memory.get("settings") or {}
    pending = settings.get("pending_domain_clarification")
    assert isinstance(pending, dict)
    assert pending["domains"] == ["calendar"]


def test_two_domains_never_calls_dispatch_stays_ambiguous(memory):
    llm = _FakeLLM("mail, calendar")
    with patch.object(jarvis, "_dispatch_confirmed_domain") as dispatch:
        answer = jarvis.maybe_ask_domain_clarification(llm, memory, "check das mal für mich")

    dispatch.assert_not_called()
    assert answer is not None
    assert "oder" in answer

    settings = memory.get("settings") or {}
    pending = settings.get("pending_domain_clarification")
    assert pending["domains"] == ["mail", "calendar"]


def test_config_toggle_disables_direct_dispatch(memory):
    llm = _FakeLLM("calendar")
    with patch.object(jarvis, "_dispatch_confirmed_domain") as dispatch:
        answer = jarvis.maybe_ask_domain_clarification(
            llm, memory, "was steht bei mir so an", config={"stage2_direct_dispatch_enabled": False}
        )

    dispatch.assert_not_called()
    assert "Meinten Sie gerade" in answer
    settings = memory.get("settings") or {}
    assert isinstance(settings.get("pending_domain_clarification"), dict)


def test_config_toggle_defaults_to_enabled_when_config_omitted(memory):
    llm = _FakeLLM("calendar")
    with patch.object(jarvis, "_dispatch_confirmed_domain", return_value="Direkte Antwort.") as dispatch:
        answer = jarvis.maybe_ask_domain_clarification(llm, memory, "was steht bei mir so an")

    dispatch.assert_called_once()
    assert answer == "Direkte Antwort."


def test_photo_worker_is_passed_through_to_dispatch(memory):
    llm = _FakeLLM("photos")
    fake_worker = object()
    with patch.object(jarvis, "_dispatch_confirmed_domain", return_value="Foto-Antwort.") as dispatch:
        jarvis.maybe_ask_domain_clarification(llm, memory, "zeig mir was dazu", photo_worker=fake_worker)

    dispatch.assert_called_once_with("photos", "zeig mir was dazu", memory, photo_worker=fake_worker)


def test_no_domain_classified_returns_none_without_dispatch_attempt(memory):
    llm = _FakeLLM("keine")
    with patch.object(jarvis, "_dispatch_confirmed_domain") as dispatch:
        answer = jarvis.maybe_ask_domain_clarification(llm, memory, "wie geht's dir")

    dispatch.assert_not_called()
    assert answer is None
    settings = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings
