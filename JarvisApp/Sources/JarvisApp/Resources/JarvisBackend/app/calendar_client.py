from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from data_dir import data_root


class CalendarAccessError(RuntimeError):
    pass


CALENDAR_HELPER_BUNDLE_ID = "com.leon.jarvis.calendarhelper"


def _macos_sdk_path() -> str:
    """Siehe photos_client.py::_macos_sdk_path() - dieselbe Notwendigkeit, den
    zum aktiven Xcode-Compiler passenden SDK-Pfad explizit anzugeben, sonst
    greift auf diesem Mac faelschlich die (nicht passende) CommandLineTools-SDK."""
    try:
        result = subprocess.run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _time_safe_stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _run_process(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CalendarAccessError("Kalender-Helfer hat zu lange nicht geantwortet.") from exc


def _read_and_remove(path: Path) -> str:
    if not path.exists():
        return ""
    output = path.read_text(encoding="utf-8", errors="replace").strip()
    try:
        path.unlink()
    except OSError:
        pass
    return output


def _is_launch_services_error(result: subprocess.CompletedProcess[str]) -> bool:
    error = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return any(
        marker in error
        for marker in (
            "_lsopenurlswithcompletionhandler",
            "error -10825",
            "cannot be opened",
            "konnte nicht geöffnet werden",
            "kann nicht geöffnet werden",
        )
    )


class CalendarHelper:
    """Kompiliert/startet den EventKit-basierten Swift-Helfer (calendar_helper.swift)
    fuer schnelle, datumsgefilterte Termin-/Erinnerungsabfragen - Ersatz fuer den
    AppleScript-Weg in list_upcoming_calendar_items()/list_open_reminders(), der
    JEDES einzelne Event per eigenem IPC-Aufruf abfragt und bei mehreren hundert
    Terminen (mehrjaehrig wiederkehrende Feiertage etc.) zuverlaessig ueber die
    35s-Toleranz lief (gemessen: 24s allein fuer die Startdatum-Eigenschaft aller
    349 Termine, ganz ohne die weiteren ~13 Properties, die die volle Abfrage noch
    zusaetzlich braucht). EventKit fragt dieselben Daten nativ/indiziert ab, ohne
    Skript-Bridge-Overhead. Baut/registriert den Helfer nach demselben bewaehrten
    Muster wie photos_client.py::PhotoIndex (siehe dort fuer die volle Begruendung
    der einzelnen Schritte: stabiler Pfad gegen wiederholte Privacy-Prompts,
    eingebettetes Info.plist per Linker-Flag fuer TCC-Bundle-Identitaet, Codesign,
    LaunchServices-Registrierung, Fallback von App-Bundle-Start auf direkten
    Binary-Aufruf)."""

    def __init__(self) -> None:
        self.app_dir = Path(__file__).resolve().parent
        self.helper_source = self.app_dir / "calendar_helper.swift"
        self.helper_bundle = data_root() / "CalendarHelper" / "Jarvis Calendar Helper.app"
        self.helper_contents = self.helper_bundle / "Contents"
        self.helper_macos = self.helper_contents / "MacOS"
        self.helper_resources = self.helper_contents / "Resources"
        self.helper_plist = self.helper_contents / "Info.plist"
        self.helper_binary = self.helper_macos / "JarvisCalendarHelper"

    def _ensure_helper_bundle(self) -> None:
        self.helper_macos.mkdir(parents=True, exist_ok=True)
        self.helper_resources.mkdir(parents=True, exist_ok=True)
        plist_text = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>de</string>
    <key>CFBundleDisplayName</key>
    <string>Jarvis Calendar Helper</string>
    <key>CFBundleExecutable</key>
    <string>JarvisCalendarHelper</string>
    <key>CFBundleIdentifier</key>
    <string>com.leon.jarvis.calendarhelper</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Jarvis Calendar Helper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>NSCalendarsUsageDescription</key>
    <string>Jarvis braucht Zugriff, um Ihre Termine schnell abzufragen.</string>
    <key>NSCalendarsFullAccessUsageDescription</key>
    <string>Jarvis braucht Zugriff, um Ihre Termine schnell abzufragen.</string>
    <key>NSRemindersUsageDescription</key>
    <string>Jarvis braucht Zugriff, um Ihre offenen Erinnerungen schnell abzufragen.</string>
    <key>NSRemindersFullAccessUsageDescription</key>
    <string>Jarvis braucht Zugriff, um Ihre offenen Erinnerungen schnell abzufragen.</string>
</dict>
</plist>
"""
        if not self.helper_plist.exists() or self.helper_plist.read_text(encoding="utf-8") != plist_text:
            self.helper_plist.write_text(plist_text, encoding="utf-8")

    def _ensure_helper(self) -> Path:
        self._ensure_helper_bundle()
        needs_compile = not self.helper_binary.exists()
        if not needs_compile:
            binary_mtime = self.helper_binary.stat().st_mtime
            needs_compile = (
                self.helper_source.stat().st_mtime > binary_mtime
                or self.helper_plist.stat().st_mtime > binary_mtime
            )

        if not needs_compile:
            self._register_helper_bundle()
            return self.helper_binary

        command = [
            "xcrun",
            "swiftc",
            str(self.helper_source),
            "-o",
            str(self.helper_binary),
            "-target",
            "arm64-apple-macosx14.0",
        ]
        sdk_path = _macos_sdk_path()
        if sdk_path:
            command += ["-sdk", sdk_path]
        command += [
            "-Xlinker",
            "-sectcreate",
            "-Xlinker",
            "__TEXT",
            "-Xlinker",
            "__info_plist",
            "-Xlinker",
            str(self.helper_plist),
            "-module-cache-path",
            "/private/tmp/jarvis_calendar_swift_module_cache",
            "-framework",
            "EventKit",
        ]
        env = os.environ.copy()
        env["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/jarvis_calendar_clang_cache"
        _run_process_checked(command, timeout=60, env=env)
        self._codesign_helper()
        self._register_helper_bundle()
        return self.helper_binary

    def _codesign_helper(self) -> None:
        try:
            subprocess.run(["xattr", "-cr", str(self.helper_bundle)], capture_output=True, text=True, timeout=20)
        except Exception as exc:
            print(f"Kalender-Helfer: xattr -cr fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

        for command in (
            ["codesign", "--force", "--sign", "-", "--identifier", CALENDAR_HELPER_BUNDLE_ID, str(self.helper_binary)],
            ["codesign", "--force", "--deep", "--sign", "-", "--identifier", CALENDAR_HELPER_BUNDLE_ID, str(self.helper_bundle)],
        ):
            try:
                subprocess.run(command, capture_output=True, text=True, timeout=30)
            except Exception as exc:
                print(f"Kalender-Helfer: codesign fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

    def _register_helper_bundle(self) -> None:
        try:
            subprocess.run(
                [
                    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                    "-f",
                    str(self.helper_bundle),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            print(f"Kalender-Helfer: lsregister fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

    def run(self, args: list[str], timeout: int = 30) -> str:
        self._ensure_helper()
        output_file = Path(tempfile.gettempdir()) / f"jarvis_calendar_helper_{os.getpid()}_{_time_safe_stamp()}.txt"

        def _invoke(command: list[str]) -> tuple[subprocess.CompletedProcess[str], str]:
            result = _run_process(command, timeout=timeout)
            return result, _read_and_remove(output_file)

        app_command = ["open", "-W", str(self.helper_bundle), "--args", *args, "--output", str(output_file)]
        result, output = _invoke(app_command)

        if result.returncode != 0 and _is_launch_services_error(result):
            self._register_helper_bundle()
            result, output = _invoke(app_command)

        if result.returncode != 0 and _is_launch_services_error(result):
            binary_command = [str(self.helper_binary), *args, "--output", str(output_file)]
            result, output = _invoke(binary_command)

        clean_output = output.strip()
        if result.returncode != 0 or clean_output.startswith("ERROR:"):
            error = clean_output.removeprefix("ERROR:").strip()
            if not error:
                error = (result.stderr or result.stdout).strip()
            if "nicht erlaubt" in error.lower() or "denied" in error.lower() or "restricted" in error.lower():
                raise CalendarAccessError(
                    error
                    + " Öffne Systemeinstellungen > Datenschutz & Sicherheit > Kalender/Erinnerungen "
                    "und erlaube Jarvis Calendar Helper den Zugriff."
                )
            raise CalendarAccessError(error or "Kalender-Helfer konnte nicht antworten.")

        return clean_output


def _run_process_checked(command: list[str], timeout: int, env: dict[str, str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != 0:
        raise CalendarAccessError(
            f"Kalender-Helfer konnte nicht kompiliert werden: {(result.stderr or result.stdout).strip()}"
        )


_CALENDAR_HELPER = CalendarHelper()


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


_GERMAN_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
_GERMAN_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
    "September", "Oktober", "November", "Dezember",
)


def _german_datetime_string(value: datetime) -> str:
    """Wie AppleScripts "date ... as string" (z.B. "Dienstag, 18. August 2026 um
    19:00:00") - fuer Kompatibilitaet mit jarvis.py::_format_event_time(), das
    genau dieses Format erwartet, unabhaengig davon ob die Daten ueber AppleScript
    oder den EventKit-Helfer kamen."""
    weekday = _GERMAN_WEEKDAYS[value.weekday()]
    month = _GERMAN_MONTHS[value.month - 1]
    return f"{weekday}, {value.day}. {month} {value.year} um {value:%H:%M:%S}"


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # ISO8601DateFormatter().string(from:) im Swift-Helfer liefert standardmaessig
        # UTC mit "Z"-Suffix (z.B. "2026-08-19T08:30:00Z"), nicht mit numerischem
        # Offset wie urspruenglich angenommen - live beim ersten Testlauf entdeckt
        # (leere Startzeit-Anzeige, weil datetime.fromisoformat() auf Python 3.9,
        # der Laufzeit dieser App, "Z" nicht versteht und eine ValueError wirft, die
        # hier vorher still verschluckt wurde). "Z" -> "+00:00" macht es fuer 3.9
        # verdaulich. Anschliessend in die lokale Zeitzone konvertieren und wieder
        # tz-naiv machen, weil der Rest dieses Moduls (Vergleiche mit datetime.now())
        # durchgehend tz-naive, lokale Zeit erwartet - sonst waeren alle Termine um
        # den UTC-Offset (in Deutschland 1-2h) verschoben.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _events_from_helper_json(raw_json: str) -> list[dict[str, object]]:
    records = json.loads(raw_json or "[]")
    result: list[dict[str, object]] = []
    for record in records:
        start_dt = _parse_iso(str(record.get("start") or ""))
        end_dt = _parse_iso(str(record.get("end") or ""))
        result.append(
            {
                "calendar": record.get("calendar") or "",
                "title": record.get("title") or "",
                "start": _german_datetime_string(start_dt) if start_dt else "",
                "end": _german_datetime_string(end_dt) if end_dt else "",
                "start_dt": start_dt,
                "end_dt": end_dt,
                "all_day": bool(record.get("allDay")),
            }
        )
    return result


def _reminders_from_helper_json(raw_json: str) -> list[dict[str, str]]:
    records = json.loads(raw_json or "[]")
    return [
        {
            "list": record.get("list") or "",
            "title": record.get("title") or "",
            "due": record.get("due") or "",
        }
        for record in records
    ]


def list_upcoming_calendar_items(limit: int = 5, until: datetime | None = None) -> dict[str, list[dict[str, object]]]:
    limit = max(1, int(limit))

    try:
        helper_args = ["events", "--limit", str(limit)]
        if until is not None:
            # .isoformat() auf einem tz-naiven datetime liefert keinen Zeitzonen-
            # Offset (z.B. "2026-08-18T23:59:59") - Swifts ISO8601DateFormatter
            # verlangt aber standardmaessig einen (Z oder numerisch) und gibt bei
            # dessen Fehlen still nil zurueck, wodurch "until" im Helfer komplett
            # ignoriert wurde (live beobachtet: eine "heute"-Abfrage zeigte Termine
            # bis in den Oktober). .astimezone() ohne Argument interpretiert ein
            # naives datetime als System-Lokalzeit und haengt deren Offset an, ohne
            # die Uhrzeit selbst zu veraendern.
            helper_args += ["--until", until.astimezone().isoformat()]
        raw_json = _CALENDAR_HELPER.run(helper_args, timeout=30)
        return {"items": _events_from_helper_json(raw_json)}
    except CalendarAccessError:
        raise
    except Exception as exc:
        # Kompilier-/Laufzeitfehler des Helfers (z.B. fehlendes Xcode auf einer
        # aelteren macOS-Version) duerfen die Kalenderabfrage nicht hart brechen -
        # AppleScript-Fallback uebernimmt, nur langsamer. Siehe Kommentar an
        # CalendarHelper fuer die Begruendung, warum der Helfer ueberhaupt existiert.
        print(f"Kalender-Helfer fehlgeschlagen, Fallback auf AppleScript: {type(exc).__name__}: {exc}")

    return _list_upcoming_calendar_items_applescript(limit=limit, until=until)


def _list_upcoming_calendar_items_applescript(
    limit: int = 5, until: datetime | None = None
) -> dict[str, list[dict[str, object]]]:
    until_setup = ""
    until_check = ""
    if until is not None:
        until_literal = _escape_applescript_text(_german_date_literal(until))
        until_setup = f'\n    set untilDate to date "{until_literal}"'
        until_check = " and startDate is less than untilDate"

    # NOTE: an earlier version of this tried "every event of calendarRef whose start
    # date > nowDate" to avoid materializing a calendar's full event history up front.
    # Reverted - Calendar.app's AppleScript "whose" filtering on events is unreliable
    # (confirmed: it silently returned zero events, breaking "welche Termine habe ich
    # heute" entirely) rather than a real speed win. Back to the plain procedural filter,
    # which is slower on calendars with long history but actually returns events.
    #
    # Zusaetzlich zu den bestehenden Text-Feldern (start/end, locale-formatiert, nur
    # zur Anzeige) liefert das Skript jetzt auch numerische Datumsbestandteile (Jahr/
    # Monat/Tag/Stunde/Minute) ueber AppleScripts eigene Datumsobjekt-Eigenschaften
    # (year of/month of/...) statt ueber "as string" - sprachunabhaengig, kein
    # Format-Raten in Python noetig (siehe plans/2026-08-08-jarvis-termin-nudges.md).
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxItems to {limit}
    set outputText to ""
    set itemCount to 0
    set nowDate to current date{until_setup}

    tell application "Calendar"
        repeat with calendarRef in calendars
            repeat with eventRef in (every event of calendarRef)
                if itemCount is greater than or equal to maxItems then return outputText
                try
                    set startDate to start date of eventRef
                    if startDate is greater than nowDate{until_check} then
                        set endDate to end date of eventRef
                        set isAllDay to allday event of eventRef
                        set outputText to outputText & name of calendarRef as string & fieldSeparator & summary of eventRef as string & fieldSeparator & startDate as string & fieldSeparator & endDate as string & fieldSeparator & (year of startDate as string) & fieldSeparator & (month of startDate as integer as string) & fieldSeparator & (day of startDate as string) & fieldSeparator & (hours of startDate as string) & fieldSeparator & (minutes of startDate as string) & fieldSeparator & (year of endDate as string) & fieldSeparator & (month of endDate as integer as string) & fieldSeparator & (day of endDate as string) & fieldSeparator & (hours of endDate as string) & fieldSeparator & (minutes of endDate as string) & fieldSeparator & (isAllDay as string) & recordSeparator
                        set itemCount to itemCount + 1
                    end if
                end try
            end repeat
        end repeat
    end tell

    return outputText
    """
    raw = _run_applescript(script, app_name="Kalender")
    return {"items": _parse_calendar_items(raw)}


_CALENDAR_ITEM_KEYS = [
    "calendar", "title", "start", "end",
    "start_year", "start_month", "start_day", "start_hour", "start_minute",
    "end_year", "end_month", "end_day", "end_hour", "end_minute",
    "all_day",
]


def _build_datetime(item: dict[str, str], prefix: str) -> datetime | None:
    """Baut ein datetime aus den numerischen AppleScript-Feldern (siehe
    list_upcoming_calendar_items). Gibt None statt eine Exception zu werfen, wenn
    ein einzelner Termin unerwartete/fehlende Werte hat - ein kaputtes Feld bei
    einem Termin darf nie die ganze Terminliste zum Absturz bringen."""
    try:
        return datetime(
            int(item[f"{prefix}_year"]),
            int(item[f"{prefix}_month"]),
            int(item[f"{prefix}_day"]),
            int(item[f"{prefix}_hour"]),
            int(item[f"{prefix}_minute"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


def _parse_calendar_items(raw_output: str) -> list[dict[str, object]]:
    items = _parse_items(raw_output, _CALENDAR_ITEM_KEYS)
    result: list[dict[str, object]] = []
    for item in items:
        enriched: dict[str, object] = dict(item)
        enriched["start_dt"] = _build_datetime(item, "start")
        enriched["end_dt"] = _build_datetime(item, "end")
        enriched["all_day"] = str(item.get("all_day", "")).strip().lower() == "true"
        result.append(enriched)
    return result


def events_on_date(items: list[dict[str, object]], on: datetime | None = None) -> list[dict[str, object]]:
    """Filtert Kalendertermine auf einen bestimmten Tag (Standard: heute), anhand des
    robusten, numerisch geparsten start_dt statt eines locale-formatierten
    Datumsvergleichs. Termine ohne start_dt (Parsing fehlgeschlagen) werden bewusst
    NICHT herausgefiltert, damit ein einzelner kaputter Termin nicht faelschlich
    "keine Termine heute" ergibt. Gemeinsam genutzt von
    jarvis.py::answer_calendar_query() und dem Tagesbriefing (Baustein C, siehe
    plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md)."""
    target = (on or datetime.now()).date()
    return [item for item in items if item.get("start_dt") is None or item["start_dt"].date() == target]


def list_open_reminders(limit: int = 5) -> dict[str, list[dict[str, str]]]:
    limit = max(1, int(limit))

    try:
        raw_json = _CALENDAR_HELPER.run(["reminders", "--limit", str(limit)], timeout=30)
        return {"items": _reminders_from_helper_json(raw_json)}
    except CalendarAccessError:
        raise
    except Exception as exc:
        print(f"Kalender-Helfer (Erinnerungen) fehlgeschlagen, Fallback auf AppleScript: {type(exc).__name__}: {exc}")

    return _list_open_reminders_applescript(limit=limit)


def _list_open_reminders_applescript(limit: int = 5) -> dict[str, list[dict[str, str]]]:
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
        # "tell application X to launch" per osascript liefert bei geschlossener App
        # inzwischen zuverlaessig -600 ("Programm laeuft nicht") statt tatsaechlich zu
        # starten (live reproduziert am 2026-08-17, macOS-Verhaltensaenderung, keine
        # Berechtigungsfrage - sobald die App laeuft, funktioniert AppleScript-Zugriff
        # sofort ohne Freigabe-Dialog). "open" ist der gleiche Start-Weg wie ein
        # Finder-Doppelklick und startet zuverlaessig; -g haelt die App im Hintergrund,
        # damit ein stiller "was steht heute an"-Check nicht das Kalender-Fenster
        # aufreisst.
        subprocess.run(
            ["open", "-g", "-a", process_name],
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
            # 20s war zu knapp bemessen: list_upcoming_calendar_items() liest jedes
            # Event ueber einen eigenen, spuerbar langsamen AppleScript-Zugriff (kein
            # Sammelzugriff moeglich, siehe Kommentar dort) und iteriert dabei durch
            # ALLE Events aller Kalender, nicht nur zukuenftige - bei mehreren hundert
            # Terminen (Feiertage/Geburtstage ueber Jahre) lag die reale Dauer bereits
            # bei 13-20s, was den alten Grenzwert regelmaessig knapp verfehlte und zu
            # einem Timeout-Fehler fuehrte, obwohl Calendar.app nur langsam war, nicht
            # haengengeblieben. 35s als reale Sicherheitsmarge, gemessen an echten
            # Laufzeiten (siehe Bugreport von Leon, 2026-08-10).
            timeout=35,
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
    # AppleScript string literals cannot contain a raw newline - event/reminder notes
    # (which can come from a mail body snippet via auto_calendar_from_mail_enabled)
    # commonly span multiple lines, which previously broke the generated script's
    # syntax mid-string instead of being embedded safely. Represent it via
    # AppleScript's own `return` keyword by reopening/closing the string instead of
    # ever emitting a raw newline byte into the script text.
    normalized = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return escaped.replace("\n", '" & return & "')


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
