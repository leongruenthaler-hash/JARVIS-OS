from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from data_dir import data_root


@dataclass
class ConversationTurn:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationManager:
    def __init__(self, base_path: Path | None = None, max_turns: int = 40):
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "conversation.json"
        self.max_turns = max_turns
        self.turns: list[ConversationTurn] = self._load()

    def _load(self) -> list[ConversationTurn]:
        if not self.path.exists():
            self._save([])
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken = self.path.with_suffix(".json.broken")
            self.path.rename(broken)
            self._save([])
            return []
        turns: list[ConversationTurn] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or item.get("text") or "").strip()
            if role and content:
                turns.append(
                    ConversationTurn(
                        role=role,
                        content=content,
                        created_at=str(item.get("created_at") or datetime.now().isoformat(timespec="seconds")),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
        return turns[-self.max_turns :]

    def _save(self, turns: list[ConversationTurn] | None = None) -> None:
        payload = turns if turns is not None else self.turns
        data = [
            {
                "role": turn.role,
                "content": turn.content,
                "created_at": turn.created_at,
                "metadata": turn.metadata,
            }
            for turn in payload[-self.max_turns :]
        ]
        # Atomic write (tmp + rename) so a crash mid-write can't leave a truncated,
        # unparseable conversation.json behind; 0600 since this is unencrypted chat
        # history and the only thing gating it is filesystem permissions.
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(self.path)

    def append(self, role: str, content: str, **metadata: Any) -> ConversationTurn:
        turn = ConversationTurn(role=role, content=content, metadata=dict(metadata))
        self.turns.append(turn)
        self.turns = self.turns[-self.max_turns :]
        self._save()
        return turn

    def as_messages(self, recent_limit: int = 8) -> list[dict[str, str]]:
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.turns[-recent_limit:]
            if turn.content.strip()
        ]

    def clear(self) -> None:
        self.turns = []
        self._save()

    def summary(self, limit: int = 6) -> str:
        if not self.turns:
            return "Kein Gesprächsverlauf vorhanden."
        parts = [f"{turn.role}: {turn.content}" for turn in self.turns[-limit:]]
        return " | ".join(parts)
