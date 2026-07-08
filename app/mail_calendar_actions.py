from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from calendar_client import CalendarAccessError, create_calendar_event, create_reminder
from mail_client import MailMessage


MONTHS = {
    "januar": 1,
    "jan": 1,
    "februar": 2,
    "feb": 2,
    "märz": 3,
    "maerz": 3,
    "mrz": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
}


INVOICE_TERMS = (
    "rechnung",
    "invoice",
    "zahlbar",
    "zahlung",
    "fällig",
    "faellig",
    "mahnung",
    "überweisung",
    "ueberweisung",
    "betrag",
    "beleg",
)

EVENT_TERMS = (
    "termin",
    "meeting",
    "besprechung",
    "einladung",
    "appointment",
    "call",
    "gespräch",
    "gespraech",
    "webinar",
    "veranstaltung",
)

DEADLINE_TERMS = (
    "frist",
    "deadline",
    "bis zum",
    "spätestens",
    "spaetestens",
    "erinnerung",
)


def create_calendar_actions_from_messages(
    messages: list[MailMessage],
    config: dict[str, Any],
    existing_keys: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    existing_keys = existing_keys or set()
    created: list[dict[str, str]] = []
    created_keys: list[str] = []

    for message in messages:
        plan = plan_calendar_action(message, config)
        if plan is None:
            continue

        action_key = _action_key(message, plan)
        if action_key in existing_keys:
            continue

        try:
            if plan["kind"] == "event":
                create_calendar_event(
                    plan["title"],
                    plan["when"],
                    duration_minutes=int(config.get("auto_calendar_event_duration_minutes", 60)),
                    calendar_name=config.get("calendar_name"),
                    notes=plan["notes"],
                )
            else:
                create_reminder(
                    plan["title"],
                    plan["when"],
                    list_name=config.get("reminders_list_name"),
                    notes=plan["notes"],
                )
        except CalendarAccessError as exc:
            created.append(
                {
                    "status": "error",
                    "kind": plan["kind"],
                    "title": plan["title"],
                    "when": plan["when"].isoformat(timespec="minutes"),
                    "error": str(exc),
                }
            )
            continue

        created_keys.append(action_key)
        created.append(
            {
                "status": "created",
                "kind": plan["kind"],
                "title": plan["title"],
                "when": plan["when"].isoformat(timespec="minutes"),
                "source": f"{message.sender}: {message.subject}",
            }
        )

    return created, created_keys


def plan_calendar_action(message: MailMessage, config: dict[str, Any]) -> dict[str, Any] | None:
    text = _combined_text(message)
    normalized = _normalize(text)

    has_invoice = any(term in normalized for term in INVOICE_TERMS)
    has_event = any(term in normalized for term in EVENT_TERMS)
    has_deadline = any(term in normalized for term in DEADLINE_TERMS)
    if not has_invoice and not has_event and not has_deadline:
        return None

    parsed = _extract_datetime(text, config)
    if parsed is None:
        return None

    when, has_time = parsed
    kind = "event" if has_event and has_time and not has_invoice else "reminder"
    title_prefix = "Termin" if kind == "event" else "Erinnerung"
    subject = (message.subject or "Mail prüfen").strip()
    title = f"{title_prefix}: {subject}"[:120]
    notes = (
        f"Automatisch aus Mail erkannt.\n"
        f"Von: {message.sender}\n"
        f"Betreff: {message.subject}\n"
        f"Empfangen: {message.received}"
    )

    return {
        "kind": kind,
        "title": title,
        "when": when,
        "notes": notes,
    }


def _combined_text(message: MailMessage) -> str:
    return " ".join(
        part
        for part in (message.sender, message.subject, message.received, message.preview)
        if part
    )


def _extract_datetime(text: str, config: dict[str, Any]) -> tuple[datetime, bool] | None:
    now = datetime.now()
    default_hour, default_minute = _parse_default_time(
        str(config.get("auto_calendar_default_time", "09:00"))
    )
    hour, minute, has_time = _extract_time(text, default_hour, default_minute)
    normalized_text = _normalize_umlauts(text).lower()

    relative_date = _extract_relative_date(normalized_text, now, hour, minute)
    if relative_date is not None:
        return relative_date, has_time

    iso_date = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso_date:
        year = int(iso_date.group(1))
        month = int(iso_date.group(2))
        day = int(iso_date.group(3))
        result = _safe_datetime(year, month, day, hour, minute, now)
        return (result, has_time) if result is not None else None

    numeric_date = re.search(
        r"\b([0-3]?\d)[.\/-]([01]?\d)(?:[.\/-]((?:20)?\d{2}))?\b",
        text,
    )
    if numeric_date:
        day = int(numeric_date.group(1))
        month = int(numeric_date.group(2))
        year_text = numeric_date.group(3)
        year = _parse_year(year_text, now.year)
        result = _safe_datetime(year, month, day, hour, minute, now)
        return (result, has_time) if result is not None else None

    month_date = re.search(
        r"\b([0-3]?\d)\.?\s+"
        r"(januar|jan|februar|feb|märz|maerz|mrz|april|apr|mai|juni|jun|juli|jul|august|aug|september|sep|oktober|okt|november|nov|dezember|dez)"
        r"(?:\s+(20\d{2}))?\b",
        _normalize_umlauts(text),
        flags=re.IGNORECASE,
    )
    if month_date:
        day = int(month_date.group(1))
        month = MONTHS[month_date.group(2).lower()]
        year = int(month_date.group(3)) if month_date.group(3) else now.year
        result = _safe_datetime(year, month, day, hour, minute, now)
        return (result, has_time) if result is not None else None

    return None


def _extract_relative_date(
    normalized_text: str,
    now: datetime,
    hour: int,
    minute: int,
) -> datetime | None:
    if re.search(r"\b(?:heute)\b", normalized_text):
        return datetime(now.year, now.month, now.day, hour, minute)

    if re.search(r"\b(?:morgen)\b", normalized_text):
        target = now + timedelta(days=1)
        return datetime(target.year, target.month, target.day, hour, minute)

    if re.search(r"\b(?:uebermorgen|übermorgen)\b", normalized_text):
        target = now + timedelta(days=2)
        return datetime(target.year, target.month, target.day, hour, minute)

    weekdays = {
        "montag": 0,
        "dienstag": 1,
        "mittwoch": 2,
        "donnerstag": 3,
        "freitag": 4,
        "samstag": 5,
        "sonntag": 6,
    }
    for name, weekday in weekdays.items():
        if not re.search(rf"\b(?:naechsten\s+|nächsten\s+)?{name}\b", normalized_text):
            continue

        days_ahead = (weekday - now.weekday()) % 7
        if days_ahead == 0 or "naechsten" in normalized_text or "nächsten" in normalized_text:
            days_ahead += 7

        target = now + timedelta(days=days_ahead)
        return datetime(target.year, target.month, target.day, hour, minute)

    return None


def _extract_time(text: str, default_hour: int, default_minute: int) -> tuple[int, int, bool]:
    colon_time = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if colon_time:
        return int(colon_time.group(1)), int(colon_time.group(2)), True

    hour_time = re.search(r"\b(?:um\s+)?([01]?\d|2[0-3])\s*uhr\b", _normalize_umlauts(text), flags=re.IGNORECASE)
    if hour_time:
        return int(hour_time.group(1)), 0, True

    return default_hour, default_minute, False


def _parse_default_time(value: str) -> tuple[int, int]:
    match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
    if not match:
        return 9, 0

    hour = min(max(int(match.group(1)), 0), 23)
    minute = min(max(int(match.group(2)), 0), 59)
    return hour, minute


def _parse_year(year_text: str | None, default_year: int) -> int:
    if not year_text:
        return default_year

    year = int(year_text)
    if year < 100:
        return 2000 + year
    return year


def _safe_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    now: datetime,
) -> datetime | None:
    try:
        result = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    if result.date() < now.date() and year == now.year:
        try:
            result = datetime(year + 1, month, day, hour, minute)
        except ValueError:
            return None

    return result


def _action_key(message: MailMessage, plan: dict[str, Any]) -> str:
    source_id = message.message_id or f"{message.sender}:{message.subject}"
    return f"{source_id}|{plan['kind']}|{plan['when'].isoformat(timespec='minutes')}|{plan['title']}"


def _normalize(text: str) -> str:
    return _normalize_umlauts(text).lower()


def _normalize_umlauts(text: str) -> str:
    return (
        str(text)
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
    )
