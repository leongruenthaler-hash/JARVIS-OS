from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionPlan:
    action: str
    target: str = ""
    requires_confirmation: bool = True
    danger_level: str = "medium"
    explanation: str = ""


class ActionRouter:
    SAFE_ACTIONS = {
        "open_app",
        "show_status",
        "summarize",
        "search",
        "read_only",
    }

    RISKY_ACTIONS = {
        "send_mail",
        "delete_file",
        "move_file",
        "create_calendar_event",
        "delete_calendar_event",
        "create_reminder",
        "delete_reminder",
        "send_api_request",
        "write_memory",
    }

    def classify(self, action: str, target: str = "", explanation: str = "") -> ActionPlan:
        normalized = str(action or "").strip().lower()
        if normalized in self.SAFE_ACTIONS:
            return ActionPlan(action=normalized, target=target, requires_confirmation=False, danger_level="low", explanation=explanation)
        if normalized in self.RISKY_ACTIONS:
            return ActionPlan(action=normalized, target=target, requires_confirmation=True, danger_level="high", explanation=explanation)
        return ActionPlan(action=normalized or "unknown", target=target, requires_confirmation=True, danger_level="medium", explanation=explanation or "Jarvis braucht vor dieser Aktion eine Bestätigung.")

    def needs_confirmation(self, action: str) -> bool:
        return self.classify(action).requires_confirmation
