"""Tests fuer zwei beim Testlauf auf dem echten Mac gefundene Bugs:

1. handle_notes_command() hatte gar keinen Lese-Pfad - jede Notizen-Anfrage ohne
   erkennbaren Titel (auch reine Lese-Fragen wie "was steht in meinen Notizen")
   landete im Erstellen-Flow ("Wie soll die Notiz heissen?").
2. Aufgaben (task_manager.py) waren per Chat komplett unerreichbar - eine Frage
   dazu fiel durch die gesamte Domaenen-Kette und landete im werkzeuglosen Chat.

list_recent_notes() ruft echtes AppleScript auf - in Tests deshalb immer per
monkeypatch ersetzt, nie der echte Notes-Zugriff.
"""

from datetime import datetime

import pytest

import jarvis
from core.task_manager import TaskManager
from memory import Memory


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


# --- Bug 1: Notizen lesen ----------------------------------------------------


def test_notes_read_request_lists_notes_instead_of_asking_for_title(monkeypatch, memory):
    monkeypatch.setattr(
        jarvis,
        "list_recent_notes",
        lambda limit=5: [
            {"title": "Einkaufszettel", "modified": datetime(2026, 8, 8, 15, 37)},
            {"title": "Ideen", "modified": datetime(2026, 8, 7, 12, 0)},
        ],
    )

    answer = jarvis.handle_notes_command(memory, "was steht in meinen Notizen?")

    assert answer is not None
    assert "Wie soll die Notiz heißen" not in answer
    assert "Einkaufszettel" in answer
    assert "Ideen" in answer


def test_notes_read_request_alternate_phrasing(monkeypatch, memory):
    monkeypatch.setattr(jarvis, "list_recent_notes", lambda limit=5: [])

    answer = jarvis.handle_notes_command(memory, "zeig mir meine letzten Notizen")

    assert answer == "Ich habe keine Notizen gefunden."


def test_notes_create_request_still_asks_for_title(monkeypatch, memory):
    monkeypatch.setattr(
        jarvis, "list_recent_notes", lambda limit=5: pytest.fail("list_recent_notes sollte hier nicht aufgerufen werden")
    )

    answer = jarvis.handle_notes_command(memory, "erstelle eine neue Notiz")

    assert answer == "Wie soll die Notiz heißen?"


def test_notes_create_with_title_and_body_still_creates(monkeypatch, memory):
    created = {}

    def fake_save(title, body, append=False):
        created["title"] = title
        created["body"] = body
        return f"Erledigt. {title} steht."

    monkeypatch.setattr(jarvis, "save_note_or_append", fake_save)

    answer = jarvis.handle_notes_command(memory, "erstelle eine Notiz namens Test mit dem Inhalt Hallo")

    assert created["title"] == "Test"
    assert "Erledigt" in answer


def test_notes_read_request_surfaces_access_error(monkeypatch, memory):
    from notes_client import NotesAccessError

    def broken(limit=5):
        raise NotesAccessError("Notizen-Zugriff wurde noch nicht erlaubt.")

    monkeypatch.setattr(jarvis, "list_recent_notes", broken)

    answer = jarvis.handle_notes_command(memory, "was steht in meinen Notizen?")

    assert answer == "Notizen-Zugriff wurde noch nicht erlaubt."


# --- Bug 2: Aufgaben per Chat -------------------------------------------------


def test_tasks_command_reports_no_open_tasks(memory):
    assert jarvis.handle_tasks_command(memory, "was habe ich für offene Aufgaben?") == (
        "Sie haben aktuell keine offenen Aufgaben."
    )


def test_tasks_command_lists_real_open_tasks(memory):
    TaskManager(memory).create_task("Rechnung pruefen", priority="hoch")
    TaskManager(memory).create_task("Anruf bei Kunde")

    answer = jarvis.handle_tasks_command(memory, "was habe ich für offene Aufgaben?")

    assert "Rechnung pruefen" in answer
    assert "(hoch)" in answer
    assert "Anruf bei Kunde" in answer


def test_tasks_command_excludes_rejected_and_done_tasks(memory):
    manager = TaskManager(memory)
    done = manager.create_task("Erledigt")
    manager.update_task(done["id"], status="erledigt")
    rejected = manager.create_task("Abgelehnt")
    manager.update_task(rejected["id"], status="abgelehnt")
    manager.create_task("Offen")

    answer = jarvis.handle_tasks_command(memory, "was habe ich für offene Aufgaben?")

    assert "Offen" in answer
    assert "Erledigt" not in answer
    assert "Abgelehnt" not in answer


def test_tasks_command_returns_none_for_unrelated_text(memory):
    assert jarvis.handle_tasks_command(memory, "wie ist das wetter heute") is None


def test_tasks_command_caps_summary_and_counts_remaining(memory):
    manager = TaskManager(memory)
    for i in range(10):
        manager.create_task(f"Aufgabe {i}")

    answer = jarvis.handle_tasks_command(memory, "aufgaben")

    assert "und 2 weitere" in answer
