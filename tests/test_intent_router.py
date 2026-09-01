"""Tests fuer core/intent_router.py: die zentrale strukturierte Entscheidung, die die
alte ~30-stufige Regex-/Fuzzy-Keyword-Kaskade in jarvis.py::answer_message() ersetzt
(Plan "Jarvis-Intent-Router 2.0", 2026-09-02)."""

from unittest.mock import MagicMock

from core.intent_router import (
    RouterDecision,
    decide,
    describe_pending_action,
    parse_router_decision,
)


def test_parse_router_decision_defaults_unknown_type_to_chat():
    decision = parse_router_decision({"response_type": "irgendwas_unbekanntes"})
    assert decision.response_type == "chat"


def test_parse_router_decision_reads_all_fields():
    data = {
        "response_type": "capability_call",
        "capability": "calendar",
        "reasoning": "Nutzer fragt nach Terminen.",
    }
    decision = parse_router_decision(data)
    assert decision.response_type == "capability_call"
    assert decision.capability == "calendar"
    assert decision.reasoning == "Nutzer fragt nach Terminen."
    assert decision.is_capability_call is True
    assert decision.is_chat is False


def test_decision_type_properties():
    assert RouterDecision(response_type="chat").is_chat
    assert RouterDecision(response_type="capability_call").is_capability_call
    assert RouterDecision(response_type="confirm_pending").is_confirm
    assert RouterDecision(response_type="cancel_pending").is_cancel


def test_describe_pending_action_reports_none_when_nothing_open():
    memory = MagicMock()
    memory.get.return_value = {}
    assert describe_pending_action(memory) == "Es gibt gerade keinen offenen Vorschlag."


def test_describe_pending_action_surfaces_open_proposal_text():
    memory = MagicMock()
    memory.get.return_value = {
        "settings": {
            "pending_calendar_create": {"confirm_prompt": "Soll ich den Termin anlegen?"},
        }
    }
    # memory.get("settings") -> das obige Dict direkt (MagicMock.get ignoriert den Key-Arg)
    memory.get.return_value = {"pending_calendar_create": {"confirm_prompt": "Soll ich den Termin anlegen?"}}

    text = describe_pending_action(memory)

    assert "offenen, noch unbeantworteten Vorschlag" in text
    assert "Soll ich den Termin anlegen?" in text


def test_decide_appends_current_question_when_not_already_the_last_history_entry():
    """Live-Bug (2026-09-02): _routing_history() liefert reine VORGESCHICHTE, nicht
    zwangslaeufig die aktuelle Frage. Ohne explizites Anhaengen sah das Modell "Welche
    Termine habe ich heute?" nie und beantwortete stattdessen die letzte Verlaufs-
    Nachricht - hier reproduziert mit unabhaengiger Alt-Historie."""
    llm = MagicMock()
    llm.ask_structured.return_value = {"response_type": "chat"}
    memory = MagicMock()
    memory.get.return_value = {}

    decide(
        llm,
        memory=memory,
        question="Welche Termine habe ich heute?",
        messages=[{"role": "user", "content": "wie geht es dir"}, {"role": "assistant", "content": "Gut, danke."}],
    )

    sent_messages = llm.ask_structured.call_args[0][0]
    assert sent_messages[-1] == {"role": "user", "content": "Welche Termine habe ich heute?"}


def test_decide_does_not_duplicate_question_already_at_end_of_history():
    llm = MagicMock()
    llm.ask_structured.return_value = {"response_type": "chat"}
    memory = MagicMock()
    memory.get.return_value = {}

    decide(
        llm,
        memory=memory,
        question="hallo",
        messages=[{"role": "user", "content": "hallo"}],
    )

    sent_messages = llm.ask_structured.call_args[0][0]
    assert sent_messages.count({"role": "user", "content": "hallo"}) == 1


def test_decide_falls_back_to_chat_when_llm_raises():
    llm = MagicMock()
    llm.ask_structured.side_effect = RuntimeError("kaputt")
    memory = MagicMock()
    memory.get.return_value = {}

    decision = decide(llm, memory=memory, question="hallo", messages=[{"role": "user", "content": "hallo"}])

    assert decision.response_type == "chat"
    assert decision.chat_reply == ""


def test_decide_returns_parsed_capability_call():
    llm = MagicMock()
    llm.ask_structured.return_value = {"response_type": "capability_call", "capability": "music"}
    memory = MagicMock()
    memory.get.return_value = {}

    decision = decide(llm, memory=memory, question="spiel musik", messages=[])

    assert decision.response_type == "capability_call"
    assert decision.capability == "music"


def test_decide_prepends_router_system_prompt_and_drops_caller_system_message():
    llm = MagicMock()
    llm.ask_structured.return_value = {"response_type": "chat"}
    memory = MagicMock()
    memory.get.return_value = {}

    decide(
        llm,
        memory=memory,
        question="hallo",
        messages=[{"role": "system", "content": "alter system prompt"}, {"role": "user", "content": "hallo"}],
    )

    sent_messages = llm.ask_structured.call_args[0][0]
    assert sent_messages[0]["role"] == "system"
    assert "alter system prompt" not in sent_messages[0]["content"]
    assert sent_messages[-1] == {"role": "user", "content": "hallo"}
