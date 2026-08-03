from __future__ import annotations

from dataclasses import dataclass


CRITICAL_ACTIONS = {
    "send_email",
    "create_calendar_event",
    "delete_calendar_event",
    "create_reminder",
    "delete_reminder",
    "modify_file",
    "delete_file",
    "external_api",
    "send_personal_data_to_llm",
}


@dataclass
class PlannedAction:
    action_type: str
    summary: str
    risk: str = "medium"


def requires_confirmation(action_type: str) -> bool:
    return action_type in CRITICAL_ACTIONS


def confirmation_text(action: PlannedAction) -> str:
    return f"Ich habe noch nichts ausgeführt. Geplante Aktion: {action.summary}. Soll ich das wirklich machen?"
