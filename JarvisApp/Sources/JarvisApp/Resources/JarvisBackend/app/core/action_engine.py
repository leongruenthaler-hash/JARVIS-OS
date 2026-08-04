from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ActionProposal:
    action_type: str
    execution_data: dict[str, Any]
    confirm_prompt: str


ActionExecutor = Callable[[dict[str, Any]], str]


class ActionEngine:
    def __init__(self) -> None:
        self._executors: dict[str, ActionExecutor] = {}
        # propose()/resolve() do a read-modify-write on the shared "settings" memory
        # bucket (read settings, mutate one key, write the whole dict back). Without a
        # lock, two requests racing here (e.g. a voice turn and a dashboard chat request
        # landing at nearly the same time) can interleave so one thread's settings.set()
        # overwrites the other's - silently dropping a just-proposed pending action, or
        # un-clearing one that was just resolved.
        self._lock = threading.RLock()

    def register(self, action_type: str, executor: ActionExecutor) -> None:
        self._executors[action_type] = executor

    def propose(self, memory: Any, settings_key: str, proposal: ActionProposal) -> str:
        with self._lock:
            settings = memory.get("settings") or {}
            settings[settings_key] = proposal.execution_data
            memory.set("settings", settings)
        return proposal.confirm_prompt

    def resolve(
        self,
        memory: Any,
        settings_key: str,
        pending_data: dict[str, Any],
        *,
        action_type: str,
        is_confirm: bool,
        is_cancel: bool,
        cancel_message: str,
        waiting_message: str,
    ) -> str:
        if is_cancel:
            self._clear(memory, settings_key)
            return cancel_message

        if not is_confirm:
            return waiting_message

        self._clear(memory, settings_key)
        executor = self._executors.get(action_type)
        if executor is None:
            return "Ich kenne diesen Aktionstyp gerade nicht. Bitte sag es noch einmal."
        return executor(pending_data)

    def _clear(self, memory: Any, settings_key: str) -> None:
        with self._lock:
            settings = memory.get("settings") or {}
            settings.pop(settings_key, None)
            memory.set("settings", settings)


ACTION_ENGINE = ActionEngine()
