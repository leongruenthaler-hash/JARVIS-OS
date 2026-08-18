"""Tests for the robuster Absichtserkennung
(plans/2026-08-08-jarvis-intelligenz-verbessern.md): Tippfehler-/Verhaspel-
Toleranz bei der Faehigkeits-Erkennung (Stufe 1, app/core/intent_matching.py +
app/jarvis.py::has_domain) und der LLM-Klassifikations-Rueckfrage als
Sicherheitsnetz (Stufe 2, app/jarvis.py).
"""

import pytest

from core.intent_matching import (
    fuzzy_word_match,
    has_domain_fuzzy,
    levenshtein_distance,
    normalize_umlauts,
)
from memory import Memory
import jarvis


# --- Stufe 1: core/intent_matching.py Bausteine ----------------------------


def test_normalize_umlauts_all_four_pairs():
    assert normalize_umlauts("grösse") == "groesse"
    assert normalize_umlauts("spät") == "spaet"
    assert normalize_umlauts("müde") == "muede"
    assert normalize_umlauts("schließen") == "schliessen"


def test_fuzzy_word_match_accepts_typo_but_rejects_unrelated_word():
    assert fuzzy_word_match("meil", ("mail",), max_distance=2) is True
    assert fuzzy_word_match("musik", ("mail",), max_distance=2) is False


def test_fuzzy_word_match_ignores_common_stopwords():
    # "mal" hat Editierdistanz 1 zu "mail" - darf trotzdem NIE als Mail-Anfrage
    # durchgehen, weil "mal" ein extrem haeufiges deutsches Fuellwort ist
    # (z.B. "spiel mal Musik").
    assert fuzzy_word_match("mal", ("mail",), max_distance=2) is False


def test_has_domain_fuzzy_multiword_terms_do_not_leak_stopword_fragments():
    # "bilder von" ist ein Mehrwort-Begriff - "von" darf daraus NICHT als
    # eigenstaendiger Fuzzy-Kandidat entstehen (siehe intent_matching.py-
    # Kommentar zu has_domain_fuzzy).
    assert has_domain_fuzzy("von", ("bilder von",)) is False
    assert has_domain_fuzzy("zeig mir bilder von rom", ("bilder von",)) is True


def test_has_domain_fuzzy_single_word_term_requires_word_boundary():
    assert has_domain_fuzzy("was siehst du auf meinem bildschirm", ("bild",)) is False
    assert has_domain_fuzzy("zeig mir das bild", ("bild",)) is True


def test_has_domain_fuzzy_multiword_term_still_uses_plain_substring():
    assert has_domain_fuzzy("kannst du das e mail machen", ("e mail",)) is True


def test_levenshtein_distance_basic():
    assert levenshtein_distance("mail", "mail") == 0
    assert levenshtein_distance("mail", "meil") == 1
    assert levenshtein_distance("", "mail") == 4


# --- Stufe 1: app/jarvis.py::has_domain Integration -------------------------


def test_has_domain_exact_match_still_works():
    assert jarvis.has_domain("öffne mail", "mail") is True
    assert jarvis.has_domain("ruf peter an", "contacts") is True


def test_has_domain_tolerates_typo():
    assert jarvis.has_domain("oeffne meil", "mail") is True


def test_has_domain_tolerates_missing_letter():
    assert jarvis.has_domain("zeig mir den klender", "calendar") is True


def test_has_domain_rejects_unrelated_text():
    assert jarvis.has_domain("wie ist das wetter heute", "mail") is False


def test_has_domain_does_not_false_positive_on_common_filler_word():
    # Regressionsfall aus diesem Gespraech: "mal" ist Distanz 1 zu "mail".
    assert jarvis.has_domain("spiel mal musik", "mail") is False
    assert jarvis.has_domain("spiel mal musik", "music") is True


def test_has_domain_existing_multiword_phrases_still_work():
    assert jarvis.has_domain("erinnere mich an den zahnarzt", "calendar") is True
    assert jarvis.has_domain("zeig mir bilder von rom", "photos") is True


def test_has_domain_single_word_term_no_longer_matches_as_substring_of_longer_word():
    # Regressionsfall aus dem Testlauf auf dem echten Mac: "bild" ist ein
    # Domaenen-Stichwort fuer "photos" und war zugleich ein Teilstring von
    # "bildschirm" - jede Bildschirm-Anfrage wurde dadurch faelschlich als
    # Fotos-Anfrage erkannt (hat sogar echte Fotos in einen Ordner kopiert statt
    # einen Screenshot zu machen). Einzelwort-Begriffe zaehlen jetzt nur noch als
    # eigenstaendiges Wort.
    assert jarvis.has_domain("was siehst du auf meinem bildschirm", "photos") is False
    assert jarvis.has_domain("was siehst du auf meinem bildschirm", "screen") is True
    assert jarvis.has_domain("mach einen screenshot von meinem bildschirm", "photos") is False


def test_has_domain_single_word_term_still_matches_as_standalone_word():
    assert jarvis.has_domain("zeig mir das bild", "photos") is True
    assert jarvis.has_domain("zeig mir meine bilder", "photos") is True


# --- Stufe 2: LLM-Klassifikation als Sicherheitsnetz ------------------------


class _FakeLLM:
    """Minimaler Ersatz fuer LLMClient.ask() - kein echter Modellaufruf."""

    def __init__(self, response: str):
        self._response = response
        self.last_messages = None

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None):
        self.last_messages = messages
        return self._response


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_classify_domain_via_llm_parses_single_label():
    llm = _FakeLLM("mail")
    assert jarvis.classify_domain_via_llm(llm, "irgendwas unklares") == ["mail"]


def test_classify_domain_via_llm_parses_two_labels():
    llm = _FakeLLM("mail, calendar")
    assert jarvis.classify_domain_via_llm(llm, "irgendwas unklares") == ["mail", "calendar"]


def test_classify_domain_via_llm_none_label_returns_empty():
    llm = _FakeLLM("keine")
    assert jarvis.classify_domain_via_llm(llm, "wie geht es dir") == []


def test_classify_domain_via_llm_prompt_contains_self_statement_example():
    # Regressionstest fuer den Live-Bug: eine reine Selbstauskunft ("Ich lebe seit
    # 18 Jahren in Amberg") wurde faelschlich als mail/calendar klassifiziert. Der
    # Prompt muss ein explizites Gegenbeispiel enthalten (gleiche Haertungs-Technik
    # wie beim News-Baustein).
    llm = _FakeLLM("keine")
    jarvis.classify_domain_via_llm(llm, "Ich lebe schon seit 18 Jahren in Amberg in Deutschland")
    system_content = llm.last_messages[0]["content"]
    assert "Amberg" in system_content
    assert "keine" in system_content


def test_classify_domain_via_llm_swallows_exceptions():
    class _BrokenLLM:
        def ask(self, *args, **kwargs):
            raise RuntimeError("Ollama nicht erreichbar")

    assert jarvis.classify_domain_via_llm(_BrokenLLM(), "irgendwas") == []


def test_maybe_ask_domain_clarification_stores_pending_state_and_asks(memory):
    # Seit plans/2026-08-16-jarvis-stufe2-klassifikation-direkt-beantworten.md
    # versucht eine eindeutige Ein-Domaenen-Klassifikation zuerst eine direkte
    # Antwort (siehe test_stage2_direct_dispatch.py) - dieser Test isoliert
    # bewusst weiterhin nur das reine Rueckfrage-Verhalten selbst, indem er das
    # neue Verhalten explizit abschaltet.
    llm = _FakeLLM("mail")
    question = "kannst du das für mich checken"

    answer = jarvis.maybe_ask_domain_clarification(
        llm, memory, question, config={"stage2_direct_dispatch_enabled": False}
    )

    assert answer is not None
    assert "Mail" in answer or "mail" in answer.lower()

    settings = memory.get("settings") or {}
    pending = settings.get("pending_domain_clarification")
    assert isinstance(pending, dict)
    assert pending["domains"] == ["mail"]
    assert pending["question"] == question


def test_maybe_ask_domain_clarification_returns_none_when_llm_finds_nothing(memory):
    llm = _FakeLLM("keine")
    assert jarvis.maybe_ask_domain_clarification(llm, memory, "wie geht's dir") is None
    settings = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings


def test_pending_domain_clarification_flow_cancel(memory):
    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": ["mail"], "question": "check das mal"}
    memory.set("settings", settings)

    answer = jarvis.handle_pending_domain_clarification_flow(memory, "nein danke")

    assert answer is not None
    settings_after = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings_after


def test_pending_domain_clarification_flow_unrelated_reply_falls_through(memory):
    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": ["mail", "calendar"], "question": "check das mal"}
    memory.set("settings", settings)

    # Weder Bestaetigung noch erkennbare Domaene in der Antwort - Flow gibt None
    # zurueck (normal weiterverarbeiten), raet aber nicht auf gut Glueck.
    answer = jarvis.handle_pending_domain_clarification_flow(memory, "wie ist das wetter heute")

    assert answer is None
    settings_after = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings_after


def test_pending_domain_clarification_flow_has_no_pending_state_returns_none(memory):
    assert jarvis.handle_pending_domain_clarification_flow(memory, "ja") is None
