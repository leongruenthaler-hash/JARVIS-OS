"""Test fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Begruessungs-Bug: "Hallo Jarvis" - die naheliegendste reale Formulierung,
Weckwort plus Gruss - matchte bisher keine der Kurzformeln in
handle_local_command(), nur das isolierte Wort "hallo" tat das. Siehe
docs/current-system-assessment.md, Abschnitt 41."""

import jarvis


def test_hallo_jarvis_triggers_warm_greeting():
    answer = jarvis.handle_local_command("Hallo Jarvis")
    assert answer is not None
    assert "Was liegt an" in answer


def test_bare_hallo_still_works():
    answer = jarvis.handle_local_command("Hallo")
    assert answer is not None
    assert "Was liegt an" in answer


def test_danke_jarvis_triggers_thanks_response():
    answer = jarvis.handle_local_command("Danke Jarvis")
    assert answer == "Gern. Höflichkeit ist eine seltene, aber wertvolle Ressource."


def test_jarvis_alone_still_returns_was_liegt_an():
    assert jarvis.handle_local_command("Jarvis") == "Was liegt an?"


def test_unrelated_sentence_containing_jarvis_not_swallowed():
    # "Jarvis" alleine am Rand darf keine völlig andere, laengere Anfrage kapern.
    assert jarvis.handle_local_command("Jarvis wie ist das Wetter heute") is None
