from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_MAX_ITEMS_PER_SECTION = 3


def _format_calendar_item(item: dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("summary") or "Termin")
    start_dt = item.get("start_dt")
    if start_dt is not None:
        return f"{title} um {start_dt:%H:%M} Uhr"
    raw_start = str(item.get("start") or "")
    return f"{title} ({raw_start})" if raw_start else title


def _format_task(task: dict[str, Any]) -> str:
    title = str(task.get("title") or "Aufgabe")
    priority = str(task.get("priority") or "").strip()
    return f"{title} ({priority})" if priority and priority != "mittel" else title


def _format_reminder(reminder: dict[str, Any]) -> str:
    return str(reminder.get("title") or reminder.get("summary") or "Erinnerung")


def _format_section(
    label: str,
    items: list[dict[str, Any]],
    formatter,
    *,
    max_items: int,
) -> str:
    """Baut einen Briefing-Abschnitt aus bis zu `max_items` Eintraegen, mit einer
    kurzen "und N weitere" Ergaenzung, falls mehr vorhanden sind - bewusst begrenzt,
    weil das Briefing auch vorgelesen wird (siehe
    plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md, Offene Frage 1: 3 pro
    Abschnitt, von Leon bestaetigt)."""
    if not items:
        return ""
    shown = items[:max_items]
    remaining = len(items) - len(shown)
    text = "; ".join(formatter(item) for item in shown)
    if remaining > 0:
        noun = "weiterer" if remaining == 1 else "weitere"
        text += f" und {remaining} {noun}"
    return f"{label}: {text}."


def build_daily_briefing(
    *,
    calendar_items: list[dict[str, Any]] | None = None,
    reminders: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    mail_summary: str = "",
    weather_summary: str = "",
    system_summary: str = "",
    max_items_per_section: int = DEFAULT_MAX_ITEMS_PER_SECTION,
) -> str:
    calendar_items = calendar_items or []
    reminders = reminders or []
    tasks = tasks or []

    parts = [f"Tagesbriefing für {datetime.now().strftime('%d.%m.%Y')}."]
    if weather_summary:
        parts.append(f"Wetter: {weather_summary}.")

    calendar_section = _format_section(
        "Heute wichtig", calendar_items, _format_calendar_item, max_items=max_items_per_section
    )
    if calendar_section:
        parts.append(calendar_section)

    task_section = _format_section("Offene Aufgaben", tasks, _format_task, max_items=max_items_per_section)
    if task_section:
        parts.append(task_section)

    reminder_section = _format_section(
        "Erinnerungen", reminders, _format_reminder, max_items=max_items_per_section
    )
    if reminder_section:
        parts.append(reminder_section)

    if mail_summary:
        parts.append(f"Mails: {mail_summary}.")
    if system_summary:
        parts.append(f"System: {system_summary}.")
    if len(parts) == 1:
        parts.append("Aktuell ist nichts Dringendes auffällig. Verdächtig ruhig, fast schon unverschämt.")
    return " ".join(parts)
