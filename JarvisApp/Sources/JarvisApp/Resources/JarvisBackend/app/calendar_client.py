from __future__ import annotations

import subprocess
import time
from datetime import datetime


class CalendarAccessError(RuntimeError):
    pass


def create_calendar_event(
    title: str,
    start_at: datetime,
    duration_minutes: int = 60,
    calendar_name: str | None = None,
    notes: str = "",
) -> str:
    safe_title = _escape_applescript_text(title)
    safe_notes = _escape_applescript_text(notes)
    safe_calendar = _escape_applescript_text(calendar_name or "")
    start_literal = _escape_applescript_text(_german_date_literal(start_at))
    duration_minutes = max(15, int(duration_minutes))

    script = f"""
    set eventDate to date "{start_literal}"
    set endDate to eventDate + ({duration_minutes} * minutes)
    set configuredCalendar to "{safe_calendar}"

    tell application "Calendar"
        set targetCalendar to missing value

        if configuredCalendar is not "" then
            repeat with calendarRef in calendars
                if name of calendarRef as string is configuredCalendar then
                    set targetCalendar to calendarRef
                    exit repeat
                end if
            end repeat
        end if

        if targetCalendar is missing value then
            set targetCalendar to first calendar
        end if

        make new event at end of events of targetCalendar with properties {{summary:"{safe_title}", start date:eventDate, end date:endDate, description:"{safe_notes}"}}
    end tell
    """

    _run_applescript(script, app_name="Kalender")
    return f"Kalendereintrag erstellt: {title}"


def create_reminder(
    title: str,
    due_at: datetime,
    list_name: str | None = None,
    notes: str = "",
) -> str:
    safe_title = _escape_applescript_text(title)
    safe_notes = _escape_applescript_text(notes)
    safe_list = _escape_applescript_text(list_name or "")
    due_literal = _escape_applescript_text(_german_date_literal(due_at))

    script = f"""
    set reminderDate to date "{due_literal}"
    set configuredList to "{safe_list}"

    tell application "Reminders"
        set targetList to missing value

        if configuredList is not "" then
            repeat with listRef in lists
                if name of listRef as string is configuredList then
                    set targetList to listRef
                    exit repeat
                end if
            end repeat
        end if

        if targetList is missing value then
            set targetList to first list
        end if

        make new reminder at end of reminders of targetList with properties {{name:"{safe_title}", body:"{safe_notes}", due date:reminderDate}}
    end tell
    """

    _run_applescript(script, app_name="Erinnerungen")
    return f"Erinnerung erstellt: {title}"


def list_upcoming_calendar_items(limit: int = 5, until: datetime | None = None) -> dict[str, list[dict[str, str]]]:
    limit = max(1, int(limit))
    until_setup = ""
    whose_until = ""
    if until is not None:
        until_literal = _escape_applescript_text(_german_date_literal(until))
        until_setup = f'\n    set untilDate to date "{until_literal}"'
        whose_until = " and start date < untilDate"

    # A plain "every event of calendarRef" makes Calendar.app materialize every event
    # ever created in that calendar (years of history) before the loop below gets a
    # chance to early-return via maxItems - on a calendar with a long history this can
    # take a very long time or hit the caller's timeout. "whose start date > nowDate"
    # lets Calendar.app do that filtering itself, so only upcoming events are pulled.
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxItems to {limit}
    set outputText to ""
    set itemCount to 0
    set nowDate to current date{until_setup}

    tell application "Calendar"
        repeat with calendarRef in calendars
            if itemCount is greater than or equal to maxItems then return outputText
            set upcomingEvents to (every event of calendarRef whose start date > nowDate{whose_until})
            repeat with eventRef in upcomingEvents
                if itemCount is greater than or equal to maxItems then return outputText
                try
                    set outputText to outputText & name of calendarRef as string & fieldSeparator & summary of eventRef as string & fieldSeparator & start date of eventRef as string & fieldSeparator & end date of eventRef as string & recordSeparator
                    set itemCount to itemCount + 1
                end try
            end repeat
        end repeat
    end tell

    return outputText
    """
    raw = _run_applescript(script, app_name="Kalender")
    return {"items": _parse_items(raw, ["calendar", "title", "start", "end"])}


def list_open_reminders(limit: int = 5) -> dict[str, list[dict[str, str]]]:
    limit = max(1, int(limit))
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxItems to {limit}
    set outputText to ""
    set itemCount to 0

    tell application "Reminders"
        repeat with listRef in lists
            repeat with reminderRef in (every reminder of listRef)
                if itemCount is greater than or equal to maxItems then return outputText
                try
                    set doneFlag to completed of reminderRef
                    if doneFlag is false then
                        set dueText to ""
                        try
                            set dueText to due date of reminderRef as string
                        end try
                        set outputText to outputText & name of listRef as string & fieldSeparator & name of reminderRef as string & fieldSeparator & dueText & recordSeparator
                        set itemCount to itemCount + 1
                    end if
                end try
            end repeat
        end repeat
    end tell

    return outputText
    """
    raw = _run_applescript(script, app_name="Erinnerungen")
    return {"items": _parse_items(raw, ["list", "title", "due"])}


def _german_date_literal(value: datetime) -> str:
    weekdays = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    months = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    return (
        f"{weekdays[value.weekday()]}, {value.day}. {months[value.month - 1]} {value.year} "
        f"um {value.hour:02d}:{value.minute:02d}:00"
    )


_APPLESCRIPT_PROCESS_NAMES = {
    "Kalender": "Calendar",
    "Erinnerungen": "Reminders",
}


def _ensure_app_running(process_name: str, timeout: float = 6.0) -> None:
    check_script = f'tell application "System Events" to (name of processes) contains "{process_name}"'

    def _is_running() -> bool:
        try:
            result = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    if _is_running():
        return

    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{process_name}" to launch'],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return

    waited = 0.0
    while waited < timeout:
        time.sleep(0.3)
        waited += 0.3
        if _is_running():
            return


def _run_applescript(script: str, app_name: str):
    process_name = _APPLESCRIPT_PROCESS_NAMES.get(app_name, app_name)
    _ensure_app_running(process_name)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        raise CalendarAccessError(
            f"{app_name} hat zu lange nicht geantwortet. Öffne {app_name} einmal normal und versuch es erneut."
        )

    if result.returncode == 0:
        return result.stdout

    error_text = (result.stderr or result.stdout).strip()
    lowered_error = error_text.lower()
    if "not authorized" in lowered_error or "not allowed" in lowered_error:
        raise CalendarAccessError(
            f"{app_name}-Zugriff wurde noch nicht erlaubt. Öffne macOS Systemeinstellungen "
            f"> Datenschutz & Sicherheit > Automation und erlaube Terminal oder VS Code den Zugriff."
        )
    if "syntax error" in lowered_error or "-2741" in lowered_error or "-2753" in lowered_error:
        raise CalendarAccessError(
            f"{app_name} konnte den AppleScript-Befehl nicht verarbeiten. "
            f"Öffne {app_name} einmal normal und prüfe in Systemeinstellungen > Datenschutz & Sicherheit > Automation, "
            "ob Terminal, VS Code oder Jarvis die App steuern darf. Ich habe nichts angelegt."
        )

    raise CalendarAccessError(f"{app_name} konnte nicht geschrieben werden: {error_text}")


def _escape_applescript_text(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').strip()


def _parse_items(raw_output: str, keys: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for record in raw_output.split(chr(30)):
        record = record.strip()
        if not record:
            continue
        parts = record.split(chr(31))
        if not parts:
            continue
        item = {key: parts[index].strip() if index < len(parts) else "" for index, key in enumerate(keys)}
        items.append(item)
    return items
