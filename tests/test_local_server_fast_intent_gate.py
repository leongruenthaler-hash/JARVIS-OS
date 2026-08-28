"""Regression fuer local_server.py::_answer_with_core(): route_fast_intent()
kennt nur den aktuellen Text, nicht den Gespraechs-Zustand
(pending_reservation_details) - eine Folgeantwort innerhalb einer laufenden
Reservierung wie "Welche Uhrzeiten waeren denn zur Verfuegung" enthaelt
keines der Reservierungs-Schluesselwoerter, matcht aber die Uhrzeit-
Heuristik in fast_intent_router.py. Live beobachtet 2026-08-28: Jarvis
antwortete faelschlich nur mit der aktuellen Uhrzeit, statt die offene
Reservierungs-Rueckfrage zu beantworten.

Nutzt bewusst das ECHTE jarvis.fast_intent_would_hijack_pending_reservation()
im fake_core (statt es zu stubben) - ein frueherer Fix beschraenkte den
Fast-Pfad blind auf "irgendeine Reservierung offen", was auch einen echten
Themenwechsel wie "Wie spaet ist es?" blockiert haette (Codex-Review
2026-08-28, Folgerunde) - siehe
test_fast_intent_still_runs_for_an_unrelated_topic_switch_during_reservation."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jarvis
import local_server
from memory import Memory


def _make_server(memory: Memory) -> local_server.JarvisLocalServer:
    server = local_server.JarvisLocalServer.__new__(local_server.JarvisLocalServer)
    server.memory = memory
    server.models = SimpleNamespace(active_model="phi4-mini")
    server.photo_worker = None
    server.mail_worker = None
    server.pending_mail_followup = False
    server.llm = None
    server.config = {}
    return server


def _fake_core(fast_intent_calls: list[str], dispatch_chain_calls: list[str]) -> SimpleNamespace:
    def fake_route_fast_intent(question: str) -> str:
        fast_intent_calls.append(question)
        return "Es ist jetzt 13:07 Uhr."

    def fake_answer_message(question, memory, llm, config, **kwargs):
        dispatch_chain_calls.append(question)
        return SimpleNamespace(
            text="Diese Zeiten sind noch frei: 18:00, 19:00.",
            provider="local",
            model="phi4-mini",
            pending_mail_followup=False,
        )

    return SimpleNamespace(
        is_end_command=lambda q: False,
        route_fast_intent=fake_route_fast_intent,
        # Bewusst die ECHTE Funktion, nicht gestubbt - siehe Modul-Docstring.
        fast_intent_would_hijack_pending_reservation=jarvis.fast_intent_would_hijack_pending_reservation,
        AnswerWorkers=lambda **kwargs: SimpleNamespace(photo_worker=None, mail_worker=None),
        answer_message=fake_answer_message,
        clean_ai_answer=lambda text: text,
    )


def test_fast_intent_is_skipped_for_a_plausible_reservation_continuation(tmp_path):
    memory = Memory(base_path=tmp_path)
    memory.set("settings", {"pending_reservation_details": {"accumulated_text": "x", "set_at": time.time()}})
    server = _make_server(memory)

    fast_intent_calls: list[str] = []
    dispatch_chain_calls: list[str] = []
    fake_core = _fake_core(fast_intent_calls, dispatch_chain_calls)
    server._core_module = lambda: fake_core
    server._clean_question = lambda text: text
    server._handle_fast_commands = lambda text: None
    server._handle_local_photo_vision_command = lambda text: None

    result = server._answer_with_core("Welche Uhrzeiten wären denn zur Verfügung")

    assert fast_intent_calls == []
    assert dispatch_chain_calls == ["Welche Uhrzeiten wären denn zur Verfügung"]
    assert result == "Diese Zeiten sind noch frei: 18:00, 19:00."


def test_fast_intent_still_runs_for_an_unrelated_topic_switch_during_reservation(tmp_path):
    # Regression: eine erste Fassung blockierte den Fast-Pfad bei JEDER
    # offenen Reservierung, auch fuer einen erkennbar unabhaengigen
    # Themenwechsel wie "Wie spaet ist es?" - handle_reservation_command()
    # haette diese Nachricht ohnehin verworfen (keine Fortsetzung), aber ohne
    # den Fast-Pfad ging die schnelle, deterministische Uhrzeit-Antwort
    # verloren (Codex-Review 2026-08-28, Folgerunde).
    memory = Memory(base_path=tmp_path)
    memory.set("settings", {"pending_reservation_details": {"accumulated_text": "x", "set_at": time.time()}})
    server = _make_server(memory)

    fast_intent_calls: list[str] = []
    dispatch_chain_calls: list[str] = []
    fake_core = _fake_core(fast_intent_calls, dispatch_chain_calls)
    server._core_module = lambda: fake_core
    server._clean_question = lambda text: text
    server._finalize_answer = lambda core, question, answer, **kwargs: answer

    result = server._answer_with_core("Wie spät ist es?")

    assert fast_intent_calls == ["Wie spät ist es?"]
    assert dispatch_chain_calls == []
    assert result == "Es ist jetzt 13:07 Uhr."


def test_fast_intent_still_runs_for_date_time_questions_that_merely_resemble_continuations(tmp_path):
    # Regression: eine erste Fassung nutzte die BREITE
    # _RESERVATION_CONTINUATION_RE (matcht schon bei jeder Ziffer/jedem
    # Wochentag/"uhr" als Teilstring) fuer diesen Gate - "Wie spaet ist es
    # morgen?" oder "Welcher Wochentag ist der 28.?" enthalten dieselben
    # Woerter wie eine echte Reservierungs-Fortsetzung und haetten den
    # Fast-Pfad faelschlich blockiert. Schwerwiegender als nur eine
    # verpasste Rueckfrage: "morgen" ist ein gueltiges Datums-Schluesselwort
    # und haette potenziell sogar als NEUE (falsche) Datumsangabe in die
    # laufende Reservierung aufgenommen werden koennen (Codex-Review
    # 2026-08-28, weitere Folgerunde).
    memory = Memory(base_path=tmp_path)
    memory.set("settings", {"pending_reservation_details": {"accumulated_text": "x", "set_at": time.time()}})
    server = _make_server(memory)

    for question in ("Wie spät ist es morgen?", "Welcher Wochentag ist der 28.?"):
        fast_intent_calls: list[str] = []
        dispatch_chain_calls: list[str] = []
        fake_core = _fake_core(fast_intent_calls, dispatch_chain_calls)
        server._core_module = lambda fc=fake_core: fc
        server._clean_question = lambda text: text
        server._finalize_answer = lambda core, question, answer, **kwargs: answer

        result = server._answer_with_core(question)

        assert fast_intent_calls == [question], question
        assert dispatch_chain_calls == [], question
        assert result == "Es ist jetzt 13:07 Uhr.", question


def test_fast_intent_still_runs_without_a_pending_reservation(tmp_path):
    memory = Memory(base_path=tmp_path)
    server = _make_server(memory)

    fast_intent_calls: list[str] = []
    dispatch_chain_calls: list[str] = []
    fake_core = _fake_core(fast_intent_calls, dispatch_chain_calls)
    server._core_module = lambda: fake_core
    server._clean_question = lambda text: text
    server._finalize_answer = lambda core, question, answer, **kwargs: answer

    result = server._answer_with_core("Wie spät ist es?")

    assert fast_intent_calls == ["Wie spät ist es?"]
    assert result == "Es ist jetzt 13:07 Uhr."


def test_fast_intent_still_runs_for_an_expired_pending_reservation(tmp_path):
    # Regression: eine bereits abgelaufene (TTL-ueberschrittene) Reservierung
    # zaehlte urspruenglich weiterhin als "offen" - eine Folgeantwort wie
    # "Welche Uhrzeiten gibt es?" haette den Fast-Pfad dadurch unnoetig
    # blockiert, obwohl handle_reservation_command() die abgelaufene
    # Reservierung ohnehin nur noch verwirft (Codex-Review 2026-08-28,
    # weitere Folgerunde).
    memory = Memory(base_path=tmp_path)
    memory.set(
        "settings",
        {
            "pending_reservation_details": {
                "accumulated_text": "x",
                "set_at": time.time() - jarvis.PENDING_RESERVATION_DETAILS_TTL_SECONDS - 10,
            }
        },
    )
    server = _make_server(memory)

    fast_intent_calls: list[str] = []
    dispatch_chain_calls: list[str] = []
    fake_core = _fake_core(fast_intent_calls, dispatch_chain_calls)
    server._core_module = lambda: fake_core
    server._clean_question = lambda text: text
    server._finalize_answer = lambda core, question, answer, **kwargs: answer

    result = server._answer_with_core("Welche Uhrzeiten gibt es?")

    assert fast_intent_calls == ["Welche Uhrzeiten gibt es?"]
    assert result == "Es ist jetzt 13:07 Uhr."


def test_cli_and_server_entry_points_both_use_the_shared_gate_function():
    # Regression: main() (CLI-Sprachschleife) und local_server.py (der
    # tatsaechliche Einstiegspunkt der App) riefen route_fast_intent()
    # urspruenglich unabhaengig voneinander auf - eine Reservierungs-
    # Sonderbehandlung in nur einem der beiden Pfade haette den Fehler
    # (Uhrzeit-Antwort statt Reservierungs-Fortsetzung) im jeweils anderen
    # weiterbestehen lassen. Beide nutzen jetzt dieselbe geteilte Funktion
    # (Codex-Review 2026-08-28, Folgerunde).
    import inspect

    jarvis_source = inspect.getsource(jarvis)
    assert "def fast_intent_would_hijack_pending_reservation(" in jarvis_source
    assert "fast_intent_would_hijack_pending_reservation(question, memory)" in jarvis_source

    server_source = inspect.getsource(local_server)
    assert "core.fast_intent_would_hijack_pending_reservation(question, memory)" in server_source
