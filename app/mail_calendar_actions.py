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
)

# Automatisierte Massen-/Social-Media-Digests (z.B. LinkedIn-Aktivitaets-Updates)
# enthalten oft beliebigen fremden Post-Inhalt, der zufaellig ein EVENT_TERMS/
# INVOICE_TERMS/DEADLINE_TERMS-Wort trifft (live gefunden: ein LinkedIn-Post ueber
# "der Boarding Call gilt noch" loeste faelschlich einen Kalender-Vorschlag aus,
# obwohl die Mail selbst gar keine Einladung an Leon war). Deterministischer
# Absender-Vorfilter VOR der Stichwort-Erkennung, gleiche Technik wie der
# CORRECTIV-Kategorie-Vorfilter beim News-Baustein.
_BULK_SENDER_MARKERS = (
    "noreply",
    "no-reply",
    "donotreply",
    "notifications-noreply",
    "notifications@",
    "newsletter@",
    "mailer-daemon",
)


def _looks_like_bulk_or_notification(message: MailMessage) -> bool:
    sender = _normalize(message.sender or "")
    return any(marker in sender for marker in _BULK_SENDER_MARKERS)


def create_calendar_actions_from_messages(
    messages: list[MailMessage],
    config: dict[str, Any],
    existing_keys: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Detects invoice/event/deadline mentions in inbound mail and turns them into
    *proposals*, not real Calendar/Reminders entries. Inbound email is untrusted content
    (trivially spoofable subject/body), so nothing here calls create_calendar_event/
    create_reminder directly - unlike every other mutating action in this codebase
    (ACTION_ENGINE.propose/resolve), silently writing real Calendar entries off the back
    of unauthenticated mail content would be the one unconfirmed automated-action path.
    A caller must invoke execute_planned_calendar_action() after explicit user consent."""
    existing_keys = existing_keys or set()
    proposed: list[dict[str, str]] = []
    proposed_keys: list[str] = []

    for message in messages:
        plan = plan_calendar_action(message, config)
        if plan is None:
            continue

        action_key = _action_key(message, plan)
        if action_key in existing_keys:
            continue

        proposed_keys.append(action_key)
        proposed.append(
            {
                "status": "proposed",
                "action_key": action_key,
                "kind": plan["kind"],
                "title": plan["title"],
                "when": plan["when"].isoformat(timespec="minutes"),
                "notes": plan["notes"],
                "source": f"{message.sender}: {message.subject}",
                # Separate from "when" (the calendar event's own time, which can be in
                # the future) - this is when the proposal itself was created, used by
                # the Proactivity Engine to nudge about proposals that have sat
                # unconfirmed for a while.
                "proposed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    return proposed, proposed_keys


def execute_planned_calendar_action(action: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """Actually creates the Calendar event / Reminder for a single previously-proposed
    action. Only call this after the user has explicitly confirmed it (see
    MailBackgroundWorker.resolve_pending_calendar_action in background_tasks.py)."""
    from datetime import datetime as _datetime

    kind = str(action.get("kind") or "")
    title = str(action.get("title") or "")
    notes = str(action.get("notes") or "")

    try:
        when = _datetime.fromisoformat(str(action.get("when")))
        if kind == "event":
            create_calendar_event(
                title,
                when,
                duration_minutes=int(config.get("auto_calendar_event_duration_minutes", 60)),
                calendar_name=config.get("calendar_name"),
                notes=notes,
            )
        else:
            create_reminder(
                title,
                when,
                list_name=config.get("reminders_list_name"),
                notes=notes,
            )
    except (CalendarAccessError, ValueError, TypeError) as exc:
        # ValueError/TypeError guard against a missing or corrupted "when"/duration
        # value (e.g. a stale persisted proposal) - without this, execute would
        # raise an unhandled exception instead of surfacing a clean error result.
        return {**action, "status": "error", "error": str(exc)}

    return {**action, "status": "created"}


def plan_calendar_action(message: MailMessage, config: dict[str, Any]) -> dict[str, Any] | None:
    if _looks_like_bulk_or_notification(message):
        return None

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
    # Deliberately excludes message.received: Mail.app formats it as a full
    # German date string (e.g. "Donnerstag, 7. August 2025 um 21:15:00"), which
    # contains a weekday name and a day/month/year pattern that would otherwise
    # match the very date/weekday regexes used below - causing almost every
    # invoice/event/deadline mail to get an extracted date derived from its own
    # arrival timestamp instead of any date actually mentioned in the content.
    return " ".join(
        part
        for part in (message.sender, message.subject, message.preview)
        if part
    )


def _extract_datetime(text: str, config: dict[str, Any]) -> tuple[datetime, bool] | None:
    now = datetime.now()
    normalized_text = _normalize_umlauts(text).lower()

    # "in X Minuten/Stunden" wurde bisher gar nicht erkannt - _extract_time()
    # findet dabei kein "HH:MM"/"HH Uhr"-Muster, also fiel die Anfrage komplett
    # durch ("Für Kalender oder Erinnerung brauche ich noch Datum oder
    # Uhrzeit."), obwohl der Nutzer eine vollkommen eindeutige relative
    # Zeitangabe gemacht hat. Live beobachtet 2026-08-19. Muss VOR der
    # regulaeren _extract_time()-Ermittlung geprueft werden, da diese sonst nur
    # die Standard-Uhrzeit (z.B. 09:00) einsetzen wuerde statt "jetzt + Delta".
    relative_offset = re.search(r"\bin\s+(\d+)\s*(minuten?|min|stunden?|std|h)\b", normalized_text)
    if relative_offset:
        amount = int(relative_offset.group(1))
        unit = relative_offset.group(2)
        delta = timedelta(hours=amount) if unit in ("stunden", "stunde", "std", "h") else timedelta(minutes=amount)
        return now + delta, True

    default_hour, default_minute = _parse_default_time(
        str(config.get("auto_calendar_default_time", "09:00"))
    )
    hour, minute, has_time = _extract_time(text, default_hour, default_minute)

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
