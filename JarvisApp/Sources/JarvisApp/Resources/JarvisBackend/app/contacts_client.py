from __future__ import annotations

import subprocess
from dataclasses import dataclass
from urllib.parse import quote

from core.intent_matching import levenshtein_distance as _levenshtein_distance


FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"


@dataclass
class Contact:
    name: str
    phones: list[str]


class ContactAccessError(RuntimeError):
    pass


def list_contacts(limit: int = 200) -> list[Contact]:
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxContacts to {int(limit)}
    set outputText to ""
    set outputCount to 0

    tell application "Contacts"
        repeat with personRef in people
            if outputCount is greater than or equal to maxContacts then return outputText

            set personName to ""
            set phoneText to ""

            try
                set personName to name of personRef as string
            end try

            try
                repeat with phoneRef in phones of personRef
                    set phoneValue to value of phoneRef as string
                    if phoneValue is not "" then
                        if phoneText is "" then
                            set phoneText to phoneValue
                        else
                            set phoneText to phoneText & "|" & phoneValue
                        end if
                    end if
                end repeat
            end try

            if personName is not "" and phoneText is not "" then
                set outputText to outputText & personName & fieldSeparator & phoneText & recordSeparator
                set outputCount to outputCount + 1
            end if
        end repeat
    end tell

    return outputText
    """

    raw_output = _run_applescript(script)
    return _parse_contacts(raw_output)


def find_contacts(name_query: str, limit: int = 200) -> list[Contact]:
    normalized_query = _normalize_name(name_query)
    if not normalized_query:
        return []

    direct_matches = _find_contacts_applescript(name_query, limit=limit)
    if direct_matches:
        return direct_matches

    query_parts = set(normalized_query.split())
    compact_query = _compact_name(normalized_query)
    query_without_vowels = _without_vowels(normalized_query)
    matches: list[tuple[int, Contact]] = []
    for contact in list_contacts(limit=limit):
        normalized_name = _normalize_name(contact.name)
        if not normalized_name:
            continue

        compact_name = _compact_name(normalized_name)
        name_without_vowels = _without_vowels(normalized_name)
        score = 0
        if normalized_query == normalized_name:
            score += 100
        if normalized_query in normalized_name:
            score += 40

        if compact_query and compact_name:
            if compact_query == compact_name:
                score += 100

            distance = _levenshtein_distance(compact_query, compact_name)
            if distance <= 1:
                score += 70
            elif distance == 2 and min(len(compact_query), len(compact_name)) >= 4:
                score += 35

            if query_without_vowels and query_without_vowels == name_without_vowels:
                score += 60

        name_parts = set(normalized_name.split())
        score += len(query_parts & name_parts) * 15

        # Ein isolierter distance==2-Treffer (Zeile oben, +35) alleine ist ein zu
        # schwaches Signal, um als "passender Kontakt" praesentiert zu werden -
        # "Papa" matchte so z.B. "Mama" (Distanz 2 bei 4 Zeichen: p->m, p->m),
        # ein falscher Familienangehoeriger, nicht nur ein Tippfehler. Ab 40
        # Punkten (z.B. schon ein reiner Teilstring-Treffer) bleibt echte
        # Tippfehler-Toleranz erhalten, nur der schwaechste isolierte Fuzzy-
        # Treffer wird ausgefiltert. Live beobachtet 2026-08-20.
        if score >= 40:
            matches.append((score, contact))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [contact for _, contact in matches[:5]]


def call_contact_by_name(name_query: str) -> str:
    matches = find_contacts(name_query)
    if not matches:
        return f"Ich finde keinen Kontakt mit dem Namen {name_query}."

    if len(matches) > 1:
        names = ", ".join(contact.name for contact in matches[:3])
        return f"Ich finde mehrere passende Kontakte: {names}. Sag bitte den Namen genauer."

    contact = matches[0]
    if len(contact.phones) > 1:
        return (
            f"Ich finde bei {contact.name} mehrere Telefonnummern. "
            "Sag bitte genauer, welche Nummer ich verwenden soll."
        )

    phone = _clean_phone(contact.phones[0] if contact.phones else "")
    if not phone:
        return f"Ich finde bei {contact.name} keine Telefonnummer."

    auto_confirmed = _open_phone_url(phone, contact.name)
    if auto_confirmed:
        return f"Ich öffne und bestätige den FaceTime-Audio-Anruf bei {contact.name}."

    return (
        f"Ich habe FaceTime für {contact.name} geöffnet. "
        "Falls der Anrufen-Knopf stehen bleibt, erlaube Terminal oder VS Code unter Bedienungshilfen, damit ich ihn automatisch drücken kann."
    )


def call_phone_number(contact_name: str, phone: str) -> str:
    cleaned_phone = _clean_phone(phone)
    if not cleaned_phone:
        return f"Ich finde bei {contact_name} keine saubere Telefonnummer."

    auto_confirmed = _open_phone_url(cleaned_phone, contact_name)
    if auto_confirmed:
        return f"Ich öffne und bestätige den FaceTime-Audio-Anruf bei {contact_name}."

    return (
        f"Ich habe FaceTime für {contact_name} geöffnet. "
        "Falls der Anrufen-Knopf stehen bleibt, erlaube Terminal oder VS Code unter Bedienungshilfen, damit ich ihn automatisch drücken kann."
    )


def _open_phone_url(phone: str, contact_name: str) -> bool:
    url = f"facetime-audio://{quote(phone, safe='+')}"
    try:
        subprocess.run(["open", url], check=True, timeout=5)
    except subprocess.SubprocessError as exc:
        raise ContactAccessError(
            f"Ich konnte den FaceTime-Audio-Anruf an {contact_name} nicht starten."
        ) from exc
    return _confirm_facetime_call()


def _confirm_facetime_call() -> bool:
    script = """
    tell application "FaceTime" to activate
    delay 0.8
    tell application "System Events"
        if not (exists process "FaceTime") then return "false"
        tell process "FaceTime"
            set frontmost to true
            delay 0.2
            try
                click button "Anrufen" of window 1
                return "true"
            on error
                try
                    click button "Call" of window 1
                    return "true"
                on error
                    try
                        key code 36
                        return "true"
                    on error
                        return "false"
                    end try
                end try
            end try
        end tell
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.SubprocessError:
        return False

    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _run_applescript(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise ContactAccessError(
            "Kontakte hat zu lange nicht geantwortet. Öffne Kontakte einmal normal und versuch es dann erneut."
        )

    if result.returncode == 0:
        return result.stdout.strip()

    error_text = (result.stderr or result.stdout).strip()
    lowered_error = error_text.lower()
    if "not authorized" in lowered_error or "not allowed" in lowered_error:
        raise ContactAccessError(
            "Kontakte-Zugriff wurde noch nicht erlaubt. Öffne macOS Systemeinstellungen "
            "> Datenschutz & Sicherheit > Kontakte oder Automation und erlaube Terminal oder VS Code den Zugriff."
        )

    raise ContactAccessError(f"Kontakte konnten nicht gelesen werden: {error_text}")


def _find_contacts_applescript(name_query: str, limit: int = 200) -> list[Contact]:
    safe_query = _escape_applescript_text(name_query)
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxContacts to {int(limit)}
    set queryText to "{safe_query}"
    set outputText to ""
    set outputCount to 0

    tell application "Contacts"
        set matchedPeople to people whose name contains queryText
        repeat with personRef in matchedPeople
            if outputCount is greater than or equal to maxContacts then return outputText

            set personName to ""
            set phoneText to ""

            try
                set personName to name of personRef as string
            end try

            try
                repeat with phoneRef in phones of personRef
                    set phoneValue to value of phoneRef as string
                    if phoneValue is not "" then
                        if phoneText is "" then
                            set phoneText to phoneValue
                        else
                            set phoneText to phoneText & "|" & phoneValue
                        end if
                    end if
                end repeat
            end try

            if personName is not "" and phoneText is not "" then
                set outputText to outputText & personName & fieldSeparator & phoneText & recordSeparator
                set outputCount to outputCount + 1
            end if
        end repeat
    end tell

    return outputText
    """
    try:
        return _parse_contacts(_run_applescript(script))
    except ContactAccessError:
        return []


def _parse_contacts(raw_output: str) -> list[Contact]:
    contacts: list[Contact] = []
    if not raw_output:
        return contacts

    for record in raw_output.split(RECORD_SEPARATOR):
        record = record.strip(" \n\r\t")
        if not record:
            continue

        fields = record.split(FIELD_SEPARATOR)
        if len(fields) < 2:
            continue

        phones = [phone.strip() for phone in fields[1].split("|") if phone.strip()]
        contacts.append(Contact(name=fields[0].strip(), phones=phones))

    return contacts


def _normalize_name(text: str) -> str:
    return "".join(char.lower() if char.isalnum() else " " for char in text).strip()


def _compact_name(text: str) -> str:
    return "".join(_normalize_name(text).split())


def _without_vowels(text: str) -> str:
    return "".join(char for char in _compact_name(text) if char not in "aeiouäöü")


def _clean_phone(phone: str) -> str:
    cleaned = "".join(char for char in phone if char.isdigit() or char == "+")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def _escape_applescript_text(value: str) -> str:
    # AppleScript string literals cannot contain a raw newline - a literal \r/\n in
    # value (e.g. a multi-line name_query) previously broke the generated script's
    # syntax mid-string instead of being embedded safely, and in principle let an
    # embedded newline change how the rest of the script parses. Represent it via
    # AppleScript's own `return` keyword by reopening/closing the string instead of
    # ever emitting a raw newline byte into the script text.
    normalized = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return escaped.replace("\n", '" & return & "')
