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
    def __init__(self, answer="Chat-Antwort", route=None, router_decision=None):
        self._answer = answer
        self._route = route or _route()
        self.ask_calls = []
        # Default: der Intent-Router (core/intent_router.py) entscheidet "chat" - die
        # meisten bestehenden Tests wollen den alten "faellt durch bis zur normalen
        # Chat-Antwort"-Pfad pruefen, nicht Capability-Routing. Tests, die gezielt eine
        # Capability/Bestaetigung testen wollen, uebergeben ein eigenes Dict.
        self._router_decision = router_decision or {"response_type": "chat", "chat_reply": answer}

    def plan(self, messages, user_text=None, force_local=False):
        return self._route

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False, **kwargs):
        self.ask_calls.append({"messages": messages, "user_text": user_text, "force_local": force_local})
        return self._answer

    def ask_structured(self, messages, json_schema, route=None, force_local=False, **kwargs):
        return self._router_decision

    def ask_stream(self, messages, max_output_tokens=None, user_text=None, route=None, on_chunk=None, force_local=False, **kwargs):
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


def test_router_capability_call_invokes_the_chosen_capability(memory, workers):
    # Seit dem Intent-Router-Umbau (2026-09-02) entscheidet das Modell strukturiert,
    # WELCHE Capability zustaendig ist, statt einer festen has_domain()-Kaskade - siehe
    # core/intent_router.py.
    llm = _FakeLLM(router_decision={"response_type": "capability_call", "capability": "notes"})
    with patch.object(jarvis, "handle_notes_command", return_value="Notiz erstellt") as fake_notes, \
         patch.object(jarvis, "handle_calendar_command") as fake_calendar:
        result = jarvis.answer_message("Notiz: Milch kaufen", memory, llm, {}, workers=workers)

    fake_notes.assert_called_once()
    fake_calendar.assert_not_called()
    assert result.text == "Notiz erstellt"


def test_router_capability_call_uses_cleaned_capability_command_when_present(memory, workers):
    """capability_command (core/intent_router.py::ROUTER_SCHEMA, Nutzerwunsch 2026-09-03:
    Claude Code soll effektiver mit dem Befehl arbeiten koennen) - der Handler bekommt die
    vom Router bereits bereinigte Formulierung statt des rohen, ggf. umgangssprachlichen
    Nutzertexts."""
    llm = _FakeLLM(router_decision={
        "response_type": "capability_call",
        "capability": "notes",
        "capability_command": "Erstelle eine Notiz mit dem Inhalt: Milch kaufen",
    })
    captured_ctx = {}

    from core.capabilities import get_capability

    original_handler = get_capability("notes").handler

    def wrapped_handler(ctx):
        captured_ctx["text"] = ctx.text
        return "Notiz erstellt"

    get_capability("notes").handler = wrapped_handler
    try:
        result = jarvis.answer_message("äh Notiz Milch kaufen sozusagen", memory, llm, {}, workers=workers)
    finally:
        get_capability("notes").handler = original_handler

    assert captured_ctx["text"] == "Erstelle eine Notiz mit dem Inhalt: Milch kaufen"
    assert result.text == "Notiz erstellt"


def test_router_capability_call_falls_back_to_raw_question_without_capability_command(memory, workers):
    llm = _FakeLLM(router_decision={"response_type": "capability_call", "capability": "notes"})

    from core.capabilities import get_capability

    captured_ctx = {}
    original_handler = get_capability("notes").handler

    def wrapped_handler(ctx):
        captured_ctx["text"] = ctx.text
        return "Notiz erstellt"

    get_capability("notes").handler = wrapped_handler
    try:
        result = jarvis.answer_message("Notiz: Milch kaufen", memory, llm, {}, workers=workers)
    finally:
        get_capability("notes").handler = original_handler

    assert captured_ctx["text"] == "Notiz: Milch kaufen"
    assert result.text == "Notiz erstellt"


def test_router_capability_call_permission_denial_returns_prompt_without_calling_handler(memory, workers):
    llm = _FakeLLM(router_decision={"response_type": "capability_call", "capability": "notes"})
    with patch.object(jarvis, "ensure_privacy_domain_permission", return_value="Erlaubst du Notizen?") as fake_ensure, \
         patch.object(jarvis, "handle_notes_command") as fake_notes:
        result = jarvis.answer_message("Notiz: Milch kaufen", memory, llm, {}, workers=workers)

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


# --- Router-Fallback + finaler Chat --------------------------------------------


def test_falls_through_to_chat_when_nothing_matches(memory, workers):
    llm = _FakeLLM(answer="Allgemeine Antwort")
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None), \
         patch.object(jarvis, "is_gemini_available", return_value=False):
        result = jarvis.answer_message("wie geht es dir", memory, llm, {}, workers=workers)

    assert result.text == "Allgemeine Antwort"
    assert result.provider == "ollama"
    assert result.model == "phi4-mini"


def test_chat_answer_reports_gemini_as_source_when_available(memory, workers):
    """Live-Bug 2026-09-03: force_provider="gemini" (siehe llm_client.py) aendert nur,
    WER antwortet - ohne diesen Nachtrag zeigte das "source"-Feld weiterhin den
    globalen Standard-Provider, obwohl Gemini tatsaechlich geantwortet hat."""
    llm = _FakeLLM(answer="Allgemeine Antwort")
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None), \
         patch.object(jarvis, "is_gemini_available", return_value=True):
        result = jarvis.answer_message("wie geht es dir", memory, llm, {"gemini_model": "gemini-2.5-flash"}, workers=workers)

    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


# --- Tagesbriefing: muss auch im Server-/App-Pfad greifen, nicht nur CLI -------
# (Bugreport 2026-08-10: "starte das morgen Briefing" im App-Chat fiel bisher
# durch die gesamte Kette durch und landete beim allgemeinen Chat, der ohne
# echte Kalender-/Aufgaben-/Mail-Daten frei erfundene Inhalte produzierte.)


def test_briefing_request_uses_real_data_not_general_chat(memory, workers):
    llm = _FakeLLM(answer="Frei erfundene Antwort")
    with patch.object(jarvis, "handle_daily_briefing_command", return_value="Echtes Briefing mit echten Daten") as fake_briefing:
        result = jarvis.answer_message("starte doch bitte mal das morgen Briefing", memory, llm, {}, workers=workers)

    fake_briefing.assert_called_once()
    assert result.text == "Echtes Briefing mit echten Daten"


# --- _result(): zentraler Vorname-Leak-Fix ---------------------------------
# Live entdeckter Bug (2026-08-13): mehrere fest formulierte Antworten
# (handle_project_command, handle_local_command, handle_system_command)
# nutzten configured_user_name() direkt, ohne durch strip_first_name_address()
# zu laufen - das passierte bisher nur im finalen allgemeinen Chat-Pfad.
# Fix: _result(), der EINZIGE Ausgangspunkt fuer jede Antwort aus
# answer_message(), bereinigt jetzt selbst. Siehe
# docs/current-system-assessment.md, Abschnitt 41.


def test_direct_handler_answer_has_first_name_stripped(memory, workers):
    with patch.object(jarvis, "handle_system_command", return_value=None), \
         patch.object(jarvis, "handle_preference_command", return_value=None), \
         patch.object(jarvis, "handle_style_command", return_value=None), \
         patch.object(jarvis, "handle_project_command", return_value="Es ist ambitioniert, Leon, aber nicht abwegig."):
        result = jarvis.answer_message("was hältst du von meinem projekt", memory, _FakeLLM(), {}, workers=workers)

    assert "Leon" not in result.text
    assert "ambitioniert" in result.text


def test_direct_handler_answer_without_name_is_unchanged(memory, workers):
    with patch.object(jarvis, "handle_system_command", return_value="Ja, Internetzugriff ist aktiv."):
        result = jarvis.answer_message("bist du online", memory, _FakeLLM(), {}, workers=workers)

    assert result.text == "Ja, Internetzugriff ist aktiv."


def test_general_chat_answer_still_has_name_stripped(memory, workers):
    llm = _FakeLLM(answer="Danke der Nachfrage, Leon!")
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None), \
         patch.object(jarvis, "is_gemini_available", return_value=False):
        result = jarvis.answer_message("wie geht es dir", memory, llm, {}, workers=workers)

    assert "Leon" not in result.text
    assert len(llm.ask_calls) == 1


def test_briefing_trigger_matches_words_separated_by_space(memory):
    # handle_daily_briefing_command selbst pruefen (nicht gemockt): "morgen
    # briefing" als zwei separate Woerter muss erkannt werden, nicht nur die
    # exakten Komposita "tagesbriefing"/"morgenuebersicht"/"abendbriefing".
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}), \
         patch.object(jarvis, "list_open_reminders", return_value={"items": []}), \
         patch.object(jarvis, "has_permission", return_value=False):
        result = jarvis.handle_daily_briefing_command(memory, "starte doch bitte mal das morgen Briefing")

    assert result is not None


def test_briefing_trigger_none_for_unrelated_text(memory):
    assert jarvis.handle_daily_briefing_command(memory, "wie wird das Wetter") is None


def test_streaming_uses_ask_stream_and_forwards_chunks(memory, workers):
    llm = _FakeLLM(answer="Gestreamte Antwort")
    chunks = []
    with patch.object(jarvis, "has_domain", return_value=False), \
         patch.object(jarvis, "looks_like_calendar_query", return_value=False), \
         patch.object(jarvis, "maybe_ask_domain_clarification", return_value=None), \
         patch.object(jarvis, "should_use_web_search", return_value=False), \
         patch.object(jarvis, "ensure_cloud_llm_permission", return_value=None), \
         patch.object(jarvis, "execute_promised_action_if_possible", return_value=None), \
         patch.object(jarvis, "is_gemini_available", return_value=False):
        result = jarvis.answer_message(
            "wie geht es dir", memory, llm, {}, workers=workers, on_llm_chunk=chunks.append
        )

    assert result.text == "Gestreamte Antwort"
    # Chunks kommen absichtlich NICHT mehr live waehrend ask_stream() an (siehe
    # answer_message()-Kommentar zu Codex-Adversarial-Review 2026-08-23), sondern
    # erst danach, wortweise, auf Basis des bereits sicherheitsgeprueften Texts -
    # geprueft wird hier deshalb nur, dass der vollstaendige Text ankommt, nicht
    # die exakte Fragmentierung.
    assert "".join(chunks) == "Gestreamte Antwort"
