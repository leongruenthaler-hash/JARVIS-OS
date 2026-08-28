"""Tests fuer Baustein E (mehrstufige Auftraege), siehe
plans/2026-08-09-jarvis-mehrstufige-auftraege.md.

Drei Ebenen:
1. app/core/multistep_planner.py - reine Plan-Validierung, kein echter LLM-Aufruf.
2. jarvis.py::looks_like_multistep_request - Ausloeser-Erkennung.
3. jarvis.py::execute_multistep_plan / _continue_multistep_chain_if_pending -
   Ausfuehrungs-Kette, inkl. Anhalten bei Bestaetigungsbedarf und Abbruch mit
   Vorschlaegen. _dispatch_confirmed_domain wird dabei per monkeypatch ersetzt,
   damit kein echter Domaenen-Handler (AppleScript etc.) laeuft.
"""

import json
import time

import pytest

import jarvis
from core.multistep_planner import parse_plan_response, plan_multistep
from memory import Memory


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


# --- app/core/multistep_planner.py: Plan-Validierung ------------------------


def test_parse_plan_response_valid_single_step():
    raw = '[{"domain": "mail", "teilauftrag": "raeum den posteingang auf"}]'
    assert parse_plan_response(raw, max_steps=4) == [
        {"domain": "mail", "teilauftrag": "raeum den posteingang auf"}
    ]


def test_parse_plan_response_valid_multi_step_with_markdown_fence():
    raw = '```json\n[{"domain": "mail", "teilauftrag": "a"}, {"domain": "calendar", "teilauftrag": "b"}]\n```'
    result = parse_plan_response(raw, max_steps=4)
    assert result == [
        {"domain": "mail", "teilauftrag": "a"},
        {"domain": "calendar", "teilauftrag": "b"},
    ]


def test_parse_plan_response_rejects_too_many_steps():
    raw = json.dumps([{"domain": "mail", "teilauftrag": f"schritt {i}"} for i in range(5)])
    assert parse_plan_response(raw, max_steps=4) is None


def test_parse_plan_response_rejects_unknown_domain():
    raw = '[{"domain": "wetter", "teilauftrag": "sag mir das wetter"}]'
    assert parse_plan_response(raw, max_steps=4) is None


def test_parse_plan_response_rejects_empty_teilauftrag():
    raw = '[{"domain": "mail", "teilauftrag": ""}]'
    assert parse_plan_response(raw, max_steps=4) is None


def test_parse_plan_response_rejects_non_array():
    assert parse_plan_response("das ist keine liste", max_steps=4) is None


def test_parse_plan_response_rejects_empty_array():
    assert parse_plan_response("[]", max_steps=4) is None


class _FakePlannerLLM:
    def __init__(self, response: str):
        self._response = response

    def ask(self, messages, max_output_tokens=None, user_text=None):
        return self._response


def test_plan_multistep_returns_steps_for_valid_json():
    llm = _FakePlannerLLM('[{"domain": "mail", "teilauftrag": "a"}, {"domain": "calendar", "teilauftrag": "b"}]')
    steps = plan_multistep(llm, "raeum die mails auf und erinnere mich")
    assert steps == [
        {"domain": "mail", "teilauftrag": "a"},
        {"domain": "calendar", "teilauftrag": "b"},
    ]


def test_plan_multistep_returns_none_for_invalid_response():
    llm = _FakePlannerLLM("ich verstehe nicht ganz, was du meinst")
    assert plan_multistep(llm, "irgendwas") is None


def test_plan_multistep_swallows_exceptions():
    class _BrokenLLM:
        def ask(self, *args, **kwargs):
            raise RuntimeError("kein Modell erreichbar")

    assert plan_multistep(_BrokenLLM(), "irgendwas") is None


# --- jarvis.py::looks_like_multistep_request --------------------------------


def test_looks_like_multistep_request_true_for_two_domains_and_connector():
    assert (
        jarvis.looks_like_multistep_request("leg eine notiz an und erinnere mich morgen an den zahnarzt")
        is True
    )


def test_looks_like_multistep_request_false_for_single_domain_even_with_connector():
    assert (
        jarvis.looks_like_multistep_request("erinnere mich morgen an den zahnarzt und übermorgen auch")
        is False
    )


def test_looks_like_multistep_request_false_without_connector_word():
    assert jarvis.looks_like_multistep_request("mach eine notiz erinnere mich morgen") is False


def test_looks_like_multistep_request_recognizes_reservation_via_wider_matcher():
    # Regression: looks_like_multistep_request() baute matched_domains
    # ausschliesslich ueber has_domain() - fuer "reservation" gibt es aber
    # einen zusaetzlichen, breiteren Erkennungspfad (has_reservation_domain(),
    # siehe _looks_like_table_reservation()). Ein Satz wie "reserviere doch
    # bitte einen tisch und schreibe eine notiz" wurde vom Reservierungs-
    # Handler zwar als Reservierung erkannt, aber NICHT als eine der zwei
    # Domaenen fuer die Mehrschritt-Planung gezaehlt - ein frueherer
    # Einzelschritt-Handler haette die Anfrage dadurch abgefangen, bevor der
    # zweite Schritt (Notiz) je ankam (Codex-Review 2026-08-27, Folgerunde -
    # gleiche Inkonsistenz-Klasse wie bereits bei
    # record_pattern_event_if_matched() behoben).
    assert jarvis.looks_like_multistep_request("reserviere doch bitte einen tisch und schreibe eine notiz") is True


# --- jarvis.py::execute_multistep_plan --------------------------------------


def test_execute_multistep_plan_runs_all_steps_in_order(monkeypatch, memory):
    calls = []

    def fake_dispatch(domain, question, mem, photo_worker=None):
        calls.append((domain, question))
        return f"{domain} erledigt."

    monkeypatch.setattr(jarvis, "_dispatch_confirmed_domain", fake_dispatch)

    steps = [
        {"domain": "notes", "teilauftrag": "leg eine notiz an"},
        {"domain": "calendar", "teilauftrag": "erinnere mich morgen"},
    ]
    answer = jarvis.execute_multistep_plan(steps, memory, photo_worker=None)

    assert calls == [("notes", "leg eine notiz an"), ("calendar", "erinnere mich morgen")]
    assert "notes erledigt." in answer
    assert "calendar erledigt." in answer
    assert (memory.get("settings") or {}).get("pending_multistep_queue") is None


def test_execute_multistep_plan_pauses_on_new_pending_key(monkeypatch, memory):
    def fake_dispatch(domain, question, mem, photo_worker=None):
        if domain == "mail":
            settings = mem.get("settings") or {}
            settings["pending_mail_delete"] = {"count": 3}
            mem.set("settings", settings)
            return "Soll ich wirklich löschen?"
        return f"{domain} erledigt."

    monkeypatch.setattr(jarvis, "_dispatch_confirmed_domain", fake_dispatch)

    steps = [
        {"domain": "notes", "teilauftrag": "leg eine notiz an"},
        {"domain": "mail", "teilauftrag": "lösch alte mails"},
        {"domain": "calendar", "teilauftrag": "erinnere mich morgen"},
    ]
    answer = jarvis.execute_multistep_plan(steps, memory, photo_worker=None)

    assert "notes erledigt." in answer
    assert "Soll ich wirklich löschen?" in answer
    queue = (memory.get("settings") or {}).get("pending_multistep_queue")
    assert queue["waiting_on_key"] == "pending_mail_delete"
    assert queue["remaining_steps"] == [{"domain": "calendar", "teilauftrag": "erinnere mich morgen"}]
    assert queue["done_summaries"] == ["notes erledigt."]


def test_execute_multistep_plan_aborts_on_failed_step_with_suggestion(monkeypatch, memory):
    def fake_dispatch(domain, question, mem, photo_worker=None):
        if domain == "photos":
            return None
        return f"{domain} erledigt."

    monkeypatch.setattr(jarvis, "_dispatch_confirmed_domain", fake_dispatch)

    steps = [
        {"domain": "notes", "teilauftrag": "leg eine notiz an"},
        {"domain": "photos", "teilauftrag": "zeig mir fotos"},
        {"domain": "calendar", "teilauftrag": "erinnere mich morgen"},
    ]
    answer = jarvis.execute_multistep_plan(steps, memory, photo_worker=None)

    assert "notes erledigt." in answer
    assert "konnte ich leider nicht weiterhelfen" in answer
    assert "restlichen Schritte" in answer
    assert (memory.get("settings") or {}).get("pending_multistep_queue") is None


# --- Kettenfortsetzung ueber handle_pending_action_flow ---------------------


def test_continue_chain_after_action_engine_confirmation(monkeypatch, memory):
    monkeypatch.setitem(jarvis.ACTION_ENGINE._executors, "mail_delete", lambda data: "Mails gelöscht.")
    monkeypatch.setattr(
        jarvis, "_dispatch_confirmed_domain", lambda domain, q, mem, photo_worker=None: "Notiz erstellt."
    )

    settings = {
        "pending_mail_delete": {"count": 2},
        "pending_multistep_queue": {
            "retry_step": {"domain": "mail", "teilauftrag": "lösch alte mails"},
            "remaining_steps": [{"domain": "notes", "teilauftrag": "mach eine notiz"}],
            "waiting_on_key": "pending_mail_delete",
            "done_summaries": ["Termin erstellt."],
        },
    }
    memory.set("settings", settings)

    answer = jarvis.handle_pending_action_flow(memory, "ja", photo_worker=None)

    assert "Termin erstellt." in answer
    assert "Mails gelöscht." in answer
    assert "Notiz erstellt." in answer
    assert (memory.get("settings") or {}).get("pending_multistep_queue") is None


def test_continue_chain_abort_on_cancel_gives_suggestion(memory):
    settings = {
        "pending_mail_delete": {"count": 2},
        "pending_multistep_queue": {
            "retry_step": {"domain": "mail", "teilauftrag": "lösch alte mails"},
            "remaining_steps": [{"domain": "notes", "teilauftrag": "mach eine notiz"}],
            "waiting_on_key": "pending_mail_delete",
            "done_summaries": ["Termin erstellt."],
        },
    }
    memory.set("settings", settings)

    answer = jarvis.handle_pending_action_flow(memory, "nein", photo_worker=None)

    assert "Termin erstellt." in answer
    assert "Notiz" in answer or "notes" in answer.lower()
    assert (memory.get("settings") or {}).get("pending_multistep_queue") is None
    assert (memory.get("settings") or {}).get("pending_mail_delete") is None


def test_continue_chain_after_permission_granted_retries_triggering_step(monkeypatch, memory):
    class _FakePermissionManager:
        granted: list[str] = []

        def __init__(self, *args, **kwargs):
            pass

        def grant(self, permission, source="unknown"):
            _FakePermissionManager.granted.append(permission)

    _FakePermissionManager.granted = []
    monkeypatch.setattr(jarvis, "PermissionManager", _FakePermissionManager)
    monkeypatch.setattr(
        jarvis, "_dispatch_confirmed_domain", lambda domain, q, mem, photo_worker=None: "Termin erinnert."
    )

    retry_step = {"domain": "calendar", "teilauftrag": "erinnere mich an den zahnarzt"}
    settings = {
        "pending_permission": {"permission": "calendar", "action": "x", "set_at": time.time()},
        "pending_multistep_queue": {
            "retry_step": retry_step,
            "remaining_steps": [],
            "waiting_on_key": "pending_permission",
            "done_summaries": ["Notiz erledigt."],
        },
    }
    memory.set("settings", settings)

    answer = jarvis.handle_pending_action_flow(memory, "ja", photo_worker=None)

    assert "Notiz erledigt." in answer
    assert "Termin erinnert." in answer
    assert (memory.get("settings") or {}).get("pending_multistep_queue") is None
    assert _FakePermissionManager.granted == ["calendar"]
