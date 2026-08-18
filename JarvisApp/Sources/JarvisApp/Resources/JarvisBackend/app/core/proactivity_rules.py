from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.intent_matching import fuzzy_word_match

"""Default Proactivity Engine rules (Master-Plan Abschnitt 8.4).

Die Kalender-Regeln (rule_calendar_event_starting_soon,
rule_calendar_events_overlap) wurden nachtraeglich ergaenzt, siehe
plans/2026-08-08-jarvis-termin-nudges.md: calendar_client.py liefert seitdem
zusaetzlich zu den locale-formatierten Text-Feldern auch numerische
Datumsbestandteile (year/month/day/hour/minute ueber AppleScripts eigene
Datumsobjekt-Eigenschaften, sprachunabhaengig), aus denen ein echtes
datetime pro Termin gebaut wird - vorher war das nicht moeglich (siehe
docs/proactivity.md).
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
            "data": {
                "count": count,
                "action_keys": [
                    action.get("action_key") for action in old_enough if action.get("action_key")
                ],
            },
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


def rule_photo_vision_analysis_completed(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Siehe plans/2026-08-16-jarvis-proaktive-abschluss-meldung.md - meldet einen
    abgeschlossenen lokalen Foto-Vision-Lauf, ohne dass der Nutzer aktiv nachfragen
    muss. Der Zeitstempel im dedup_key (statt eines festen Strings) ist Absicht,
    siehe rule_calendar_event_starting_soon oben: derselbe Lauf wird nur einmal
    gemeldet, ein SPAETERER, neuer Abschluss (z.B. der naechste Nacht-Lauf) bekommt
    einen neuen Key und wird trotzdem gemeldet, statt von der Cooldown-Logik der
    Engine dauerhaft verschluckt zu werden."""
    config = context.get("config") or {}
    if not bool(config.get("proactivity_photo_vision_completion_enabled", True)):
        return []

    run = context.get("photo_vision_run") or {}
    if run.get("status") != "completed":
        return []
    finished_at = str(run.get("finished_at") or "").strip()
    if not finished_at:
        return []
    analyzed = int(run.get("analyzed") or 0)
    if analyzed <= 0:
        return []

    count_phrase = "1 neues Foto" if analyzed == 1 else f"{analyzed} neue Fotos"
    errors = int(run.get("errors") or 0)
    error_note = f" ({errors} davon nicht analysierbar)" if errors else ""
    return [
        {
            "priority": "information",
            "message": f"Ich bin mit der Foto-Analyse durch, {count_phrase} beschrieben{error_note}.",
            "reason": f"Lokale Foto-Vision-Analyse abgeschlossen um {finished_at}, {analyzed} Foto(s) neu analysiert.",
            "data": {"analyzed": analyzed, "errors": errors, "finished_at": finished_at},
            "dedup_key": f"photo_vision_completed:{finished_at}",
        }
    ]


def rule_calendar_event_starting_soon(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    events = context.get("upcoming_calendar_events") or []
    soon_minutes = float(config.get("proactivity_calendar_event_soon_minutes", 15))
    now = datetime.now()

    results: list[dict[str, Any]] = []
    for event in events:
        start_dt = event.get("start_dt")
        if start_dt is None or event.get("all_day"):
            continue
        minutes_until = (start_dt - now).total_seconds() / 60
        if 0 <= minutes_until <= soon_minutes:
            title = str(event.get("title") or "Termin")
            results.append(
                {
                    "priority": "wichtig",
                    "message": f"{title} beginnt in {max(0, round(minutes_until))} Minute(n).",
                    "reason": (
                        f"Termin '{title}' beginnt um {start_dt:%H:%M} Uhr, das ist innerhalb "
                        f"der konfigurierten {soon_minutes:.0f}-Minuten-Vorwarnzeit."
                    ),
                    "data": {"title": title, "start": start_dt.isoformat()},
                    # Ein Zeitstempel pro dedup_key statt nur des Titels - derselbe
                    # wiederkehrende Termin an einem anderen Tag soll trotzdem erneut
                    # gemeldet werden, nicht dauerhaft als "schon gemeldet" gelten.
                    "dedup_key": f"calendar_soon:{title}:{start_dt.isoformat()}",
                }
            )
    return results


def rule_calendar_events_overlap(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    events = context.get("upcoming_calendar_events") or []
    lookahead_hours = float(config.get("proactivity_calendar_lookahead_hours", 6))
    now = datetime.now()
    horizon = now.timestamp() + lookahead_hours * 3600

    candidates = [
        event
        for event in events
        if event.get("start_dt") is not None
        and event.get("end_dt") is not None
        and now.timestamp() <= event["start_dt"].timestamp() <= horizon
    ]
    # Deterministisch sortieren, damit derselbe Termin-Vergleich immer denselben
    # dedup_key erzeugt, egal in welcher Reihenfolge upcoming_calendar_events
    # diesmal aus AppleScript zurueckkam.
    candidates.sort(key=lambda event: (event["start_dt"], str(event.get("title") or "")))

    results: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for index, first in enumerate(candidates):
        for other_index in range(index + 1, len(candidates)):
            second = candidates[other_index]
            if second["start_dt"] >= first["end_dt"]:
                # Termine sind zeitlich sortiert - sobald der naechste Termin erst
                # beginnt, nachdem der aktuelle schon vorbei ist, kann kein weiterer
                # nachfolgender Termin mehr mit `first` ueberlappen.
                break
            if (index, other_index) in seen_pairs:
                continue
            seen_pairs.add((index, other_index))
            first_title = str(first.get("title") or "Termin")
            second_title = str(second.get("title") or "Termin")
            results.append(
                {
                    "priority": "relevant",
                    "message": (
                        f"'{first_title}' ({first['start_dt']:%H:%M}) und '{second_title}' "
                        f"({second['start_dt']:%H:%M}) überschneiden sich."
                    ),
                    "reason": f"Beide Termine liegen zeitlich innerhalb der naechsten {lookahead_hours:.0f} Stunden und überlappen sich.",
                    "data": {
                        "first_title": first_title,
                        "second_title": second_title,
                        "first_start": first["start_dt"].isoformat(),
                        "second_start": second["start_dt"].isoformat(),
                    },
                    "dedup_key": f"calendar_overlap:{first['start_dt'].isoformat()}:{second['start_dt'].isoformat()}",
                }
            )
    return results


_GERMAN_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

# Haeufige, generische Termin-Titel-Woerter, die nie fuer sich allein einen
# Mail-Termin-Treffer ausloesen duerfen (sonst z.B. jede Mail mit "Meeting" im
# Namen faelschlich zu jedem Termin mit "Meeting" im Titel passen wuerde) -
# dieselbe Lehre wie die Fuellwort-Ausnahmeliste in core/intent_matching.py.
_GENERIC_TITLE_WORDS = frozenset(
    {
        "meeting", "call", "termin", "termine", "besprechung", "gespraech",
        "sync", "review", "planning", "standup", "abstimmung", "video",
        "telefonat", "chat", "the", "und", "mit", "bei", "von", "zum", "zur",
    }
)

# Generische Absender-Bezeichnungen (automatisierte Mails, Firmen-Postfaecher) -
# kein echter Personenname, darf also nie fuer sich allein einen Treffer
# ausloesen (beim Testen konkret aufgefallen: "Info <info@shop.de>" matchte
# faelschlich "Info-Abend Schule").
_GENERIC_SENDER_WORDS = frozenset(
    {
        "info", "support", "service", "team", "kontakt", "kundenservice",
        "noreply", "no-reply", "newsletter", "hello", "hallo", "admin",
        "office", "buero", "mail", "kunde", "bestellung", "rechnung",
    }
)


def _extract_sender_name(sender: str) -> str:
    """Baut einen Anzeigenamen aus dem rohen AppleScript-sender-Text
    ('Name <email@beispiel.de>' oder nur einer reinen E-Mail-Adresse)."""
    sender = str(sender or "").strip()
    if "<" in sender:
        name_part = sender.split("<", 1)[0].strip().strip('"').strip()
        email_part = sender.split("<", 1)[1].split(">", 1)[0]
    else:
        name_part = ""
        email_part = sender

    if name_part:
        return name_part

    local_part = email_part.split("@", 1)[0]
    return re.sub(r"[._\-]+", " ", local_part).strip()


def rule_mail_matches_upcoming_event(context: dict[str, Any]) -> list[dict[str, Any]]:
    config = context.get("config") or {}
    messages = context.get("new_mail_messages") or []
    events = context.get("upcoming_calendar_events") or []
    if not messages or not events:
        return []

    lookahead_hours = float(config.get("proactivity_calendar_lookahead_hours", 6))
    now = datetime.now()
    horizon = now.timestamp() + lookahead_hours * 3600
    candidate_events = [
        event
        for event in events
        if event.get("start_dt") is not None and now.timestamp() <= event["start_dt"].timestamp() <= horizon
    ]
    if not candidate_events:
        return []

    results: list[dict[str, Any]] = []
    seen_pairs: set[str] = set()
    for message in messages:
        sender_name = _extract_sender_name(str(message.get("sender") or ""))
        name_words = [
            word
            for word in sender_name.lower().split()
            if len(word) > 2 and word not in _GENERIC_SENDER_WORDS
        ]
        if not name_words:
            continue

        for event in candidate_events:
            title = str(event.get("title") or "")
            title_words = [
                word
                for word in re.findall(r"[a-zA-ZäöüÄÖÜß]+", title.lower())
                if len(word) > 2 and word not in _GENERIC_TITLE_WORDS
            ]
            if not title_words:
                continue
            if not any(fuzzy_word_match(word, tuple(title_words), max_distance=1) for word in name_words):
                continue

            start_dt = event["start_dt"]
            mail_id = str(message.get("id") or message.get("subject") or "")
            pair_key = f"{mail_id}:{title}:{start_dt.isoformat()}"
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            weekday = _GERMAN_WEEKDAYS[start_dt.weekday()]
            results.append(
                {
                    "priority": "relevant",
                    "message": (
                        f"Mail von {sender_name} ist da — ihr habt '{title}' am {weekday} "
                        f"um {start_dt:%H:%M} Uhr."
                    ),
                    "reason": f"Absendername '{sender_name}' passt zum Titel des anstehenden Termins '{title}'.",
                    "data": {
                        "sender": sender_name,
                        "subject": str(message.get("subject") or ""),
                        "event_title": title,
                        "event_start": start_dt.isoformat(),
                    },
                    "dedup_key": f"mail_event_match:{pair_key}",
                }
            )
            # Ein Treffer pro Mail reicht - verhindert, dass eine einzelne Mail
            # gegen mehrere aehnlich benannte Termine mehrfach meldet.
            break
    return results


def rule_recurring_usage_pattern(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Baustein D, siehe plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md.
    Liest bereits fertig ausgewertete Muster aus dem Context (Kategorie + grobe
    Zeit, siehe core/usage_patterns.py) - diese Regel selbst sieht nie den
    Anfrage-Wortlaut, nur was ihr im Context uebergeben wird."""
    config = context.get("config") or {}
    patterns = context.get("recurring_usage_patterns") or []
    if not patterns:
        return []

    min_weeks = int(config.get("proactivity_pattern_min_weeks", 3))
    results: list[dict[str, Any]] = []
    for pattern in patterns:
        week_count = int(pattern.get("week_count", 0))
        if week_count < min_weeks:
            continue
        domain = str(pattern.get("domain") or "")
        weekday_name = str(pattern.get("weekday_name") or "")
        time_bucket = str(pattern.get("time_bucket") or "")
        results.append(
            {
                "priority": "information",
                "message": (
                    f"Du fragst seit {week_count} Wochen {weekday_name}s {time_bucket} nach "
                    f"'{domain}' - soll ich dir das automatisch zeigen?"
                ),
                "reason": (
                    f"Muster '{domain}/{weekday_name}/{time_bucket}' kam in {week_count} der "
                    "letzten Wochen vor."
                ),
                "data": {"domain": domain, "weekday_name": weekday_name, "time_bucket": time_bucket},
                # Ein dedup_key pro Muster, nicht pro Vorkommen - der Vorschlag kommt
                # einmalig, danach greift dismiss_forever/snooze wie bei jeder Regel.
                "dedup_key": f"usage_pattern:{domain}:{weekday_name}:{time_bucket}",
            }
        )
    return results


def rule_important_news(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Baustein "Wichtige Nachrichten", siehe
    plans/2026-08-09-jarvis-news-baustein.md. Liest ausschliesslich bereits
    fertig als wichtig eingestufte Meldungen aus dem Context
    (news_background_worker.py::drain_important_news()) - diese Regel selbst
    ruft nie ein Sprachmodell auf, bleibt also wie jede andere Regel eine reine,
    deterministische Funktion (siehe proactivity_engine.py's Grundprinzip)."""
    news_items = context.get("important_news") or []
    if not news_items:
        return []

    if len(news_items) == 1:
        item = news_items[0]
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        message = f"Wichtige Meldung von CORRECTIV: {title}."
        if summary:
            message += f" {summary}"
    else:
        titles = "; ".join(str(item.get("title") or "").strip() for item in news_items[:3])
        message = f"{len(news_items)} wichtige Meldungen von CORRECTIV, u. a.: {titles}."

    ids = sorted(str(item.get("id") or "") for item in news_items)
    dedup_key = "important_news:" + hashlib.sha1(",".join(ids).encode("utf-8")).hexdigest()[:12]

    return [
        {
            "priority": "wichtig",
            "message": message,
            "reason": f"{len(news_items)} neue, als wichtig eingestufte Meldung(en) von CORRECTIV.",
            "data": {"count": len(news_items), "titles": [item.get("title") for item in news_items]},
            "dedup_key": dedup_key,
        }
    ]


DEFAULT_RULES = (
    ("low_disk_space", rule_low_disk_space),
    ("pending_calendar_actions_waiting", rule_pending_calendar_actions_waiting),
    ("unconfirmed_memory_facts", rule_unconfirmed_memory_facts),
    ("new_unread_mail", rule_new_unread_mail),
    ("calendar_event_starting_soon", rule_calendar_event_starting_soon),
    ("calendar_events_overlap", rule_calendar_events_overlap),
    ("mail_matches_upcoming_event", rule_mail_matches_upcoming_event),
    ("recurring_usage_pattern", rule_recurring_usage_pattern),
    ("important_news", rule_important_news),
    ("photo_vision_analysis_completed", rule_photo_vision_analysis_completed),
)


def register_default_rules(engine) -> None:
    for name, rule in DEFAULT_RULES:
        engine.register(name, rule)
