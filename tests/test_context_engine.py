"""Unit tests for the Context Engine (app/core/context_engine.py, Phase B).

Covers the three things build_memory_summary() (the old approach) couldn't do:
relevance-aware selection, a character budget, and Context Pack filtering.
"""

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from memory import Memory  # noqa: E402
from context_engine import ContextEngine, active_context_pack  # noqa: E402


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_relevant_fact_beats_more_recent_irrelevant_fact(memory):
    memory.remember_fact("Leon trinkt Kaffee ohne Zucker.", category="Vorlieben")
    memory.remember_fact("Leon nutzt Xcode fuer die App.", category="Organisation")

    engine = ContextEngine(max_chars=1000, max_facts=5)
    selected = engine.select_facts(memory, "Was trinkt Leon gerne?", touch=False)

    assert selected[0]["content"].startswith("Leon trinkt Kaffee")


def test_no_query_overlap_falls_back_to_recency(memory):
    memory.remember_fact("Erste Tatsache", category="facts")
    memory.remember_fact("Zweite Tatsache", category="facts")
    # remember_fact() timestamps at second resolution, so two facts created in the
    # same test tick would otherwise tie - force a real recency difference instead
    # of relying on wall-clock timing.
    facts = memory.data["long_memory"]["facts"]
    facts[0]["updated_at"] = "2026-01-01T10:00:00"
    facts[1]["updated_at"] = "2026-01-02T10:00:00"

    engine = ContextEngine(max_chars=1000, max_facts=5)
    selected = engine.select_facts(memory, "Wie ist das Wetter heute?", touch=False)

    # Zero keyword overlap for either fact -> most recently updated wins, matching
    # the old build_memory_summary()'s recency-only behaviour as a graceful fallback.
    assert selected[0]["content"] == "Zweite Tatsache"


def test_char_budget_is_respected(memory):
    long_fact = "A" * 400
    memory.remember_fact(long_fact, category="facts")
    memory.remember_fact("B" * 400, category="facts")

    engine = ContextEngine(max_chars=500, max_facts=10)
    selected = engine.select_facts(memory, "", touch=False)

    # Both facts together (800 chars) exceed the 500-char budget - only one fits.
    assert len(selected) == 1


def test_max_facts_cap_is_respected(memory):
    for index in range(5):
        memory.remember_fact(f"Fakt Nummer {index}.", category="facts")

    engine = ContextEngine(max_chars=10_000, max_facts=2)
    selected = engine.select_facts(memory, "", touch=False)
    assert len(selected) == 2


def test_pending_confirmation_facts_are_never_selected(memory):
    memory.remember_fact("Noch nicht bestaetigt", status="pending_confirmation")
    memory.remember_fact("Bestaetigt", status="confirmed")

    engine = ContextEngine()
    selected = engine.select_facts(memory, "", touch=False)

    contents = [f["content"] for f in selected]
    assert "Bestaetigt" in contents
    assert "Noch nicht bestaetigt" not in contents


def test_context_pack_filters_by_category(memory):
    memory.remember_fact("Persoenliche Vorliebe", category="Vorlieben")
    memory.remember_fact("Projekt-Notiz", category="Organisation")

    engine = ContextEngine()
    pack = {"categories": ["Vorlieben"], "tags": []}
    selected = engine.select_facts(memory, "", context_pack=pack, touch=False)

    contents = [f["content"] for f in selected]
    assert contents == ["Persoenliche Vorliebe"]


def test_context_pack_filters_by_tag(memory):
    memory.remember_fact("Getaggt", category="facts", tags=["jarvis-projekt"])
    memory.remember_fact("Nicht getaggt", category="facts")

    engine = ContextEngine()
    pack = {"categories": [], "tags": ["jarvis-projekt"]}
    selected = engine.select_facts(memory, "", context_pack=pack, touch=False)

    contents = [f["content"] for f in selected]
    assert contents == ["Getaggt"]


def test_touch_marks_selected_facts_as_used(memory):
    memory.remember_fact("Wird verwendet.")
    fact_id = memory.all_facts()[0]["id"]
    assert memory.get_fact_by_id(fact_id)["last_used_at"] is None

    engine = ContextEngine()
    engine.select_facts(memory, "Wird verwendet.", touch=True)

    assert memory.get_fact_by_id(fact_id)["last_used_at"] is not None


def test_build_memory_summary_returns_placeholder_when_empty(memory):
    engine = ContextEngine()
    summary = engine.build_memory_summary(memory, "irgendeine Frage", touch=False)
    assert summary == "Keine wichtigen Langzeitnotizen."


def test_active_context_pack_resolves_from_config():
    config = {
        "active_context_pack": "persoenlich",
        "context_packs": {"persoenlich": {"categories": ["Profil"], "tags": []}},
    }
    pack = active_context_pack(config)
    assert pack == {"categories": ["Profil"], "tags": []}


def test_active_context_pack_none_when_not_set():
    assert active_context_pack({}) is None
    assert active_context_pack({"active_context_pack": "does-not-exist", "context_packs": {}}) is None
