from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from memory import Memory


class JarvisMemorySystem:
    def __init__(self, base_path: Path | None = None):
        self.memory = Memory(base_path)

    def remember_user_fact(self, content: str, category: str = "facts", source: str = "manual") -> str:
        return self.memory.upsert_fact(content, category=category, source=source)

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

    def maybe_remember(self, content: str, category: str = "facts", source: str = "auto") -> str:
        if not self.should_store_fact(content):
            return "ignored"
        return self.remember_user_fact(content, category=category, source=source)

    def maybe_forget(self, query: str) -> int:
        return self.memory.forget_facts_matching(query)

    def export(self) -> dict[str, Any]:
        return {
            "personality": self.memory.get("personality"),
            "long_memory": self.memory.get("long_memory"),
            "projects": self.memory.get("projects"),
            "settings": self.memory.get("settings"),
        }
