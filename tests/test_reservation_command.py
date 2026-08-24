from __future__ import annotations

from unittest.mock import patch

import pytest

import jarvis
from memory import Memory
from model_router import ModelRoute
from permission_manager import PermissionManager


@pytest.fixture(autouse=True)
def _run_push_thread_synchronously(monkeypatch):
    # handle_reservation_command() feuert send_push() in einem Hintergrund-Thread
    # (siehe Kommentar dort) statt den Live-Chat-Pfad auf ntfy warten zu lassen -
    # in Tests soll der Seiteneffekt trotzdem deterministisch VOR der Assertion
    # passiert sein, deshalb hier synchron statt in einem echten Thread ausfuehren.
    class _SynchronousThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(jarvis.threading, "Thread", _SynchronousThread)


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def _remember_restaurant(memory: Memory) -> None:
    memory.remember_fact(
        "Restaurant Hans im Glück: https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551",
        category="facts",
    )


class _FakeLLM:
    """Minimaler LLM-Stub fuer answer_message() - wird in diesem Testfall nie
    tatsaechlich befragt, weil handle_reservation_command() vorher greift oder
    der Berechtigungs-Check die Kette abbricht."""

    def plan(self, messages, user_text=None, force_local=False):
        return ModelRoute(
            provider="ollama", model="phi4-mini", max_output_tokens=160, num_ctx=1024,
            temperature=0.3, recent_context_limit=6, compact_prompt=False, stream=False, mode="performance",
        )

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False):
        return "Chat-Antwort"


def test_revoked_permission_blocks_pending_reservation_followup(memory, tmp_path, monkeypatch):
    # Regression: has_domain(question, "reservation") matcht eine kurze
    # Folgeantwort wie "19 Uhr" nicht - der Berechtigungs-Check am Dispatch-
    # Aufrufer war urspruenglich daran gekoppelt und wurde deshalb fuer
    # Folgeantworten komplett uebersprungen. Ein zwischenzeitlicher
    # Berechtigungsentzug waehrend eines laufenden Reservierungs-Dialogs haette
    # so unbemerkt durchgehen koennen (Codex-Review 2026-08-23).
    monkeypatch.setattr(jarvis, "PermissionManager", lambda base_path=None: PermissionManager(base_path=tmp_path))
    PermissionManager(base_path=tmp_path).grant("reservation", source="test_setup")

    _remember_restaurant(memory)
    workers = jarvis.AnswerWorkers()
    llm = _FakeLLM()

    first = jarvis.answer_message("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory, llm, {}, workers=workers)
    assert "personen" in first.text.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    PermissionManager(base_path=tmp_path).revoke("reservation", source="test_setup")

    second = jarvis.answer_message("2", memory, llm, {}, workers=workers)

    assert "reservation" in second.text.lower() or "zustimmung" in second.text.lower()
    assert memory.get("settings").get("pending_reservation_open") is None


def test_revoked_permission_blocks_pending_confirmation_at_execute_time(memory, tmp_path, monkeypatch):
    # Regression: handle_pending_action_flow() (bearbeitet "ja"/"nein") laeuft
    # in der Dispatch-Kette VOR dem regulaeren Berechtigungs-Check - ein
    # Entzug NACH dem Vorschlag, aber VOR der "ja"-Bestaetigung, wurde bisher
    # beim Ausfuehren gar nicht mehr geprueft und haette TheFork trotzdem
    # geoeffnet (Codex-Review 2026-08-23).
    monkeypatch.setattr(jarvis, "PermissionManager", lambda base_path=None: PermissionManager(base_path=tmp_path))
    PermissionManager(base_path=tmp_path).grant("reservation", source="test_setup")

    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True):
        jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen um 19 Uhr für 2 Personen", memory=memory
        )
    assert memory.get("settings").get("pending_reservation_open") is not None

    PermissionManager(base_path=tmp_path).revoke("reservation", source="test_setup")

    with patch("subprocess.run") as run:
        result = jarvis.handle_pending_action_flow(memory, "ja")

    run.assert_not_called()  # darf TheFork nicht mehr oeffnen, sobald die Berechtigung weg ist
    assert "entzogen" in result.lower()
    assert memory.get("settings").get("pending_reservation_open") is None


def test_pasted_thefork_link_gets_remembered_instead_of_looping(memory):
    # Regression: die Rueckfrage versprach "schick mir den TheFork-Link, dann
    # merke ich ihn mir", aber nichts hat den Link je gespeichert - eine
    # Antwort mit dem Link haette die Frage endlos wiederholt (Codex-Review
    # 2026-08-23).
    first = jarvis.handle_reservation_command("ich möchte einen tisch reservieren", memory=memory)
    assert "restaurant" in first.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    second = jarvis.handle_reservation_command(
        "https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551", memory=memory
    )
    # Restaurant jetzt bekannt, aber Datum/Uhrzeit/Personenzahl fehlen noch -
    # keine Endlosschleife bei derselben Frage mehr.
    assert "restaurant" not in second.lower() or "tag" in second.lower() or "uhrzeit" in second.lower()
    facts = memory.search_facts("Restaurant")
    assert any("hans-im-gluck-burgergrill-bar-amberg-spitalkirche" in f.get("content", "") for f in facts)


def test_hint_selects_correct_restaurant_among_several(memory):
    # Regression: der Vergleich war urspruenglich verkehrt herum und wurde von
    # einem einzigen hinterlegten Restaurant maskiert (fiel trotzdem auf
    # candidates[0] zurueck) - erst mit einem zweiten Restaurant zeigt sich der
    # echte Bug (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    memory.remember_fact(
        "Restaurant Pizza Blitz: https://www.thefork.de/restaurant/pizza-blitz-amberg-r999999",
        category="facts",
    )
    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Pizza Blitz", memory=memory
        )
    settings = memory.get("settings") or {}
    pending = settings.get("pending_reservation_open")
    assert pending is not None
    assert "pizza-blitz-amberg-r999999" in pending["url"]


def test_bare_restaurant_name_answers_disambiguation_question(memory):
    # Regression: _RESERVATION_CONTINUATION_RE erkennt Zeit-/Personenzahl-
    # Antworten, aber keinen blossen Restaurantnamen ("Pizza Blitz" auf
    # "Welches Restaurant meinst du?") - ohne Zusatz-Check waere die
    # Rueckfrage bei mehreren hinterlegten Restaurants nie beantwortbar
    # gewesen (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    memory.remember_fact(
        "Restaurant Pizza Blitz: https://www.thefork.de/restaurant/pizza-blitz-amberg-r999999",
        category="facts",
    )
    first = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr für 2 Personen", memory=memory)
    assert "restaurant" in first.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    with patch.object(jarvis, "send_push", return_value=True):
        second = jarvis.handle_reservation_command("Pizza Blitz", memory=memory)

    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "pizza-blitz-amberg-r999999" in pending["url"]


def test_none_for_unrelated_text(memory):
    assert jarvis.handle_reservation_command("wie geht es dir", memory=memory) is None


def test_asks_for_restaurant_when_none_known(memory):
    result = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr für 2 Personen", memory=memory)
    assert result is not None
    assert "thefork-link" in result.lower() or "restaurant" in result.lower()


def test_asks_for_date_and_time_when_missing(memory):
    _remember_restaurant(memory)
    result = jarvis.handle_reservation_command("ich möchte eine reservierung für 2 personen", memory=memory)
    assert "wann" in result.lower() or "tag" in result.lower() or "uhrzeit" in result.lower()


def test_asks_for_party_size_when_missing(memory):
    _remember_restaurant(memory)
    result = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr", memory=memory)
    assert "personen" in result.lower()


def test_happy_path_proposes_and_sends_push_with_prefilled_url(memory):
    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True) as send_push:
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Hans im Glück", memory=memory
        )

    assert "hans im glück" in result.lower()
    assert "bestätig" in result.lower() or "sag ja" in result.lower()

    settings = memory.get("settings") or {}
    pending = settings.get("pending_reservation_open")
    assert isinstance(pending, dict)
    assert "hour=1140" in pending["url"]  # 19:00 = 19*60 = 1140 Minuten seit Mitternacht
    assert "partySize=2" in pending["url"]
    assert pending["url"].startswith("https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551?")
    assert "set_at" in pending

    send_push.assert_called_once()
    push_kwargs = send_push.call_args.kwargs
    assert push_kwargs["url"] == pending["url"]


def test_followup_answers_complete_the_reservation_across_turns(memory):
    # Regression: eine kurze Folgeantwort wie "19 Uhr" oder "2 Personen" matcht
    # has_domain(text, "reservation") nicht - ohne den pending_reservation_details-
    # Mechanismus wuerde die Anfrage tot enden und der Nutzer muesste alles
    # nochmal von vorn sagen (Codex-Review 2026-08-23).
    _remember_restaurant(memory)

    first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück heute", memory=memory)
    assert "uhr" in first.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    second = jarvis.handle_reservation_command("19 Uhr", memory=memory)
    assert "personen" in second.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    with patch.object(jarvis, "send_push", return_value=True):
        third = jarvis.handle_reservation_command("für 2 Personen", memory=memory)

    assert "hans im glück" in third.lower()
    assert memory.get("settings").get("pending_reservation_details") is None
    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "hour=1140" in pending["url"]
    assert "partySize=2" in pending["url"]


def test_invalid_party_size_can_be_corrected(memory):
    # Regression: "fuer 0 Personen" wird abgelehnt und nachgefragt, aber "0
    # Personen" blieb im aufaddierten Text stehen - re.search() fand bei der
    # naechsten Extraktion weiterhin die alte "0", eine Korrektur-Antwort ("2")
    # kam nie an (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr für 0 Personen", memory=memory)
    assert memory.get("settings").get("pending_reservation_details") is not None

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command("2", memory=memory)

    assert "hans im glück" in result.lower()
    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "partySize=2" in pending["url"]


def test_bare_number_answers_party_size_question(memory):
    # Regression: die natuerlichste Antwort auf "Fuer wie viele Personen...?"
    # ist eine blanke Zahl ("2"), nicht "fuer 2 Personen" - ohne Fallback haette
    # das die Frage endlos wiederholt (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command("2", memory=memory)

    assert "hans im glück" in result.lower()
    assert memory.get("settings").get("pending_reservation_details") is None
    pending = memory.get("settings").get("pending_reservation_open")
    assert "partySize=2" in pending["url"]


def test_unrelated_followup_discards_pending_details(memory):
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück heute", memory=memory)
    assert memory.get("settings").get("pending_reservation_details") is not None

    result = jarvis.handle_reservation_command("wie ist eigentlich das Wetter", memory=memory)

    assert result is None
    assert memory.get("settings").get("pending_reservation_details") is None


def test_stale_confirmation_expires_instead_of_firing(memory):
    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True):
        jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Hans im Glück", memory=memory
        )

    settings = memory.get("settings") or {}
    settings["pending_reservation_open"]["set_at"] -= jarvis.PENDING_RESERVATION_OPEN_TTL_SECONDS + 1
    memory.set("settings", settings)

    with patch("subprocess.run") as run:
        result = jarvis.handle_pending_action_flow(memory, "ja")

    run.assert_not_called()  # eine abgelaufene Anfrage darf niemals noch den Browser oeffnen
    assert "abgelaufen" in result.lower()
    assert memory.get("settings").get("pending_reservation_open") is None
