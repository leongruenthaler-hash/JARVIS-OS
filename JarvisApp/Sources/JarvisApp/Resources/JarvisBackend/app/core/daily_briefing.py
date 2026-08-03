from __future__ import annotations

from datetime import datetime
from typing import Any


def build_daily_briefing(
    *,
    calendar_items: list[dict[str, Any]] | None = None,
    reminders: list[dict[str, Any]] | None = None,
    mail_summary: str = "",
    weather_summary: str = "",
    system_summary: str = "",
) -> str:
    calendar_items = calendar_items or []
    reminders = reminders or []

    parts = [f"Tagesbriefing für {datetime.now().strftime('%d.%m.%Y')}."]
    if weather_summary:
        parts.append(f"Wetter: {weather_summary}.")
    if calendar_items:
        first = calendar_items[0]
        title = str(first.get("title") or first.get("summary") or "Termin")
        parts.append(f"Heute wichtig: {title}.")
    if reminders:
        first_reminder = str(reminders[0].get("title") or reminders[0].get("summary") or "Erinnerung")
        parts.append(f"Erinnerung: {first_reminder}.")
    if mail_summary:
        parts.append(f"Mails: {mail_summary}.")
    if system_summary:
        parts.append(f"System: {system_summary}.")
    if len(parts) == 1:
        parts.append("Aktuell ist nichts Dringendes auffällig. Verdächtig ruhig, fast schon unverschämt.")
    return " ".join(parts)

