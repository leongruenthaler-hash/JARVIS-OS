"""Unit tests for the Task Manager (app/core/task_manager.py, Phase D).

Covers the master-plan requirement that auto-detected tasks must never
silently become binding (Abschnitt 10.4): propose_task() vs. create_task().
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
from task_manager import TaskManager  # noqa: E402


@pytest.fixture
def manager(tmp_path):
    return TaskManager(Memory(base_path=tmp_path))


def test_create_task_is_immediately_open(manager):
    task = manager.create_task("Rechnung bezahlen")
    assert task["status"] == "offen"
    assert task["source"] == "manual"
    assert task["id"]


def test_propose_task_is_not_binding(manager):
    task = manager.propose_task("Vom Gespräch erkannte Aufgabe", source="conversation")
    assert task["status"] == "vorgeschlagen"
    # A proposed task must not show up as an actionable "offen" task by default.
    assert manager.list_tasks(status="offen") == []
    assert manager.list_tasks(status="vorgeschlagen") == [task]


def test_confirm_task_moves_proposed_to_open(manager):
    task = manager.propose_task("Zu bestätigen")
    assert manager.confirm_task(task["id"]) is True
    updated = manager.get_task(task["id"])
    assert updated["status"] == "offen"


def test_confirm_task_fails_for_non_proposed_task(manager):
    task = manager.create_task("Bereits offen")
    assert manager.confirm_task(task["id"]) is False


def test_reject_task_sets_status(manager):
    task = manager.propose_task("Wird abgelehnt")
    assert manager.reject_task(task["id"]) is True
    assert manager.get_task(task["id"])["status"] == "abgelehnt"


def test_list_tasks_excludes_rejected_by_default(manager):
    task = manager.propose_task("Wird abgelehnt")
    manager.reject_task(task["id"])
    assert manager.list_tasks() == []
    assert len(manager.list_tasks(include_rejected=True)) == 1


def test_invalid_priority_falls_back_to_mittel(manager):
    task = manager.create_task("Test", priority="nicht-real")
    assert task["priority"] == "mittel"


def test_update_task_only_touches_editable_fields(manager):
    task = manager.create_task("Original")
    original_created_at = task["created_at"]

    ok = manager.update_task(task["id"], title="Geändert", priority="hoch", not_a_field="x")
    assert ok is True

    updated = manager.get_task(task["id"])
    assert updated["title"] == "Geändert"
    assert updated["priority"] == "hoch"
    assert "not_a_field" not in updated
    assert updated["created_at"] == original_created_at


def test_delete_task(manager):
    task = manager.create_task("Löschbar")
    assert manager.delete_task(task["id"]) is True
    assert manager.get_task(task["id"]) is None
    assert manager.delete_task(task["id"]) is False


def test_list_tasks_filters_by_project(manager):
    manager.create_task("A", project="jarvis")
    manager.create_task("B", project="privat")
    jarvis_tasks = manager.list_tasks(project="jarvis")
    assert len(jarvis_tasks) == 1
    assert jarvis_tasks[0]["title"] == "A"


def test_blocked_tasks_detects_unfinished_dependency(manager):
    dependency = manager.create_task("Zuerst")
    blocked = manager.create_task("Danach", depends_on=[dependency["id"]])

    blocked_ids = [task["id"] for task in manager.blocked_tasks()]
    assert blocked["id"] in blocked_ids

    manager.update_task(dependency["id"], status="erledigt")
    blocked_ids_after = [task["id"] for task in manager.blocked_tasks()]
    assert blocked["id"] not in blocked_ids_after


def test_create_task_rejects_empty_title(manager):
    with pytest.raises(ValueError):
        manager.create_task("   ")
