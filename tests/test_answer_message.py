"""Charakterisierungs-/Regressionstests fuer jarvis.py::answer_message() - die
gemeinsame Antwort-Logik, die main() (CLI) und local_server.py::_answer_with_core()
(App) seit plans/2026-08-09-jarvis-cli-server-aufraeumen.md gemeinsam nutzen. Vor
diesem Umbau hatte die Dispatch-Kette selbst KEINE Tests (nur die einzelnen
Handler-Funktionen waren getestet) - das hier haelt den Ist-Zustand fest, damit
kuenftige Aenderungen an der Reihenfolge/Berechtigungs-Klammer nicht unbemerkt
auseinanderdriften wie es main()/_answer_with_core() vor dem Umbau bereits taten."""

from unittest.mock import patch

import pytest

import jarvis
from memory import Memory
from model_router import ModelRoute


def _route(provider="ollama", model="phi4-mini", compact=False):
    return ModelRoute(
        provider=provider,
        model=model,
        max_output_tokens=160,
        num_ctx=1024,
        temperature=0.3,
        recent_context_limit=6,
        compact_prompt=compact,
        stream=False,
        mode="performance",
    )


class _FakeLLM:
    def __init__(self, answer="Chat-Antwort", route=None):
        self._answer = answer
        self._route = route or _route()
        self.ask_calls = []

    def plan(self, messages, user_text=None, force_local=False):
        return self._route

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False):
        self.ask_calls.append({"messages": messages, "user_text": user_text, "force_local": force_local})
        return self._answer

    def ask_stream(self, messages, max_output_tokens=None, user_text=None, route=None, on_chunk=None, force_local=False):
        if callable(on_chunk):
            on_chunk(self._answer)
        return self._answer


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


@pytest.fixture
def workers():
    return jarvis.AnswerWorkers()


@pytest.fixture(autouse=True)
def _no_permissions_required(monkeypatch, tmp_path):
    # ensure_privacy_domain_permission()/has_permission() beide gehen ueber einen
    # frischen PermissionManager(), der ohne expliziten base_path die echte
    # Produktions-data_root() nutzen wuerde - hier auf tmp_path umlenken, gleiches
    # Muster wie in test_multistep_planner.py/test_privacy_command.py.
    from permission_manager import PermissionManager

    class _AllowAllPermissionManager(PermissionManager):
        def __init__(self, base_path=None):
            super().__init__(base_path=tmp_path)

        def is_allowed(self, permission):
            return True

        def is_requested(self, permission):
            return True

    monkeypatch.setattr(jarvis, "PermissionManager", _AllowAllPermissionManager)
    monkeypatch.setattr(jarvis, "permissions_required", lambda: False)


def test_is_end_command_short_circuits_before_any_handler(memory, workers):
    with patch.object(jarvis, "handle_system_command") as fake_system:
        result = jarvis.answer_message("beenden", memory, _FakeLLM(), {}, workers=workers)

    fake_system.assert_not_called()
    assert "wieder still" in result.text


def test_first_matching_direct_handler_wins_and_stops_dispatch(memory, workers):
    with patch.object(jarvis, "handle_system_command", return_value="System-Antwort") as fake_system, \
         patch.object(jarvis, "handle_local_command") as fake_local:
        result = jarvis.answer_message("irgendwas", memory, _FakeLLM(), {}, workers=workers)

    fake_system.assert_called_once()
    fake_local.assert_not_called()
    assert result.text == "System-Antwort"


def test_notes_handler_wins_over_calendar_when_only_notes_matches(memory, workers):
    with patch.object(jarvis, "has_domain", side_effect=lambda q, d: d == "notes"), \
         patch.object(jarvis, "handle_notes_command", return_value="Notiz erstellt") as fake_notes, \
         patch.object(jarvis, "handle_calendar_command") as fake_calendar:
        result = jarvis.answer_message("Notiz: Milch kaufen", memory, _FakeLLM(), {}, workers=workers)

    fake_notes.assert_called_once()
    fake_calendar.assert_not_called()
    assert result.text == "Notiz erstellt"


def test_domain_permission_denial_returns_prompt_without_calling_handler(memory, workers):
    with patch.object(jarvis, "has_domain", side_effect=lambda q, d: d == "notes"), \
         patch.object(jarvis, "ensure_privacy_domain_permission", return_value="Erlaubst du Notizen?") as fake_ensure, \
         patch.object(jarvis, "handle_notes_command") as fake_notes:
        result = jarvis.answer_message("Notiz: Milch kaufen", memory, _FakeLLM(), {}, workers=workers)

    fake_ensure.assert_called()
    fake_notes.assert_not_called()
    assert result.text == "Erlaubst du Notizen?"


# --- record_exchange: pro Handler unterschiedliches Verhalten (aus main() uebernommen) --


def test_system_command_answer_is_not_recorded(memory, workers):
    with patch.object(jarvis, "handle_system_command", return_value="System-Antwort"), \
         patch.object(jarvis, "record_exchange") as fake_record:
        jarvis.answer_message("status", memory, _FakeLLM(), {}, workers=workers)

    fake_record.assert_not_called()


def test_model_command_answer_recorded_without_auto_memory(memory, workers):
    with patch.object(jarvis, "handle_system_command", return_value=None), \
         patch.object(jarvis, "handle_model_command", return_value="Modell gewechselt"), \
         patch.object(jarvis, "record_exchange") as fake_record:
        jarvis.answer_message("nutze gemma", memory, _FakeLLM(), {}, workers=workers)

    fake_record.assert_called_once()
    _, kwargs = fake_record.call_args
    assert kwargs.get("auto_memory") is False


def test_pending_note_flow_answer_recorded_normally(memory, workers):
    with patch.object(jarvis, "handle_pending_note_flow", return_value="Notiz gespeichert"), \
         patch.object(jarvis, "record_exchange") as fake_record:
        jarvis.answer_message("Milch", memory, _FakeLLM(), {}, workers=workers)

    fake_record.assert_called_once()
    _, kwargs = fake_record.call_args
    assert "auto_memory" not in kwargs


# --- pending_mail_followup ------------------------------------------------------


def test_mail_command_sets_pending_mail_followup_true(memory, workers):
    with patch.object(jarvis, "has_domain", side_effect=lambda q, d: d == "mail"), \
         patch.object(jarvis, "handle_mail_document_export_command", return_value=None), \
         patch.object(jarvis, "handle_background_mail_command", return_value=None), \
         patch.object(jarvis, "handle_mail_command", return_value="3 neue Mails"):
        result = jarvis.answer_message("was ist neu in meiner mail", memory, _FakeLLM(), {}, workers=workers, pending_mail_followup=False)

    assert result.pending_mail_followup is True


def test_music_command_resets_pending_mail_followup(memory, workers):
    with patch.object(jarvis, "has_domain", side_effect=lambda q, d: d == "music"), \
         patch.object(jarvis, "handle_music_command", return_value="Musik gestartet"):
        result = jarvis.answer_message("spiel musik", memory, _FakeLLM(), {}, workers=workers, pending_mail_followup=True)

    assert result.pending_mail_followup is False


# --- Stufe 2 + finaler Chat-Fallback --------------------------------------------


def test_domain_clarification_used_when_nothing_else_matches(memory, workers):
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value="Meintest du deine Mails?"):
        result = jarvis.answer_message("irgendwas unklares", memory, _FakeLLM(), {}, workers=workers)

    assert result.text == "Meintest du deine Mails?"


def test_falls_through_to_chat_when_nothing_matches(memory, workers):
    llm = _FakeLLM(answer="Allgemeine Antwort")
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None):
        result = jarvis.answer_message("wie geht es dir", memory, llm, {}, workers=workers)

    assert result.text == "Allgemeine Antwort"
    assert result.provider == "ollama"
    assert result.model == "phi4-mini"


def test_streaming_uses_ask_stream_and_forwards_chunks(memory, workers):
    llm = _FakeLLM(answer="Gestreamte Antwort")
    chunks = []
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None):
        result = jarvis.answer_message(
            "wie geht es dir", memory, llm, {}, workers=workers, on_llm_chunk=chunks.append
        )

    assert result.text == "Gestreamte Antwort"
    assert chunks == ["Gestreamte Antwort"]
