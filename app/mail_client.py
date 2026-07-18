from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"


@dataclass
class MailMessage:
    message_id: str
    sender: str
    subject: str
    received: str
    preview: str


@dataclass
class MailboxSummary:
    account: str
    mailbox: str
    message_count: int


@dataclass
class MailDocumentExportResult:
    category: str
    folder: str
    matched_messages: int
    saved_files: list[str]
    note_files: list[str]


class MailAccessError(RuntimeError):
    pass


MAIL_DOCUMENT_CATEGORIES = {
    "rechnungen": {
        "folder": "Rechnungen",
        "keywords": (
            "rechnung",
            "rechnungen",
            "invoice",
            "beleg",
            "quittung",
            "zahlungsbeleg",
            "abrechnung",
            "zahlung",
            "bezahlt",
            "betrag",
            "mahnung",
            "gebuehr",
            "gebühr",
            "steuer",
        ),
    },
    "versicherungen": {
        "folder": "Versicherungen",
        "keywords": (
            "versicherung",
            "versicherungen",
            "police",
            "vertrag",
            "beitrag",
            "schaden",
            "schadensmeldung",
            "haftpflicht",
            "krankenversicherung",
            "kfz versicherung",
            "allianz",
            "huk",
            "axa",
            "ergo",
        ),
    },
    "abonnements": {
        "folder": "Abonnements",
        "keywords": (
            "abo",
            "abos",
            "abonnement",
            "abonnements",
            "subscription",
            "mitgliedschaft",
            "verlängerung",
            "verlaengerung",
            "renewal",
            "kündigung",
            "kuendigung",
            "netflix",
            "spotify",
            "icloud",
            "apple",
            "youtube premium",
        ),
    },
}


def list_mailboxes(max_mailboxes: int = 25) -> list[MailboxSummary]:
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxMailboxes to {int(max_mailboxes)}
    set outputText to ""
    set outputCount to 0

    tell application "Mail"
        repeat with accountRef in every account
            set accountName to name of accountRef as string
            repeat with mailboxRef in every mailbox of accountRef
                if outputCount is greater than or equal to maxMailboxes then return outputText

                set mailboxName to name of mailboxRef as string
                set mailboxCount to 0
                try
                    set mailboxCount to count of messages of mailboxRef
                end try

                set outputText to outputText & accountName & fieldSeparator & mailboxName & fieldSeparator & mailboxCount & recordSeparator
                set outputCount to outputCount + 1
            end repeat
        end repeat
    end tell

    return outputText
    """

    raw_output = _run_applescript(script)
    return _parse_mailboxes(raw_output)


def list_inbox_messages(
    max_messages: int = 10,
    preview_chars: int = 700,
    account_name: str | None = None,
    mailbox_name: str | None = None,
    include_preview: bool = False,
) -> list[MailMessage]:
    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    include_preview_value = "true" if include_preview else "false"
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set maxMessages to {int(max_messages)}
    set previewChars to {int(preview_chars)}
    set includePreview to {include_preview_value}
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"
    set outputText to ""

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return ""

        set mailboxMessages to messages of targetMailbox
        set messageCount to count of mailboxMessages
        if messageCount is 0 then return ""

        if messageCount < maxMessages then
            set limitCount to messageCount
        else
            set limitCount to maxMessages
        end if

        repeat with messageIndex from 1 to limitCount
            set messageRef to item messageIndex of mailboxMessages
            set messageId to ""
            set senderText to ""
            set subjectText to ""
            set receivedText to ""
            set bodyText to ""

            try
                set messageId to id of messageRef as string
            end try

            try
                set senderText to sender of messageRef as string
            end try

            try
                set subjectText to subject of messageRef as string
            end try

            try
                set receivedText to date received of messageRef as string
            end try

            if includePreview then
                try
                    set bodyText to content of messageRef as string
                    if (length of bodyText) is greater than previewChars then
                        set bodyText to text 1 thru previewChars of bodyText
                    end if
                end try
            end if

            set outputText to outputText & messageId & fieldSeparator & senderText & fieldSeparator & subjectText & fieldSeparator & receivedText & fieldSeparator & bodyText & recordSeparator
        end repeat

        if outputText is "" then
            repeat with accountRef in every account
                repeat with mailboxRef in every mailbox of accountRef
                    set mailboxText to name of mailboxRef as string
                    if mailboxText is "INBOX" or mailboxText is "Posteingang" or mailboxText is "Eingang" then
                        set mailboxMessages to messages of mailboxRef
                        set messageCount to count of mailboxMessages
                        if messageCount > 0 then
                            if messageCount < maxMessages then
                                set limitCount to messageCount
                            else
                                set limitCount to maxMessages
                            end if

                            repeat with messageIndex from 1 to limitCount
                                set messageRef to item messageIndex of mailboxMessages
                                set senderText to ""
                                set subjectText to ""
                                set receivedText to ""

                                try
                                    set senderText to sender of messageRef as string
                                end try

                                try
                                    set subjectText to subject of messageRef as string
                                end try

                                try
                                    set receivedText to date received of messageRef as string
                                end try

                                set bodyText to ""
                                if includePreview then
                                    try
                                        set bodyText to content of messageRef as string
                                        if (length of bodyText) is greater than previewChars then
                                            set bodyText to text 1 thru previewChars of bodyText
                                        end if
                                    end try
                                end if

                                set outputText to outputText & "" & fieldSeparator & senderText & fieldSeparator & subjectText & fieldSeparator & receivedText & fieldSeparator & bodyText & recordSeparator
                            end repeat
                            exit repeat
                        end if
                    end if
                end repeat
            end repeat
        end if
    end tell

    return outputText
    """

    raw_output = _run_applescript(script)
    return _parse_messages(raw_output)


def unread_inbox_count(account_name: str | None = None, mailbox_name: str | None = None) -> int:
    """Just the unread count, without pulling any message content - used by the
    Dashboard's Mail card, which only needs a number plus a couple of recent
    subjects (from `list_inbox_messages`), not full message bodies."""
    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    script = f"""
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return "0"
        return (unread count of targetMailbox) as string
    end tell
    """
    raw_output = _run_applescript(script)
    try:
        return int(raw_output.strip())
    except ValueError:
        return 0


def fetch_message_previews(
    message_ids: list[str],
    preview_chars: int = 700,
    account_name: str | None = None,
    mailbox_name: str | None = None,
    max_scan: int = 80,
) -> dict[str, str]:
    cleaned_ids = [
        _escape_applescript_text(message_id)
        for message_id in message_ids
        if str(message_id).strip()
    ]
    if not cleaned_ids:
        return {}

    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    apple_ids = "{" + ", ".join(f'"{message_id}"' for message_id in cleaned_ids) + "}"
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set targetIds to {apple_ids}
    set maxScan to {int(max_scan)}
    set previewChars to {int(preview_chars)}
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"
    set outputText to ""

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return ""

        set mailboxMessages to messages of targetMailbox
        set messageCount to count of mailboxMessages
        if messageCount is 0 then return ""

        if messageCount < maxScan then
            set limitCount to messageCount
        else
            set limitCount to maxScan
        end if

        repeat with messageIndex from 1 to limitCount
            set messageRef to item messageIndex of mailboxMessages
            set messageId to ""
            try
                set messageId to id of messageRef as string
            end try

            if targetIds contains messageId then
                set bodyText to ""
                try
                    set bodyText to content of messageRef as string
                    if (length of bodyText) is greater than previewChars then
                        set bodyText to text 1 thru previewChars of bodyText
                    end if
                end try
                set outputText to outputText & messageId & fieldSeparator & bodyText & recordSeparator
            end if
        end repeat
    end tell

    return outputText
    """

    raw_output = _run_applescript(script)
    previews: dict[str, str] = {}
    for record in raw_output.split(RECORD_SEPARATOR):
        record = record.strip(" \n\r\t")
        if not record:
            continue
        fields = record.split(FIELD_SEPARATOR)
        if len(fields) < 2:
            continue
        previews[fields[0].strip()] = fields[1].strip()
    return previews


def list_unread_messages(max_messages: int = 10, preview_chars: int = 700) -> list[MailMessage]:
    return list_inbox_messages(max_messages=max_messages, preview_chars=preview_chars)


def export_categorized_mail_documents(
    categories: list[str] | None = None,
    max_messages: int = 80,
    account_name: str | None = None,
    mailbox_name: str | None = None,
    desktop_root: Path | None = None,
) -> list[MailDocumentExportResult]:
    selected_categories = normalize_document_categories(categories)
    if not selected_categories:
        selected_categories = ["rechnungen", "versicherungen", "abonnements"]

    root = desktop_root or Path.home() / "Desktop"
    root.mkdir(parents=True, exist_ok=True)

    messages = list_inbox_messages(
        max_messages=max_messages,
        account_name=account_name,
        mailbox_name=mailbox_name,
        include_preview=False,
    )

    results: list[MailDocumentExportResult] = []
    for category in selected_categories:
        category_config = MAIL_DOCUMENT_CATEGORIES[category]
        folder = root / str(category_config["folder"])
        folder.mkdir(parents=True, exist_ok=True)

        matched_messages = [
            message
            for message in messages
            if _message_matches_document_category(message, category)
        ]
        saved_files: list[str] = []
        note_files: list[str] = []

        if matched_messages:
            message_ids = [message.message_id for message in matched_messages if message.message_id]
            if message_ids:
                saved_files = _export_attachments_for_message_ids(
                    message_ids,
                    folder,
                    account_name=account_name,
                    mailbox_name=mailbox_name,
                )

            if not saved_files:
                note_ids = [message.message_id for message in matched_messages if message.message_id]
                if note_ids:
                    previews = fetch_message_previews(
                        note_ids,
                        preview_chars=1400,
                        account_name=account_name,
                        mailbox_name=mailbox_name,
                        max_scan=max_messages,
                    )
                    for message in matched_messages:
                        message.preview = previews.get(message.message_id, "")
                note_files = _write_message_notes(folder, category, matched_messages)

        results.append(
            MailDocumentExportResult(
                category=category,
                folder=str(folder),
                matched_messages=len(matched_messages),
                saved_files=saved_files,
                note_files=note_files,
            )
        )

    return results


def normalize_document_categories(categories: list[str] | None) -> list[str]:
    if not categories:
        return []

    normalized_categories: list[str] = []
    for category in categories:
        normalized = _normalize_text(category)
        if normalized in {"rechnung", "rechnungen", "beleg", "belege", "invoice"}:
            normalized = "rechnungen"
        elif normalized in {"versicherung", "versicherungen", "police", "policen"}:
            normalized = "versicherungen"
        elif normalized in {"abo", "abos", "abonnement", "abonnements", "subscription"}:
            normalized = "abonnements"

        if normalized in MAIL_DOCUMENT_CATEGORIES and normalized not in normalized_categories:
            normalized_categories.append(normalized)

    return normalized_categories


def move_matching_messages_to_trash(
    search_terms: list[str],
    max_messages: int = 50,
    account_name: str | None = None,
    mailbox_name: str | None = None,
) -> list[MailMessage]:
    cleaned_terms = [
        _escape_applescript_text(term)
        for term in search_terms
        if str(term).strip()
    ]
    if not cleaned_terms:
        return []

    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    apple_terms = "{" + ", ".join(f'"{term}"' for term in cleaned_terms) + "}"
    script = f"""
    set fieldSeparator to ASCII character 31
    set recordSeparator to ASCII character 30
    set targetTerms to {apple_terms}
    set maxMessages to {int(max_messages)}
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"
    set outputText to ""

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return ""

        set messagesToDelete to {{}}
        set messageCount to count of messages of targetMailbox
        if messageCount < maxMessages then
            set limitCount to messageCount
        else
            set limitCount to maxMessages
        end if

        repeat with messageIndex from 1 to limitCount
            set messageRef to item messageIndex of messages of targetMailbox
            set senderText to ""
            set subjectText to ""
            set messageId to ""

            try
                set senderText to sender of messageRef as string
            end try
            try
                set subjectText to subject of messageRef as string
            end try
            try
                set messageId to id of messageRef as string
            end try

            set searchableText to senderText & " " & subjectText
            repeat with targetTerm in targetTerms
                if searchableText contains (targetTerm as string) then
                    set end of messagesToDelete to messageRef
                    set outputText to outputText & messageId & fieldSeparator & senderText & fieldSeparator & subjectText & fieldSeparator & "" & fieldSeparator & "" & recordSeparator
                    exit repeat
                end if
            end repeat
        end repeat

        repeat with messageRef in messagesToDelete
            try
                delete messageRef
            end try
        end repeat
    end tell

    return outputText
    """

    raw_output = _run_applescript(script, timeout=20)
    return _parse_messages(raw_output)


def move_messages_to_trash(
    message_ids: list[str],
    account_name: str | None = None,
    mailbox_name: str | None = None,
) -> int:
    cleaned_ids = [
        _escape_applescript_text(message_id)
        for message_id in message_ids
        if str(message_id).strip()
    ]
    if not cleaned_ids:
        return 0

    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    apple_ids = "{" + ", ".join(f'"{message_id}"' for message_id in cleaned_ids) + "}"
    script = f"""
    set targetIds to {apple_ids}
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"
    set movedCount to 0

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return "0"

        set messagesToDelete to {{}}
        repeat with messageRef in messages of targetMailbox
            set messageId to ""
            try
                set messageId to id of messageRef as string
            end try

            if targetIds contains messageId then
                set end of messagesToDelete to messageRef
            end if
        end repeat

        repeat with messageRef in messagesToDelete
            try
                delete messageRef
                set movedCount to movedCount + 1
            end try
        end repeat
    end tell

    return movedCount as string
    """

    raw_output = _run_applescript(script, timeout=20)
    try:
        return int(raw_output.strip() or "0")
    except ValueError:
        return 0


def _escape_applescript_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').strip()


def _export_attachments_for_message_ids(
    message_ids: list[str],
    output_folder: Path,
    account_name: str | None = None,
    mailbox_name: str | None = None,
) -> list[str]:
    cleaned_ids = [
        _escape_applescript_text(message_id)
        for message_id in message_ids
        if str(message_id).strip()
    ]
    if not cleaned_ids:
        return []

    output_folder.mkdir(parents=True, exist_ok=True)
    output_folder_text = _escape_applescript_text(str(output_folder) + "/")
    configured_account = _escape_applescript_text(account_name or "")
    configured_mailbox = _escape_applescript_text(mailbox_name or "")
    apple_ids = "{" + ", ".join(f'"{message_id}"' for message_id in cleaned_ids) + "}"
    script = f"""
    set recordSeparator to ASCII character 30
    set targetIds to {apple_ids}
    set outputFolder to "{output_folder_text}"
    set configuredAccount to "{configured_account}"
    set configuredMailbox to "{configured_mailbox}"
    set outputText to ""

    on sanitizeFileName(sourceText)
        set cleanedText to sourceText as string
        set illegalChars to {{":", "/"}}
        repeat with illegalChar in illegalChars
            set AppleScript's text item delimiters to illegalChar as string
            set textParts to text items of cleanedText
            set AppleScript's text item delimiters to "-"
            set cleanedText to textParts as string
        end repeat
        set AppleScript's text item delimiters to ""
        if cleanedText is "" then set cleanedText to "mail-anhang"
        return cleanedText
    end sanitizeFileName

    tell application "Mail"
        set targetMailbox to missing value

        if configuredAccount is not "" and configuredMailbox is not "" then
            repeat with accountRef in every account
                set accountText to name of accountRef as string
                if accountText is configuredAccount then
                    repeat with mailboxRef in every mailbox of accountRef
                        set mailboxText to name of mailboxRef as string
                        if mailboxText is configuredMailbox then
                            set targetMailbox to mailboxRef
                            exit repeat
                        end if
                    end repeat
                end if
            end repeat
        end if

        if targetMailbox is missing value then
            try
                set targetMailbox to inbox
            end try
        end if

        if targetMailbox is missing value then return ""

        set messageIndex to 0
        repeat with messageRef in messages of targetMailbox
            set messageId to ""
            try
                set messageId to id of messageRef as string
            end try

            if targetIds contains messageId then
                set messageIndex to messageIndex + 1
                set attachmentIndex to 0
                repeat with attachmentRef in mail attachments of messageRef
                    set attachmentIndex to attachmentIndex + 1
                    set attachmentName to ""
                    try
                        set attachmentName to name of attachmentRef as string
                    end try
                    set safeName to my sanitizeFileName(attachmentName)
                    set savePath to outputFolder & messageIndex & "-" & attachmentIndex & "-" & safeName
                    try
                        save attachmentRef in POSIX file savePath
                        set outputText to outputText & savePath & recordSeparator
                    end try
                end repeat
            end if
        end repeat
    end tell

    return outputText
    """
    raw_output = _run_applescript(script, timeout=60)
    return [
        record.strip()
        for record in raw_output.split(RECORD_SEPARATOR)
        if record.strip()
    ]


def _message_matches_document_category(message: MailMessage, category: str) -> bool:
    config = MAIL_DOCUMENT_CATEGORIES.get(category)
    if not config:
        return False

    haystack = _normalize_text(
        " ".join(
            part
            for part in (message.sender, message.subject, message.received, message.preview)
            if part
        )
    )
    return any(_normalize_text(keyword) in haystack for keyword in config["keywords"])


def _write_message_notes(folder: Path, category: str, messages: list[MailMessage]) -> list[str]:
    note_files: list[str] = []
    for index, message in enumerate(messages, start=1):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base_name = sanitize_filename(message.subject or category)[:70] or category
        note_path = folder / f"{timestamp}-{index}-{base_name}.txt"
        note_path.write_text(
            "\n".join(
                (
                    f"Kategorie: {MAIL_DOCUMENT_CATEGORIES[category]['folder']}",
                    f"Von: {message.sender}",
                    f"Betreff: {message.subject}",
                    f"Empfangen: {message.received}",
                    "",
                    "Auszug:",
                    message.preview or "(Kein Mail-Text auslesbar.)",
                )
            ),
            encoding="utf-8",
        )
        note_files.append(str(note_path))
    return note_files


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[:/\\]+", "-", str(value).strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß ._()-]+", "", cleaned)
    return cleaned.strip(" ._") or "Mail"


def _normalize_text(value: str) -> str:
    text = str(value).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _run_applescript(script: str, timeout: int = 8) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Mail" to activate'],
                capture_output=True,
                text=True,
                timeout=4,
            )
        except Exception:
            pass
        time.sleep(1)
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout + 4,
            )
        except subprocess.TimeoutExpired:
            raise MailAccessError(
                "Apple Mail hat zu lange nicht geantwortet. Oeffne Mail einmal normal, "
                "warte bis der Posteingang geladen ist, und versuch es dann nochmal."
            )

    if result.returncode == 0:
        return result.stdout.strip()

    error_text = (result.stderr or result.stdout).strip()
    lowered_error = error_text.lower()
    if "not authorized" in lowered_error or "not allowed" in lowered_error:
        raise MailAccessError(
            "Apple Mail Zugriff wurde noch nicht erlaubt. Oeffne macOS "
            "Systemeinstellungen > Datenschutz & Sicherheit > Automation "
            "und erlaube Terminal oder VS Code den Zugriff auf Mail."
        )

    if "application can't be found" in lowered_error or "kann nicht gelesen werden" in lowered_error:
        raise MailAccessError(
            "Apple Mail ist aus dieser Umgebung gerade nicht erreichbar. "
            "Starte Jarvis aus deinem normalen Terminal und bestaetige die macOS-Frage, "
            "dass Terminal oder VS Code Mail steuern darf."
        )

    if "syntax error" in lowered_error and "klassenname" in lowered_error:
        raise MailAccessError(
            "Apple Mail konnte aus dieser Umgebung sein Scripting-Woerterbuch nicht sauber laden. "
            "Starte Jarvis aus deinem normalen Terminal, nicht aus einer isolierten Umgebung, "
            "und bestaetige die macOS-Automation-Freigabe fuer Mail."
        )

    raise MailAccessError(f"Apple Mail konnte nicht gelesen werden: {error_text}")


def _parse_messages(raw_output: str) -> list[MailMessage]:
    messages: list[MailMessage] = []
    if not raw_output:
        return messages

    for record in raw_output.split(RECORD_SEPARATOR):
        record = record.strip(" \n\r\t")
        if not record:
            continue

        fields = record.split(FIELD_SEPARATOR)
        if len(fields) < 5:
            continue

        messages.append(
            MailMessage(
                message_id=fields[0].strip(),
                sender=fields[1].strip(),
                subject=fields[2].strip() or "(Ohne Betreff)",
                received=fields[3].strip(),
                preview=fields[4].strip(),
            )
        )

    return messages


def _parse_mailboxes(raw_output: str) -> list[MailboxSummary]:
    mailboxes: list[MailboxSummary] = []
    if not raw_output:
        return mailboxes

    for record in raw_output.split(RECORD_SEPARATOR):
        record = record.strip()
        if not record:
            continue

        fields = record.split(FIELD_SEPARATOR)
        if len(fields) < 3:
            continue

        try:
            message_count = int(fields[2].strip())
        except ValueError:
            message_count = 0

        mailboxes.append(
            MailboxSummary(
                account=fields[0].strip() or "(Unbekanntes Konto)",
                mailbox=fields[1].strip() or "(Unbenannter Ordner)",
                message_count=message_count,
            )
        )

    return mailboxes
