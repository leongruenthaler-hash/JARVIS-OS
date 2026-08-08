from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from memory import Memory


class JarvisMemorySystem:
    def __init__(self, base_path: Path | None = None):
        self.memory = Memory(base_path)

    def remember_user_fact(
        self,
        content: str,
        category: str = "facts",
        source: str = "manual",
        *,
        confidence: float = 1.0,
        sensitivity: str = "normal",
        status: str = "confirmed",
    ) -> str:
        return self.memory.upsert_fact(
            content,
            category=category,
            source=source,
            confidence=confidence,
            sensitivity=sensitivity,
            status=status,
        )

    def should_store_fact(self, content: str) -> bool:
        text = " ".join(str(content or "").split()).strip()
        if not text:
            return False

        lowered = text.lower()
        if len(text) < 12:
            return False
        if lowered in {"ok", "okay", "ja", "nein", "danke", "passt"}:
            return False
        if sum(1 for word in text.split() if len(word) > 2) < 3:
            return False
        if any(marker in lowered for marker in ("ich bin nur", "test", "debug", "fehler", "fehlermeldung")):
            return False
        return True

    def add_project_note(self, project: str, note: str) -> None:
        # get() + set() is a read-modify-write pair with a gap in between - two
        # concurrent calls (e.g. two requests handled on different threads by
        # local_server.py) can both read the same "projects" dict, append to their
        # own copy, and the second set() silently overwrites the first note. Hold
        # Memory's own lock across the whole read-modify-write so it's atomic.
        with self.memory._lock:
            projects = self.memory.get("projects") or {}
            project_entry = projects.setdefault(project, {"notes": [], "updated_at": None})
            project_entry.setdefault("notes", [])
            project_entry["notes"].append(
                {
                    "content": note,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            project_entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.memory.set("projects", projects)

    def profile(self) -> dict[str, Any]:
        return self.memory.get("personality") or {}

    def facts_summary(self, limit: int = 8) -> str:
        facts = self.memory.all_facts()
        if facts:
            return "; ".join(
                str(item.get("content", ""))
                for item in facts[:limit]
                if item.get("content")
            ) or "Keine wichtigen Langzeitnotizen."
        return "Keine wichtigen Langzeitnotizen."

    def maybe_remember(
        self,
        content: str,
        category: str = "facts",
        source: str = "auto",
        *,
        confidence: float = 1.0,
        sensitivity: str = "normal",
        status: str = "confirmed",
    ) -> str:
        if not self.should_store_fact(content):
            return "ignored"
        return self.remember_user_fact(
            content,
            category=category,
            source=source,
            confidence=confidence,
            sensitivity=sensitivity,
            status=status,
        )

    def maybe_forget(self, query: str) -> int:
        return self.memory.forget_facts_matching(query)

    def export(self) -> dict[str, Any]:
        return {
            "personality": self.memory.get("personality"),
            "long_memory": self.memory.get("long_memory"),
            "projects": self.memory.get("projects"),
            "settings": self.memory.get("settings"),
        }
