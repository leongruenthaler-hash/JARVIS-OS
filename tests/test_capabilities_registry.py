"""Tests fuer core/capabilities.py: die Registry, die dem neuen Intent-Router
(core/intent_router.py) sagt, welche Faehigkeiten es gibt - Teil des Umbaus weg von der
alten Regex-Kaskade (Plan "Jarvis-Intent-Router 2.0", 2026-09-02)."""

from core.capabilities import (
    CapabilityContext,
    all_capabilities,
    capability_catalog_text,
    get_capability,
    register_capability,
)


def test_register_and_get_capability_roundtrip():
    called = {}

    def handler(ctx: CapabilityContext):
        called["text"] = ctx.text
        return "Antwort"

    register_capability("test_cap_roundtrip", "Eine Test-Faehigkeit.", handler, mutates=True)
    cap = get_capability("test_cap_roundtrip")

    assert cap is not None
    assert cap.name == "test_cap_roundtrip"
    assert cap.mutates is True
    ctx = CapabilityContext(text="hallo", memory=None, llm=None, config={})
    assert cap.handler(ctx) == "Antwort"
    assert called["text"] == "hallo"


def test_get_capability_returns_none_for_unknown_name():
    assert get_capability("does_not_exist_xyz") is None


def test_capability_catalog_text_includes_registered_names_and_mutates_marker():
    register_capability("test_cap_catalog_a", "Beschreibung A.", lambda ctx: None, mutates=False)
    register_capability("test_cap_catalog_b", "Beschreibung B.", lambda ctx: None, mutates=True)

    text = capability_catalog_text()

    assert "test_cap_catalog_a: Beschreibung A." in text
    assert "test_cap_catalog_b: Beschreibung B." in text
    assert "verändert etwas" in text.split("test_cap_catalog_b")[1].split("\n")[0]


def test_all_capabilities_includes_the_real_jarvis_capabilities():
    # jarvis.py registriert beim Import ueber _register_all_capabilities() alle echten
    # Faehigkeiten (Kalender, Mail, Dateien, ...) - importiert wird hier nur, damit dieser
    # Test unabhaengig von der Importreihenfolge in anderen Testdateien zuverlaessig ist.
    import jarvis  # noqa: F401

    names = {cap.name for cap in all_capabilities()}
    for expected in ("calendar", "mail", "files", "notes", "music", "contacts"):
        assert expected in names
