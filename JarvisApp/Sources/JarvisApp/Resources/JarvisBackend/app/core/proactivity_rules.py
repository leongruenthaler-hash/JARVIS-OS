from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

"""Default Proactivity Engine rules (Master-Plan Abschnitt 8.4).

Deliberately scoped to data sources that are already robust, ISO-timestamped
Python data - NOT Calendar.app's AppleScript output. calendar_client.py's
"start"/"end" fields are locale-formatted date *strings* (e.g. German long
form) with no reliable, dependency-free way to parse them back into a
datetime here; a "Termin beginnt bald" / "zwei Termine ueberschneiden sich"
rule needs calendar_client.py itself to emit numeric date components first
(a real change to a working AppleScript query - see the calendar regression
fixed earlier this session). That's flagged as a follow-up, not implemented
here, to avoid touching that fragile query again without being able to test
against a real Calendar.app.
"""


def rule_low_disk_space(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    threshold_percent = float(config.get("proactivity_low_disk_percent_threshold", 10))
    critical_percent = float(config.get("proactivity_critical_disk_percent_threshold", 3))

    try:
        usage = shutil.disk_usage(str(Path.home()))
    except OSError:
        return []

    if usage.total <= 0:
        return []
    free_percent = (usage.free / usage.total) * 100
    if free_percent >= threshold_percent:
        return []

    free_gb = usage.free / (1024**3)
    priority = "kritisch" if free_percent < critical_percent else "wichtig"
    return [
        {
            "priority": priority,
            "message": f"Nur noch {free_gb:.1f} GB freier Speicherplatz ({free_percent:.1f}%).",
            "reason": (
                f"Freier Speicherplatz ({free_percent:.1f}%) liegt unter dem konfigurierten "
                f"Schwellenwert ({threshold_percent:.0f}%)."
            ),
            "data": {"free_gb": round(free_gb, 1), "free_percent": round(free_percent, 1)},
            "dedup_key": "low_disk_space",
        }
    ]


def rule_pending_calendar_actions_waiting(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    pending = context.get("pending_calendar_actions") or []
    if not pending:
        return []

    hours_threshold = float(config.get("proactivity_pending_calendar_action_hours", 2))
    now = datetime.now()
    old_enough = []
    for action in pending:
        proposed_at = str(action.get("proposed_at") or "")
        if not proposed_at:
            # Proposal predates the proposed_at field (or is malformed) - err toward
            # surfacing it rather than silently never nudging about it.
            old_enough.append(action)
            continue
        try:
            timestamp = datetime.fromisoformat(proposed_at)
        except ValueError:
            old_enough.append(action)
            continue
        if (now - timestamp).total_seconds() / 3600 >= hours_threshold:
            old_enough.append(action)

    if not old_enough:
        return []

    count = len(old_enough)
    noun = "Vorschlag" if count == 1 else "Vorschläge"
    sample = old_enough[0].get("title") or "ein Termin"
    return [
        {
            "priority": "relevant",
            "message": f"{count} Kalender-{noun} aus deinen Mails warten noch auf deine Bestätigung (u. a. {sample}).",
            "reason": (
                f"{count} aus Mail erkannte(r) Kalender-{noun} sind seit mindestens "
                f"{hours_threshold:.0f} Stunde(n) unbeantwortet."
            ),
            "data": {"count": count},
            "dedup_key": "pending_calendar_actions",
        }
    ]


def rule_unconfirmed_memory_facts(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    pending_facts = context.get("pending_confirmation_facts") or []
    min_count = int(config.get("proactivity_pending_facts_min_count", 3))
    if len(pending_facts) < min_count:
        return []

    count = len(pending_facts)
    return [
        {
            "priority": "information",
            "message": f"{count} Erinnerungen warten im Gedächtnis-Bereich auf deine Bestätigung.",
            "reason": f"{count} gespeicherte Fakten haben den Status 'pending_confirmation'.",
            "data": {"count": count},
            "dedup_key": "unconfirmed_memory_facts",
        }
    ]


def rule_new_unread_mail(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    new_messages = context.get("new_mail_messages") or []
    min_count = int(config.get("proactivity_new_mail_min_count", 3))
    if len(new_messages) < min_count:
        return []

    count = len(new_messages)
    first_subject = str((new_messages[0] or {}).get("subject") or "").strip()
    detail = f" (u. a. '{first_subject}')" if first_subject else ""
    return [
        {
            "priority": "relevant",
            "message": f"{count} neue Mail(s) seit dem letzten Hintergrund-Check{detail}.",
            "reason": f"Der letzte Mail-Hintergrundscan fand {count} neue Nachricht(en).",
            "data": {"count": count},
            "dedup_key": "new_unread_mail",
        }
    ]


DEFAULT_RULES = (
    ("low_disk_space", rule_low_disk_space),
    ("pending_calendar_actions_waiting", rule_pending_calendar_actions_waiting),
    ("unconfirmed_memory_facts", rule_unconfirmed_memory_facts),
    ("new_unread_mail", rule_new_unread_mail),
)


def register_default_rules(engine) -> None:
    for name, rule in DEFAULT_RULES:
        engine.register(name, rule)
