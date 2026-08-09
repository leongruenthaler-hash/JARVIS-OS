"""Unit tests for the Phase B memory fact schema (app/memory.py).

Uses Memory(base_path=tmp_path) so tests never touch the real user's
memory/ directory - no JARVIS_DATA_DIR juggling needed.
"""

from datetime import datetime, timedelta

import pytest

from memory import Memory, SENSITIVITY_LEVELS, is_fact_expired


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_remember_fact_has_full_phase_b_schema(memory):
    memory.remember_fact("Leon mag Kaffee ohne Zucker.", category="Vorlieben", source="manual")

    facts = memory.all_facts()
    assert len(facts) == 1
    fact = facts[0]

    for field in (
        "id", "content", "category", "scope", "source_type", "source_reference",
        "created_at", "updated_at", "last_used_at", "confidence", "sensitivity",
        "retention_policy", "expires_at", "user_confirmed", "status", "tags",
        "related_entities",
    ):
        assert field in fact, f"missing field: {field}"

    # remember_fact() normalizes content via normalize_memory_text(), which strips
    # trailing punctuation - not a bug, just how facts get stored.
    assert fact["content"] == "Leon mag Kaffee ohne Zucker"
    assert fact["category"] == "Vorlieben"
    assert fact["source_type"] == "manual"
    assert fact["status"] == "confirmed"
    assert fact["sensitivity"] == "normal"
    assert fact["id"]


def test_remember_fact_accepts_sensitivity_and_retention(memory):
    memory.remember_fact(
        "Leon hat eine Katze namens Mimi.",
        category="Profil",
        source="auto",
        sensitivity="personal",
        retention_policy="expires",
        expires_at=(datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
        tags=["haustier"],
    )
    fact = memory.all_facts()[0]
    assert fact["sensitivity"] == "personal"
    assert fact["retention_policy"] == "expires"
    assert fact["tags"] == ["haustier"]
    assert not is_fact_expired(fact)


def test_invalid_sensitivity_falls_back_to_normal(memory):
    memory.remember_fact("Test.", sensitivity="not-a-real-level")
    fact = memory.all_facts()[0]
    assert fact["sensitivity"] == "normal"
    assert fact["sensitivity"] in SENSITIVITY_LEVELS


def test_legacy_entry_without_phase_b_fields_is_migrated_lazily(memory):
    # Simulates a fact written by a pre-Phase-B Memory Engine: only the old fields.
    memory.data["long_memory"]["facts"] = [
        {
            "content": "Alte Erinnerung ohne neue Felder.",
            "created_at": "2026-01-01T10:00:00",
            "updated_at": "2026-01-01T10:00:00",
            "category": "facts",
            "source": "manual",
        }
    ]

    facts = memory.all_facts()
    assert len(facts) == 1
    fact = facts[0]
    assert fact["id"]
    assert fact["status"] == "confirmed"
    assert fact["user_confirmed"] is True
    assert fact["sensitivity"] == "normal"
    assert fact["source_type"] == "manual"  # derived from legacy "source" field


def test_expired_fact_excluded_by_default_but_visible_on_request(memory):
    memory.remember_fact(
        "Läuft ab.",
        retention_policy="expires",
        expires_at=(datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
    )
    memory.remember_fact("Bleibt.")

    active = memory.all_facts()
    assert len(active) == 1
    assert active[0]["content"] == "Bleibt"

    everything = memory.all_facts(include_expired=True)
    assert len(everything) == 2


def test_rejected_fact_excluded_by_default(memory):
    memory.remember_fact("Wird abgelehnt.")
    fact_id = memory.all_facts()[0]["id"]

    assert memory.reject_fact(fact_id) is True
    assert memory.all_facts() == []
    assert len(memory.all_facts(include_rejected=True)) == 1


def test_confirm_fact_sets_status_and_user_confirmed(memory):
    memory.remember_fact("Zu bestaetigen.", status="pending_confirmation")
    fact_id = memory.all_facts(include_expired=True, include_rejected=True)[0]["id"]

    assert memory.confirm_fact(fact_id) is True
    fact = memory.get_fact_by_id(fact_id)
    assert fact["status"] == "confirmed"
    assert fact["user_confirmed"] is True


def test_update_fact_only_touches_editable_fields(memory):
    memory.remember_fact("Original.", category="facts")
    fact_id = memory.all_facts()[0]["id"]
    original_created_at = memory.get_fact_by_id(fact_id)["created_at"]

    ok = memory.update_fact(fact_id, content="Geaendert.", category="Profil", not_a_real_field="x")
    assert ok is True

    fact = memory.get_fact_by_id(fact_id)
    assert fact["content"] == "Geaendert."
    assert fact["category"] == "Profil"
    assert "not_a_real_field" not in fact
    assert fact["created_at"] == original_created_at  # created_at is immutable


def test_delete_fact_by_id(memory):
    memory.remember_fact("Loeschbar.")
    fact_id = memory.all_facts()[0]["id"]

    assert memory.delete_fact_by_id(fact_id) is True
    assert memory.all_facts() == []
    assert memory.delete_fact_by_id(fact_id) is False  # already gone


def test_touch_fact_sets_last_used_at(memory):
    memory.remember_fact("Wird benutzt.")
    fact_id = memory.all_facts()[0]["id"]
    assert memory.get_fact_by_id(fact_id)["last_used_at"] is None

    memory.touch_fact(fact_id)
    assert memory.get_fact_by_id(fact_id)["last_used_at"] is not None


def test_upsert_fact_updates_existing_without_losing_id(memory):
    memory.upsert_fact("Leon nutzt VS Code.", category="Vorlieben", source="auto")
    original_id = memory.all_facts()[0]["id"]

    result = memory.upsert_fact("Leon nutzt VS Code.", category="Vorlieben", source="auto")
    assert result == "updated"
    assert memory.all_facts()[0]["id"] == original_id
    assert len(memory.all_facts()) == 1


# --- JarvisMemorySystem: Dual-Instance-Bug (2026-08-09) ---------------------
#
# JarvisMemorySystem(memory.base_path) hat frueher IMMER eine neue, eigene
# Memory-Instanz gebaut, selbst wenn der Aufrufer schon eine lebendige Instanz
# hatte. Memory laedt seinen Zustand nur einmal bei __init__ in den
# Prozessspeicher - zwei getrennte Instanzen auf demselben Pfad laufen dadurch
# auseinander: neu gespeicherte Fakten waren fuer die Instanz des Aufrufers
# unsichtbar (lokal_server.py's langlebiges self.memory, das auch
# /api/memory/facts bedient), bis der Prozess neu gestartet wurde. Ein
# anschliessendes memory.trim_facts() auf der veralteten Instanz hat die Datei
# danach sogar mit dem alten, leeren Stand ueberschrieben - echter Datenverlust,
# nicht nur Unsichtbarkeit. Live auf dem echten Mac so gefunden: "Gedaechtnis"
# zeigte dauerhaft nichts an.


def test_jarvis_memory_system_accepts_existing_memory_instance(memory):
    from core.memory_system import JarvisMemorySystem

    memory_system = JarvisMemorySystem(memory)

    assert memory_system.memory is memory


def test_jarvis_memory_system_writes_are_visible_on_the_passed_in_instance(memory):
    from core.memory_system import JarvisMemorySystem

    memory_system = JarvisMemorySystem(memory)
    result = memory_system.maybe_remember("Leon mag kurze Antworten.", category="Vorlieben", source="auto")

    assert result == "created"
    # Kernpunkt des Bugfixes: derselbe `memory`-Fixture-Aufrufer, NICHT eine
    # versteckte zweite Instanz, sieht den Fakt sofort.
    assert any(f["content"] == "Leon mag kurze Antworten" for f in memory.all_facts())


def test_auto_update_memory_fact_survives_trim_facts_call(monkeypatch, memory):
    import jarvis

    monkeypatch.setattr(jarvis, "AUTO_MEMORY_ENABLED", True)
    monkeypatch.setattr(jarvis, "has_permission", lambda permission: True)

    notes = jarvis.auto_update_memory(memory, "Ich mag es, wenn du kurze Antworten gibst.")

    assert notes  # "gespeichert unter ..."
    # Regressionsfall: trim_facts() lief bisher auf einer veralteten Kopie und hat
    # die Datei mit dem alten (leeren) Stand ueberschrieben - der gerade
    # gespeicherte Fakt verschwand wieder, sofort nach dem Speichern.
    facts = memory.all_facts(include_expired=True, include_rejected=True)
    assert len(facts) == 1
    assert "mag" in facts[0]["content"]


def test_jarvis_memory_system_still_accepts_a_bare_path(tmp_path):
    from core.memory_system import JarvisMemorySystem

    memory_system = JarvisMemorySystem(tmp_path)

    assert memory_system.memory.base_path == tmp_path
