"""Regressionstest fuer core/personality_manager.py::humor_instruction(): Nutzerwunsch
2026-09-02 - bei humor_level=100 fuehlte sich Jarvis nicht mehr so durchgaengig witzig
an wie in der Anfangsphase. Die alte Formulierung fuer den obersten Level-Bereich
(71-100) war noch relativ zurueckhaltend ("in fast jeder Antwort... such aktiv nach
Gelegenheiten"). Eine neue, deutlich staerkere Maximalstufe fuer >90 fordert explizit
eine Pointe in so gut wie jedem Satz, statt nur bei besonders passenden Gelegenheiten."""

from core.personality_manager import humor_instruction


def test_level_100_uses_the_maximum_escalation_tier():
    text = humor_instruction(100)
    assert "Maximalstufe" in text
    assert "so gut wie jeden Satz" in text


def test_level_91_also_uses_the_maximum_tier():
    assert "Maximalstufe" in humor_instruction(91)


def test_level_90_still_uses_the_previous_ausgepraegt_tier():
    text = humor_instruction(90)
    assert "Maximalstufe" not in text
    assert "sehr ausgepraegter Zug" in text


def test_maximum_tier_still_protects_critical_confirmation_questions():
    text = humor_instruction(100)
    assert "Ja/Nein-Frage muss glasklar bleiben" in text


def test_low_level_still_disables_humor():
    text = humor_instruction(10)
    assert "praktisch ausgeschaltet" in text
