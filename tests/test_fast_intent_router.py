from __future__ import annotations

import pytest

from fast_intent_router import FastIntentRouter


@pytest.mark.parametrize(
    "text",
    [
        "Reserviere einen Tisch bei Hans im Glück morgen um 19 Uhr für 2 Personen",
        "Tisch reservieren für morgen 19 Uhr",
        "Ich brauche eine Reservierung für 19 Uhr",
        "Ich möchte einen Tisch buchen, morgen um 19 Uhr",
        "Reserviere mir einen Tisch für 19 Uhr",
    ],
)
def test_reservation_requests_with_time_are_not_swallowed_by_time_query(text):
    # Regression: eine Reservierungs-Anfrage mit Uhrzeit ("...19 Uhr...") wurde
    # vom Zeit-Fast-Intent abgefangen und faelschlich nur mit der aktuellen
    # Uhrzeit beantwortet, statt die eigentliche Dispatch-Kette
    # (core.answer_message -> handle_reservation_command) zu erreichen - live
    # beobachtet 2026-08-27. Deckt alle fuenf Trigger-Phrasen aus
    # DOMAIN_TERMS["reservation"] (app/jarvis.py) ab, nicht nur eine - eine
    # erste Fassung dieses Fixes deckte nur "reservier(ung)" ab und liess
    # "tisch buchen" weiterhin durchfallen (Codex-Review 2026-08-27).
    router = FastIntentRouter()
    assert router.route(text) is None


def test_plain_time_query_still_handled_fast():
    router = FastIntentRouter()
    decision = router.route("Wie spät ist es?")
    assert decision is not None
    assert decision.intent == "show_time"


def test_calendar_entry_with_time_still_not_swallowed():
    router = FastIntentRouter()
    decision = router.route("Ich hab heute um 9 Uhr Zahnarzt, trag das bitte ein.")
    assert decision is None
