from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from memory import Memory

# Master-Plan Abschnitt 10.4: "Jarvis darf erkannte Aufgaben nicht stillschweigend als
# verbindlich speichern." Jede automatisch erkannte Aufgabe landet deshalb mit status
# "vorgeschlagen", nie direkt "offen" - siehe propose_task() vs. create_task().
STATUSES = ("vorgeschlagen", "offen", "in_arbeit", "erledigt", "abgelehnt")
PRIORITIES = ("niedrig", "mittel", "hoch", "kritisch")


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


class TaskManager:
    """Aufgabenverwaltung (Phase D). Eigenständige memory-Bucket ("tasks"), getrennt
    von Apple Reminders (app/calendar_client.py list_open_reminders/create_reminder) -
    das sind systemweite Erinnerungen, hier geht es um interne Projekt-/Alltagsaufgaben
    mit Priorität, Abhängigkeiten und Status, die nicht zwingend in Reminders.app
    auftauchen sollen. Siehe docs/tasks.md."""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        # create_task()/propose_task()/update_task()/delete_task() all do a
        # read-modify-write on the shared "tasks" memory bucket (self._all() reads
        # the whole list, mutate, self._save() writes the whole list back). Without a
        # lock, two requests racing here (e.g. a voice turn creating a task while a
        # dashboard chat request updates another one) can interleave so one thread's
        # write overwrites the other's - silently dropping a just-created task or an
        # in-flight status change. Same class of bug already fixed in
        # ActionEngine.propose()/resolve() (see action_engine.py) for the same reason.
        self._lock = threading.RLock()

    def _all(self) -> list[dict[str, Any]]:
        tasks = self.memory.get("tasks")
        return tasks if isinstance(tasks, list) else []

    def _save(self, tasks: list[dict[str, Any]]) -> None:
        self.memory.set("tasks", tasks)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        project: str | None = None,
        include_rejected: bool = False,
    ) -> list[dict[str, Any]]:
        tasks = self._all()
        if not include_rejected:
            tasks = [task for task in tasks if task.get("status") != "abgelehnt"]
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        if project:
            tasks = [task for task in tasks if task.get("project") == project]
        return tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        for task in self._all():
            if task.get("id") == task_id:
                return task
        return None

    def _new_entry(
        self,
        title: str,
        *,
        status: str,
        project: str | None,
        priority: str,
        deadline: str | None,
        tags: list[str] | None,
        depends_on: list[str] | None,
        source: str,
        source_reference: str | None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "id": _new_task_id(),
            "title": title.strip(),
            "project": project,
            "priority": priority if priority in PRIORITIES else "mittel",
            "deadline": deadline,
            "status": status if status in STATUSES else "offen",
            "source": source,
            "source_reference": source_reference,
            "depends_on": list(depends_on or []),
            "tags": list(tags or []),
            "created_at": now,
            "updated_at": now,
        }

    def create_task(
        self,
        title: str,
        *,
        project: str | None = None,
        priority: str = "mittel",
        deadline: str | None = None,
        tags: list[str] | None = None,
        depends_on: list[str] | None = None,
        source: str = "manual",
        source_reference: str | None = None,
    ) -> dict[str, Any]:
        """Direkt erstellte, sofort verbindliche Aufgabe - nur für explizite
        Nutzeranfragen ("erstelle eine Aufgabe ...") oder die manuelle UI."""
        title = title.strip()
        if not title:
            raise ValueError("Aufgabentitel darf nicht leer sein.")
        entry = self._new_entry(
            title,
            status="offen",
            project=project,
            priority=priority,
            deadline=deadline,
            tags=tags,
            depends_on=depends_on,
            source=source,
            source_reference=source_reference,
        )
        with self._lock:
            tasks = self._all()
            tasks.append(entry)
            self._save(tasks)
        return entry

    def propose_task(
        self,
        title: str,
        *,
        project: str | None = None,
        priority: str = "mittel",
        deadline: str | None = None,
        tags: list[str] | None = None,
        source: str = "conversation",
        source_reference: str | None = None,
    ) -> dict[str, Any]:
        """Automatisch erkannte Aufgabe (aus Gespräch oder Mail) - status
        "vorgeschlagen", wird erst durch confirm_task() verbindlich."""
        title = title.strip()
        if not title:
            raise ValueError("Aufgabentitel darf nicht leer sein.")
        entry = self._new_entry(
            title,
            status="vorgeschlagen",
            project=project,
            priority=priority,
            deadline=deadline,
            tags=tags,
            depends_on=None,
            source=source,
            source_reference=source_reference,
        )
        with self._lock:
            tasks = self._all()
            tasks.append(entry)
            self._save(tasks)
        return entry

    def update_task(self, task_id: str, **fields: Any) -> bool:
        editable = {"title", "project", "priority", "deadline", "tags", "depends_on", "status"}
        with self._lock:
            tasks = self._all()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                for key, value in fields.items():
                    if key not in editable:
                        continue
                    if key == "priority" and value not in PRIORITIES:
                        continue
                    if key == "status" and value not in STATUSES:
                        continue
                    task[key] = value
                task["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self._save(tasks)
                return True
            return False

    def set_status(self, task_id: str, status: str) -> bool:
        if status not in STATUSES:
            return False
        return self.update_task(task_id, status=status)

    def confirm_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None or task.get("status") != "vorgeschlagen":
            return False
        return self.set_status(task_id, "offen")

    def reject_task(self, task_id: str) -> bool:
        return self.set_status(task_id, "abgelehnt")

    def delete_task(self, task_id: str) -> bool:
        tasks = self._all()
        remaining = [task for task in tasks if task.get("id") != task_id]
        if len(remaining) == len(tasks):
            return False
        self._save(remaining)
        return True

    def blocked_tasks(self) -> list[dict[str, Any]]:
        """Aufgaben, deren depends_on-Liste eine noch nicht erledigte Aufgabe enthält."""
        tasks = self._all()
        by_id = {task["id"]: task for task in tasks}
        blocked = []
        for task in tasks:
            if task.get("status") in ("erledigt", "abgelehnt"):
                continue
            for dependency_id in task.get("depends_on") or []:
                dependency = by_id.get(dependency_id)
                if dependency and dependency.get("status") != "erledigt":
                    blocked.append(task)
                    break
        return blocked
