from __future__ import annotations

import html
import re
import subprocess
from datetime import datetime


class NotesAccessError(RuntimeError):
    pass


def create_note(title: str, body: str, folder_name: str | None = None) -> str:
    safe_title = _escape_applescript_text(title)
    safe_body_html = _escape_applescript_text(_body_to_html(title, body))
    safe_folder = _escape_applescript_text(folder_name or "")

    script = f"""
    set noteTitle to "{safe_title}"
    set noteBody to "{safe_body_html}"
    set configuredFolder to "{safe_folder}"

    tell application "Notes"
        set targetFolder to missing value

        if configuredFolder is not "" then
            repeat with accountRef in accounts
                repeat with folderRef in folders of accountRef
                    if name of folderRef as string is configuredFolder then
                        set targetFolder to folderRef
                        exit repeat
                    end if
                end repeat
                if targetFolder is not missing value then exit repeat
            end repeat
        end if

        if targetFolder is missing value then
            try
                set targetFolder to first folder of default account
            on error
                set targetFolder to first folder of first account
            end try
        end if

        make new note at targetFolder with properties {{name:noteTitle, body:noteBody}}
    end tell
    """

    _run_applescript(script)
    return f"Notiz erstellt: {title}"


def append_to_note(title: str, text: str, folder_name: str | None = None) -> str:
    safe_title = _escape_applescript_text(title)
    safe_append_html = _escape_applescript_text(_append_to_html(text))
    safe_folder = _escape_applescript_text(folder_name or "")

    script = f"""
    set noteTitle to "{safe_title}"
    set appendHtml to "{safe_append_html}"
    set configuredFolder to "{safe_folder}"
    set targetNote to missing value

    tell application "Notes"
        if configuredFolder is not "" then
            repeat with accountRef in accounts
                repeat with folderRef in folders of accountRef
                    if name of folderRef as string is configuredFolder then
                        repeat with noteRef in notes of folderRef
                            if name of noteRef as string is noteTitle then
                                set targetNote to noteRef
                                exit repeat
                            end if
                        end repeat
                    end if
                    if targetNote is not missing value then exit repeat
                end repeat
                if targetNote is not missing value then exit repeat
            end repeat
        end if

        if targetNote is missing value then
            repeat with accountRef in accounts
                repeat with folderRef in folders of accountRef
                    repeat with noteRef in notes of folderRef
                        if name of noteRef as string is noteTitle then
                            set targetNote to noteRef
                            exit repeat
                        end if
                    end repeat
                    if targetNote is not missing value then exit repeat
                end repeat
                if targetNote is not missing value then exit repeat
            end repeat
        end if

        if targetNote is missing value then
            try
                set targetFolder to first folder of default account
            on error
                set targetFolder to first folder of first account
            end try
            make new note at targetFolder with properties {{name:noteTitle, body:("<h1>" & noteTitle & "</h1>" & appendHtml)}}
        else
            set body of targetNote to (body of targetNote & appendHtml)
        end if
    end tell
    """

    _run_applescript(script)
    return f"Notiz aktualisiert: {title}"


def list_recent_notes(limit: int = 5) -> list[dict]:
    """Liest Titel + Änderungsdatum aller Notizen ueber alle Accounts/Ordner (kein
    Textinhalt - reine Uebersicht, siehe handle_notes_command in jarvis.py, das
    bisher gar keinen Lese-Pfad hatte und jede Lese-Anfrage faelschlich in den
    Erstellen-Flow laufen liess). Zahlen statt formatiertem Datumstext, dieselbe
    Technik wie calendar_client.py::_build_datetime() - sprachunabhaengig, kein
    fragiles String-Parsing eines lokal formatierten AppleScript-Datums noetig."""
    script = """
    tell application "Notes"
        set output to {}
        repeat with accountRef in accounts
            repeat with folderRef in folders of accountRef
                repeat with noteRef in notes of folderRef
                    set noteTitle to name of noteRef as string
                    set modDate to modification date of noteRef
                    set y to year of modDate as string
                    set mo to (month of modDate as integer) as string
                    set d to day of modDate as string
                    set h to hours of modDate as string
                    set mi to minutes of modDate as string
                    set end of output to noteTitle & "\t" & y & "\t" & mo & "\t" & d & "\t" & h & "\t" & mi
                end repeat
            end repeat
        end repeat
        set AppleScript's text item delimiters to return
        set outputText to output as string
        set AppleScript's text item delimiters to ""
        return outputText
    end tell
    """
    raw = _run_applescript(script, timeout=25, capture=True) or ""

    notes: list[dict] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        title, year, month, day, hour, minute = parts
        try:
            modified = datetime(int(year), int(month), int(day), int(hour), int(minute))
        except ValueError:
            continue
        notes.append({"title": title, "modified": modified})

    notes.sort(key=lambda note: note["modified"], reverse=True)
    return notes[:limit]


def _run_applescript(script: str, *, timeout: int = 12, capture: bool = False):
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise NotesAccessError(
            "Notizen hat zu lange nicht geantwortet. Öffne Notizen einmal normal und versuch es erneut."
        )

    if result.returncode == 0:
        return result.stdout.strip() if capture else None

    error_text = (result.stderr or result.stdout).strip()
    lowered_error = error_text.lower()
    if "not authorized" in lowered_error or "not allowed" in lowered_error:
        raise NotesAccessError(
            "Notizen-Zugriff wurde noch nicht erlaubt. Öffne macOS Systemeinstellungen "
            "> Datenschutz & Sicherheit > Automation und erlaube Terminal oder VS Code den Zugriff."
        )

    raise NotesAccessError(f"Notizen konnte nicht geschrieben werden: {error_text}")


def _body_to_html(title: str, body: str) -> str:
    lines = _clean_lines(body)
    if _looks_like_list(lines):
        content = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
        return f"<h1>{html.escape(title)}</h1><ul>{content}</ul>"

    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return f"<h1>{html.escape(title)}</h1>{paragraphs}"


def _append_to_html(text: str) -> str:
    lines = _clean_lines(text)
    if _looks_like_list(lines):
        return "<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in lines) + "</ul>"

    return "".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _clean_lines(text: str) -> list[str]:
    text = str(text).strip()
    if "\n" not in text and _should_split_inline_list(text):
        text = re.sub(r"\s*(?:,|;| und )\s*", "\n", text)

    lines = []
    seen = set()
    for line in text.splitlines():
        cleaned = line.strip(" .,!?:;-")
        normalized = cleaned.lower()
        if cleaned and normalized not in seen:
            lines.append(cleaned)
            seen.add(normalized)
    return lines or [" "]


def _should_split_inline_list(text: str) -> bool:
    lowered = text.lower()
    if "," in lowered or ";" in lowered:
        return True

    shopping_words = {
        "milch",
        "brot",
        "eier",
        "käse",
        "kaese",
        "butter",
        "wasser",
        "nudeln",
        "reis",
        "tomaten",
        "bananen",
        "äpfel",
        "aepfel",
        "einkaufen",
        "einkaufszettel",
        "einkaufsliste",
    }
    return " und " in lowered and any(word in lowered for word in shopping_words)


def _looks_like_list(lines: list[str]) -> bool:
    if len(lines) >= 2:
        return True

    shopping_words = {
        "milch",
        "brot",
        "eier",
        "käse",
        "kaese",
        "butter",
        "wasser",
        "nudeln",
        "reis",
        "tomaten",
        "bananen",
        "äpfel",
        "aepfel",
    }
    combined = " ".join(lines).lower()
    return any(word in combined for word in shopping_words)


def _escape_applescript_text(value: str) -> str:
    # AppleScript string literals cannot contain a raw newline - a literal \r/\n in
    # value (e.g. a multi-line note title or folder name) previously broke the
    # generated script's syntax mid-string instead of being embedded safely, and in
    # principle let an embedded newline change how the rest of the script parses.
    # Represent it via AppleScript's own `return` keyword by reopening/closing the
    # string instead of ever emitting a raw newline byte into the script text.
    normalized = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return escaped.replace("\n", '" & return & "')
