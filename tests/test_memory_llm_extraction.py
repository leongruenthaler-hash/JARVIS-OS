"""Tests fuer die LLM-gestuetzte Gedaechtnis-Extraktion (bisher ungetestet, siehe
plans/2026-08-09-jarvis-gedaechtnis-llm-extraktion.md) - Auslöse-Filter
(looks_like_memory_candidate), Prompt-Aufbau, Antwort-Parsing, Sicherheits-Filter
und der End-to-End-Fluss in _run_llm_memory_extraction()."""

import pytest

import jarvis
from memory import Memory


# --- looks_like_memory_candidate: schaerferer Vorfilter ---------------------


@pytest.mark.parametrize(
    "text",
    [
        "Ich trinke morgens immer erst einen Kaffee",
        "Ich wohne seit letztem Jahr in Berlin",
        "Mein Lieblingsessen ist Pizza",
        "Ich arbeite als Softwareentwickler",
    ],
)
def test_looks_like_memory_candidate_true_for_statements(text):
    assert jarvis.looks_like_memory_candidate(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Kannst du mir kurz sagen, wie spät es ist?",
        "Was ist mein nächster Termin?",
        "Wie ist das Wetter heute?",
        "Sag mir bitte, ob ich neue Mails habe",
    ],
)
def test_looks_like_memory_candidate_false_for_questions_and_requests(text):
    assert jarvis.looks_like_memory_candidate(text) is False


def test_looks_like_memory_candidate_false_for_transient_event():
    assert jarvis.looks_like_memory_candidate("Ich habe versucht die Datei zu öffnen aber es hat nicht geklappt") is False


def test_looks_like_memory_candidate_false_for_command():
    assert jarvis.looks_like_memory_candidate("Erstelle mir eine Notiz über meinen Einkauf") is False


def test_looks_like_memory_candidate_false_for_short_text():
    assert jarvis.looks_like_memory_candidate("Ich bin da") is False


def test_looks_like_memory_candidate_false_for_bare_self_reference_without_verb():
    # "ich"/"mein" kommt vor, aber ohne ein passendes Aussage-Verb - kein plausibler
    # Fakt-Kandidat, sollte keinen LLM-Aufruf mehr ausloesen (vorher: loser Filter).
    assert jarvis.looks_like_memory_candidate("Also bei mir und meinem Nachbarn nebenan") is False


def test_looks_like_memory_candidate_true_for_durable_directive():
    # Durable-marker-Pfad (should_skip_auto_memory=False) bleibt unveraendert permissiv.
    assert jarvis.looks_like_memory_candidate("Ich möchte dass du mich immer siezt") is True


# --- _build_memory_extraction_messages ---------------------------------------


def test_build_memory_extraction_messages_contains_examples_and_user_text():
    messages = jarvis._build_memory_extraction_messages("Ich wohne in Hamburg", "Leon")
    assert messages[0]["role"] == "system"
    assert "Leon" in messages[0]["content"]
    assert "Beispiele" in messages[0]["content"]
    assert "has_fact" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "Ich wohne in Hamburg"}


# --- _parse_llm_fact_response --------------------------------------------------


def test_parse_llm_fact_response_true_with_fact():
    assert jarvis._parse_llm_fact_response('{"has_fact": true, "fact": "Leon wohnt in Hamburg."}') == "Leon wohnt in Hamburg."


def test_parse_llm_fact_response_false():
    assert jarvis._parse_llm_fact_response('{"has_fact": false, "fact": null}') is None


def test_parse_llm_fact_response_strips_markdown_fence():
    raw = '```json\n{"has_fact": true, "fact": "Leon mag Pizza."}\n```'
    assert jarvis._parse_llm_fact_response(raw) == "Leon mag Pizza."


def test_parse_llm_fact_response_recovers_json_with_leading_prose():
    # Live beim Testen aufgefallen: das kleine lokale Modell haelt sich trotz
    # Anweisung nicht immer an "nur JSON" und stellt manchmal einen Satz davor.
    raw = 'Hier ist meine Analyse: {"has_fact": true, "fact": "Leon wohnt in Berlin."}'
    assert jarvis._parse_llm_fact_response(raw) == "Leon wohnt in Berlin."


def test_parse_llm_fact_response_recovers_json_with_trailing_prose():
    raw = '{"has_fact": false, "fact": null} - das ist meine Einschätzung.'
    assert jarvis._parse_llm_fact_response(raw) is None


def test_parse_llm_fact_response_raises_on_invalid_json():
    with pytest.raises(ValueError):
        jarvis._parse_llm_fact_response("das ist kein JSON")


def test_parse_llm_fact_response_raises_on_missing_has_fact():
    with pytest.raises(ValueError):
        jarvis._parse_llm_fact_response('{"fact": "irgendwas"}')


def test_parse_llm_fact_response_raises_on_true_without_fact_text():
    with pytest.raises(ValueError):
        jarvis._parse_llm_fact_response('{"has_fact": true, "fact": ""}')


# --- _passes_sensitive_content_filter / _looks_self_referential ---------------


def test_passes_sensitive_content_filter_rejects_sensitive_marker():
    assert jarvis._passes_sensitive_content_filter("Leon hat eine Krankheit") is False


def test_passes_sensitive_content_filter_accepts_normal_fact():
    assert jarvis._passes_sensitive_content_filter("Leon wohnt in Hamburg.") is True


def test_looks_self_referential_true():
    assert jarvis._looks_self_referential("Leon wohnt in Hamburg.", "Leon") is True


def test_looks_self_referential_false_for_third_party():
    assert jarvis._looks_self_referential("Sein Bruder wohnt in Hamburg.", "Leon") is False


# --- _run_llm_memory_extraction: End-to-End ------------------------------------


class _FakeLLM:
    def __init__(self, response: str):
        self._response = response

    def plan(self, messages, user_text=None, force_local=False):
        return None

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False):
        return self._response


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_run_llm_memory_extraction_stores_pending_confirmation(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _FakeLLM('{"has_fact": true, "fact": "Leon wohnt in Hamburg."}'))

    jarvis._run_llm_memory_extraction("Ich wohne in Hamburg", memory, "Leon")

    facts = memory.all_facts(include_expired=True, include_rejected=True)
    assert len(facts) == 1
    assert facts[0]["status"] == "pending_confirmation"
    assert facts[0]["source_type"] == "auto-llm"
    assert facts[0]["confidence"] == 0.7


def test_run_llm_memory_extraction_discards_no_fact(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _FakeLLM('{"has_fact": false, "fact": null}'))

    jarvis._run_llm_memory_extraction("Wie spät ist es?", memory, "Leon")

    assert memory.all_facts(include_expired=True, include_rejected=True) == []


def test_run_llm_memory_extraction_discards_third_party_fact(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _FakeLLM('{"has_fact": true, "fact": "Sein Bruder wohnt in Hamburg."}'))

    jarvis._run_llm_memory_extraction("Mein Bruder wohnt in Hamburg", memory, "Leon")

    assert memory.all_facts(include_expired=True, include_rejected=True) == []


def test_run_llm_memory_extraction_marks_sensitive_fact_confidential(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _FakeLLM('{"has_fact": true, "fact": "Leon hat eine Diagnose bekommen."}'))

    jarvis._run_llm_memory_extraction("Ich habe eine Diagnose bekommen", memory, "Leon")

    facts = memory.all_facts(include_expired=True, include_rejected=True)
    assert len(facts) == 1
    assert facts[0]["sensitivity"] == "confidential"
    assert facts[0]["status"] == "pending_confirmation"


def test_run_llm_memory_extraction_swallows_malformed_response(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _FakeLLM("kein json hier"))

    jarvis._run_llm_memory_extraction("Ich wohne in Hamburg", memory, "Leon")

    assert memory.all_facts(include_expired=True, include_rejected=True) == []


def test_run_llm_memory_extraction_swallows_llm_exception(monkeypatch, memory):
    class _BrokenLLM:
        def plan(self, *args, **kwargs):
            raise RuntimeError("kein Modell erreichbar")

    monkeypatch.setattr(jarvis, "LLMClient", lambda config: _BrokenLLM())

    jarvis._run_llm_memory_extraction("Ich wohne in Hamburg", memory, "Leon")

    assert memory.all_facts(include_expired=True, include_rejected=True) == []
