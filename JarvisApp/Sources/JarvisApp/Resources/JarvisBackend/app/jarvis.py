from __future__ import annotations

import json
import os
import sys
import tempfile
import re
import threading
import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL.*",
    category=Warning,
)

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

from background_tasks import MailBackgroundWorker
from audio_stream import StreamingAudioListener
from contacts_client import ContactAccessError, call_contact_by_name, call_phone_number, find_contacts, list_contacts
from calendar_client import (
    CalendarAccessError,
    create_calendar_event,
    create_reminder,
    delete_calendar_event,
    delete_reminder,
    events_on_date,
    list_open_reminders,
    list_upcoming_calendar_items,
)
from desktop_client import (
    DesktopAccessError,
    clean_desktop_name,
    create_desktop_folder,
    move_desktop_item,
    move_desktop_items_matching,
    search_desktop,
    summarize_desktop,
)
from files_client import (
    FileAccessError,
    clean_file_name,
    copy_item,
    create_folder,
    detect_root_hint,
    find_item,
    list_cleanup_candidates,
    move_item,
    move_items_matching,
    move_to_trash,
    search_files,
    suggest_cleanup_files,
    summarize_folder,
)
from llm_client import LLMClient
from mail_client import (
    MailAccessError,
    export_categorized_mail_documents,
    fetch_message_previews,
    list_inbox_messages,
    list_mailboxes,
    move_matching_messages_to_trash,
    move_messages_to_trash,
    normalize_document_categories,
    search_messages_by_terms,
    unread_inbox_count,
)
from mail_calendar_actions import _extract_datetime
from core.action_engine import ACTION_ENGINE, ActionProposal
from core.context_engine import CONTEXT_ENGINE, active_context_pack
from core.conversation_manager import ConversationManager
from core.daily_briefing import build_daily_briefing
from core.memory_system import JarvisMemorySystem
from core.task_manager import TaskManager
from core.usage_patterns import record_pattern_event
from core import (
    voice_mode_instruction,
    voice_mode_forces_compact,
    voice_mode_forces_local_only,
    voice_mode_disables_web_search,
    normalize_voice_mode,
)
from core.intent_matching import has_domain_fuzzy, normalize_umlauts
from core.multistep_planner import plan_multistep
from memory import Memory
from model_manager import ModelManager
from music_client import (
    MusicAccessError,
    adjust_volume,
    list_playlists,
    next_track,
    now_playing,
    pause_music,
    play_music,
    play_playlist,
    play_search,
    previous_track,
)
from notes_client import NotesAccessError, append_to_note, create_note, delete_note, list_recent_notes
from permission_manager import PermissionManager
from privacy_dashboard import PrivacyDashboard
from privacy_logger import PrivacyLogger
from secure_storage import (
    SecureStorageError,
    check_secure_storage,
    delete_openai_api_key,
    prompt_and_store_openai_key,
    remove_openai_key_from_env_file,
)
from photos_client import (
    PhotoBackgroundWorker,
    PhotosAccessError,
    extract_photo_count_query,
    extract_photo_query,
)
from action_confirmation import PlannedAction, confirmation_text, requires_confirmation
from data_dir import data_root
from settings import load_config
from stt_engines import STTEngineError, create_stt_engine
from fast_intent_router import FastIntentRouter
from model_router import ModelRouter
from jarvis_personality import build_compact_jarvis_system_prompt, build_jarvis_system_prompt, normalize_jarvis_messages
from voice_output import VoiceOutput
from web_search import check_internet_access, format_search_results, search_web


JARVIS_VERSION = "2026-06-26-audio-v3"

load_dotenv(data_root() / ".env")

CONFIG = load_config()


def _fresh_profile_config() -> dict[str, Any]:
    try:
        return load_config()
    except Exception:
        return CONFIG


def configured_user_name() -> str:
    fresh = _fresh_profile_config()
    return str(fresh.get("creator_name") or "Nutzer").strip() or "Nutzer"


def configured_user_address() -> str:
    fresh = _fresh_profile_config()
    salutation = str(fresh.get("user_salutation") or "sir").strip().lower()
    if salutation == "madam":
        return "Madam"
    if salutation == "none":
        return configured_user_name()
    return "Sir"


SAMPLERATE = int(CONFIG.get("samplerate", 16000))
INPUT_DEVICE = CONFIG.get("input_device")
CHANNELS = 1
MAX_RECORDING_SECONDS = int(CONFIG.get("max_recording_seconds", 20))
MIN_SPEECH_SECONDS = float(CONFIG.get("min_speech_seconds", 0.45))
MIN_AUDIO_PEAK = float(CONFIG.get("min_audio_peak", 0.025))
AUDIO_GAIN_TARGET = float(CONFIG.get("audio_gain_target", 0.18))
STT_ENGINE = str(CONFIG.get("stt_engine", "moonshine_streaming"))
CHUNK_SECONDS = float(CONFIG.get("chunk_seconds", 0.3))
SILENCE_LIMIT = float(CONFIG.get("silence_limit", 0.55))
VOLUME_THRESHOLD = float(CONFIG.get("volume_threshold", 0.008))
WEB_SEARCH_ENABLED = bool(CONFIG.get("web_search_enabled", True))
WEB_SEARCH_MAX_RESULTS = int(CONFIG.get("web_search_max_results", 5))
WEB_SEARCH_AUTO = bool(CONFIG.get("web_search_auto", True))
MAIL_ENABLED = bool(CONFIG.get("mail_enabled", True))
MAIL_MAX_MESSAGES = int(CONFIG.get("mail_max_messages", 8))
MAIL_INBOX_ACCOUNT = CONFIG.get("mail_inbox_account")
MAIL_INBOX_MAILBOX = CONFIG.get("mail_inbox_mailbox")
_RESOLVED_MAIL_INBOX: tuple[str, str] | None = None


def resolve_mail_inbox() -> tuple[str, str]:
    """Liefert (account_name, mailbox_name) fuer das Haupt-Postfach. Faellt auf
    Auto-Erkennung zurueck (erste Mailbox namens "INBOX", ueber alle Accounts),
    wenn mail_inbox_account/mail_inbox_mailbox in der Config leer sind - das ist
    genau der Standard in config.beta-template.json fuer frische Installationen.
    Ohne diese Auto-Erkennung blieben Mail-Status, Mail-Zusammenfassung und die
    Mail-Loesch-/Export-Befehle fuer JEDEN frischen Tester dauerhaft funktionslos,
    obwohl Mail.app korrekt verbunden ist - live beobachtet 2026-08-18:
    check_mail_status() meldete "iCloud INBOX macht Verstecken", obwohl die
    iCloud-INBOX mit 370 Nachrichten nachweislich vorhanden war. Ergebnis wird
    zwischengespeichert, damit nicht jede Mail-Anfrage erneut alle Mailboxen
    abfragt."""
    global _RESOLVED_MAIL_INBOX
    if MAIL_INBOX_ACCOUNT and MAIL_INBOX_MAILBOX:
        return MAIL_INBOX_ACCOUNT, MAIL_INBOX_MAILBOX
    if _RESOLVED_MAIL_INBOX is not None:
        return _RESOLVED_MAIL_INBOX
    try:
        for mailbox in list_mailboxes(max_mailboxes=50):
            if mailbox.mailbox.strip().lower() == "inbox":
                _RESOLVED_MAIL_INBOX = (mailbox.account, mailbox.mailbox)
                return _RESOLVED_MAIL_INBOX
    except Exception:
        pass
    return MAIL_INBOX_ACCOUNT, MAIL_INBOX_MAILBOX
MUSIC_ENABLED = bool(CONFIG.get("music_enabled", True))
CONTACTS_ENABLED = bool(CONFIG.get("contacts_enabled", True))
NOTES_ENABLED = bool(CONFIG.get("notes_enabled", True))
PHOTOS_ENABLED = bool(CONFIG.get("photos_enabled", True))
RECENT_CONTEXT_MESSAGES = min(int(CONFIG.get("recent_context_messages", 6)), 6)
AUTO_MEMORY_ENABLED = bool(CONFIG.get("auto_memory_enabled", True))
AUTO_MEMORY_MAX_FACTS = int(CONFIG.get("auto_memory_max_facts", 120))
AUTO_MEMORY_LLM_EXTRACTION_ENABLED = bool(CONFIG.get("auto_memory_llm_extraction_enabled", False))
MEMORY_SUMMARY_MAX_FACTS = int(CONFIG.get("memory_summary_max_facts", 10))
CONTEXT_ENGINE.max_facts = MEMORY_SUMMARY_MAX_FACTS
PERFORMANCE_LOG = bool(CONFIG.get("performance_log", True))
OPENAI_MAX_OUTPUT_TOKENS = int(CONFIG.get("openai_max_output_tokens", 180))
MAIL_SUMMARY_MAX_OUTPUT_TOKENS = int(CONFIG.get("mail_summary_max_output_tokens", 320))
AKTIVIERUNGSWOERTER = CONFIG.get("wake_words", ["jarvis"])
VOICE_OUTPUT = VoiceOutput(CONFIG)
PRIVACY_LOGGER = PrivacyLogger(enabled=bool(CONFIG.get("privacy_logging_enabled", True)))
FAST_INTENT_ROUTER = FastIntentRouter()
MODEL_ROUTER = ModelRouter(CONFIG)

END_PHRASES = {
    "danke jarvis das passt",
    "danke jarvis das passt soweit",
    "danke das passt",
    "danke das passt soweit",
    "nein danke das passt",
    "nein danke das passt soweit",
    "das passt",
    "das passt soweit",
    "passt soweit",
    "bis später",
    "bis spaeter",
    "tschüss",
    "tschuess",
    "beenden",
    "stop",
}


def permissions_required() -> bool:
    return bool(CONFIG.get("privacy_require_permissions", True))


# A pending permission confirmation ("Sag ja zum Erlauben") used to stay open
# indefinitely - any later, completely unrelated "ja"/"okay" could silently confirm
# it. 5 minutes is generous for a real back-and-forth but short enough that it can't
# survive into an unrelated later conversation.
PENDING_PERMISSION_TTL_SECONDS = 300

# Wie lange eine ausgelieferte "X Kalender-Vorschlaege warten auf deine
# Bestaetigung"-Meldung im Chat noch per freiem Satz ("das bestaetige ich
# nicht") beantwortbar ist. Grosszuegiger als PENDING_PERMISSION_TTL_SECONDS,
# weil Leon eine Proaktivitaets-Meldung oft erst Stunden spaeter liest -
# siehe plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.
PENDING_MAIL_CALENDAR_CONFIRMATION_TTL_SECONDS = 24 * 3600

# Wie lange ein gerade im Chat gezeigter Speicherplatz-Aufraeum-Vorschlag noch
# per "ja"/"lösch die" bestaetigt werden kann - kuerzer als die Kalender-TTL,
# weil das hier eine unmittelbare Gespraechsfolge ist (der Vorschlag wurde
# gerade erst gezeigt), nicht eine Stunden spaeter gelesene Benachrichtigung.
# Siehe plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md.
PENDING_CLEANUP_CONFIRMATION_TTL_SECONDS = 30 * 60


def ensure_permission(memory: Memory, permission: str, action_summary: str) -> str | None:
    if not permissions_required():
        return None
    manager = PermissionManager()
    if manager.is_allowed(permission):
        return None

    settings = memory.get("settings") or {}
    settings["pending_permission"] = {
        "permission": permission,
        "action": action_summary,
        "set_at": time.time(),
    }
    memory.set("settings", settings)
    manager.mark_explanation_shown(permission)
    privacy_log("permission_manager", "pending_permission_set", permission=permission, action=action_summary)
    return (
        f"Dafür brauche ich Ihre ausdrückliche Zustimmung für {permission}. "
        f"Warum: {manager.explanation(permission)} "
        f"Geplante Nutzung: {action_summary}. Sag ja zum Erlauben oder nein zum Abbrechen."
    )


def has_permission(permission: str) -> bool:
    if not permissions_required():
        return True
    return PermissionManager().is_allowed(permission)


def ensure_cloud_llm_permission(memory: Memory, question: str) -> str | None:
    provider = ModelManager(CONFIG).provider
    if provider not in {"openai", "anthropic", "google"}:
        return None
    external = ensure_permission(memory, "external_api", "Jarvis würde einen externen API-Dienst verwenden.")
    if external:
        return external
    return ensure_permission(
        memory,
        "cloud_llm",
        "Jarvis würde Ihre Anfrage an eine Cloud-KI senden, um eine Antwort zu erzeugen.",
    )


def ensure_privacy_domain_permission(memory: Memory, permission: str, action_summary: str) -> str | None:
    return ensure_permission(memory, permission, action_summary)


def handle_privacy_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("datenschutz", "privacy", "berechtigung", "berechtigungen", "logs", "verlauf", "daten export", "daten löschen", "daten loeschen")):
        return None

    dashboard = PrivacyDashboard(CONFIG)
    manager = PermissionManager()

    # \b vor "aktiviere" ist notwendig, nicht nur Stil: ohne Wortgrenze matchte
    # "aktiviere" auch als Teilstring von "deaktiviere" ("de" + "aktiviere"), also
    # loeste z.B. "deaktiviere dateien" faelschlich grant_match aus (der VOR
    # revoke_match geprueft wird) und hat die Berechtigung erlaubt statt
    # entzogen - in der Praxis so gefunden.
    grant_match = re.search(r"\b(?:erlaube|aktiviere)\s+(mail|kalender|erinnerungen|kontakte|dateien|mikrofon|kamera|standort|internet|fotos|photos|bildschirm|ki|cloud|speicher|memory)", normalized)
    revoke_match = re.search(r"\b(?:deaktiviere|verbiete|entziehe)\s+(mail|kalender|erinnerungen|kontakte|dateien|mikrofon|kamera|standort|internet|fotos|photos|bildschirm|ki|cloud|speicher|memory)", normalized)
    mapping = {
        "mikrofon": "microphone",
        "kamera": "camera",
        "standort": "location",
        "kalender": "calendar",
        "erinnerungen": "reminders",
        "kontakte": "contacts",
        "dateien": "files",
        "fotos": "photos",
        "photos": "photos",
        "bildschirm": "screen",
        "ki": "cloud_llm",
        "cloud": "cloud_llm",
        "speicher": "memory",
        "memory": "memory",
        "notizen": "notes",
        "notiz": "notes",
        "musik": "music",
        "music": "music",
        "mail": "mail",
        "internet": "internet",
    }
    if grant_match:
        permission = mapping.get(grant_match.group(1))
        if permission:
            manager.grant(permission)
            return f"Erlaubt: {permission}. Sie können diese Berechtigung jederzeit wieder deaktivieren."
    if revoke_match:
        permission = mapping.get(revoke_match.group(1))
        if permission:
            manager.revoke(permission)
            return f"Deaktiviert: {permission}. Jarvis nutzt diesen Bereich nicht mehr ohne neue Zustimmung."

    if "export" in normalized:
        path = dashboard.export_data()
        return f"Datenschutz-Export erstellt: {path}"
    if "alle daten" in normalized and ("lösch" in normalized or "loesch" in normalized):
        return dashboard.delete_all_data()
    if "verlauf" in normalized and ("lösch" in normalized or "loesch" in normalized):
        return dashboard.delete_history()
    if "logs" in normalized and ("lösch" in normalized or "loesch" in normalized):
        return dashboard.clear_logs()

    return dashboard.status()


def privacy_log(module: str, event: str, success: bool = True, **metadata):
    try:
        PRIVACY_LOGGER.log(module, event, success=success, **metadata)
    except Exception:
        pass


def console_text(text: str, kind: str = "content") -> str:
    if bool(CONFIG.get("privacy_redact_console", True)) and kind in {"transcript", "prompt", "answer", "search"}:
        return "[redacted]"
    return str(text)


def get_input_device():
    env_device = os.getenv("JARVIS_INPUT_DEVICE")
    configured_device = env_device if env_device is not None else INPUT_DEVICE

    if configured_device in (None, ""):
        default_input = sd.default.device[0]
        if default_input == -1:
            fallback_device = find_first_input_device()
            if fallback_device is not None:
                print(f"Kein Standard-Mikrofon gesetzt. Nutze Eingabegerät {fallback_device}.")
                return fallback_device

            raise RuntimeError(
                "Kein Standard-Mikrofon gefunden. Oeffne macOS Systemeinstellungen > "
                "Datenschutz & Sicherheit > Mikrofon und erlauben Sie Ihrem Terminal den Zugriff. "
                "Falls noetig, ermittle danach die Geraetenummer mit: "
                ".venv/bin/python -m sounddevice"
            )
        return None

    try:
        return int(configured_device)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "input_device muss eine Geraetenummer sein, zum Beispiel 0 oder 1."
        ) from exc


def find_first_input_device() -> int | None:
    try:
        devices = sd.query_devices()
    except Exception:
        return None

    for index, device in enumerate(devices):
        try:
            if int(device.get("max_input_channels", 0)) > 0:
                return index
        except AttributeError:
            continue

    return None


def remove_wake_word(text: str) -> tuple[bool, str]:
    aliases = {
        normalize_text(word)
        for word in AKTIVIERUNGSWOERTER
    }
    aliases.update(
        {
            "jarvis",
            "javis",
            "jarves",
            "jarvice",
            "jarvies",
            "jarvisse",
            "jathers",
            "jaros",
            "jarus",
            "trabbers",
            "jobs",
            "john",
            "thomas",
        }
    )

    # Ueber Spans auf dem Original-Text arbeiten statt ueber re.findall() + " ".join():
    # Letzteres zerlegt in reine Wort-Tokens und verliert dabei jede Interpunktion
    # aus dem Rest des Satzes (z.B. wird aus "19:00 Uhr" "19 00 Uhr" - der
    # Doppelpunkt verschwindet), was nachgelagerte Uhrzeit-/Datums-Regexe wie
    # _extract_time() in mail_calendar_actions.py falsch parsen laesst. Live-Bug:
    # "Jarvis erstell mir heute einen Termin um 19:00 Uhr telefonieren" wurde zu
    # einem Termin um 00:00 Uhr.
    matches = list(re.finditer(r"[\wäöüÄÖÜß]+", text, flags=re.UNICODE))
    found_index: int | None = None

    for index, match in enumerate(matches):
        normalized_word = normalize_text(match.group(0))
        if normalized_word in aliases or _looks_like_wake_word(normalized_word):
            found_index = index
            break

    if found_index is None:
        return False, text.strip(" ,.!?;:")

    remove_from_index = found_index
    if found_index > 0 and normalize_text(matches[found_index - 1].group(0)) in {"hallo", "hey", "hi"}:
        remove_from_index = found_index - 1

    start = matches[remove_from_index].start()
    end = matches[found_index].end()
    cleaned = text[:start] + text[end:]
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip(" ,.!?;:")
    if normalize_text(cleaned) in {"hallo", "hey", "hi"}:
        cleaned = ""

    return True, cleaned


_WAKE_WORD_FALSE_POSITIVES = {"warum", "darum", "jargon"}


def _looks_like_wake_word(word: str) -> bool:
    if len(word) < 4:
        return False
    if word in _WAKE_WORD_FALSE_POSITIVES:
        return False

    candidates = ("jarvis", "javis", "jaros", "jarus", "jathers", "trabbers")
    return min(_levenshtein_distance(word, candidate) for candidate in candidates) <= 2


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0

    if not left:
        return len(right)

    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current

    return previous[-1]


def prepare_audio_for_stt(audio: np.ndarray) -> np.ndarray:
    audio = audio.astype(np.float32)
    audio = audio - float(np.mean(audio))

    peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return audio

    if peak < AUDIO_GAIN_TARGET:
        audio = audio * (AUDIO_GAIN_TARGET / peak)

    return np.clip(audio, -1.0, 1.0)


def build_input(
    memory: Memory,
    user_text: str,
    web_context: str | None = None,
    transient_history: list[dict[str, str]] | None = None,
    compact: bool = False,
) -> list[dict[str, str]]:
    personality = memory.get("personality") or {}
    self_model = memory.get("self_model") or {}
    settings = memory.get("settings") or {}
    if bool(CONFIG.get("privacy_store_conversation", False)):
        try:
            previous_conversation = ConversationManager().as_messages(recent_limit=RECENT_CONTEXT_MESSAGES)
        except Exception:
            previous_conversation = memory.get("conversation") or []
    else:
        previous_conversation = []
    fresh_profile = _fresh_profile_config()
    assistant_name = fresh_profile.get("assistant_name", "Jarvis")
    creator_name = fresh_profile.get("creator_name", "Leon")
    user_salutation = fresh_profile.get("user_salutation", "sir")
    # Context Engine picks facts relevant to user_text first, then fills up to the
    # budget with the most recent ones - replaces the old build_memory_summary(), which
    # only ever returned the N most-recently-updated facts regardless of the question.
    memory_summary = CONTEXT_ENGINE.build_memory_summary(
        memory, user_text, context_pack=active_context_pack(CONFIG)
    )
    temporary_style = get_temporary_style_instruction(settings)
    # Master-Plan Abschnitt 6.4 (Gesprächsmodi). "kurz"/"diskret" force the compact
    # prompt regardless of what the model router decided based on message length.
    voice_mode = str(settings.get("voice_mode") or "standard")
    mode_instruction = voice_mode_instruction(voice_mode)
    effective_compact = compact or voice_mode_forces_compact(voice_mode)

    if effective_compact:
        system_text = build_compact_jarvis_system_prompt(
            assistant_name=assistant_name,
            creator_name=creator_name,
            user_salutation=user_salutation,
            personality=personality,
            memory_summary=memory_summary,
            mode_instruction=mode_instruction,
            self_model=self_model,
        )
    else:
        system_text = build_jarvis_system_prompt(
            assistant_name=assistant_name,
            creator_name=creator_name,
            user_salutation=user_salutation,
            personality=personality,
            memory_summary=memory_summary,
            temporary_style=temporary_style,
            mode_instruction=mode_instruction,
            self_model=self_model,
        )

    combined_history = list(previous_conversation)
    if transient_history:
        combined_history.extend(transient_history)

    recent_messages = [
        message
        for message in combined_history[-RECENT_CONTEXT_MESSAGES:]
        if "plattform" not in message.get("content", "").lower()
        and "memory-funktion" not in message.get("content", "").lower()
        and "memory aktiv" not in message.get("content", "").lower()
    ]
    if web_context:
        source_instruction = (
            f"Nenne keine Quellen oder URLs, außer {creator_name} fragt ausdrücklich danach."
            if not settings.get("include_sources", False)
            else "Nenne am Ende die wichtigsten Quellen als URLs."
        )
        user_text = (
            "Beantworte die Frage mit Hilfe der folgenden aktuellen Web-Suchergebnisse. "
            f"Antworte auf Deutsch, knapp. {source_instruction}\n\n"
            f"Frage: {user_text}\n\n"
            f"Web-Suchergebnisse:\n{web_context}"
        )

    return normalize_jarvis_messages([
        {"role": "system", "content": system_text},
        *recent_messages,
        {"role": "user", "content": user_text},
    ], recent_limit=RECENT_CONTEXT_MESSAGES + 1, fallback_system_prompt=system_text)


def route_fast_intent(question: str) -> str | None:
    decision = FAST_INTENT_ROUTER.route(question)
    if decision is None:
        return None

    if decision.intent in {"show_time", "show_date"} and decision.response:
        return decision.response

    if decision.intent == "open_app" and decision.target:
        import subprocess

        try:
            result = subprocess.run(["open", "-a", decision.target], capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            return f"Ich habe {decision.target} gestartet, aber macOS brauchte dafür etwas zu lange."

        if result.returncode == 0:
            return f"Ich öffne {decision.target}, {configured_user_address()}."
        error_text = (result.stderr or result.stdout or "").strip()
        return f"Ich konnte {decision.target} gerade nicht öffnen: {error_text or 'Unbekannter Fehler'}"

    if decision.intent == "model_status":
        return ModelManager(CONFIG).status_text()

    if decision.intent == "user_identity":
        name = configured_user_name()
        fresh = _fresh_profile_config()
        salutation = str(fresh.get("user_salutation") or "sir").strip().lower()
        if salutation == "none":
            return f"Du heißt {name}."
        return f"Sie heißen {name}, {configured_user_address()}."

    if decision.intent == "status":
        return f"Alles läuft, {configured_user_address()}."

    return None


def today_key() -> str:
    return date.today().isoformat()


def get_temporary_style_instruction(settings: dict) -> str:
    temporary_style = settings.get("temporary_style")
    if not isinstance(temporary_style, dict):
        return ""

    if temporary_style.get("date") != today_key():
        return ""

    instruction = temporary_style.get("instruction", "")
    if not instruction:
        return ""

    return f"Heutiger Tagesstil: {instruction} "


def normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[,;:]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" ,.!?;:")


# Satzanfaenge, an denen eine Nachricht eher wie eine eigenstaendige Frage
# klingt als wie die Antwort auf eine offene Rueckfrage (Notiz-Inhalt,
# Kalender-Bestaetigung, Aufraeum-Bestaetigung, ...). Frueher hatten
# handle_pending_note_flow() und handle_pending_action_flow() je eine eigene,
# leicht unterschiedliche Kopie dieser Liste - die Notiz-Kopie kannte W-Fragen
# UND "hast du"/"kannst du"/"gibt es", die Bestaetigungs-Kopie nur W-Fragen.
# Genau diese Luecke sorgte in der Runde-2-Simulation (2026-08-13) dafuer,
# dass "Hab ich heute irgendwas Wichtiges bekommen im Posteingang?" - eine
# stinknormale Ja/Nein-Frage ohne W-Fragewort - unbemerkt als Notiz-Inhalt
# uebernommen und an eine echte Notiz angehaengt wurde. Eine gemeinsame,
# vollstaendige Liste (W-Fragen UND Ja/Nein-Fragen) fuer beide Stellen
# verhindert, dass sie wieder auseinanderlaufen.
QUESTION_SHAPE_PREFIXES = (
    "was ", "welche ", "welcher ", "welches ", "wann ", "wie ", "wo ", "warum ", "wieso ", "wer ",
    "hab ich", "habe ich", "hast du", "haben sie",
    "bin ich", "bist du", "sind sie",
    "ist ", "sind ", "war ",
    "kann ich", "kannst du", "können sie", "könnte ich", "könnten sie",
    "soll ich", "sollst du", "sollen wir", "sollte ich",
    "darf ich", "dürfen wir",
    "muss ich", "musst du", "müssen wir",
    "wird ", "werden ", "gibt es",
)

# Imperativ-Verben, mit denen ein VOLLSTAENDIG NEUER, eigenstaendiger Befehl an
# Jarvis typischerweise beginnt - anders als handle_pending_action_flow()s
# eigene "explicit_new_command"-Liste (Zeile ~3585) wird das hier per
# startswith() auf den SATZANFANG geprueft (nicht "irgendwo im Satz"), weil
# reiner Notiz-INHALT diese Woerter durchaus enthalten darf, nur eben nicht als
# erstes Wort. Ohne diese Liste hatte handle_pending_note_flow() nur den engeren
# QUESTION_SHAPE_PREFIXES-Schutz und ein Nachfolgesatz wie "Zeig mir die Notiz
# Urlaubsplanung." wurde als Titel einer laengst unabhaengigen offenen
# Notiz-Rueckfrage uebernommen - live beobachtet 2026-08-19 in einem
# 2266-Saetze-Testdurchlauf: mehrere komplett unabhaengige Test-Saetze wurden
# so als Titel/Inhalt echter, ungewollter Notizen gespeichert.
COMMAND_SHAPE_PREFIXES = (
    "zeig ", "zeige ", "öffne ", "oeffne ", "erstelle ", "erstell ", "lösche ", "loesche ",
    "lösch ", "loesch ", "spiel ", "spiele ", "ruf ", "rufe ", "suche ", "such ", "finde ",
    "starte ", "kopiere ", "verschiebe ", "verschieb ", "pausier", "mach ", "mache ",
    "schau ", "guck ", "lies ", "lese ", "trag ", "trage ", "sag ", "sag,", "sag mal",
    "ergänze ", "ergaenze ", "füge ", "fuege ", "streich ", "entferne ", "vergiss ",
)


# Fuellwoerter, die ein Mensch beim Sprechen natuerlicherweise einstreut
# ("Was steht EIGENTLICH auf..."), die aber eng gefasste Trigger-Phrasen wie
# "was steht auf" zerreissen, weil dort ein exakter Teilstring-Vergleich
# laeuft. strip_filler_words() ist NUR fuer Erkennungs-Vergleiche gedacht -
# niemals auf echten Notiz-/Aufgaben-Inhalt oder gespeicherten Nutzertext
# anwenden, sonst gehen echte Woerter verloren. Siehe Runde-2-Simulation,
# docs/current-system-assessment.md Abschnitt 42.
_FILLER_WORDS = {"eigentlich", "mal", "gerade", "grad", "halt", "eben", "denn", "einfach", "mittlerweile", "übrigens", "uebrigens"}


def strip_filler_words(normalized_text: str) -> str:
    words = [word for word in normalized_text.split(" ") if word not in _FILLER_WORDS]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


DOMAIN_TERMS = {
    "notes": (
        "notiz",
        "notizen",
        "einkaufszettel",
        "einkaufsliste",
        "zettel",
    ),
    "calendar": (
        "kalender",
        "termin",
        "termine",
        "kalendereintrag",
        "termineintrag",
        # "kalender"/"termin" zaehlen laut has_domain_fuzzy() nur als
        # EIGENSTAENDIGES Wort (bewusst, siehe Kommentar dort - sonst matcht
        # z.B. "bild" in "bildschirm" faelschlich). Ein natuerliches deutsches
        # Kompositum wie "Terminkalender" enthaelt "kalender" aber ohne
        # Wortgrenze dazwischen und faellt dadurch sonst komplett durch. Live
        # beobachtet 2026-08-19: "Was hatte ich heute in meinem Terminkalender
        # stehen" wurde nicht erkannt und landete in der Domaenen-Rueckfrage.
        "terminkalender",
        "erinnerungsliste",
        "terminliste",
        "erinnerung",
        "erinnerungen",
        "erinnere mich",
        "termine heute",
        "agenda",
        # "wochenende"/"eingetragen"/"ansteht" waren bewusst zu generische
        # Einzelwoerter, die auf ganz normalen, kalenderfremden Saetzen matchten
        # (z.B. "Ich fahre am Wochenende zu meinen Eltern" -> faelschlich
        # "Fuer Kalender oder Erinnerung brauche ich noch Datum oder Uhrzeit.").
        # Kein Recall-Verlust: "was steht" (CALENDAR_QUERY_PHRASES, siehe
        # looks_like_calendar_query()) faengt "Was steht am Wochenende an?"
        # weiterhin unabhaengig davon ab - has_domain() UND
        # looks_like_calendar_query() werden an der Dispatch-Stelle per ODER
        # geprueft. Live beobachtet 2026-08-20 im Mehrfach-Audit.
    ),
    "mail": (
        "mail",
        "mails",
        "email",
        "emails",
        "e mail",
        "posteingang",
        "postfach",
        "mailfach",
        "inbox",
        "archiv",
        "icloud inbox",
        # "nachricht"/"nachrichten" bewusst NICHT hier, das ueberlappt zu stark mit
        # normalen Alltagssaetzen ("hast du eine Nachricht fuer mich") - bleibt fuer
        # Stufe 2 (LLM-Klassifikation) offen statt Stufe 1 falsch-positiv zu machen.
    ),
    "photos": (
        "foto",
        "fotos",
        "bild",
        "bilder",
        "photos",
        "fotomediathek",
        "fotoindex",
        "foto index",
        "index statistik",
        "indexstatistik",
        "bilder von",
        "aufnahmen",
    ),
    "screen": (
        "bildschirm",
        "bildschirmfoto",
        "bildschirmaufnahme",
        "screenshot",
        "screen shot",
        "was siehst du gerade",
        "schau dir meinen bildschirm",
        "schau auf meinen bildschirm",
        "guck dir meinen bildschirm",
    ),
    # Bewusst enge, mehrwortige Ausloese-Saetze statt einer allgemeinen
    # "Kamera"-Domaene (siehe plans/2026-08-11-jarvis-kamera-feedback.md) -
    # ein einzelnes Wort wie "foto" wuerde sich sofort mit der Fotos-Domaene
    # ueberschneiden, aehnliches Kollisionsrisiko wie der bereits behobene
    # Bildschirm/Fotos-Bug dieser Sitzung.
    "camera": (
        "wie sehe ich aus",
        "wie sehe ich heute aus",
        "wie ist mein outfit",
        "wie sieht mein outfit aus",
        "mach ein foto von mir",
        "nimm ein foto von mir auf",
        "schau dir mein outfit an",
    ),
    "files": (
        "datei",
        "dateien",
        "ordner",
        "dokumente",
        "downloads",
        "download",
        "desktop",
        "schreibtisch",
        "benutzerordner",
        "alle dateien",
        "allen dateien",
        "home",
        "projektordner",
        "jarvis code",
        "unterlagen",
    ),
    "music": (
        "musik",
        "music",
        "apple music",
        "lied",
        "song",
        # "titel" bewusst NICHT als bloßes Einzelwort hier (wie schon bei
        # "nachricht"/mail weiter oben begruendet) - "Titel" ist im Alltagsdeutsch
        # genauso der Titel einer Notiz/eines Dokuments wie ein Musiktitel. Ein
        # einzelnes Wort haette z.B. "Notiz mit dem Titel X" faelschlich als
        # Zwei-Domaenen-Satz (notes+music) erkannt und in einen kaputten
        # Mehrschritt-Auftrag aufgeteilt, der den eigentlichen Titel verlor. Live
        # beobachtet 2026-08-18. Stattdessen nur die spezifischeren, eindeutig
        # musikbezogenen Mehrwort-Phrasen.
        "naechster titel",
        "nächster titel",
        "titel wechseln",
        "titel ueberspringen",
        "titel überspringen",
        "welcher titel",
        "playlist",
        "wiedergabeliste",
        "wiedergabe",
        "abspielen",
        "song spielen",
        # Reine Status-Fragen ohne das Wort "Musik" fielen bisher komplett aus
        # has_domain() heraus, obwohl handle_music_command() dafuer laengst einen
        # echten now_playing()-Pfad hat (Zeile ~6484) - der wurde nie erreicht,
        # weil das has_domain()-Gate schon vorher mit None aussteigt. Landete
        # dann im werkzeuglosen Chat, der eine komplett erfundene Antwort gab.
        # Live beobachtet 2026-08-19: "Was läuft gerade?" -> "Aktuell läuft auf
        # ProSieben eine Reality-Show ...".
        "was läuft",
        "was laeuft",
        "läuft gerade",
        "laeuft gerade",
        "aktueller titel",
        "aktuelle musik",
        "was wird gerade gespielt",
        "was spielt gerade",
    ),
    "contacts": (
        "kontakt",
        "kontakte",
        "telefonbuch",
        "adressbuch",
        "anruf",
        "anrufen",
        "ruf",
        "rufe",
        "telefonier",
        "telefoniere",
        # "Wie ist die Nummer von X?" enthaelt keinen anderen Kontakte-Begriff
        # und fiel deshalb komplett aus has_domain() heraus - landete dann nicht
        # im echten find_contacts()-Lookup (handle_contact_command), sondern im
        # werkzeuglosen Chat, der eine erfundene, aber plausibel klingende Nummer
        # ausgab statt "nicht gefunden". Live beobachtet 2026-08-19: dieselbe
        # erfundene Nummer "+49 30 12345678" tauchte bei mehreren komplett
        # unterschiedlichen, nicht existierenden Namen identisch wieder auf.
        # Mehrwort-Phrase (nicht blosses "nummer"), um keine Kollision mit
        # Haus-/Konto-/Rechnungsnummer o.ae. zu riskieren.
        "nummer von",
        # "kontaktdaten" ist ein Kompositum und zaehlt laut has_domain_fuzzy()
        # nicht als Teilstring-Treffer von "kontakt" (bewusst, siehe Kommentar
        # dort) - "Zeig mir die Kontaktdaten von X" fiel deshalb komplett aus
        # has_domain() heraus. Gleiche Luecke wie "Terminkalender"/"kalender".
        "kontaktdaten",
    ),
    "tasks": (
        "aufgabe",
        "aufgaben",
        "aufgabenliste",
        "to do",
        "todo",
        "todos",
        "offene aufgaben",
    ),
}


def has_domain(text: str, domain: str) -> bool:
    # Umlaut-Normalisierung + Fuzzy-Wortvergleich bewusst nur hier, nicht global in
    # normalize_text() (das hat 60+ Aufrufstellen mit eigenen Umlaut-Vergleichen,
    # die dadurch kaputtgehen wuerden) - siehe
    # plans/2026-08-08-jarvis-intelligenz-verbessern.md, Aufgabe 2.
    normalized = normalize_umlauts(normalize_text(text))
    terms = DOMAIN_TERMS.get(domain, ())
    normalized_terms = tuple(normalize_umlauts(term) for term in terms)
    return has_domain_fuzzy(normalized, normalized_terms)


def record_pattern_event_if_matched(text: str) -> None:
    """Baustein D (siehe plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md):
    zaehlt fuer jede erkannte Faehigkeit ein Muster-Ereignis (nur Kategorie +
    grobe Zeit, nie den Text selbst). Aufrufer ist dafuer verantwortlich, das nur
    bei erteilter "usage_patterns"-Berechtigung aufzurufen - diese Funktion prueft
    das bewusst nicht selbst, um keine Abhaengigkeit auf den PermissionManager
    einzufuehren."""
    for domain in DOMAIN_TERMS:
        if has_domain(text, domain):
            record_pattern_event(domain)


CALENDAR_QUERY_PHRASES = (
    "was steht",
    "was habe ich",
    "wann habe ich",
    "was für termine",
    "was fuer termine",
    "welche termine",
    "was liegt an",
    "was ist heute los",
    "nächster termin",
    "naechster termin",
    "nächste termin",
    "hab ich diese woche",
    "hab ich noch was vor",
    "was hab ich vor",
)


def looks_like_calendar_query(text: str) -> bool:
    normalized = normalize_text(text)
    return any(phrase in normalized for phrase in CALENDAR_QUERY_PHRASES)


def remove_domain_words(text: str, domain: str) -> str:
    cleaned = strip_wake_word_from_text(text)
    terms = sorted(DOMAIN_TERMS.get(domain, ()), key=len, reverse=True)
    for term in terms:
        cleaned = re.sub(rf"\b{re.escape(term)}\b", " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(
        r"\b(?:bitte|mal|mir|für mich|fuer mich|raus|heraus|an|auf|in|aus|von|nach|zum|zur|den|die|das|der|dem|einen|eine|allen|allem|alle)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:such|suche|finde|zeig|zeige|lies|lese|scan|scanne|mach|mache|erstelle|erstell|spiel|spiele|starte|öffne|oeffne)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" .,!?:;")


def extract_folder_name_from_command(text: str, root_hint: str | None = None) -> str:
    cleaned = strip_wake_word_from_text(text)
    patterns = (
        r"(?:ordner|folder)\s+(?:namens\s+|mit\s+(?:dem\s+)?namen\s+)?(.+?)(?:\s+(?:auf|am|in|unter|bei)\s+.+)?[.?!]*$",
        r"(?:erstelle|erstell|mach|mache|leg|lege)\s+(?:mir\s+)?(?:einen\s+|eine\s+|neuen\s+|neue\s+)?(.+?)(?:\s+(?:auf|am|in|unter|bei)\s+.+)?[.?!]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            cleaned = match.group(1)
            break

    cleaned = re.sub(
        r"\b(?:bitte|mal|mir|einen|eine|neuen|neue|ordner|folder|erstelle|erstell|mach|mache|leg|lege|auf|am|in|unter|bei|meinem|meinen|meiner|namens)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")


def extract_file_search_query(text: str) -> str:
    cleaned = strip_wake_word_from_text(text)
    after_nach = re.search(r"\bnach\s+(.+?)[.?!]*$", cleaned, flags=re.IGNORECASE)
    if after_nach:
        cleaned = after_nach.group(1)
        cleaned = re.sub(
            r"\s+(?:in|unter|auf|am|bei|aus|von)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code).*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    else:
        in_root_then_query = re.search(
            r"(?:such|suche|finde|zeig|zeige)\s+(?:mir\s+)?(?:in|unter|auf|am|bei|aus|von)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code)\s+(.+?)[.?!]*$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if in_root_then_query:
            cleaned = in_root_then_query.group(1)
        else:
            cleaned = ""
    match = re.search(
        r"(?:such|suche|finde|zeig|zeige)\s+(?:mir\s+)?(.+?)(?:\s+(?:in|unter|auf|am|bei|aus|von)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code).*)?[.?!]*$",
        cleaned or strip_wake_word_from_text(text),
        flags=re.IGNORECASE,
    )
    if cleaned:
        pass
    elif match:
        cleaned = match.group(1)
    else:
        cleaned = remove_domain_words(text, "files")

    cleaned = re.sub(r"\b(?:nach|datei|dateien|ordner|bitte|mal|mir|namens|eine|einen|einer)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")



def extract_bulk_file_move(text: str) -> tuple[str, str] | None:
    cleaned = strip_wake_word_from_text(text)
    normalized = normalize_text(cleaned)
    if not any(term in normalized for term in ("datei", "dateien", "dokument", "dokumente", "file", "files")):
        return None
    if not any(term in normalized for term in ("verschieb", "pack", "lege", "leg", "sortier", "räume", "raeume", "kopier")):
        return None

    target_match = re.search(
        r"(?:in|nach|zu)\s+(?:den\s+|dem\s+|der\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in|unter)\s+(?:meinem\s+|meinen\s+|meiner\s+|dem\s+|der\s+)?(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code))?[.?!]*$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not target_match:
        return None

    target = clean_file_name(target_match.group(1))
    before_target = cleaned[: target_match.start()].strip()
    query = ""

    query_patterns = (
        r"(?:mit|wo|deren|die|alle)\s+(.+?)\s+(?:im\s+namen|namen|name|heißen|heissen|heißt|heisst|tragen|enthält|enthaelt|enthalten)",
        r"(?:im\s+namen|namen|name)\s+(.+)$",
    )
    for pattern in query_patterns:
        match = re.search(pattern, before_target, flags=re.IGNORECASE)
        if match:
            query = clean_file_name(match.group(1))
            break

    if not query and target:
        target_norm = normalize_text(target)
        for candidate in (
            "bewerbungen",
            "bewerbung",
            "rechnungen",
            "rechnung",
            "versicherungen",
            "versicherung",
            "abonnements",
            "abo",
            "fotos",
            "foto",
            "bilder",
            "bild",
        ):
            if candidate in normalized and candidate not in target_norm:
                query = candidate
                break
        if not query and target_norm in normalized:
            query = target

    query = re.sub(r"\b(?:alle|ganzen|ganze|dateien|datei|dokumente|dokument|files|file|bitte|mal|mir|mit|die|der|das|den|dem|eine|einen|einem)\b", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip(" .,!?:;\"'")
    target = re.sub(r"\s+", " ", target).strip(" .,!?:;\"'")

    if not query or not target:
        return None
    return query, target


def strip_wake_word_from_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^(?:hallo|hey|hi|okay|ok)\s+", "", cleaned, flags=re.IGNORECASE)

    wake_pattern = "|".join(re.escape(str(word)) for word in AKTIVIERUNGSWOERTER)
    if wake_pattern:
        cleaned = re.sub(
            rf"^(?:{wake_pattern})[\s,.:;!?-]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    return cleaned.strip(" .,!?:;\"'")


TRANSIENT_MARKERS = (
    "das war aber noch nicht alles",
    "das war noch nicht alles",
    "funktioniert nicht",
    "klappt nicht",
    "ging nicht",
    "geht nicht",
    "immer noch nicht",
    "immer noch",
    "ich sehe hier",
    "fehler",
    "problem",
    "komisch",
    "falsch",
    "nicht richtig",
    "nicht so ganz",
    "hat nicht",
    "kaputt",
    "nervt",
)

TRANSIENT_STARTS = (
    "scanne",
    "scan",
    "suche",
    "such",
    "kopiere",
    "verschiebe",
    "erstelle",
    "öffne",
    "oeffne",
    "spiel",
    "spiele",
    "rufe",
    "ruf",
    "lies",
    "fasse",
    "prüfe",
    "pruefe",
    "zeige",
    "mach",
    "mache",
)


def should_skip_auto_memory(text: str) -> bool:
    normalized = normalize_text(strip_wake_word_from_text(text))
    if len(normalized) < 12:
        return True

    if any(marker in normalized for marker in TRANSIENT_MARKERS):
        return True

    durable_markers = {
        "ab jetzt",
        "in zukunft",
        "zukünftig",
        "zukuenftig",
        "standardmäßig",
        "standardmaessig",
        "normalerweise",
        "bevorzuge",
        "ich möchte dass",
        "ich moechte dass",
        "ich will dass",
        "jarvis soll",
        "du sollst",
        "ich nutze",
        "ich verwende",
        "merk dir",
        "merke dir",
        "speicher",
        "speichere",
    }
    if any(marker in normalized for marker in durable_markers):
        return False

    # "immer" alleine ist zu breit. Es wird nur zusammen mit einer klaren Vorgabe gemerkt.
    if "immer" in normalized and any(marker in normalized for marker in ("soll", "sprich", "ansprech", "verwende", "nutze")):
        return False

    if normalized.startswith(TRANSIENT_STARTS):
        return True

    return True


_MEMORY_CANDIDATE_QUESTION_STARTS = (
    "was ",
    "wer ",
    "wie ",
    "wo ",
    "wann ",
    "warum ",
    "wieso ",
    "welche ",
    "welcher ",
    "welches ",
    "kannst du",
    "könntest du",
    "koenntest du",
    "würdest du",
    "wuerdest du",
    "hast du",
    "bist du",
    "gibt es",
    "ist es",
)

_MEMORY_CANDIDATE_REQUEST_STARTS = (
    "gib mir",
    "sag mir",
    "zeig mir",
    "erzähl mir",
    "erzaehl mir",
    "erklär mir",
    "erklaer mir",
)

# Eine Selbstauskunft sollte wie eine Aussage klingen (ein passendes Verb enthalten),
# nicht nur zufaellig "ich"/"mein" irgendwo im Satz haben - sonst loest z.B.
# "kannst du mir helfen, ich verstehe das nicht" unnoetig einen LLM-Aufruf aus, obwohl
# da gar kein dauerhafter Fakt drinsteckt. Live beim News-Baustein gelernt: der
# eigentliche Hebel gegen Uebertreibung ist ein schaerferer Vorfilter, nicht nur eine
# Anweisung im Prompt.
_MEMORY_CANDIDATE_STATEMENT_VERBS = (
    "bin",
    "habe",
    "hab",
    "mag",
    "mochte",
    "möchte",
    "moechte",
    "heiße",
    "heisse",
    "wohne",
    "lebe",
    "arbeite",
    "studiere",
    "fahre",
    "spiele",
    "interessiere",
    "liebe",
    "hasse",
    "trinke",
    "esse",
    "nutze",
    "verwende",
    "bevorzuge",
    "brauche",
    "plane",
    "wünsche",
    "wuensche",
    "ist",
    "sind",
    "war",
    "waren",
)


def looks_like_memory_candidate(text: str) -> bool:
    normalized = normalize_text(strip_wake_word_from_text(text))
    if len(normalized) < 12:
        return False
    if any(marker in normalized for marker in TRANSIENT_MARKERS):
        return False
    if normalized.startswith(TRANSIENT_STARTS):
        return False
    if normalized.endswith("?") or normalized.startswith(_MEMORY_CANDIDATE_QUESTION_STARTS):
        return False
    if normalized.startswith(_MEMORY_CANDIDATE_REQUEST_STARTS):
        return False
    if not should_skip_auto_memory(text):
        return True

    self_reference_markers = ("ich ", "mein ", "meine ", "meiner ", "meinen ", "meinem ")
    if not any(marker in normalized for marker in self_reference_markers):
        return False
    return any(verb in normalized for verb in _MEMORY_CANDIDATE_STATEMENT_VERBS)


def clean_memory_subject(text: str) -> str:
    cleaned = str(text).strip(" .,!?:;\"'")
    cleaned = re.sub(r"^(?:okay|ok|dann|bitte|ja|also)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:merk(?:e)?\s+dir|merk(?:e)?\s+ich\s+dir|merk(?:e)?|speicher(?:e)?|kannst du dir merken)\s+(?:bitte\s+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:für|fuer)\s+die\s+zukunft\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^dass\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")


def classify_memory_category(text: str) -> tuple[str, str]:
    """Returns (category, sensitivity). Sensitivity mirrors memory.SENSITIVITY_LEVELS
    and is a best-effort default based on the category alone - it does not replace
    SENSITIVE_FACT_MARKERS / _passes_sensitive_content_filter, which still gate whether
    a fact is stored at all."""
    normalized = normalize_text(text)
    if any(word in normalized for word in ("musik", "stimme", "tts", "antwort", "sprich", "sprache", "ansprech", "humor", "tone", "stil")):
        return "Vorlieben", "normal"
    if any(word in normalized for word in ("mail", "e mail", "rechnung", "versicherung", "abo", "abonnement")):
        return "Mail", "normal"
    if any(word in normalized for word in ("foto", "bilder", "desktop", "schreibtisch", "datei", "ordner")):
        return "Dateien", "normal"
    if any(word in normalized for word in ("kontakt", "anruf", "telefon", "kalender", "notiz")):
        return "Organisation", "normal"
    if any(word in normalized for word in ("ich heiße", "ich heisse", "mein name", "meine adresse", "mein geburtstag", "leon hat", "leon ist", "katze", "katzen")):
        return "Profil", "personal"
    return "Auto", "normal"


def extract_auto_memory_facts(text: str) -> list[tuple[str, str, str]]:
    original = strip_wake_word_from_text(text).strip(" .,!?:;")
    normalized = normalize_text(original)
    facts: list[tuple[str, str, str]] = []
    user_name = configured_user_name()

    # should_skip_auto_memory() gate gilt nur fuer die directive-artigen (anchored) Muster -
    # die unanchored Fakten-Muster unten haben ihre eigene, leichtgewichtigere Pruefung
    # (Laenge + TRANSIENT_MARKERS), da sie absichtlich auch Saetze ohne "durable_marker"
    # (z.B. "ab jetzt", "merk dir") erfassen sollen.
    if len(normalized) < 12:
        return facts
    skip_anchored = should_skip_auto_memory(original)

    cleaned_subject = clean_memory_subject(original)

    # anchored=True: directive-artige Muster, nur am Satzanfang (re.match), unveraendert.
    # anchored=False: rein selbstbezogene Fakten-Muster, auch mitten im Satz erkannt (re.search) -
    # jeder so gefundene Treffer wird zusaetzlich gegen TRANSIENT_MARKERS geprueft (siehe Schleife unten).
    # (?<!\d) vor dem Satzende-Punkt verhindert, dass deutsche Ordinalzahlen wie "3. März" am
    # internen Punkt abgeschnitten werden.
    patterns = [
        (
            r"^(?:ich möchte|ich moechte|ich will),?\s+dass\s+(.+)$",
            lambda match: f"{user_name} möchte, dass {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"^normalerweise\s+sollst\s+du\s+(.+)$",
            lambda match: f"Jarvis soll normalerweise {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"^du\s+mich\s+immer\s+mit\s+(.+?)\s+ansprichst$",
            lambda match: f"Jarvis soll {user_name} immer mit {match.group(1).strip(' .,!?:;')} ansprechen.",
            True,
        ),
        (
            r"^ich\s+(.+?)\s+habe$",
            lambda match: f"{user_name} hat {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"^(?:jarvis\s+)?soll\s+(.+)$",
            lambda match: f"Jarvis soll {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"^(?:du sollst)\s+(.+)$",
            lambda match: f"Jarvis soll {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"^(?:ab jetzt|in zukunft|zukünftig|zukuenftig)\s+(.+)$",
            lambda match: f"Ab jetzt gilt: {clean_memory_subject(match.group(1))}.",
            True,
        ),
        (
            r"^ich\s+(?:bevorzuge|nutze|verwende)\s+(.+)$",
            lambda match: f"{user_name} bevorzugt oder nutzt {match.group(1).strip(' .,!?:;')}.",
            True,
        ),
        (
            r"\bich\s+habe\s+(.+?)(?=(?<!\d)[.,!?]|$)",
            lambda match: f"{user_name} hat {match.group(1).strip(' .,!?:;')}.",
            False,
        ),
        (
            r"\bich\s+bin\s+(.+?)(?=(?<!\d)[.,!?]|$)",
            lambda match: f"{user_name} ist {match.group(1).strip(' .,!?:;')}.",
            False,
        ),
        (
            r"\bich\s+mag\s+(kein[e]?\s+)?(.+?)(?=(?<!\d)[.,!?]|$)",
            lambda match: (
                f"{user_name} mag {match.group(2).strip(' .,!?:;')} nicht."
                if match.group(1)
                else f"{user_name} mag {match.group(2).strip(' .,!?:;')}."
            ),
            False,
        ),
        (
            r"\bmein(?:e|er|en|em)?\s+(.+?)\s+(?:ist|heißt|heisst)\s+(.+?)(?=(?<!\d)[.,!?]|$)",
            lambda match: f"{user_name}s {match.group(1).strip(' .,!?:;')} ist {match.group(2).strip(' .,!?:;')}.",
            False,
        ),
    ]

    candidates = [original]
    if cleaned_subject and normalize_text(cleaned_subject) != normalized:
        candidates.append(cleaned_subject)

    for candidate in candidates:
        for pattern, builder, anchored in patterns:
            if anchored and skip_anchored:
                continue

            matcher = re.match if anchored else re.search
            match = matcher(pattern, candidate, flags=re.IGNORECASE)
            if not match:
                continue

            if not anchored and any(marker in normalize_text(candidate) for marker in TRANSIENT_MARKERS):
                continue

            fact = normalize_memory_fact(builder(match))
            if fact:
                category, sensitivity = classify_memory_category(fact)
                facts.append((category, fact, sensitivity))
            break
        if facts:
            break

    if not facts and not skip_anchored and cleaned_subject:
        cleaned_norm = normalize_text(cleaned_subject)
        if "immer" in cleaned_norm and any(marker in cleaned_norm for marker in ("soll", "sprich", "ansprech", "verwende", "nutze")):
            fact = normalize_memory_fact(f"Dauerhafte Vorgabe von {user_name}: {cleaned_subject}.")
            category, sensitivity = classify_memory_category(fact)
            facts.append((category, fact, sensitivity))

    return facts[:2]


def normalize_memory_fact(fact: str) -> str:
    cleaned = " ".join(str(fact).strip().split())
    cleaned = cleaned.strip(" .,!?:;")
    replacements = {
        "du mich": configured_user_name(),
        "mich": configured_user_name(),
        "mir": configured_user_name(),
    }
    for source, target in replacements.items():
        cleaned = re.sub(rf"\b{re.escape(source)}\b", target, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?:;")
    if not cleaned:
        return ""
    return cleaned + "."


SENSITIVE_FACT_MARKERS = (
    "krankheit",
    "diagnose",
    "medikament",
    "therapie",
    "depression",
    "angststörung",
    "angststoerung",
    "psychisch",
    "konto",
    "iban",
    "kontonummer",
    "gehalt",
    "kredit",
    "schulden",
    "passwort",
    "pin code",
    "kreditkarte",
)


def _build_memory_extraction_messages(user_text: str, user_name: str) -> list[dict[str, str]]:
    # Beispiele im Prompt statt nur einer abstrakten Anweisung - dieselbe Lehre wie
    # beim News-Wichtigkeits-Filter (plans/2026-08-09-jarvis-news-baustein.md): ein
    # kleines lokales Modell haelt sich an "im Zweifel: false" viel zuverlaessiger,
    # wenn es konkrete Positiv-/Negativ-Beispiele sieht, statt nur eine Regel zu lesen.
    system = (
        "Du bist ein striktes Extraktions-Werkzeug, kein Assistent. Analysiere NUR die folgende "
        f"Nutzeraussage von {user_name} und entscheide, ob sie einen dauerhaften, persönlichen Fakt "
        f"ÜBER {user_name} SELBST enthält (nicht über andere, namentlich genannte Personen).\n"
        "Speichere NIEMALS: Gesundheits- oder Krankheitsdetails, Finanz- oder Kontodaten, Beträge, "
        "Passwörter, Aussagen primär über eine andere Person, oder einmalige/flüchtige Ereignisse "
        "und Beschwerden.\n\n"
        "Beispiele:\n"
        '- "Ich trinke morgens immer erst einen Kaffee, bevor ich irgendwas mache" -> '
        f'{{"has_fact": true, "fact": "{user_name} trinkt morgens als erstes einen Kaffee."}}\n'
        '- "Ich wohne seit letztem Jahr in Berlin" -> '
        f'{{"has_fact": true, "fact": "{user_name} wohnt in Berlin."}}\n'
        '- "Kannst du mir kurz sagen, wie spät es ist?" -> {"has_fact": false, "fact": null} '
        "(eine Frage, keine Selbstauskunft)\n"
        '- "Ich habe gerade versucht, die Datei zu öffnen, aber es hat nicht geklappt" -> '
        '{"has_fact": false, "fact": null} (ein einmaliges, flüchtiges Ereignis, kein dauerhafter '
        "Fakt)\n"
        '- "Mein Bruder hat morgen Geburtstag" -> {"has_fact": false, "fact": null} '
        f"(handelt primär von einer anderen Person, nicht von {user_name} selbst)\n\n"
        f"Falls die Aussage tatsächlich einen dauerhaften Fakt über {user_name} enthält, formuliere "
        f"ihn als kurzen, neutralen Satz, der mit '{user_name}' beginnt.\n"
        'Antworte NUR mit kompaktem JSON, ohne weiteren Text: {"has_fact": true, "fact": "..."} '
        'oder {"has_fact": false, "fact": null}. Im Zweifel: has_fact=false.'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]


_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_fact_response(raw: str) -> str | None:
    cleaned = str(raw or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Live beim Testen aufgefallen: das kleine lokale Modell haelt sich trotz
        # strikter Anweisung ("Antworte NUR mit JSON") nicht immer daran und stellt
        # z.B. noch einen erklaerenden Satz davor/danach. Gleiche Rettungs-Technik wie
        # in core/multistep_planner.py::_extract_json_array() - das erste
        # JSON-Objekt im Text heraussuchen, statt die ganze Antwort sofort zu
        # verwerfen. Schlaegt AUCH das fehl, bleibt es beim sicheren Fehlschlagen
        # (kein Fakt wird gespeichert) statt zu raten.
        match = _JSON_OBJECT_PATTERN.search(cleaned)
        if not match:
            raise ValueError("Auto-Memory LLM-Antwort ist kein valides JSON.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Auto-Memory LLM-Antwort ist kein valides JSON: {exc}") from exc

    if not isinstance(data, dict) or "has_fact" not in data:
        raise ValueError("Auto-Memory LLM-Antwort hat nicht die erwartete Form.")

    if not data.get("has_fact"):
        return None

    fact = str(data.get("fact") or "").strip()
    if not fact:
        raise ValueError("Auto-Memory LLM-Antwort meldet has_fact=true ohne fact-Text.")

    return fact


def _passes_sensitive_content_filter(fact: str) -> bool:
    normalized = normalize_text(fact)
    return not any(marker in normalized for marker in SENSITIVE_FACT_MARKERS)


def _looks_self_referential(fact: str, user_name: str) -> bool:
    """
    Best-Effort-Heuristik, KEIN verlaesslicher Schutz: prueft nur, ob der extrahierte
    Fakt-Satz den Nutzernamen oder eine Ich-Form als mutmassliches Subjekt enthaelt. Laesst
    sich durch Umformulierung leicht umgehen und erkennt keine echte grammatische Subjekt-
    Objekt-Struktur - dient nur als zusaetzliche, unscharfe Schicht neben der Prompt-
    Instruktion in _build_memory_extraction_messages(), nicht als Ersatz dafuer.
    """
    normalized = normalize_text(fact)
    name_normalized = normalize_text(user_name)
    return bool(name_normalized) and (
        normalized.startswith(name_normalized)
        or f" {name_normalized} " in f" {normalized} "
    )


def _run_llm_memory_extraction(user_text: str, memory: Memory, user_name: str, force_local: bool = False) -> None:
    logger = PrivacyLogger(memory.base_path / "logs")
    try:
        llm = LLMClient(CONFIG)
        route = llm.plan([], user_text=user_text, force_local=force_local)
        messages = _build_memory_extraction_messages(user_text, user_name)
        # 600 statt vorher 80: reasoning-faehige Modelle (aktuell qwen3:4b)
        # brauchen oft 300-500+ Token allein zum "Nachdenken", bevor die
        # eigentliche extrahierte Antwort kommt (siehe
        # llm_client.py::_THINKING_CAPABLE_MODELS) - mit 80 Token kam bei
        # solchen Modellen oft eine leere Antwort zurueck, das Nachdenken
        # allein sprengte das Budget.
        raw = llm.ask(messages, max_output_tokens=600, user_text=user_text, route=route, force_local=force_local, raw_system_prompt=True)
        fact = _parse_llm_fact_response(raw)
    except Exception as exc:
        logger.log("auto_memory_llm", "extraction_failed", success=False, error=type(exc).__name__)
        print(f"Auto-Memory LLM-Extraktion fehlgeschlagen: {type(exc).__name__}")
        return

    if not fact:
        return

    # Fakten primär über eine andere Person werden weiterhin komplett verworfen - das ist
    # kein Fall, den der Nutzer für sich selbst bestätigen/ablehnen könnte, sondern ein
    # Datenschutzproblem gegenüber Dritten.
    if not _looks_self_referential(fact, user_name):
        logger.log("auto_memory_llm", "filtered", success=True, reason="third_party")
        return

    memory_system = JarvisMemorySystem(memory)
    category, sensitivity = classify_memory_category(fact)
    is_sensitive = not _passes_sensitive_content_filter(fact)
    if is_sensitive:
        # Landet auf einem SENSITIVE_FACT_MARKERS-Treffer (Gesundheit, Konto, Passwort, ...).
        # Wird nicht mehr stillschweigend verworfen, sondern wie jeder andere LLM-Fakt als
        # pending_confirmation gespeichert - zusätzlich mit sensitivity="confidential", damit
        # er in der Gedächtnis-Ansicht erkennbar als sensibel markiert ist. Der Nutzer
        # entscheidet selbst, ob er bestätigt oder ablehnt.
        sensitivity = "confidential"

    # LLM-Extraktion ist unsicherer als die regelbasierte (Halluzinationsrisiko, keine
    # feste Satzstruktur) - deshalb niedrigere confidence und erst pending_confirmation,
    # statt sofort als bestätigt zu gelten. Der Nutzer bestätigt/lehnt in der
    # Gedächtnis-Ansicht ab (siehe docs/context-and-memory.md).
    result = memory_system.maybe_remember(
        fact,
        category=category,
        source="auto-llm",
        confidence=0.7,
        sensitivity=sensitivity,
        status="pending_confirmation",
    )
    if result in ("created", "updated"):
        logger.log(
            "auto_memory_llm",
            "sensitive_pending_confirmation" if is_sensitive else "pending_confirmation",
            success=True,
        )
        print(f"Memory (LLM): {result} unter {category} (pending_confirmation): {console_text(fact, 'answer')}")


def auto_update_memory(memory: Memory, user_text: str, assistant_text: str = "") -> list[str]:
    if not AUTO_MEMORY_ENABLED or not has_permission("memory"):
        return []

    normalized = normalize_text(strip_wake_word_from_text(user_text))
    notes: list[str] = []
    memory_system = JarvisMemorySystem(memory)

    forget_match = re.match(
        r"^(?:vergiss|lösche|loesche|streich|entferne)\s+(?:bitte\s+)?(?:dass\s+)?(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if forget_match:
        query = forget_match.group(1).strip()
        removed = memory_system.maybe_forget(query)
        if removed:
            notes.append(f"Memory: {removed} passende Erinnerung geloescht.")
        return notes

    for category, fact, sensitivity in extract_auto_memory_facts(user_text):
        # Mirrors _run_llm_memory_extraction(): SENSITIVE_FACT_MARKERS / _passes_sensitive_content_filter
        # must gate every auto-captured fact, not just LLM-extracted ones (see classify_memory_category()
        # docstring). Without this, regex patterns like "ich habe .../ich bin ..." could store health,
        # financial or other sensitive facts as immediately-confirmed memory.
        if not _passes_sensitive_content_filter(fact):
            result = memory_system.maybe_remember(
                fact,
                category=category,
                source="auto",
                sensitivity="confidential",
                status="pending_confirmation",
            )
        else:
            result = memory_system.maybe_remember(fact, category=category, source="auto", sensitivity=sensitivity)
        if result == "created":
            notes.append(f"Memory: gespeichert unter {category}: {fact}")
        elif result == "updated":
            notes.append(f"Memory: aktualisiert unter {category}: {fact}")

    if notes:
        memory.trim_facts(AUTO_MEMORY_MAX_FACTS)
    elif AUTO_MEMORY_LLM_EXTRACTION_ENABLED and looks_like_memory_candidate(user_text):
        voice_mode = str((memory.get("settings") or {}).get("voice_mode") or "")
        threading.Thread(
            target=_run_llm_memory_extraction,
            args=(user_text, memory, configured_user_name(), voice_mode_forces_local_only(voice_mode)),
            daemon=True,
        ).start()

    return notes


def record_exchange(memory: Memory, user_text: str, assistant_text: str, auto_memory: bool = True):
    if bool(CONFIG.get("privacy_store_conversation", False)) and has_permission("memory"):
        try:
            conversation = ConversationManager()
            conversation.append("user", user_text)
            conversation.append("assistant", assistant_text)
        except Exception:
            memory.add_conversation("user", user_text)
            memory.add_conversation("assistant", assistant_text)
            memory.trim_conversation(40)

    if auto_memory:
        for note in auto_update_memory(memory, user_text, assistant_text):
            print(console_text(note, "answer"))


def is_end_command(text: str) -> bool:
    normalized = normalize_text(text)
    without_wake = normalize_text(strip_wake_word_from_text(text))
    wake_removed_anywhere = normalized
    for wake_word in AKTIVIERUNGSWOERTER:
        wake_removed_anywhere = re.sub(rf"\b{re.escape(str(wake_word).lower())}\b", " ", wake_removed_anywhere)
    wake_removed_anywhere = normalize_text(wake_removed_anywhere)

    candidates = {normalized, without_wake, wake_removed_anywhere}
    if any(candidate in END_PHRASES for candidate in candidates):
        return True

    end_patterns = (
        r"^(?:okay|ok|alles klar)?\s*(?:danke|dank dir)?\s*(?:das )?passt(?: soweit)?$",
        r"^(?:danke|dank dir)\s*(?:das )?passt(?: soweit)?$",
        r"^(?:nein )?danke\s*(?:das )?passt(?: soweit)?$",
        r"^(?:alles klar|okay|ok)\s*(?:das )?passt(?: soweit)?$",
        r"^(?:bis später|bis spaeter|tschüss|tschuess)$",
    )
    return any(
        re.match(pattern, candidate, flags=re.IGNORECASE)
        for candidate in candidates
        for pattern in end_patterns
    )


def should_use_web_search(text: str) -> bool:
    normalized = normalize_text(text)

    if is_internet_check(text):
        return False

    explicit_web_keywords = {
        "such im internet",
        "suche im internet",
        "google",
        "googel",
        "schau im internet",
        "schau online",
        "recherchiere",
        "such mal",
        "suche mal",
        "schau nach",
        "was ist aktuell",
        "aktuell",
        "neueste",
        "neusten",
        "letzte",
        "letzten",
        "nachrichten",
        "internet",
        "online",
        "gibt's neues",
        "gibt es neues",
        "neuigkeiten",
    }

    if any(keyword in normalized for keyword in explicit_web_keywords):
        return True

    if not WEB_SEARCH_AUTO:
        return False

    current_keywords = {
        "aktuell",
        "heute",
        "gerade",
        "momentan",
        "inzwischen",
        "mittlerweile",
        "preis",
        "kosten",
        "kostet",
        "wert",
        "börse",
        "kurs",
        "wetter",
        "nachrichten",
        "modell",
        "modelle",
    }

    changing_topics = {
        "iphone",
        "airpods",
        "apple",
        "ios",
        "macos",
        "openai",
        "chatgpt",
        "gpt",
        "ollama",
        "tesla",
        "nvidia",
        "aktie",
        "bitcoin",
        "ethereum",
        "bundesliga",
        "formel 1",
        "fußball",
        "fussball",
        "wahl",
        "präsident",
        "praesident",
        "kanzler",
        "minister",
    }

    factual_intents = (
        "sag mir",
        "sagt mir",
        "erzähl mir",
        "erzaehl mir",
        "kannst du mir",
        "was weißt du",
        "was weisst du",
        "informationen über",
        "informationen ueber",
        "infos über",
        "infos ueber",
    )

    question_starters = (
        "wer ist",
        "wer war",
        "was ist",
        "was hältst",
        "was haeltst",
        "was denkst",
        "wie findest",
        "welches ist",
        "welche ist",
        "welcher ist",
        "gibt es",
        "wann kommt",
        "wann ist",
        "wann wurde",
        "wie viel kostet",
        "was kostet",
    )

    has_question_shape = normalized.endswith("?") or normalized.startswith(question_starters)
    has_current_keyword = any(keyword in normalized for keyword in current_keywords)
    has_changing_topic = any(topic in normalized for topic in changing_topics)
    has_factual_intent = any(intent in normalized for intent in factual_intents)
    mentions_recent_year = re.search(r"\b20(2[4-9]|3[0-9])\b", normalized) is not None
    mentions_product_number = re.search(
        r"\b(?:iphone|airpods|air pods|ios|gpt|macbook|watch|pixel|galaxy)\s*(?:pro|max|plus|ultra|mini)?\s*\d+",
        normalized,
    ) is not None

    if has_current_keyword:
        return True

    if mentions_product_number:
        return True

    if has_factual_intent and has_changing_topic:
        return True

    if has_factual_intent and re.search(r"\b(?:über|ueber|zu|von)\b", normalized):
        return True

    if mentions_recent_year and has_question_shape:
        return True

    if has_changing_topic and has_question_shape:
        return True

    return False


def build_search_query(text: str) -> str:
    normalized = text.strip()

    topic_match = re.search(
        r"\b(?:über|ueber|zu|von)\s+(?:dem|der|die|das|den|einem|einer)?\s*(.+?)(?:\s+(?:sagen|erzählen|erzaehlen))?[.?!]*$",
        normalized,
        flags=re.IGNORECASE,
    )
    if topic_match:
        normalized = topic_match.group(1).strip()

    normalized = re.sub(
        r"^.*?(?:ich habe eine frage(?: und zwar)?|meine frage ist|und zwar|dann sag(?:t)? mir doch mal|sag(?:t)? mir doch mal|sag(?:t)? mir(?: mal)?(?: bitte)?|erzähl mir(?: doch)?(?: mal)?|erzaehl mir(?: doch)?(?: mal)?|was hältst du(?: eigentlich)? von|was haeltst du(?: eigentlich)? von),?\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()

    normalized = re.sub(
        r"^(?:na,?\s*)?(?:das ist doch gut\.?\s*)?",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()

    cleanup_patterns = [
        r"^such(?:e)?(?: mal)?(?: bitte)?(?: im internet)?(?: nach)?\s+",
        r"^schau(?: mal)?(?: bitte)?(?: im internet| online)?(?: nach)?\s+",
        r"^recherchiere(?: bitte)?\s+",
        r"^google(?: bitte)?\s+",
    ]

    for pattern in cleanup_patterns:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE).strip()

    product_match = re.search(
        r"\b(i\s*phone|iphone|air\s*pods|airpods|ios|gpt|macbook|apple watch|watch|pixel|galaxy)\s*(?:(pro|max|plus|ultra|mini)\s*)?([0-9]{1,2})(?:\s*(pro|max|plus|ultra|mini))?\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if product_match:
        product = product_match.group(1).replace(" ", "")
        first_suffix = product_match.group(2) or ""
        number = product_match.group(3)
        second_suffix = product_match.group(4) or ""
        if first_suffix:
            normalized = f"{product} {first_suffix} {number}".strip()
        else:
            normalized = f"{product} {number} {second_suffix}".strip()

    normalized = re.sub(
        r"\b(?:bitte|doch|mal|etwas|wirklich|gar nichts|kannst du mir|sag mir|sagt mir)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,.!?:;")

    if not re.search(r"\b20(2[4-9]|3[0-9])\b", normalized):
        normalized = f"{normalized} aktuell"

    return normalized or text


def is_internet_check(text: str) -> bool:
    normalized = normalize_text(text)
    internet_words = (
        "internet zugriff",
        "internetzugriff",
        "internet zugruf",
        "internetzugruf",
        "online zugriff",
        "netz zugriff",
    )
    check_words = (
        "hast du",
        "überprüfen",
        "ueberpruefen",
        "prüfen",
        "pruefen",
        "testen",
        "checken",
        "funktioniert",
    )
    return any(word in normalized for word in internet_words) and any(
        word in normalized for word in check_words
    )



def handle_model_command(
    text: str,
    memory: Memory | None = None,
    model_manager: ModelManager | None = None,
) -> str | None:
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("modell", "gemma", "qwen", "openai", "lokal", "cloud")):
        return None

    # `model_manager` laesst den Aufrufer eine bereits vorhandene, langlebige
    # Instanz durchreichen (siehe local_server.py::self.models) statt hier immer
    # eine neue zu bauen - ModelManager cacht model_settings.json genau wie
    # Memory (siehe Gedaechtnis-Bugfix), eine zweite, kurzlebige Instanz wuerde
    # sonst denselben Daten-Verlust-Bug reproduzieren: ein Schreibvorgang ueber
    # diese frische Instanz waere fuer die langlebige unsichtbar, und ein
    # spaeterer Schreibvorgang der langlebigen Instanz wuerde ihn stillschweigend
    # wieder ueberschreiben.
    manager = model_manager or ModelManager(CONFIG)

    if any(term in normalized for term in ("welches modell", "welches model", "modell nutzt", "model nutzt", "modell verwendest", "model verwendest")):
        return manager.status_text()

    if "standardmodell" in normalized or "standard modell" in normalized:
        return manager.use_standard_model()

    if "gemma" in normalized:
        return manager.use_local_model("gemma3:4b")

    if "qwen" in normalized:
        return manager.use_local_model("qwen3:4b")

    if "arbeite lokal" in normalized or "lokal arbeiten" in normalized or "nutze lokal" in normalized or "cloud deaktiv" in normalized or "openai deaktiv" in normalized:
        return manager.work_locally()

    if "nutze openai" in normalized or "openai aktiv" in normalized or "cloud ki" in normalized:
        permission_answer = ensure_permission(memory, "cloud_llm", "Jarvis würde OpenAI als Cloud-KI aktivieren.") if memory is not None else None
        if permission_answer is not None:
            return permission_answer
        api_permission = ensure_permission(memory, "external_api", "Jarvis würde externe API-Anfragen an OpenAI erlauben.") if memory is not None else None
        if api_permission is not None:
            return api_permission
        return manager.use_openai()

    return None


def handle_system_command(text: str) -> str | None:
    normalized = normalize_text(text)

    if (
        "warum" in normalized
        and any(term in normalized for term in ("live internetsuche", "live suche", "internetsuche"))
        and any(term in normalized for term in ("kannst du nicht", "kannst du gerade keine", "keine"))
    ):
        return (
            f"Das war ein Fehler in meiner Entscheidungslogik, {configured_user_address()}. "
            "Ich kann online prüfen; ich hätte es direkt tun sollen. Uncharmant, aber reparabel."
        )

    if not is_internet_check(text):
        return None

    ok, detail = check_internet_access()
    if ok:
        return f"Ja, {configured_user_name()}. Internetzugriff ist aktiv. Ich habe gerade nachgesehen."

    return f"Nein, der Internetzugriff spinnt gerade. Detail: {detail}"


def handle_preference_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    settings = memory.get("settings") or {}

    no_sources = (
        "keine quellenangaben" in normalized
        or "keine quellen" in normalized
        or "ohne quellenangaben" in normalized
        or "ohne quellen" in normalized
        or "quellenangaben mehr" in normalized
    )

    wants_sources = (
        "mit quellenangaben" in normalized
        or "mit quellen" in normalized
        or "quellen bitte" in normalized
    )

    if no_sources:
        settings["include_sources"] = False
        memory.set("settings", settings)
        memory.remember("Vorlieben", "Quellenangaben", "keine Quellenangaben, außer ausdrücklich gewünscht")
        return f"Verstanden, {configured_user_address()}. Quellen lasse ich weg."

    if wants_sources:
        settings["include_sources"] = True
        memory.set("settings", settings)
        memory.remember("Vorlieben", "Quellenangaben", "Quellenangaben anzeigen")
        return f"Verstanden, {configured_user_address()}. Quellen nenne ich wieder."

    if (
        "hast du dir das" in normalized
        and any(term in normalized for term in ("langzeit", "langzeitgedächtnis", "langzeitgedaechtnis", "abgespeichert", "gespeichert"))
    ):
        include_sources = settings.get("include_sources", False)
        if include_sources:
            return f"Ja, {configured_user_address()}. Ihre Quellen-Präferenz steht auf: Quellen anzeigen."
        return f"Ja, {configured_user_address()}. Quellen lasse ich weg."

    return None


def handle_daily_briefing_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    # "briefing" deckt als Teilstring auch "morgen briefing"/"abend briefing"
    # (als zwei separate Woerter gesprochen/getippt) sowie "tagesbriefing"/
    # "abendbriefing" ab - vorher wurden nur die exakten Komposita erkannt,
    # sodass z.B. "starte das morgen briefing" durchrutschte und stattdessen
    # beim allgemeinen Chat landete, der dann mangels echter Daten frei
    # erfundene Inhalte produzierte (siehe Screenshot-Bugreport von Leon).
    if "briefing" not in normalized and "morgenübersicht" not in normalized and "morgenuebersicht" not in normalized:
        return None

    calendar_items = []
    reminders = []
    open_tasks = []
    mail_summary = ""
    try:
        # "heutige Termine" statt "naechste 3 Termine" - konsistent mit
        # local_server.py::daily_briefing(), siehe
        # plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md. Live entdeckter
        # Bug (2026-08-13): hier fehlte bisher das "until"-Limit, das
        # local_server.py::daily_briefing() bereits hatte - list_upcoming_
        # calendar_items() iteriert Kalender-fuer-Kalender in beliebiger
        # Reihenfolge (nicht nach Datum sortiert) und brach schon nach den
        # ersten 10 GEFUNDENEN (nicht: naechsten) Terminen ab, bevor
        # events_on_date() ueberhaupt zum Filtern kam - ein heutiger Termin
        # aus einem spaeter durchsuchten Kalender fiel dadurch komplett
        # unter den Tisch. Siehe docs/current-system-assessment.md,
        # Abschnitt 41.
        now = datetime.now()
        end_of_today = datetime(now.year, now.month, now.day, 23, 59, 59)
        calendar_items = events_on_date(list_upcoming_calendar_items(limit=20, until=end_of_today).get("items", []))
    except Exception:
        calendar_items = []
    try:
        reminders = list_open_reminders(limit=3).get("items", [])
    except Exception:
        reminders = []
    try:
        open_tasks = TaskManager(memory).list_tasks(status="offen") + TaskManager(memory).list_tasks(status="in_arbeit")
    except Exception:
        open_tasks = []
    if has_permission("mail"):
        try:
            unread = unread_inbox_count()
            mail_summary = f"{unread} ungelesen" if unread else "keine ungelesenen Mails"
        except Exception:
            mail_summary = ""

    weather_summary = ""
    system_summary = ""
    if "morgen" in normalized or "morgenübersicht" in normalized:
        system_summary = "Morgens direkt auf das Wesentliche schauen."
    if "abend" in normalized:
        system_summary = "Abends ruhig kurz abschließen, statt große Oper zu spielen."

    briefing = build_daily_briefing(
        calendar_items=calendar_items,
        reminders=reminders,
        tasks=open_tasks,
        mail_summary=mail_summary,
        weather_summary=weather_summary,
        system_summary=system_summary,
    )
    return briefing


def handle_style_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    settings = memory.get("settings") or {}

    wants_looser_today = (
        "heute" in normalized
        and any(term in normalized for term in ("lockerer", "entspannter", "lässiger", "laessiger", "weniger hochgestochen"))
    )

    wants_normal_today = (
        "heute" in normalized
        and any(term in normalized for term in ("normal", "normaler", "wieder normal", "standard", "seriöser", "serioeser"))
    )

    if wants_looser_today:
        settings["temporary_style"] = {
            "date": today_key(),
            "style": "locker",
            "instruction": (
                "Sprich für den Rest des Tages etwas lockerer und natürlicher. "
                "Bleib trotzdem präzise, souverän und knapp. Weniger hochgestochen, mehr persönlicher Assistent. "
                "Trockener Humor darf etwas deutlicher durchkommen, Übertreibung nicht."
            ),
        }
        memory.set("settings", settings)
        return f"Verstanden, {configured_user_address()}. Heute etwas lockerer."

    if wants_normal_today:
        settings.pop("temporary_style", None)
        memory.set("settings", settings)
        return f"Verstanden, {configured_user_address()}. Standard ist wieder aktiv."

    if (
        any(term in normalized for term in ("welchen stil", "tagesstil", "wie sprichst du heute"))
        or ("bist du" in normalized and "locker" in normalized)
    ):
        temporary_style = settings.get("temporary_style")
        if isinstance(temporary_style, dict) and temporary_style.get("date") == today_key():
            return f"Heutiger Stil: {temporary_style.get('style', 'angepasst')}, {configured_user_address()}."
        return f"Standardmodus, {configured_user_address()}. Ruhig und knapp."

    return None


def handle_personality_command(memory: Memory, text: str) -> str | None:
    """TARS-Style Humor-/Ehrlichkeits-Regler per Sprachbefehl - Leons Wunsch
    2026-08-21. Gleiches Muster wie handle_style_command oben: Text parsen,
    Wert in memory["personality"]["behavior"] schreiben, Bestaetigung zurueckgeben."""
    from core.personality_manager import clamp_level

    normalized = normalize_text(text)
    if "humor" not in normalized and "ehrlich" not in normalized and "honest" not in normalized:
        return None

    is_humor = "humor" in normalized
    field = "humor_level" if is_humor else "honesty_level"
    label = "Humor" if is_humor else "Ehrlichkeit"

    personality = memory.get("personality") or {}
    behavior = personality.get("behavior") or {}
    current = clamp_level(behavior.get(field), 60 if is_humor else 90)

    increase_terms = ["mehr", "hoeher", "höher", "rauf", "erhoeh", "erhöh"]
    decrease_terms = ["weniger", "runter", "niedriger", "senk", "aus"]
    if is_humor:
        increase_terms += ["lustiger", "witziger", "humorvoller"]
        decrease_terms += ["ernster", "sachlicher"]
    else:
        increase_terms += ["ehrlicher", "direkter", "offener"]
        decrease_terms += ["vorsichtiger", "diplomatischer", "zurueckhaltender", "zurückhaltender"]

    match = re.search(r"(\d{1,3})\s*(%|prozent)?", normalized)
    if match:
        new_level = max(0, min(100, int(match.group(1))))
    elif any(term in normalized for term in increase_terms):
        new_level = max(0, min(100, current + 20))
    elif any(term in normalized for term in decrease_terms):
        new_level = max(0, min(100, current - 20))
    else:
        return None

    behavior[field] = new_level
    personality["behavior"] = behavior
    memory.set("personality", personality)
    return f"{label} auf {new_level} gesetzt, {configured_user_address()}."


def handle_self_preference_command(memory: Memory, text: str) -> str | None:
    """Simulierte Vorlieben fuer das Selbstmodell (Leons Wunsch 2026-08-22,
    "Bewusstsein simulieren"). Bewusst NUR per Sprachbefehl gesetzt, nie von
    der LLM selbst erfunden - siehe self_model_instruction() in
    core/personality_manager.py fuer die Ehrlichkeitspflicht, die dieses
    Feature erst vertretbar macht."""
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("du magst", "du liebst", "du hasst")):
        return None

    topic = ""
    stance = ""
    negative = re.search(r"du magst (.+?) nicht\b", normalized) or re.search(
        r"du magst kein[e]?\s+(.+)", normalized
    )
    if negative:
        topic = re.sub(r"\s+mehr$", "", negative.group(1)).strip()
        stance = "mag ich nicht"
    elif match := re.search(r"du hasst (.+)", normalized):
        topic = match.group(1).strip()
        stance = "hasse ich"
    elif match := re.search(r"du liebst (.+)", normalized):
        topic = match.group(1).strip()
        stance = "liebe ich"
    elif match := re.search(r"du magst (.+)", normalized):
        topic = match.group(1).strip()
        stance = "mag ich"

    if not topic or not stance:
        return None

    self_model = memory.get("self_model") or {}
    preferences = self_model.get("preferences")
    if not isinstance(preferences, dict):
        preferences = {}
    preferences[topic] = stance
    self_model["preferences"] = preferences
    memory.set("self_model", self_model)
    return f"Verstanden, {configured_user_address()} - {topic}: {stance}."


def handle_project_command(text: str) -> str | None:
    normalized = normalize_text(text)

    project_questions = (
        "was hältst du von meinem projekt",
        "was haeltst du von meinem projekt",
        "wie findest du mein projekt",
        "was denkst du über mein projekt",
        "was denkst du ueber mein projekt",
    )

    if any(question in normalized for question in project_questions):
        return (
            f"Es ist ambitioniert, {configured_user_name()}, aber nicht abwegig. "
            "Wenn wir es sauber modular halten, hat Jarvis OS eine echte Chance; Chaos bleibt der einzige echte Saboteur."
        )

    if "projektname" in normalized and "ki software" in normalized and "verkaufen" in normalized:
        return (
            "Notiert: Das Projekt dreht sich um verkaufbare KI-Software. "
            "Ein angenehm unbescheidener Plan. Sehr gesundes Maß an Größenwahn."
        )

    return None


def handle_local_command(text: str) -> str | None:
    normalized = normalize_text(text)
    # Weckwort "jarvis" am Anfang/Ende einer sonst exakten Kurzformel abtrennen,
    # bevor gegen die Phrasen-Sets verglichen wird. Live entdeckter Bug: "Hallo
    # Jarvis" - die naheliegendste reale Formulierung, Weckwort plus Gruss -
    # matchte bisher keine der Kurzformeln unten, nur das isolierte Wort
    # "hallo" tat das. Siehe docs/current-system-assessment.md, Abschnitt 41.
    without_wake_word = re.sub(r"^jarvis\s+|\s+jarvis$", "", normalized).strip() or normalized

    greeting_phrases = {
        "hallo",
        "hey",
        "hi",
        "guten morgen",
        "guten tag",
        "guten abend",
    }

    if without_wake_word in greeting_phrases:
        return f"Ich bin da, {configured_user_name()}. Was liegt an? Ich bin heute ungewöhnlich wach."

    if normalized in {"ja", "jarvis", "ja jarvis"}:
        return "Was liegt an?"

    # "Bin wieder da" ist eine reine Wiederkehr-Meldung, kein inhaltlicher
    # Prompt - live entdeckter Bug (Runde-2-Simulation, 2026-08-13): ohne
    # eigenen Pfad lief das durch den freien Chat, der aus einer gespeicherten
    # Tatsache ("lebt in Amberg") eine unpassende, uebergriffige Vermutung
    # machte ("Herzlichen Glueckwunsch zurueck zu Amberg!"). Substring- statt
    # Exact-Match, weil Menschen das selten wortgleich tippen ("So, bin wieder
    # da" etc.). Siehe docs/current-system-assessment.md, Abschnitt 42.
    return_phrases = ("bin wieder da", "bin zurück", "bin zurueck", "wieder zurück", "wieder zurueck", "bin wieder hier")
    if any(phrase in normalized for phrase in return_phrases):
        return f"Willkommen zurück, {configured_user_name()}. Was liegt an?"

    # Kurze Stimmungs-/Stress-Aeusserungen verdienen eine kurze menschliche
    # Reaktion statt eines themenfremden Zufallsspruchs - live entdeckter Bug:
    # "Puh, stressiger Tag heute" bekam den "Spruch des Tages" statt jeder
    # Anteilnahme. Siehe docs/current-system-assessment.md, Abschnitt 42.
    stress_phrases = (
        "stressiger tag", "stressig", "anstrengend", "erschöpft", "erschoepft",
        "geschafft heute", "bin geschafft", "kaputt heute", "müde heute", "muede heute",
        "chaotisch heute", "am limit", "harter tag", "langer tag",
    )
    if any(phrase in normalized for phrase in stress_phrases):
        return "Klingt nach einem anstrengenden Tag. Soll ich Ihnen etwas abnehmen, oder brauchen Sie erstmal einen Moment?"

    thanks_phrases = {
        "danke",
        "danke dir",
        "vielen dank",
        "besten dank",
        "okay danke",
        "ok danke",
    }

    if without_wake_word in thanks_phrases:
        return "Gern. Höflichkeit ist eine seltene, aber wertvolle Ressource."

    polite_done_phrases = {
        "okay das ist okay",
        "ok das ist okay",
        "okay passt",
        "ok passt",
        "danke das passt",
        "danke passt",
        "nein danke",
        "nein danke das passt",
        "nein danke das passt soweit",
        "passt soweit",
        "das passt",
        "das passt soweit",
        "alles gut",
        "alles klar",
    }

    if without_wake_word in polite_done_phrases:
        return "Alles klar. Ich halte kurz den Mund."

    # Freie Verabschiedungen ("das wär's von mir erstmal, bis später") klingen
    # selten wie die kurzen Exact-Match-Formeln oben - live entdeckter Bug
    # (Runde-2-Simulation, 2026-08-13): landete generisch im freien Chat statt
    # der eingeuebten Jarvis-Verabschiedung. Siehe
    # docs/current-system-assessment.md, Abschnitt 42.
    farewell_phrases = (
        "bis später", "bis spaeter", "tschüss", "tschuess", "bis dann",
        "das wär's", "das wars", "bin dann mal weg", "melde mich später", "melde mich spaeter",
        "mach's gut", "machs gut", "wir sprechen uns", "das reicht für heute", "das reicht fuer heute",
    )
    if without_wake_word in {"bis später", "bis spaeter", "tschüss", "tschuess"} or any(
        phrase in normalized for phrase in farewell_phrases
    ):
        return f"Bis später, {configured_user_name()}. Ich bleibe so lange brav."

    return None


_NAME_PERMISSION_PHRASES = (
    "nenn mich bei meinem namen",
    "nenn mich beim namen",
    "du darfst mich",
    "sprich mich mit meinem namen an",
    "sag ruhig meinen namen",
)


def wants_first_name_permission(text: str) -> bool:
    """Erkennt eine ausdrueckliche Erlaubnis, den Vornamen zu benutzen -
    Gegenstueck zu strip_first_name_address()'s Default-Verhalten (Name
    niemals verwenden), siehe plans/2026-08-11-jarvis-kamera-feedback.md-
    Nachschaerfung / Leons Vorgabe 2026-08-12."""
    normalized = normalize_text(text)
    return any(phrase in normalized for phrase in _NAME_PERMISSION_PHRASES)


def strip_first_name_address(answer: str, creator_name: str) -> str:
    """Deterministischer Rueckhalt gegen das Prompt-Verbot, den Vornamen zu
    benutzen - Leons Vorgabe: Jarvis soll ihn nie beim Vornamen ansprechen,
    ausser er sagt das ausdruecklich. Live beobachtet (2026-08-12): das
    kleinere lokale Modell (phi4-mini) ignorierte die reine Prompt-Anweisung
    trotz konkretem Beispiel gelegentlich - gleiches Muster wie bei anderen
    Bausteinen diese Sitzung (Domaenen-Klassifikation, Mail-Formatierung):
    Prompt-Worte allein reichen nicht, es braucht eine harte Nachbearbeitung.
    Entfernt nur den typischen Anrede-Fall (", Name!"/", Name."/", Name,"),
    nicht jedes Vorkommen des Namens irgendwo im Text - sonst koennte eine
    legitime, andere Erwaehnung des Namens (z.B. in einem zitierten
    Gedaechtnis-Fakt) beschaedigt werden."""
    if not creator_name:
        return answer
    pattern = re.compile(rf",\s*{re.escape(creator_name)}\s*([!.,]|$)", flags=re.IGNORECASE)
    cleaned = pattern.sub(lambda m: m.group(1) if m.group(1) in {"!", "."} else "", answer)
    cleaned = re.sub(rf"^{re.escape(creator_name)}\s*[,:]\s*", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


_INVENTED_FORMAL_NAME = re.compile(
    r"(?:Herr|Frau|Herrn)\s+[A-ZÄÖÜ][\wäöüß]*(?:\s+[A-ZÄÖÜ][\wäöüß]*)?",
    flags=re.UNICODE,
)


def strip_invented_formal_address(answer: str, address: str) -> str:
    """Deterministischer Rueckhalt dagegen, dass das kleine lokale Modell
    (phi4-mini) sich einen Nachnamen ausdenkt und Leon damit anspricht (z.B.
    "..., Herr Müller."), obwohl im Profil (config.json: creator_name/
    user_salutation) nur Vorname + Anrede hinterlegt sind, kein Nachname.
    Live beobachtet 2026-08-18. Leons Vorgabe: Jarvis darf ihn nie anders
    nennen als in den Einstellungen (Vorname oder konfigurierte Anrede).
    Wie strip_first_name_address() bewusst nur auf den typischen
    Anrede-Fall beschraenkt (", Herr X!"/", Herr X."/", Herr X," oder
    "Herr X, " am Satzanfang), nicht auf jedes Vorkommen von "Herr/Frau X"
    im Text - eine legitime Erwaehnung eines Kontakts aus Mail/Kalender/
    Notizen ("Ihr Meeting mit Herrn Schmidt") soll dadurch nicht beschaedigt
    werden."""
    if not answer:
        return answer

    def _replace_trailing(match: "re.Match[str]") -> str:
        trailing = match.group(1)
        return trailing if trailing in {"!", "."} else ""

    pattern = re.compile(
        rf",\s*{_INVENTED_FORMAL_NAME.pattern}\s*([!.,]|$)",
        flags=re.UNICODE,
    )
    cleaned = pattern.sub(_replace_trailing, answer)
    cleaned = re.sub(
        rf"^{_INVENTED_FORMAL_NAME.pattern}\s*[,:]\s*",
        f"{address}, ",
        cleaned,
        flags=re.UNICODE,
    )
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def clean_ai_answer(answer: str) -> str:
    answer = clean_spoken_answer(answer)
    lowered = answer.lower()
    forbidden_memory_phrases = (
        "in dieser sitzung merke ich",
        "dauerhafte speicherung hängt",
        "memory-funktion deiner plattform",
        "memory deiner plattform",
        "plattform/app",
        "welche app/plattform",
        "memory aktiviert",
    )

    if any(phrase in lowered for phrase in forbidden_memory_phrases):
        return (
            "Ich speichere Erinnerungen lokal in meinem Jarvis-Memory. "
            "Sag einfach: Jarvis, merk dir, dass ..."
        )

    forbidden_web_phrases = (
        "keine live-internet-suche",
        "keine live-internetsuche",
        "keine live internet suche",
        "keine live internetsuche",
        "kann ich keine live",
        "kann keine aktuellen ergebnisse liefern",
        "mein wissensstand reicht",
        "mein wissensstand geht",
    )

    if any(phrase in lowered for phrase in forbidden_web_phrases):
        return (
            f"Das war unpräzise, {configured_user_address()}. Frag es noch einmal, dann prüfe ich es direkt."
        )

    forbidden_mail_phrases = (
        "ich sehe deine inbox nicht",
        "ich kann ohne angebundene daten nicht direkt lesen",
        "ich habe keinen direkten zugriff auf dein mailfach",
        "ich habe keinen zugriff auf dein mailfach",
        "ich habe keinen zugriff auf deinen posteingang",
        "ohne zugriff auf dein mailpostfach",
        "wenn du mir die betreffzeilen",
        "wenn du mir den export",
        "welche mail-app nutzt du",
        "welche app ist es",
        "welcher ordner soll",
        "welchen ordner soll",
        "meinst du icloud inbox",
        "meinst du einen konkreten mailordner",
        "der mail-inhalt ist hier nicht zugreifbar",
        "schick mir bitte die nachrichtenübersichten",
    )

    if any(phrase in lowered for phrase in forbidden_mail_phrases):
        return (
            "Ich nutze mein Apple-Mail-Modul. Sag: Jarvis, prüf meinen Posteingang."
        )

    return clean_spoken_answer(answer)


def clean_spoken_answer(text: str) -> str:
    text = str(text).strip()
    if not text:
        return ""

    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    text = text.replace("###", "")
    text = text.replace("##", "")
    text = text.replace("#", "")
    text = text.replace("•", "")
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def clean_mail_answer(answer: str) -> str:
    answer = clean_ai_answer(answer)
    replacements = {
        "Kategorie:": "Kategorie:",
        "Vorschlag:": "Vorschlag:",
    }
    for old, new in replacements.items():
        answer = answer.replace(old, new)
    answer = re.sub(
        r"(?im)^\s*(mail\s*\d+|erstens|zweitens|drittens|punkt\s*\d+|absender|betreff|empfangen|auszug)\s*[:\-]\s*",
        "",
        answer,
    )
    answer = re.sub(r"(?m)^\s*[-*]\s+", "", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = re.sub(r"\n{2,}", "\n", answer)
    return clean_spoken_answer(answer)


MAIL_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Rechnung/Finanzen": (
        "rechnung",
        "invoice",
        "beleg",
        "quittung",
        "zahlung",
        "bezahlt",
        "mahnung",
        "betrag",
        "konto",
        "bank",
        "finanz",
        "gebühr",
        "gebuehr",
    ),
    "Termin/Planung": (
        "termin",
        "meeting",
        "meeting",
        "kalender",
        "verabred",
        "fris",
        "deadline",
        "appointment",
        "schedule",
    ),
    "Wichtig/Antwort": (
        "antwort",
        "rückmeldung",
        "rueckmeldung",
        "dringend",
        "wichtig",
        "bitte",
        "freigabe",
        "entscheidung",
    ),
    "Arbeit/Projekt": (
        "projekt",
        "arbeit",
        "team",
        "ticket",
        "aufgabe",
        "status",
        "update",
        "release",
        "bug",
    ),
    "Newsletter/Werbung": (
        "newsletter",
        "werbung",
        "angebot",
        "promo",
        "sale",
        "rabatt",
        "marketing",
        "update",
    ),
    "Privat": (
        "familie",
        "freund",
        "freunde",
        "privat",
        "nachricht",
        "grüß",
        "gruess",
        "hallo",
    ),
}


def _mail_topic_from_text(text: str) -> str:
    lowered = normalize_text(text)
    for topic, keywords in MAIL_TOPIC_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return topic
    return "Unklar"


def _mail_preview_snippet(preview: str, limit: int = 140) -> str:
    snippet = clean_spoken_answer(str(preview or "").replace("\n", " "))
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) > limit:
        snippet = snippet[: limit - 1].rstrip() + "…"
    return snippet or "Kein Auszug lesbar."


def build_mail_summary_digest(
    messages: list[Any],
    account_name: str | None = None,
    mailbox_name: str | None = None,
) -> str:
    groups: dict[str, list[Any]] = {}
    for message in messages:
        topic = _mail_topic_from_text(f"{message.subject} {message.preview}")
        groups.setdefault(topic, []).append(message)

    samples = {topic: grouped_messages[:3] for topic, grouped_messages in groups.items()}
    sample_ids = [
        message.message_id
        for sample in samples.values()
        for message in sample
        if message.message_id
    ]
    if sample_ids:
        previews = fetch_message_previews(
            sample_ids,
            preview_chars=140,
            account_name=account_name,
            mailbox_name=mailbox_name,
            max_scan=len(messages),
        )
        for sample in samples.values():
            for message in sample:
                message.preview = previews.get(message.message_id, "")

    digest_lines: list[str] = []
    for topic, grouped_messages in groups.items():
        sample = samples[topic]
        digest_lines.append(f"Thema: {topic} | Anzahl: {len(grouped_messages)}")
        for message in sample:
            digest_lines.append(
                "  - "
                f"Von: {message.sender} | "
                f"Betreff: {message.subject} | "
                f"Kurz: {_mail_preview_snippet(message.preview)}"
            )
        if len(grouped_messages) > len(sample):
            digest_lines.append(f"  - Weitere ähnliche Mails: {len(grouped_messages) - len(sample)}")

    return "\n".join(digest_lines)


def summarize_mail_digest_via_llm(
    llm: LLMClient,
    digest: str,
    message_count: int,
    time_hint: str = "",
    user_question: str = "",
) -> str | None:
    """Wandelt einen rohen Mail-Digest (build_mail_summary_digest()) in eine
    kurze, thematisch gebündelte, menschlich klingende Zusammenfassung um -
    gemeinsam genutzt von handle_mail_command() (Chat-Anfragen) und
    MailBackgroundWorker._build_summary() (Hintergrundscan/"Mail-Update"),
    siehe plans/2026-08-10-jarvis-mail-update-menschlich.md. Vorher hatte
    MailBackgroundWorker eine eigene, rein mechanische Zusammenfassung
    ("Absender: Betreff" aneinandergereiht, inkl. voller E-Mail-Adressen) -
    dieselbe Qualität wie hier soll jetzt an beiden Stellen gelten.
    Gibt None zurueck, wenn die LLM-Antwort leer/unbrauchbar war, damit der
    Aufrufer auf eine mechanische Zusammenfassung zurueckfallen kann, statt
    ganz ohne Mail-Update dazustehen.

    `user_question` (optional, leer beim Hintergrund-Scan) ist die tatsaechliche
    Nutzeranfrage aus handle_mail_command() - frueher wurde sie hier nie
    durchgereicht, wodurch JEDE Mail-Formulierung (Absendersuche, "wie viele
    ungelesene", "sortier nach Wichtigkeit", ...) dieselbe generische
    Themen-Zusammenfassung bekam, egal was tatsaechlich gefragt war. Live
    beobachtet 2026-08-19 in einem 2266-Saetze-Testdurchlauf: "Gibt es eine Mail
    von Julia?" und "Wie viele ungelesene Mails habe ich?" bekamen beide
    identisch dieselbe 3-Themen-Zusammenfassung ohne jeden Bezug zur Frage."""
    from core.personality_manager import salutation_instruction

    address_instruction = salutation_instruction(configured_user_name(), str(CONFIG.get("user_salutation", "sir")))
    prompt = [
        {
            "role": "system",
            "content": (
                f"Du bist Jarvis, {configured_user_name()}s persönlicher Assistent. "
                f"{address_instruction} "
                "Fasse Apple-Mail-Übersichten auf Deutsch natürlich, knapp und in normaler gesprochener Sprache zusammen. "
                "Antworte so, als würdest du Leon kurz am Schreibtisch informieren, nicht als würdest du jede Zeile vorlesen. "
                "Wichtig: niemals die Mails einzeln als Liste herunterbeten, keine Zeile-für-Zeile-Wiedergabe, "
                "keine langen Aufzählungen, keine Tabellen und kein Markdown. "
                "Gruppiere ähnliche Mails immer nach Thema und nenne nur die Kernaussagen. "
                "Erwähne Absender, Betreff oder Datum nur, wenn es wirklich hilft. "
                "Die Antwort ist IMMER ein einziger zusammenhängender Fließtext-Absatz ohne Zeilenumbrüche, "
                "am besten in 2 bis 3 Sätzen. Beginne niemals eine Zeile mit einem Kategorie-Namen gefolgt von "
                "Doppelpunkt (also NICHT 'Wichtig: ...' oder 'Newsletter: ...' als eigene Zeile) - wenn du eine "
                "Kategorie erwähnst, dann nur beiläufig innerhalb eines normalen Satzes. "
                "Wenn mehrere ähnliche Mails dabei sind, fasse sie in einem Satz zusammen. "
                "Dir liegen teils nur Absender, Betreff und ein kurzer Auszug vor; formuliere daraus eine verständliche Lageeinschätzung, "
                "ohne zu behaupten, du hättest den vollständigen Text gelesen. "
                "Löschen oder Verschieben nur als Vorschlag, niemals als bereits ausgeführte Aktion. "
                "Mach das kurz, menschlich und mit dem üblichen trockenen Jarvis-Ton.\n\n"
                "Beispiel für den erwarteten Stil (Format, nicht Inhalt übernehmen): "
                "\"Drei Themen, Sir: eine Rechnung von Ihrem Stromanbieter über 64 Euro, fällig Ende des Monats, "
                "außerdem zwei Newsletter, die Sie vermutlich überspringen können, und eine Terminanfrage von "
                "Julia für nächste Woche, auf die Sie noch antworten sollten.\"\n\n"
                + (
                    "WICHTIG: Es gibt eine konkrete Frage von Leon (siehe unten). Beantworte GENAU DIESE Frage "
                    "zuerst und direkt (z.B. ja/nein bei einer Absendersuche, eine konkrete Zahl bei einer "
                    "Mengenfrage), und ergänze erst danach bei Bedarf kurz Kontext aus der Übersicht. Wenn die "
                    "Übersicht die Frage nicht eindeutig beantworten kann, sag das ehrlich statt zu raten oder "
                    "die generische Themen-Zusammenfassung als Ausweichantwort zu geben."
                    if user_question else
                    "Es liegt keine konkrete Frage vor - gib die normale Themen-Zusammenfassung."
                )
            ),
        },
        {
            "role": "user",
            "content": (
                (f"Meine Frage: \"{user_question}\"\n\n" if user_question else "")
                + f"Ich habe {message_count} Mail(s) gelesen. "
                f"{time_hint} "
                + (
                    "Bitte beantworte meine obige Frage direkt, als einen einzigen Fließtext-Absatz "
                    "ohne Zeilenumbrüche und ohne Kategorie-Label am Zeilenanfang:\n\n"
                    if user_question else
                    "Bitte gib mir eine natürliche Zusammenfassung nach Themen, als einen einzigen Fließtext-Absatz "
                    "ohne Zeilenumbrüche und ohne Kategorie-Label am Zeilenanfang. "
                    "Nicht jede Mail einzeln, sondern die Kernthemen und was daran wichtig ist. "
                    "Wenn es mehrere ähnliche Nachrichten gibt, fasse sie gemeinsam zusammen:\n\n"
                )
                + f"{digest}"
            ),
        },
    ]

    answer = llm.ask(
        prompt,
        max_output_tokens=MAIL_SUMMARY_MAX_OUTPUT_TOKENS,
        user_text="mail zusammenfassen und thematisch bündeln",
    )
    if not answer.strip():
        return None
    cleaned = clean_mail_answer(answer)
    # Determinister Rueckhalt gegen das kleine lokale Modell, das die Anweisung
    # "einziger Fliesstext-Absatz" trotz Prompt/Beispiel nicht zuverlaessig
    # befolgt und stattdessen Kategorie-Zeilen ("Wichtig: ...", "Privat: ...")
    # produziert - genau dasselbe Muster wie bei anderen Bausteinen diese
    # Sitzung (Domaenen-Klassifikation, Gedaechtnis-Extraktion): Prompt-Worte
    # allein reichen bei diesem Modell nicht, es braucht eine harte Nachbearbeitung.
    flattened = re.sub(r"\s*\n+\s*", " ", cleaned).strip()
    return strip_first_name_address(flattened, configured_user_name())


def humanize_camera_feedback_via_llm(llm: LLMClient, raw_description: str) -> str | None:
    """Formuliert eine rohe Vision-Modell-Bildbeschreibung
    (LocalVisionService.describe_camera_photo()) in eine persoenliche, direkt
    an den Nutzer gerichtete Einschaetzung um - siehe
    plans/2026-08-11-jarvis-kamera-feedback.md, Nachschaerfung. Ohne diesen
    Schritt kam die rohe Bildunterschrift 1:1 durch: dritte Person ("Die
    Person traegt..."), keine Anrede, keine Jarvis-Persoenlichkeit - live von
    Leon bemaengelt ("das ist nicht die Antwort, die ich erwartet habe").
    Gibt None zurueck, wenn die LLM-Antwort leer war, damit der Aufrufer auf
    die rohe Beschreibung zurueckfallen kann statt ganz ohne Antwort
    dazustehen.

    Live von Leon entdeckter Bug: die rohe Bildbeschreibung (z.B. von einem
    unzuverlaessigen lokalen Vision-Modell, siehe
    local_vision_service.py::VISION_MODEL_CANDIDATES-Kommentar) kann selbst
    schon falsch/erfunden sein - dieser Umformulierungs-Schritt darf das nicht
    verschlimmern, indem er zusaetzliche, in der Roh-Beschreibung gar nicht
    genannte Details (Kleidungsstuecke, Farben) dazuerfindet. Deshalb die
    explizite Treue-Anweisung unten."""
    from core.personality_manager import salutation_instruction

    address_instruction = salutation_instruction(configured_user_name(), str(CONFIG.get("user_salutation", "sir")))
    prompt = [
        {
            "role": "system",
            "content": (
                f"Du bist Jarvis, {configured_user_name()}s persönlicher Assistent. "
                f"{configured_user_name()} hat dich gerade gebeten, sein Aussehen/Outfit über die Kamera zu beurteilen. "
                "Du bekommst eine automatisch erzeugte, neutrale Bildbeschreibung in der dritten Person. "
                f"Formuliere daraus eine kurze, persönliche Einschätzung, die {configured_user_name()} DIREKT anspricht "
                "(nicht 'die Person', sondern 'Sie'/'Ihr Outfit'). "
                "WICHTIG: Bleib strikt bei dem, was in der Bildbeschreibung tatsächlich steht - erfinde keine "
                "zusätzlichen Kleidungsstücke, Farben oder Details, die dort nicht genannt sind. Beschreibt die "
                "Vorlage kaum oder keine Kleidung, sag das genauso direkt und unaufgeregt wie bei einem "
                "vollständigen Outfit. Beschreibt die Vorlage Unsicherheit (zu dunkel, unscharf, unklar), gib das "
                "als Unsicherheit weiter statt etwas Konkretes zu behaupten. "
                f"{address_instruction} "
                "Ein bis zwei Sätze, mit dem üblichen trockenen, sarkastischen Jarvis-Unterton, aber freundlich und "
                "nie abwertend. Kein Markdown, keine Aufzählung, kein Verweis darauf, dass du eine automatische "
                "Bildanalyse umformulierst."
            ),
        },
        {
            "role": "user",
            "content": f"Automatische Bildbeschreibung: {raw_description}",
        },
    ]
    # 600 statt vorher 90 - reasoning-faehige Modelle (aktuell qwen3:4b)
    # bauchen oft 300-500+ Token allein zum Nachdenken, sonst kaeme eine leere
    # Antwort zurueck (siehe llm_client.py::_THINKING_CAPABLE_MODELS).
    answer = llm.ask(prompt, max_output_tokens=600, user_text="kamera outfit feedback umformulieren")
    answer = answer.strip()
    if not answer:
        return None
    return strip_first_name_address(clean_ai_answer(answer), configured_user_name())


def should_ignore_transcript(text: str, audio_stats: dict[str, float]) -> bool:
    normalized = normalize_text(text)

    common_silence_hallucinations = {
        "vielen dank",
        "danke",
        "danke fürs zuschauen",
        "danke für's zuschauen",
        "bis zum nächsten mal",
        "bis zum naechsten mal",
        "untertitel der amara org community",
        "copyright wdr",
    }

    if normalized in common_silence_hallucinations:
        quiet_audio = audio_stats["mean_volume"] < audio_stats["threshold"] * 1.4
        short_audio = audio_stats["duration"] < 1.4
        if quiet_audio or short_audio:
            return True

    if len(normalized) < 3:
        return True

    return False


def has_pending_action(memory: Memory) -> bool:
    settings = memory.get("settings") or {}
    pending_keys = (
        "pending_mail_delete",
        "pending_call_contact",
        "pending_call_choice",
        "pending_permission",
        "pending_note",
        "pending_desktop_move",
        "pending_desktop_move_many",
        "pending_calendar_create",
        "pending_calendar_delete",
        "pending_mail_document_export",
        "pending_file_action",
        "pending_domain_clarification",
        "pending_mail_calendar_confirmation",
        "pending_cleanup_confirmation",
    )
    return any(isinstance(settings.get(key), dict) for key in pending_keys)


def is_short_confirmation(text: str) -> bool:
    normalized = normalize_text(text)
    return normalized in {
        "ja",
        "ja bitte",
        "okay",
        "ok",
        "mach das",
        "ja anrufen",
        "anrufen",
        "ja verschieben",
        "verschieben",
        "ja kopieren",
        "kopieren",
        "abbrechen",
        "nein",
        "nein danke",
        "stop",
        "stopp",
    }


def _whole_words(text: str) -> set[str]:
    """Zerlegt Text in sauly bereinigte, komplette Woerter (keine Teilstrings).

    Wird fuer den Fuzzy-Abgleich in pending_action_matches_text() gebraucht:
    ein naiver `wort in text`-Teilstring-Vergleich matcht auch dann, wenn
    "wach" zufaellig Teil von "wachsen" in einem Mail-Betreff ist - siehe
    Runde-2-Simulation vom 2026-08-13. Ein Vergleich gegen komplette Woerter
    verhindert genau diese Zufallstreffer.
    """
    return set(re.findall(r"[a-zäöüß0-9]+", text.lower()))


def pending_action_matches_text(settings: dict, normalized_text: str) -> bool:
    if any(term in normalized_text for term in ("berechtigung", "erlaub", "freigabe", "zugriff", "bestätig", "bestaetig")):
        return True

    context_by_key = {
        "pending_permission": (),
        "pending_desktop_move": ("desktop", "schreibtisch", "verschieb", "ordner", "datei"),
        "pending_desktop_move_many": ("desktop", "schreibtisch", "verschieb", "ordner", "datei"),
        "pending_calendar_create": ("kalender", "termin", "erinnerung", "erstelle", "morgen", "heute", "uhr"),
        "pending_calendar_delete": ("kalender", "termin", "erinnerung", "lösch", "loesch", "entferne"),
        "pending_mail_document_export": ("mail", "mails", "rechnung", "versicherung", "abo", "kopier"),
        "pending_file_action": ("datei", "ordner", "kopier", "verschieb", "lösch", "loesch", "schreibtisch", "desktop"),
        "pending_mail_delete": ("mail", "mails", "papierkorb", "lösch", "loesch", "verschieb"),
        "pending_call_contact": ("anruf", "anrufen", "ruf", "kontakt", "telefon"),
        "pending_call_choice": ("nummer", "endung", "telefon", "kontakt", "anruf"),
        "pending_mail_calendar_confirmation": ("kalender", "termin", "termine", "vorschlag", "vorschläge", "vorschlaege", "eintragen", "mail", "mails"),
        "pending_cleanup_confirmation": ("papierkorb", "löschen", "loeschen", "datei", "dateien", "speicherplatz", "aufräumen", "aufraeumen"),
    }

    for key, terms in context_by_key.items():
        pending = settings.get(key)
        if not isinstance(pending, dict):
            continue
        pending_words = _whole_words(" ".join(str(value) for value in pending.values()))
        if key == "pending_permission":
            if pending_words and any(word for word in normalized_text.split() if len(word) > 5 and word in pending_words):
                return True
            continue
        if any(term in normalized_text for term in terms):
            return True
        if pending_words and any(word for word in normalized_text.split() if len(word) > 3 and word in pending_words):
            return True

    return False


def _memory_overview_answer(memory: Memory, memory_system: "JarvisMemorySystem") -> str:
    fact_summary = memory_system.facts_summary()
    if fact_summary == "Keine wichtigen Langzeitnotizen.":
        return "Ich habe mir bisher noch keine Langzeit-Erinnerungen gespeichert."

    # Noch unbestaetigte, automatisch extrahierte Fakten (status="pending_confirmation",
    # z.B. aus Screen-Vision/LLM-Auto-Extraktion) sollen hier NICHT als bereits
    # feststehend vorgelesen werden - genau dieselbe Ausschluss-Regel wie
    # ContextEngine.select_facts() (app/core/context_engine.py) fuer den
    # Prompt-Kontext, hier aber bisher gefehlt. Live beobachtet 2026-08-20 im
    # Mehrfach-Audit: ein falsch erkannter, nie vom Nutzer geprueften Fakt wurde
    # auf "Was weißt du über mich" hin als Tatsache praesentiert.
    facts = [f for f in memory.all_facts() if f.get("status", "confirmed") != "pending_confirmation"][-10:]
    settings = memory.get("settings") or {}
    settings["pending_memory_list"] = [item.get("content", "") for item in facts]
    memory.set("settings", settings)
    fact_list = "\n".join(f"{index + 1}. {item['content']}" for index, item in enumerate(facts))
    return (
        f"Das habe ich mir gemerkt:\n{fact_list}\n"
        "Sag z. B. 'vergiss Nummer 3', wenn ich mir davon etwas nicht mehr merken soll."
    )


def handle_memory_command(memory: Memory, text: str) -> str | None:
    normalized = text.strip()
    lowered = normalized.lower().rstrip("?!. ")
    memory_system = JarvisMemorySystem(memory)

    if lowered in {"was weißt du über mich", "was weisst du über mich", "was hast du dir gemerkt"}:
        return _memory_overview_answer(memory, memory_system)

    # Meta-Frage nach dem Gespraechsverlauf ("woran haben wir zuletzt
    # gearbeitet", "was haben wir gerade gemacht") ist etwas anderes als eine
    # Frage nach einem gespeicherten Fakt - Jarvis merkt sich Fakten
    # dauerhaft, aber KEINEN Gespraechsverlauf. Live entdeckter Bug
    # (Runde-2-Simulation, 2026-08-13): ohne eigenen Pfad landete das im
    # freien Chat, der aus dem letzten Gespraechsfetzen selbstbewusst eine
    # frei erfundene "Erinnerung" praesentierte ("Ja, Sie haben mich
    # gebeten..."). Eine ehrliche Absage ist fuer einen Assistenten, dem man
    # vertrauen soll, besser als eine selbstbewusst falsche Antwort. Siehe
    # docs/current-system-assessment.md, Abschnitt 42.
    conversation_recall_phrases = (
        "woran haben wir", "woran wir zuletzt", "woran ich zuletzt", "woran wir gerade",
        "was haben wir zuletzt", "was haben wir gerade gemacht", "letztes gespräch", "letztes gespraech",
        "worüber haben wir gesprochen", "worueber haben wir gesprochen", "was haben wir besprochen",
    )
    if any(phrase in lowered for phrase in conversation_recall_phrases):
        return (
            "Ich merke mir wichtige Fakten dauerhaft, aber keinen laufenden Gesprächsverlauf. "
            "Sagen Sie mir gern kurz, worum es ging, dann kann ich anknüpfen."
        )

    forget_numbered_match = re.match(
        r"^vergiss\s+(?:die|den|nummer|fakt|den\s+punkt)?\s*"
        r"(\d+|erste|zweite|dritte|vierte|f(?:ü|ue)nfte|sechste|siebte|achte|neunte|zehnte)n?\.?$",
        lowered,
        flags=re.IGNORECASE,
    )
    if forget_numbered_match:
        ordinal_words = {
            "erste": 1,
            "zweite": 2,
            "dritte": 3,
            "vierte": 4,
            "fünfte": 5,
            "fuenfte": 5,
            "sechste": 6,
            "siebte": 7,
            "achte": 8,
            "neunte": 9,
            "zehnte": 10,
        }
        raw_index = forget_numbered_match.group(1)
        index = int(raw_index) if raw_index.isdigit() else ordinal_words.get(raw_index)

        settings = memory.get("settings") or {}
        pending_list = settings.get("pending_memory_list") or []
        if not index or index < 1 or index > len(pending_list):
            return "Dazu habe ich gerade keine passende Nummer aus der letzten Liste."

        content = pending_list[index - 1]
        removed = memory.forget_exact(content)
        if removed:
            return f"Erledigt, ich habe mir das nicht mehr gemerkt: {content}"
        return "Das konnte ich nicht mehr finden - vielleicht war es schon weg."

    # Freies "vergiss/lösche/entferne <Beschreibung>" (im Unterschied zum obigen
    # Block, der nur "vergiss Nummer X" aus einer zuvor gezeigten Liste abdeckt).
    # Frueher lief dieses Muster ausschliesslich still im Hintergrund ueber
    # auto_update_memory() mit, das zwar tatsaechlich den passenden Fakt loeschte,
    # aber KEINE Rueckmeldung gab - der Nutzer sah stattdessen die unpassende
    # Antwort des allgemeinen Chat-Pfads, wodurch das Loeschen unsichtbar blieb.
    # Live beobachtet 2026-08-18. Hier vor den allgemeinen Chat-Pfad gezogen, damit
    # der Nutzer eine klare Bestaetigung bekommt.
    forget_free_text_match = re.match(
        r"^(?:vergiss|lösche|loesche|streich|entferne),?\s+(?:bitte\s+)?(?:dass\s+)?(.+)$",
        lowered,
        flags=re.IGNORECASE,
    )
    # Nicht abfangen, wenn der Satz eigentlich zu einer anderen Domaene gehoert
    # ("lösche die Mail von X", "vergiss die Erinnerung ans Zahnarzt" -> Termin/
    # Reminders-App, nicht Gedaechtnis-Fakt) - "erinnerung" ist im Deutschen fuer
    # beides ueberladen (Erinnerung=Gedaechtnis UND Erinnerung=Reminder-App-Eintrag).
    # In diesen Faellen None zurueckgeben, damit die eigentlich zustaendige
    # Domaenen-Logik weiter unten in der Kette zum Zug kommt.
    forget_other_domain = forget_free_text_match and any(
        has_domain(text, domain) for domain in ("calendar", "mail", "photos", "files", "notes", "tasks")
    )
    if forget_free_text_match and not forget_other_domain:
        query = forget_free_text_match.group(1).strip()
        removed = memory_system.maybe_forget(query)
        if removed:
            plural = "e" if removed != 1 else ""
            return f"Erledigt, ich habe {removed} passende Erinnerung{plural} nicht mehr gespeichert."
        return "Dazu habe ich nichts Passendes gefunden, das ich vergessen könnte."

    remember_patterns = [
        r"^(?:merk dir|merke dir|erinnere dich daran),?\s*(?:dass\s+)?(.+)$",
        r"^(?:speicher|speichere),?\s*(?:dass\s+)?(.+)$",
        r"^(?:kannst du dir merken|bitte merk dir|bitte merke dir),?\s*(?:dass\s+)?(.+)$",
    ]

    for pattern in remember_patterns:
        match = re.match(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue

        memory_text = normalized[match.start(1):].strip(" .,!?:;")
        memory_system.remember_user_fact(memory_text)
        return f"Verstanden. Ich merke mir: {memory_text}"

    recall_patterns = [
        r"^(?:was weißt du über|was weisst du über|was hast du über)\s+(.+)$",
        r"^(?:erinnerst du dich an|weißt du noch|weisst du noch)\s+(.+)$",
    ]

    for pattern in recall_patterns:
        match = re.match(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue

        topic = normalized[match.start(1):].strip(" .,!?:;")
        # "was weisst du ueber mich" landete bisher hier statt in der obigen
        # Uebersicht, weil "mich" faelschlich als Such-THEMA statt als
        # Selbstbezug behandelt wurde ("mich" ist nie ein echtes Thema) -
        # lieferte die kaputte Antwort "Dazu habe ich noch nichts im
        # Langzeitgedaechtnis: mich". Siehe
        # docs/current-system-assessment.md, Abschnitt 41.
        if topic.lower().rstrip("?!. ") in {"mich", "mir"}:
            return _memory_overview_answer(memory, memory_system)

        # Gleiche Ausschluss-Regel wie oben in _memory_overview_answer() - ein
        # unbestaetigter Fakt soll nicht als feststehend praesentiert werden.
        results = [
            f for f in memory.search_facts(topic) if f.get("status", "confirmed") != "pending_confirmation"
        ]
        if not results:
            return f"Dazu habe ich noch nichts im Langzeitgedächtnis: {topic}"

        facts = "\n".join(f"- {item['content']}" for item in results[:5])
        return f"Das habe ich dazu gespeichert:\n{facts}"

    return None


def handle_pending_note_flow(memory: Memory, text: str) -> str | None:
    settings = memory.get("settings") or {}
    pending = settings.get("pending_note")
    if not isinstance(pending, dict):
        return None

    if normalize_text(text) in {"abbrechen", "vergiss es", "stopp", "stop"}:
        settings.pop("pending_note", None)
        memory.set("settings", settings)
        return "Alles klar, ich habe die offene Notiz verworfen."

    # Neue, eigenstaendige Notiz-Anfrage waehrend eine alte Notiz-Rueckfrage noch
    # offen war: nicht als Titel/Inhalt der alten Notiz uebernehmen, sondern die
    # alte verwerfen und frisch neu parsen lassen (return None laesst die
    # Handler-Kette bis zu handle_notes_command weiterlaufen). Gleiches Muster wie
    # der analoge Kalender-Bug in handle_pending_action_flow() (siehe dort). Live
    # beobachtet 2026-08-18: eine vollstaendige neue "erstelle eine Notiz mit dem
    # Titel X und dem Inhalt Y"-Anfrage wurde als Titel-Antwort auf eine laengst
    # ueberholte alte Rueckfrage genommen statt frisch verarbeitet zu werden.
    if has_domain(text, "notes") and extract_note_title(text):
        settings.pop("pending_note", None)
        memory.set("settings", settings)
        return None

    # Robusterer, domaenen-basierter Bail-out statt eines reinen Verb-Wortlisten-
    # Abgleichs: matcht die Nachricht auf irgendeine ANDERE Domaene (Mail,
    # Kalender, Dateien, Musik, ...), ist es so gut wie sicher kein Notiz-Inhalt,
    # egal mit welchem Verb der Satz anfaengt. COMMAND_SHAPE_PREFIXES (naechster
    # Block) hat zwangslaeufig Luecken (z.B. "durchsuch" fehlte) - live
    # beobachtet 2026-08-20: "Wie ist der Status meiner Mails?" (QUESTION_SHAPE-
    # Treffer auf "wie") bekam die "lasse offen stehen"-Ausweichantwort, obwohl
    # es erkennbar eine Mail-Frage war, und mehrere weitere unabhaengige
    # Mail-Fragen dahinter blieben genauso haengen, bis schliesslich
    # "Durchsuch mein Postfach nach der Bank." (kein COMMAND_SHAPE_PREFIXES-
    # Treffer) als Notiz-Inhalt gespeichert wurde.
    for _other_domain in DOMAIN_TERMS:
        if _other_domain != "notes" and has_domain(text, _other_domain):
            settings.pop("pending_note", None)
            memory.set("settings", settings)
            return None

    # Ergaenzender Schutz zum obigen Bail-out: der beginnt eine Rueckfrage NUR,
    # wenn extract_note_title() etwas findet - Saetze wie "Zeig mir die Notiz X"
    # oder "Lies mir meine letzte Mail vor" haben aber gar keinen extrahierbaren
    # Notiz-Titel (kein "mit dem Titel..."-Muster) und rutschten deshalb bisher
    # unbemerkt durch bis zur Zustands-Verarbeitung unten, wo der komplette Satz
    # als Titel/Inhalt der laengst unabhaengigen alten Rueckfrage gespeichert
    # wurde. COMMAND_SHAPE_PREFIXES faengt genau diese vollstaendigen,
    # eigenstaendigen Befehle am Satzanfang ab (siehe deren Kommentar).
    if normalize_text(text).startswith(COMMAND_SHAPE_PREFIXES):
        settings.pop("pending_note", None)
        memory.set("settings", settings)
        return None

    state = pending.get("state")
    title = str(pending.get("title") or "").strip()
    body = str(pending.get("body") or "").strip()

    # Sieht die Nachricht eher nach einer eigenstaendigen Frage aus als nach
    # Notiz-Inhalt? Live entdeckter Bug: eine voellig unabhaengige Folgefrage
    # ("Welche Aufgaben sind noch offen?") wurde bisher stillschweigend als
    # Notiz-Text uebernommen, weil hier jede Antwort ungeprueft akzeptiert
    # wurde. Gleiches Schutzmuster wie in handle_pending_action_flow() - beide
    # nutzen jetzt QUESTION_SHAPE_PREFIXES, siehe deren Kommentar fuer die
    # Geschichte, warum eine gemeinsame Liste noetig wurde. Siehe
    # docs/current-system-assessment.md, Abschnitt 41 und 42.
    normalized_reply = normalize_text(text)
    if normalized_reply.startswith(QUESTION_SHAPE_PREFIXES):
        pending_label = title or "die Notiz"
        return (
            f"Das klingt nach einer eigenen Frage, nicht nach Notiz-Inhalt. "
            f"Ich lasse {pending_label} erstmal offen stehen - sag mir, was rein soll, "
            "oder \"abbrechen\", um die Notiz zu verwerfen."
        )

    if state == "awaiting_title":
        title = clean_note_title(text)
        pending["title"] = title
        if body:
            settings.pop("pending_note", None)
            memory.set("settings", settings)
            return save_note_or_append(title, body, append=bool(pending.get("append", False)))

        pending["state"] = "awaiting_body"
        settings["pending_note"] = pending
        memory.set("settings", settings)
        return f"Alles klar. Was soll in die Notiz {title} rein?"

    if state == "awaiting_body":
        body = clean_note_body(text)
        settings.pop("pending_note", None)
        memory.set("settings", settings)
        return save_note_or_append(title or "Neue Notiz", body, append=bool(pending.get("append", False)))

    return None


_DOMAIN_CLARIFICATION_LABELS = ("mail", "calendar", "notes", "files", "photos", "screen", "contacts", "music", "tasks")


def classify_domain_via_llm(llm: LLMClient, question: str) -> list[str]:
    """Stufe 2 der Absichtserkennung (siehe plans/2026-08-08-jarvis-intelligenz-
    verbessern.md): eine knappe Klassifikationsanfrage ans ohnehin geladene kleine
    lokale Modell, NUR als Sicherheitsnetz, wenn has_domain()/has_domain_fuzzy()
    (Stufe 1) fuer KEINE Domaene angeschlagen hat. Gibt 0-2 plausible Domaenen
    zurueck, nie mehr - im Zweifel lieber nichts vorschlagen als falsch raten."""
    labels_text = ", ".join(_DOMAIN_CLARIFICATION_LABELS)
    messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein reiner Klassifikator, kein Gespraechspartner. Ordne die "
                f"Nutzeranfrage GENAU EINER dieser Kategorien zu: {labels_text}, keine. "
                "Antworte NUR mit dem Kategorie-Wort, klein geschrieben, ohne Satzzeichen "
                "und ohne Erklaerung. Bist du unsicher zwischen zwei Kategorien, antworte "
                "mit beiden, getrennt durch ein Komma. Passt erkennbar keine Kategorie, "
                "antworte mit 'keine'.\n\n"
                "Eine reine Aussage ueber die Person selbst (Wohnort, Alter, Vorlieben, "
                "Beruf, Eigenschaften) ist KEINE der obigen Faehigkeiten, auch wenn sie "
                "Woerter wie Jahre, Datum oder einen Ortsnamen enthaelt - solche Saetze "
                "beantwortest du immer mit 'keine'.\n"
                "Smalltalk, Begruessungen, Fragen nach deinem Befinden/deiner Meinung/deinen "
                "Faehigkeiten als Gespraechspartner, Witze oder allgemeines Plaudern sind "
                "ebenfalls IMMER 'keine' - auch wenn ein Wort zufaellig an eine Faehigkeit "
                "erinnert (z.B. 'geht' in 'wie geht es dir').\n"
                "Beispiele:\n"
                "'Ich lebe schon seit 18 Jahren in Amberg in Deutschland' -> keine\n"
                "'Ich mag lieber kurze Antworten' -> keine\n"
                "'Wie ist das Wetter heute' -> keine\n"
                "'Wie geht es dir, Jarvis?' -> keine\n"
                "'Was machst du gerade so?' -> keine\n"
                "'Erzaehl mir einen Witz' -> keine\n"
                "'Was haeltst du davon?' -> keine\n"
                "'Trag morgen um 9 Uhr einen Termin beim Arzt ein' -> calendar\n"
                "'Hast du neue Mails fuer mich' -> mail"
            ),
        },
        {"role": "user", "content": question},
    ]
    try:
        # 600 statt vorher 20 - gleicher Grund wie bei
        # _run_llm_memory_extraction(): reasoning-faehige Modelle brauchen oft
        # 300-500+ Token allein zum Nachdenken, sonst kommt die eigentliche
        # Ein-Wort-Klassifikation nie an. Live beobachtet 2026-08-19.
        raw = llm.ask(messages, max_output_tokens=600, user_text=question, raw_system_prompt=True)
    except Exception:
        return []

    found: list[str] = []
    for token in re.split(r"[,;/]", raw.lower()):
        cleaned = token.strip().strip(".:!? ")
        if cleaned in _DOMAIN_CLARIFICATION_LABELS and cleaned not in found:
            found.append(cleaned)
        if len(found) >= 2:
            break
    return found


_DOMAIN_CLARIFICATION_PHRASES = {
    "mail": "Ihre Mails",
    "calendar": "Ihren Kalender oder eine Erinnerung",
    "notes": "eine Notiz",
    "files": "Ihre Dateien oder Ihren Schreibtisch",
    "photos": "Ihre Fotos",
    "screen": "Ihren Bildschirm",
    "contacts": "Ihre Kontakte",
    "music": "die Musik",
    "tasks": "Ihre Aufgaben",
}


def maybe_ask_domain_clarification(
    llm: LLMClient,
    memory: Memory,
    question: str,
    *,
    photo_worker: PhotoBackgroundWorker | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Wird nur aufgerufen, wenn Stufe 1 nichts erkannt hat. Statt die Anfrage
    stillschweigend in den werkzeuglosen Chat fallen zu lassen, prueft Jarvis aktiv,
    ob Stufe 2 eine plausible Faehigkeit vermutet.

    Siehe plans/2026-08-16-jarvis-stufe2-klassifikation-direkt-beantworten.md: bei
    GENAU EINER erkannten Domaene wird zuerst versucht, direkt ueber
    _dispatch_confirmed_domain() zu antworten (denselben Handler, den auch ein
    echter Stichwort-Treffer ausloesen wuerde) - liefert der eine echte Antwort,
    wird die zurueckgegeben, keine Rueckfrage noetig. Nur wenn der Handler trotz
    erkannter Domaene nichts Konkretes liefert (None), oder bei ZWEI erkannten
    Domaenen (echte Mehrdeutigkeit), fragt Jarvis wie bisher nach - nie eine
    Vermutung stillschweigend ausfuehren (Leons ausdrueckliche Vorgabe: bei
    Unsicherheit nachfragen, nie raten)."""
    domains = classify_domain_via_llm(llm, question)
    if not domains:
        return None

    try:
        logger = PrivacyLogger(memory.base_path / "logs")
    except Exception:
        logger = None

    if len(domains) == 1 and bool((config or {}).get("stage2_direct_dispatch_enabled", True)):
        direct_answer = _dispatch_confirmed_domain(domains[0], question, memory, photo_worker=photo_worker)
        if direct_answer is not None:
            if logger is not None:
                try:
                    logger.log("intent_stage2", "domain_dispatched_directly", success=True, domain=domains[0])
                except Exception:
                    pass
            return direct_answer
        # _dispatch_confirmed_domain() konnte trotz erkannter Domaene nichts
        # Konkretes liefern (Handler gab None zurueck) - faellt bewusst auf die
        # Rueckfrage unten zurueck statt weiter zu raten oder in generischen Chat
        # zu fallen.

    if logger is not None:
        try:
            logger.log("intent_stage2", "domain_guessed", success=True, domain_count=len(domains))
        except Exception:
            pass

    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": domains, "question": question}
    memory.set("settings", settings)

    if len(domains) == 1:
        guess = _DOMAIN_CLARIFICATION_PHRASES.get(domains[0], domains[0])
        return f"Meinten Sie gerade {guess}, oder ging es um etwas anderes? Sagen Sie kurz, was gemeint war."
    guesses = " oder ".join(_DOMAIN_CLARIFICATION_PHRASES.get(domain, domain) for domain in domains)
    return f"Ging es dabei um {guesses}? Sagen Sie kurz, was gemeint war, dann mach ich weiter."


def _dispatch_confirmed_domain(
    domain: str,
    question: str,
    memory: Memory,
    photo_worker: PhotoBackgroundWorker | None = None,
) -> str | None:
    """Ruft denselben Domaenen-Handler auf, den auch ein direkter Stichwort-Treffer
    ausloesen wuerde - genutzt von handle_pending_domain_clarification_flow, NACHDEM
    der Nutzer eine Stufe-2-Rueckfrage bestaetigt hat. `question` ist hier bereits um
    das kanonische Domaenen-Stichwort ergaenzt (siehe Aufrufer), damit Handler mit
    eigener, separater Stichwort-Erkennung (z. B. handle_mail_command) die Anfrage
    zuverlaessig selbst erkennen, statt sich auf has_domain() allein zu verlassen."""
    permission_prompts = {
        "notes": "Jarvis würde eine Notiz über Apple Notes erstellen oder ändern.",
        "calendar": "Jarvis würde Kalenderdaten verwenden.",
        "files": "Jarvis würde Ihren Schreibtisch oder Dateien lokal lesen oder ändern.",
        "photos": "Jarvis würde Ihre Fotos-App oder den lokalen Fotoindex verwenden.",
        "screen": "Jarvis würde einen einzelnen Screenshot deines aktiven Fensters aufnehmen und lokal analysieren.",
        "mail": "Jarvis würde Apple Mail lokal lesen oder bearbeiten.",
        "contacts": "Jarvis würde Kontakte lesen oder einen Anruf vorbereiten.",
        "music": "Jarvis würde Apple Music oder die Musik-Wiedergabe steuern.",
    }
    prompt_text = permission_prompts.get(domain)
    if prompt_text is not None:
        permission_answer = ensure_privacy_domain_permission(memory, domain, prompt_text)
        if permission_answer is not None:
            return permission_answer
        # Der primaere Stufe-1-Dispatch (siehe answer_message()) prueft fuer
        # Erinnerungs-Formulierungen zusaetzlich die eigene "reminders"-
        # Berechtigung, getrennt von "calendar" - dieser Stufe-2-Pfad
        # (nach einer bestaetigten Domaenen-Rueckfrage) tat das bisher nicht
        # und fuehrte live Reminders/EventKit-Zugriffe aus, obwohl der Nutzer
        # nur "calendar" erlaubt und "reminders" bewusst nicht erteilt hatte.
        # Live beobachtet 2026-08-20 im Mehrfach-Audit.
        if domain == "calendar" and "erinner" in normalize_text(question):
            reminders_answer = ensure_privacy_domain_permission(
                memory, "reminders", "Jarvis würde eine Erinnerung verwenden."
            )
            if reminders_answer is not None:
                return reminders_answer

    if domain == "notes":
        return handle_notes_command(memory, question)
    if domain == "tasks":
        return handle_tasks_command(memory, question)
    if domain == "calendar":
        return handle_calendar_command(question, memory=memory)
    if domain == "files":
        return handle_desktop_command(question, memory=memory) or handle_file_command(question, memory=memory)
    if domain == "photos":
        return handle_photo_command(question, photo_worker, memory=memory)
    if domain == "screen":
        if not has_permission("screen"):
            return None
        return handle_screen_command(question, memory=memory)
    if domain == "mail":
        return handle_mail_command(LLMClient(CONFIG), question, force=True, memory=memory)
    if domain == "contacts":
        return handle_contact_command(question, memory=memory)
    if domain == "music":
        return handle_music_command(question)
    return None


_MULTISTEP_CONNECTOR_WORDS = (
    " und dann ",
    " und ",
    " danach ",
    " anschliessend ",
    " ausserdem ",
    " sowie ",
    " zusaetzlich ",
)


def looks_like_multistep_request(text: str) -> bool:
    """Baustein E (siehe plans/2026-08-09-jarvis-mehrstufige-auftraege.md): bewusst
    konservativer Ausloeser fuer die Stufe-3-Planung - nur wenn Stufe 1 bereits
    ZWEI verschiedene Domaenen im selben Satz erkennt UND ein Verbindungswort
    vorkommt. Lieber einen echten Mehrschritt-Auftrag einmal verpassen (dann laeuft
    er wie bisher als Einzelschritt weiter) als einen einfachen Satz faelschlich in
    mehrere Schritte zerlegen."""
    normalized = normalize_umlauts(normalize_text(text))
    padded = f" {normalized} "
    if not any(connector in padded for connector in _MULTISTEP_CONNECTOR_WORDS):
        return False
    matched_domains = {domain for domain in DOMAIN_TERMS if has_domain(text, domain)}
    # "camera" und "photos" teilen sich absichtlich das Stichwort "foto" (siehe
    # Kommentar bei DOMAIN_TERMS["camera"]) - ein einzelner, zusammenhaengender
    # Kamera-Wunsch wie "Mach ein Foto von mir und sag mir wie ich aussehe."
    # matcht dadurch BEIDE Domaenen und wurde faelschlich als
    # Zwei-Domaenen-Mehrschritt-Auftrag geplant, obwohl es nur eine einzige
    # Bitte ist. Live beobachtet 2026-08-19: die Planung erfand daraufhin
    # unabhaengige, nie angeforderte Zusatzschritte (Mail, Notiz). Das
    # ueberlappende Wortpaar zaehlt hier deshalb nur als EINE Domaene.
    if {"camera", "photos"} <= matched_domains:
        matched_domains = matched_domains - {"photos"}
    return len(matched_domains) >= 2


def _multistep_abort_suggestion(remaining_steps: list[dict[str, Any]], failed_step: dict[str, Any] | None = None) -> str:
    remaining_steps = remaining_steps or []
    if not remaining_steps:
        return "Sag mir gern, wie ich stattdessen weiterhelfen kann."
    names = ", ".join(
        _DOMAIN_CLARIFICATION_PHRASES.get(str(step.get("domain")), str(step.get("domain")))
        for step in remaining_steps
    )
    return (
        f"Die restlichen Schritte ({names}) habe ich noch nicht angefasst. Sag mir, "
        "ob ich sie trotzdem einzeln nacheinander machen soll, oder ob ich es anders "
        "angehen soll."
    )


def execute_multistep_plan(
    steps: list[dict[str, Any]],
    memory: Memory,
    photo_worker: PhotoBackgroundWorker | None = None,
    done_summaries: list[str] | None = None,
) -> str:
    """Baustein E: arbeitet einen vorab geplanten, festen Schritt-Plan streng
    sequenziell ab - jeder Schritt laeuft ueber denselben Domaenen-Dispatch wie ein
    normaler Einzelschritt-Auftrag (_dispatch_confirmed_domain), inklusive dessen
    bestehender Berechtigungs- und Bestaetigungslogik. Braucht ein Schritt eine
    Bestaetigung (neuer pending_*-Schluessel in den Settings, z.B. Mail loeschen
    oder eine fehlende Berechtigung), haelt die GESAMTE Kette an und merkt sich die
    restlichen Schritte in memory["settings"]["pending_multistep_queue"] - erst nach
    Bestaetigung/Ablehnung geht es weiter (siehe _continue_multistep_chain_if_pending).
    Bricht ein Schritt mit einem Fehler ab, stoppt die Kette ebenfalls, macht dabei
    aber konkrete Vorschlaege statt nur zu melden, wie weit sie gekommen ist."""
    done_summaries = list(done_summaries or [])
    remaining = list(steps)
    while remaining:
        step = remaining.pop(0)
        domain = str(step.get("domain") or "")
        teilauftrag = str(step.get("teilauftrag") or "")
        settings_before = memory.get("settings") or {}
        pre_keys = set(settings_before.keys())

        try:
            result = _dispatch_confirmed_domain(domain, teilauftrag, memory, photo_worker=photo_worker)
        except Exception:
            result = None

        settings_after = memory.get("settings") or {}
        new_pending_keys = [
            key
            for key in settings_after.keys()
            if key.startswith("pending_")
            and key != "pending_multistep_queue"
            and key not in pre_keys
            and isinstance(settings_after.get(key), dict)
        ]
        if new_pending_keys:
            waiting_key = new_pending_keys[0]
            settings_after["pending_multistep_queue"] = {
                "retry_step": step,
                "remaining_steps": remaining,
                "waiting_on_key": waiting_key,
                "done_summaries": done_summaries,
            }
            memory.set("settings", settings_after)
            summary = " ".join(part for part in done_summaries if part).strip()
            parts = [part for part in (summary, result) if part]
            return " ".join(parts) if parts else (result or "")

        if result is None:
            summary = " ".join(part for part in done_summaries if part).strip()
            suggestion = _multistep_abort_suggestion(remaining, failed_step=step)
            failure = f'Bei "{teilauftrag}" konnte ich leider nicht weiterhelfen.'
            parts = [part for part in (summary, failure, suggestion) if part]
            return " ".join(parts)

        done_summaries.append(result)

    return " ".join(part for part in done_summaries if part).strip() or "Erledigt."


def _continue_multistep_chain_if_pending(
    memory: Memory,
    resolved_key: str,
    result: str | None,
    *,
    aborted: bool,
    photo_worker: PhotoBackgroundWorker | None = None,
) -> str | None:
    """Wird nach JEDER Aufloesung eines pending_*-Zustands aufgerufen (Bestaetigung,
    Ablehnung oder Berechtigungs-Antwort) - macht nichts, wenn gerade keine
    Mehrschritt-Kette darauf wartet (`result` unveraendert), sonst fuehrt sie die
    Kette fort oder bricht sie mit Vorschlaegen ab."""
    settings = memory.get("settings") or {}
    queue = settings.get("pending_multistep_queue")
    if not isinstance(queue, dict) or queue.get("waiting_on_key") != resolved_key:
        return result

    settings.pop("pending_multistep_queue", None)
    memory.set("settings", settings)
    done_summaries = list(queue.get("done_summaries") or [])
    remaining = list(queue.get("remaining_steps") or [])
    retry_step = queue.get("retry_step")

    if aborted:
        suggestion = _multistep_abort_suggestion(remaining, failed_step=retry_step)
        summary = " ".join(part for part in done_summaries if part).strip()
        parts = [part for part in (summary, result, suggestion) if part]
        return " ".join(parts)

    if resolved_key == "pending_permission" and isinstance(retry_step, dict):
        # Die Berechtigung wurde gerade erst erteilt - der Schritt, der sie
        # ausgeloest hat, wurde noch NICHT ausgefuehrt (nur die Rueckfrage), also
        # jetzt genau einmal automatisch nachholen statt den Nutzer erneut zu
        # bitten, die Anfrage zu wiederholen ("stelle deine Anfrage noch einmal")
        # - das waere mitten in einer bereits bestaetigten Kette verwirrend.
        remaining = [retry_step] + remaining
    elif result:
        # ActionEngine-basierte Bestaetigung (z.B. Mail loeschen): der Schritt
        # wurde bereits vollstaendig ausgefuehrt, `result` ist sein fertiges
        # Ergebnis - nur noch mit den restlichen Schritten weitermachen.
        done_summaries.append(result)

    return execute_multistep_plan(remaining, memory, photo_worker=photo_worker, done_summaries=done_summaries)


def handle_pending_domain_clarification_flow(
    memory: Memory,
    text: str,
    photo_worker: PhotoBackgroundWorker | None = None,
) -> str | None:
    settings = memory.get("settings") or {}
    pending = settings.get("pending_domain_clarification")
    if not isinstance(pending, dict):
        return None

    normalized = normalize_text(text)
    candidates = [str(domain) for domain in (pending.get("domains") or []) if str(domain) in DOMAIN_TERMS]
    original_question = str(pending.get("question") or text)

    # Einmalige Rueckfrage - Zustand wird so oder so aufgeraeumt, egal wie die
    # Antwort ausfaellt, damit keine Endlosschleife aus Rueckfragen entstehen kann.
    settings.pop("pending_domain_clarification", None)
    memory.set("settings", settings)

    if normalized in {"nein", "nein danke", "abbrechen", "vergiss es", "stopp", "stop", "weder noch", "nichts davon"}:
        return "Alles klar, dann lass ich das - sagen Sie gern nochmal genauer, was ich für Sie tun soll."

    chosen: str | None = None
    if len(candidates) == 1 and normalized in {"ja", "ja bitte", "ok", "okay", "genau", "richtig", "stimmt"}:
        chosen = candidates[0]
    else:
        for domain in candidates:
            if has_domain(text, domain):
                chosen = domain
                break

    if chosen is None:
        # Antwort bestaetigt keine der Vermutungen und verneint auch nicht klar -
        # nicht raten, stattdessen normal weiterverarbeiten lassen (die Antwort
        # koennte z.B. auch ein komplett neuer, unabhaengiger Satz sein).
        return None

    # Wenn die Antwort selbst schon ein vollstaendiger, eigenstaendiger Satz ist
    # (nicht nur ein blosses "ja"/"genau"), dann direkt SIE dispatchen statt sie
    # mit der alten `original_question` zu verknuepfen - sonst "erbt" der naechste,
    # eigentlich unabhaengige Befehl den Text der laengst beantworteten Rueckfrage.
    # Live beobachtet 2026-08-19: "Kannst du Rechnung.pdf finden?" -> Rueckfrage
    # "Meinten Sie Ihre Dateien?" -> naechster, davon unabhaengiger Satz "Suche die
    # Datei Urlaubsfotos.jpg." durchsuchte faelschlich nach "Rechnung.pdf" aus der
    # alten Rueckfrage, weil hier bedingungslos mit original_question verknuepft
    # wurde. Nur echte blosse Bestaetigungen ("ja"/"genau"/...) tragen selbst
    # keinen Inhalt und brauchen die alte Frage wirklich noch.
    if normalized not in {"ja", "ja bitte", "ok", "okay", "genau", "richtig", "stimmt"}:
        direct_answer = _dispatch_confirmed_domain(chosen, text, memory, photo_worker=photo_worker)
        if direct_answer is not None:
            return direct_answer

    canonical_term = DOMAIN_TERMS.get(chosen, ("",))[0]
    reformulated = f"{canonical_term} {original_question}".strip()
    return _dispatch_confirmed_domain(chosen, reformulated, memory, photo_worker=photo_worker)


def handle_pending_action_flow(
    memory: Memory,
    text: str,
    photo_worker: PhotoBackgroundWorker | None = None,
    mail_worker: MailBackgroundWorker | None = None,
) -> str | None:
    settings = memory.get("settings") or {}
    normalized = normalize_text(text)
    confirm_terms = {
        "ja",
        "ja bitte",
        "ok",
        "okay",
        "mach das",
        "mach bitte",
        "bitte machen",
        "bestätige",
        "bestaetige",
        "ich bestätige",
        "ich bestaetige",
        "in den papierkorb",
        "löschen",
        "loeschen",
        "ruf an",
        "anrufen",
        "verschieben",
        "ja verschieben",
        "kopieren",
        "ja kopieren",
    }
    cancel_terms = {
        "nein",
        "nein danke",
        "abbrechen",
        "vergiss es",
        "stopp",
        "stop",
        "nicht machen",
        "nicht löschen",
        "nicht loeschen",
        "nicht anrufen",
        "nicht verschieben",
        "nicht kopieren",
    }
    is_confirm = (
        normalized in confirm_terms
        or normalized.startswith("ja ")
        or any(term in normalized for term in ("mach das", "ich bestätige", "ich bestaetige"))
    )
    is_cancel = (
        normalized in cancel_terms
        or any(term in normalized for term in cancel_terms if len(term) > 4)
        # "das bestätige ich nicht" o.ä. - live von Leon entdeckter Bug: eine
        # Ablehnung, die das Wort "bestätig(e/en)" selbst enthält, wurde bisher
        # von keinem der obigen Muster erfasst (kein exaktes cancel_terms-Match,
        # "nicht" alleine steht nicht in cancel_terms). Siehe
        # plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.
        or (("bestätig" in normalized or "bestaetig" in normalized) and "nicht" in normalized)
    )
    if normalized.startswith(QUESTION_SHAPE_PREFIXES):
        return None
    explicit_new_command = any(
        term in normalized
        for term in (
            "erstelle",
            "erstell",
            "schreib",
            "schreibe",
            "setz",
            "setze",
            "erinnere mich",
            "fasse",
            "prüfe",
            "pruefe",
            "suche",
            "such",
            "verschiebe",
            "kopiere",
            "öffne",
            "oeffne",
            "spiel",
            "spiele",
            "ruf",
            "rufe",
        )
    )

    pending_match = pending_action_matches_text(settings, normalized)

    if explicit_new_command and not is_confirm and not is_cancel and not pending_match:
        return None

    if not is_confirm and not is_cancel and not pending_match:
        return None

    pending_permission = settings.get("pending_permission")
    if isinstance(pending_permission, dict):
        permission = str(pending_permission.get("permission") or "").strip()
        # A permission request left standing indefinitely means any later, completely
        # unrelated "ja"/"okay" could silently confirm it - expire it instead of trusting
        # staleness. Entries from before this field existed (no "set_at") are treated as
        # expired too, since their real age is unknown.
        set_at = pending_permission.get("set_at")
        age_seconds = (time.time() - set_at) if isinstance(set_at, (int, float)) else None
        if age_seconds is None or age_seconds > PENDING_PERMISSION_TTL_SECONDS:
            settings.pop("pending_permission", None)
            memory.set("settings", settings)
            privacy_log(
                "permission_manager",
                "pending_permission_expired",
                permission=permission,
                age_seconds=round(age_seconds, 1) if age_seconds is not None else "unknown",
            )
            if is_confirm or is_cancel:
                return _continue_multistep_chain_if_pending(
                    memory,
                    "pending_permission",
                    "Die Berechtigungsanfrage ist inzwischen abgelaufen. Bitte stellen Sie Ihre Anfrage noch einmal, falls Sie sie noch erlauben möchten.",
                    aborted=True,
                    photo_worker=photo_worker,
                )
            return None
        if is_cancel:
            settings.pop("pending_permission", None)
            memory.set("settings", settings)
            return _continue_multistep_chain_if_pending(
                memory, "pending_permission", "Alles klar, ich erteile diese Berechtigung nicht.", aborted=True, photo_worker=photo_worker
            )
        if not is_confirm:
            return "Ich warte auf Ihre Entscheidung. Sagen Sie ja zum Erlauben oder nein zum Abbrechen."
        if permission:
            PermissionManager().grant(permission, source="chat_pending_permission_confirm")
            settings.pop("pending_permission", None)
            memory.set("settings", settings)
            privacy_log("permission", "granted", permission=permission)
            granted_message = f"Erlaubt: {permission}. Bitte stellen Sie Ihre Anfrage noch einmal, dann führe ich sie kontrolliert aus."
            return _continue_multistep_chain_if_pending(
                memory, "pending_permission", granted_message, aborted=False, photo_worker=photo_worker
            )
        settings.pop("pending_permission", None)
        memory.set("settings", settings)
        return _continue_multistep_chain_if_pending(
            memory, "pending_permission", "Die offene Berechtigung war unvollständig. Ich habe sie verworfen.", aborted=True, photo_worker=photo_worker
        )

    pending_desktop_move = settings.get("pending_desktop_move")
    if isinstance(pending_desktop_move, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_desktop_move",
            pending_desktop_move,
            action_type="desktop_move",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich verschiebe nichts.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Verschieben oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_desktop_move", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_desktop_move_many = settings.get("pending_desktop_move_many")
    if isinstance(pending_desktop_move_many, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_desktop_move_many",
            pending_desktop_move_many,
            action_type="desktop_move_many",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich verschiebe nichts.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Verschieben oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_desktop_move_many", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_calendar_create = settings.get("pending_calendar_create")
    if isinstance(pending_calendar_create, dict):
        if not is_confirm and not is_cancel and has_domain(text, "calendar"):
            # Neue, eigenstaendige Kalender-/Erinnerungs-Anfrage waehrend noch eine
            # alte Bestaetigung offen war: nicht pauschal mit "ich warte noch"
            # abweisen, sondern die alte (moeglicherweise laengst ueberholte)
            # Anfrage verwerfen und die neue frisch durchlaufen lassen. Sonst
            # bestaetigt ein spaeteres "Ja" versehentlich die alte, ggf. falsch
            # geparste Anfrage statt der neuen. Live beobachtet 2026-08-18: Leon
            # stellte nach einem fehlgeschlagenen Versuch ("...19:00 Uhr..." wurde
            # zu 00:00 geparst, siehe _extract_time-Fix in mail_calendar_actions.py)
            # eine neue, korrekte Anfrage - die wurde ignoriert, und "Ja" hat
            # stattdessen den alten 00:00-Eintrag angelegt.
            settings.pop("pending_calendar_create", None)
            memory.set("settings", settings)
            return None
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_calendar_create",
            pending_calendar_create,
            action_type="calendar_create",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich erstelle nichts.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Erstellen oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_calendar_create", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_calendar_delete = settings.get("pending_calendar_delete")
    if isinstance(pending_calendar_delete, dict):
        if not is_confirm and not is_cancel and has_domain(text, "calendar"):
            # Gleicher Schutz wie bei pending_calendar_create weiter oben: eine
            # neue, eigenstaendige Kalender-Anfrage waehrend noch eine alte
            # Loesch-Bestaetigung offen war soll diese nicht stillschweigend
            # uebernehmen.
            settings.pop("pending_calendar_delete", None)
            memory.set("settings", settings)
            return None
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_calendar_delete",
            pending_calendar_delete,
            action_type="calendar_delete",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich lösche nichts.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Löschen oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_calendar_delete", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    # Sammel-Bestaetigung/-Ablehnung der aus Mails erkannten Kalender-Vorschlaege,
    # sobald Jarvis die proaktive "X Kalender-Vorschlaege warten..."-Meldung
    # tatsaechlich ausgeliefert hat (Merker gesetzt in
    # local_server.py::proactivity_events()). Kein ACTION_ENGINE.resolve(), weil
    # das hier mehrere Vorschlaege auf einmal betrifft statt eines einzelnen
    # execution_data-Dicts - siehe
    # plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.
    pending_mail_calendar_confirmation = settings.get("pending_mail_calendar_confirmation")
    if isinstance(pending_mail_calendar_confirmation, dict):
        action_keys = [key for key in (pending_mail_calendar_confirmation.get("action_keys") or []) if key]
        set_at = pending_mail_calendar_confirmation.get("set_at")
        age_seconds = (time.time() - set_at) if isinstance(set_at, (int, float)) else None
        expired = (
            not action_keys
            or age_seconds is None
            or age_seconds > PENDING_MAIL_CALENDAR_CONFIRMATION_TTL_SECONDS
        )
        if expired:
            settings.pop("pending_mail_calendar_confirmation", None)
            memory.set("settings", settings)
            if is_confirm or is_cancel:
                return _continue_multistep_chain_if_pending(
                    memory,
                    "pending_mail_calendar_confirmation",
                    "Die Kalender-Vorschläge aus Ihren Mails sind nicht mehr aktuell. Sagen Sie mir gern noch einmal, worum es geht.",
                    aborted=True,
                    photo_worker=photo_worker,
                )
        elif is_cancel:
            settings.pop("pending_mail_calendar_confirmation", None)
            memory.set("settings", settings)
            if mail_worker is not None:
                mail_worker.resolve_pending_calendar_actions(action_keys, approve=False)
            noun = "Vorschlag" if len(action_keys) == 1 else "Vorschläge"
            return _continue_multistep_chain_if_pending(
                memory,
                "pending_mail_calendar_confirmation",
                f"Alles klar, ich trage die {len(action_keys)} Kalender-{noun} aus Ihren Mails nicht ein.",
                aborted=True,
                photo_worker=photo_worker,
            )
        elif is_confirm:
            settings.pop("pending_mail_calendar_confirmation", None)
            memory.set("settings", settings)
            resolved = mail_worker.resolve_pending_calendar_actions(action_keys, approve=True) if mail_worker is not None else []
            count = len(resolved)
            if count:
                noun = "Termin" if count == 1 else "Termine"
                message = f"Erledigt, ich habe {count} {noun} aus Ihren Mails eingetragen."
            else:
                message = "Ich konnte die Vorschläge gerade nicht eintragen. Sagen Sie mir gern noch einmal Bescheid."
            return _continue_multistep_chain_if_pending(
                memory, "pending_mail_calendar_confirmation", message, aborted=not count, photo_worker=photo_worker
            )
        else:
            return "Ich warte noch auf Ihre Antwort zu den Kalender-Vorschlägen aus Ihren Mails. Sagen Sie ja zum Eintragen oder nein zum Verwerfen."

    # Sammel-Bestaetigung/-Ablehnung eines gerade im Chat gezeigten
    # Speicherplatz-Aufraeum-Vorschlags (suggest_cleanup_files() in
    # handle_file_command()). Loeschen bedeutet hier immer "in den
    # Papierkorb legen", niemals endgueltig - Leons ausdrueckliche Vorgabe.
    # Siehe plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md.
    pending_cleanup_confirmation = settings.get("pending_cleanup_confirmation")
    if isinstance(pending_cleanup_confirmation, dict):
        items = [item for item in (pending_cleanup_confirmation.get("items") or []) if isinstance(item, dict) and item.get("path")]
        set_at = pending_cleanup_confirmation.get("set_at")
        age_seconds = (time.time() - set_at) if isinstance(set_at, (int, float)) else None
        expired = (
            not items
            or age_seconds is None
            or age_seconds > PENDING_CLEANUP_CONFIRMATION_TTL_SECONDS
        )
        if expired:
            settings.pop("pending_cleanup_confirmation", None)
            memory.set("settings", settings)
            if is_confirm or is_cancel:
                return _continue_multistep_chain_if_pending(
                    memory,
                    "pending_cleanup_confirmation",
                    "Der Aufräum-Vorschlag ist nicht mehr aktuell. Fragen Sie mich gern noch einmal nach löschbaren Dateien.",
                    aborted=True,
                    photo_worker=photo_worker,
                )
        elif is_cancel:
            settings.pop("pending_cleanup_confirmation", None)
            memory.set("settings", settings)
            noun = "Datei" if len(items) == 1 else "Dateien"
            return _continue_multistep_chain_if_pending(
                memory,
                "pending_cleanup_confirmation",
                f"Alles klar, ich lösche die {len(items)} {noun} nicht.",
                aborted=True,
                photo_worker=photo_worker,
            )
        elif is_confirm:
            settings.pop("pending_cleanup_confirmation", None)
            memory.set("settings", settings)
            moved, skipped = move_to_trash([Path(str(item["path"])) for item in items])
            if moved:
                noun = "Datei" if len(moved) == 1 else "Dateien"
                message = f"Erledigt, ich habe {len(moved)} {noun} in den Papierkorb gelegt."
                if skipped:
                    message += f" {len(skipped)} davon waren nicht mehr da oder ließen sich nicht verschieben."
            else:
                message = "Ich konnte keine der Dateien in den Papierkorb legen. Vielleicht wurden sie inzwischen schon verschoben oder gelöscht."
            return _continue_multistep_chain_if_pending(
                memory, "pending_cleanup_confirmation", message, aborted=not moved, photo_worker=photo_worker
            )
        else:
            return "Ich warte noch auf Ihre Antwort zum Aufräum-Vorschlag. Sagen Sie ja zum In-den-Papierkorb-Legen oder nein zum Abbrechen."

    pending_mail_document_export = settings.get("pending_mail_document_export")
    if isinstance(pending_mail_document_export, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_mail_document_export",
            pending_mail_document_export,
            action_type="mail_document_export",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich kopiere nichts.",
            waiting_message="Ich warte auf Ihr Ja oder Abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_mail_document_export", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_file_action = settings.get("pending_file_action")
    if isinstance(pending_file_action, dict):
        if not is_confirm and not is_cancel and has_domain(text, "files"):
            # Gleiches Schutzmuster wie pending_calendar_create oben (siehe
            # dortiger Kommentar) - fehlte hier bisher: eine neue, eigenstaendige
            # Datei-Anfrage waehrend eine alte Bestaetigung offen war wurde nicht
            # verworfen und frisch verarbeitet, sondern blieb an der alten
            # Rueckfrage haengen. Live beobachtet 2026-08-20 im Mehrfach-Audit.
            settings.pop("pending_file_action", None)
            memory.set("settings", settings)
            return None
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_file_action",
            pending_file_action,
            action_type="file_action",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich ändere nichts.",
            waiting_message="Ich warte auf Ihr Ja oder Abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_file_action", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_mail_delete = settings.get("pending_mail_delete")
    if isinstance(pending_mail_delete, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_mail_delete",
            pending_mail_delete,
            action_type="mail_delete",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich verschiebe keine Mails.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Ausführen oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_mail_delete", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_call = settings.get("pending_call_contact")
    if isinstance(pending_call, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_call_contact",
            pending_call,
            action_type="call_contact",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich starte keinen Anruf.",
            waiting_message="Ich warte noch auf Ihre Bestätigung. Sagen Sie ja zum Anrufen oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_call_contact", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_call_choice = settings.get("pending_call_choice")
    if isinstance(pending_call_choice, dict):
        if is_cancel:
            settings.pop("pending_call_choice", None)
            memory.set("settings", settings)
            return _continue_multistep_chain_if_pending(
                memory, "pending_call_choice", "Alles klar, ich starte keinen Anruf.", aborted=True, photo_worker=photo_worker
            )

        hint = extract_phone_hint(text)
        phones = list(pending_call_choice.get("phones") or [])
        contact_name = str(pending_call_choice.get("name") or "").strip()
        if not hint:
            return "Welche Nummer soll ich nehmen? Sag mir die Endung."

        matching_phones = [
            str(phone)
            for phone in phones
            if normalize_phone_digits(str(phone)).endswith(hint)
            or hint in normalize_phone_digits(str(phone))
        ]
        if len(matching_phones) != 1:
            endings = ", ".join(mask_phone_end(str(phone)) for phone in phones[:4])
            return f"Ich konnte die Nummer noch nicht sauber zuordnen. Ich sehe: {endings}."

        settings.pop("pending_call_choice", None)
        memory.set("settings", settings)
        # Eine Mehrschritt-Kette, die auf die (jetzt aufgeloeste) Rueckfrage nach der
        # richtigen Nummer wartet, muss ab jetzt auf die NEUE Bestaetigung warten,
        # die ACTION_ENGINE.propose() unten fuer den eigentlichen Anruf anlegt -
        # sonst wuerde die Kette nie fortgesetzt, weil ihr gemerkter Schluessel
        # ("pending_call_choice") gerade verschwunden ist.
        queue = settings.get("pending_multistep_queue")
        if isinstance(queue, dict) and queue.get("waiting_on_key") == "pending_call_choice":
            queue["waiting_on_key"] = "pending_call_contact"
            settings["pending_multistep_queue"] = queue
            memory.set("settings", settings)
        return ACTION_ENGINE.propose(
            memory,
            "pending_call_contact",
            ActionProposal(
                action_type="call_contact",
                execution_data={
                    "name": contact_name,
                    "phone": matching_phones[0],
                },
                confirm_prompt=f"Nummer {mask_phone_end(matching_phones[0])}. Soll ich anrufen?",
            ),
        )

    return None


_NOTES_READ_TRIGGERS = (
    "zeig mir",
    "zeig",
    "zeige",
    "welche notiz",
    "welche notizen",
    "was steht in",
    "was steht auf",
    "was steht meinen",
    "was ist auf",
    "was ist in",
    "liste meine notizen",
    "liste der notizen",
    "übersicht",
    "uebersicht",
    "meine notizen",
    "letzten notizen",
    "letzte notiz",
)

_NOTES_CREATE_VERBS = (
    "erstelle",
    "erstell",
    "mach",
    "mache",
    "schreib",
    "schreibe",
    "notiere",
    "leg an",
    "lege an",
    "neue notiz",
    "füge",
    "fuege",
    "hinzufügen",
    "hinzufuegen",
    "ergänze",
    "ergaenze",
)

_NOTES_DELETE_VERBS = (
    "lösche",
    "loesche",
    "löschen",
    "loeschen",
    "entferne",
    "entfernen",
    "lösch",
    "loesch",
    # "streich" fehlte komplett - "Streich die Notiz X." fiel bis zum
    # Erstellen-Flow durch und fragte "Wie soll die Notiz heißen?" statt zu
    # loeschen. Live beobachtet 2026-08-20 im Regressionstest.
    "streiche",
    "streich",
)


def _extract_note_title_for_delete(text: str) -> str | None:
    """Extrahiert den Notiz-Titel aus einer Loesch-Anfrage ("Lösche die Notiz X",
    "Entferne den Zettel X") - im Unterschied zu extract_note_title() braucht es
    hier KEIN "mit dem Titel"-Anschlusswort, da Loesch-Anfragen den Titel direkt
    nach "Notiz"/"Zettel" nennen.

    Matcht ueber re.IGNORECASE auf dem ORIGINALEN Text, nicht auf
    normalize_text()s Ausgabe - normalize_text() ersetzt Bindestriche durch
    Leerzeichen und entfernt Satzzeichen, was fuer den reinen Muster-Abgleich
    hilfreich ist, aber bei direkter Rueckgabe der erfassten Gruppe echte
    Titel-Zeichen zerstoert. delete_note()s AppleScript-Vergleich ignoriert
    Gross-/Kleinschreibung, aber KEINE Bindestrich/Leerzeichen-Unterschiede -
    ein Titel wie "JT2000-014 Einkaufen" wurde dadurch nie gefunden ("jt2000
    014 einkaufen" != "JT2000-014 Einkaufen"). Live beobachtet 2026-08-20."""
    match = re.search(
        r"(?:notiz|zettel)\s+(?:mit\s+dem\s+titel\s+|namens\s+|mit\s+namen\s+)?(?:(?:der|die|den)\s+)?(.+?)(?:\s+(?:aus\s+(?:den\s+)?notizen)\s*)?$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    title = match.group(1).strip(" .,!?:;")
    return title or None


def _looks_like_notes_read_request(text: str) -> bool:
    """Erkennt eine Lese-/Uebersichts-Anfrage ("was steht in meinen Notizen",
    "zeig mir meine Notizen"), damit handle_notes_command() sie nicht mehr
    faelschlich in den Erstellen-Flow laufen laesst (bisher gab es dafuer gar
    keinen Pfad - jede Notizen-Anfrage ohne erkennbaren Titel fragte "Wie soll
    die Notiz heissen?", auch reine Lese-Fragen). Erstell-Verben haben Vorrang,
    damit z.B. "erstelle eine notiz ueber meine notizen" weiterhin als Erstellen
    erkannt wird."""
    normalized = normalize_text(text)
    if any(verb in normalized for verb in _NOTES_CREATE_VERBS):
        return False
    if any(trigger in normalized for trigger in _NOTES_READ_TRIGGERS):
        return True
    # Fuellwort-tolerant nachschauen ("was steht EIGENTLICH auf ..."), siehe
    # strip_filler_words(). Runde-2-Simulation, 2026-08-13.
    return any(trigger in strip_filler_words(normalized) for trigger in _NOTES_READ_TRIGGERS)


def handle_notes_command(memory: Memory, text: str) -> str | None:
    if not NOTES_ENABLED:
        return None

    normalized = normalize_text(text)
    if not has_domain(text, "notes"):
        return None

    if any(term in normalized for term in ("zugriff", "funktioniert", "status")):
            return "Notizen sind aktiv. Ich kann neue machen und alte füttern."

    if _looks_like_notes_read_request(text):
        try:
            notes = list_recent_notes(limit=5)
        except NotesAccessError as exc:
            return str(exc)
        if not notes:
            return "Ich habe keine Notizen gefunden."
        items = "; ".join(
            f"{note['title']} ({note['modified'].strftime('%d.%m.%Y')})" for note in notes
        )
        return f"Ihre letzten Notizen: {items}."

    if any(verb in normalized for verb in _NOTES_DELETE_VERBS):
        delete_title = _extract_note_title_for_delete(text)
        if not delete_title:
            return "Welche Notiz soll ich löschen?"
        try:
            return delete_note(delete_title)
        except NotesAccessError as exc:
            return str(exc)

    title = extract_note_title(text)
    body = extract_note_body(text)
    append = wants_append_to_note(text)

    if "einkaufszettel" in normalized or "einkaufsliste" in normalized:
        title = title or "Einkaufszettel"
        append = True
        if not body:
            body = extract_shopping_items(text)

    if not title:
        settings = memory.get("settings") or {}
        settings["pending_note"] = {
            "state": "awaiting_title",
            "body": body,
            "append": append,
        }
        memory.set("settings", settings)
        return "Wie soll die Notiz heißen?"

    if not body:
        settings = memory.get("settings") or {}
        settings["pending_note"] = {
            "state": "awaiting_body",
            "title": title,
            "append": append,
        }
        memory.set("settings", settings)
        return f"Was kommt in {title} rein?"

    return save_note_or_append(title, body, append=append)


_TASKS_PRIORITY_LABELS = {"kritisch": "kritisch", "hoch": "hoch", "mittel": "mittel", "niedrig": "niedrig"}


def handle_tasks_command(memory: Memory, text: str) -> str | None:
    """Bisher hatten interne Aufgaben (task_manager.py, getrennt von Apple
    Reminders) ueberhaupt keinen per Chat erreichbaren Lese-Pfad - eine Frage wie
    "was habe ich fuer offene Aufgaben" fiel komplett durch die Domaenen-Kette und
    landete im werkzeuglosen Chat, der dann frei erfundene, nicht mit den echten
    (leeren oder gefuellten) Aufgaben uebereinstimmende Antworten gab. Erstellen
    ueber "Erstelle eine Aufgabe: X" ist seit 2026-08-19 ebenfalls angebunden -
    TaskManager.create_task() existierte laut eigenem Docstring genau dafuer,
    war aber nie verdrahtet."""
    if not has_domain(text, "tasks"):
        return None

    # Erstell-Anfragen ("Erstelle eine Aufgabe: X") fielen bisher bis zur
    # obigen Lese-Logik durch und bekamen faelschlich die leere/gefuellte
    # Status-Antwort ("Sie haben aktuell keine offenen Aufgaben.") statt einer
    # Rueckmeldung zur eigentlich gewuenschten Erstellung - obwohl
    # TaskManager.create_task() laut eigenem Docstring genau fuer diesen Zweck
    # gebaut wurde ("nur fuer explizite Nutzeranfragen"), war es nie an den
    # Chat-Pfad angebunden. Live beobachtet 2026-08-19.
    create_match = re.search(
        r"(?:erstelle|erstell|lege|leg|neue)\s+(?:mir\s+)?(?:eine\s+)?aufgabe\s*:?\s*(?:namens\s+)?(.+?)[.?!]*$",
        text,
        flags=re.IGNORECASE,
    )
    if create_match:
        title = create_match.group(1).strip(" .,!?:;\"'")
        title = re.sub(r"^(?:an|dass)\s+", "", title, flags=re.IGNORECASE)
        if not title:
            return "Wie soll die Aufgabe heißen?"
        TaskManager(memory).create_task(title, source="chat")
        return f"Erledigt. Aufgabe {title} steht."

    # Gleiches Loesch-Defizit wie zuvor bei Notizen/Kalender behoben: ohne
    # diesen Zweig fiel "Lösche die Aufgabe X" bis zur Lese-Logik unten durch
    # und listete stattdessen alle offenen Aufgaben auf.
    delete_match = re.search(
        r"(?:lösche|loesche|entferne)\s+(?:die\s+)?aufgabe\s*:?\s*(.+?)[.?!]*$",
        text,
        flags=re.IGNORECASE,
    )
    if delete_match:
        title = delete_match.group(1).strip(" .,!?:;\"'")
        manager = TaskManager(memory)
        match = next(
            (task for task in manager.list_tasks() if normalize_text(str(task.get("title") or "")) == normalize_text(title)),
            None,
        )
        if not match:
            return f"Ich habe keine Aufgabe mit dem Titel „{title}“ gefunden."
        manager.delete_task(str(match.get("id")))
        return f"Erledigt. Aufgabe {title} gelöscht."

    tasks = TaskManager(memory).list_tasks(status="offen") + TaskManager(memory).list_tasks(status="in_arbeit")
    if not tasks:
        return "Sie haben aktuell keine offenen Aufgaben."

    items = []
    for task in tasks[:8]:
        title = str(task.get("title") or "").strip() or "Ohne Titel"
        priority = _TASKS_PRIORITY_LABELS.get(str(task.get("priority") or ""), "")
        suffix = f" ({priority})" if priority and priority != "mittel" else ""
        items.append(f"{title}{suffix}")

    summary = "; ".join(items)
    remaining = len(tasks) - len(items)
    if remaining > 0:
        summary += f"; und {remaining} weitere" if remaining > 1 else "; und 1 weitere"

    return f"Ihre offenen Aufgaben: {summary}."


def save_note_or_append(title: str, body: str, append: bool = False) -> str:
    try:
        if append:
            append_to_note(title, body, folder_name=CONFIG.get("notes_folder_name"))
            return f"Erledigt. {title} ist ergänzt."

        create_note(title, body, folder_name=CONFIG.get("notes_folder_name"))
        return f"Erledigt. Notiz {title} steht."
    except NotesAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Notizen Fehler:", type(exc).__name__)
        return "Ich konnte Notizen nicht bearbeiten."


def wants_append_to_note(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        term in normalized
        for term in (
            "füge",
            "fuege",
            "hinzufügen",
            "hinzufuegen",
            "ergänz",
            "ergaenz",
            "schreib dazu",
            "pack",
            "setze auf",
            "auf den",
            "auf die",
        )
    )


def extract_note_title(text: str) -> str:
    patterns = (
        # "dem Titel" ist die grammatisch korrekte Form (Titel ist maskulin, Dativ
        # "dem" nicht "der") - "der" alleine als einzige Alternative liess die
        # natuerliche, korrekte Formulierung "mit dem Titel X" durchfallen. Live
        # beobachtet 2026-08-18: "erstelle eine Notiz mit dem Titel X und dem
        # Inhalt Y" fragte trotzdem "Wie soll die Notiz heißen?".
        r"(?:notiz|zettel)\s+(?:mit\s+)?(?:der|dem)?\s*(?:überschrift|ueberschrift|titel)\s+(.+?)(?:\s+(?:und|mit|inhalt|rein|dazu)\s+|$)",
        r"(?:neue\s+notiz|notiz)\s+(?:namens|heißt|heisst)\s+(.+?)(?:\s+(?:mit|und|inhalt|rein)\s+|$)",
        r"(?:in|zur|zu der|auf den|auf die)\s+(?:notiz\s+)?(.+?)\s+(?:hinzufügen|hinzufuegen|ergänzen|ergaenzen|schreiben|setzen|packen)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_note_title(match.group(1))

    normalized = normalize_text(text)
    if "einkaufszettel" in normalized:
        return "Einkaufszettel"
    if "einkaufsliste" in normalized:
        return "Einkaufsliste"

    return ""


def extract_note_body(text: str) -> str:
    patterns = (
        # "und dem Inhalt X" (nicht nur "mit dem Inhalt X") - haeufig in Kombination
        # mit "... mit dem Titel X und dem Inhalt Y", siehe extract_note_title().
        # Ohne "und" als Alternative fiel diese Formulierung auf das viel
        # allgemeinere "erstelle ... notiz ..."-Muster weiter unten zurueck, das
        # dann den ganzen Rest des Satzes inkl. "mit dem Titel ..." als Body nahm.
        r"(?:mit|und)\s+(?:dem\s+)?(?:inhalt|text)\s+(.+)$",
        r"(?:notiz|notizen|zettel)\s+(?:über|ueber|zu|für|fuer|dass)\s+(.+)$",
        r"(?:mach|mache|erstelle|erstell)\s+(?:mir\s+)?(?:eine\s+)?(?:notiz|notizen|zettel)\s+(?:über|ueber|zu|für|fuer|dass)?\s*(.+)$",
        r"(?:schreib(?:e)?\s+(?:rein|dazu)?\s*)(.+)$",
        r"(?:notiere\s+)(.+)$",
        r"(?:hinzufügen|hinzufuegen|ergänzen|ergaenzen|packen|setzen)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_note_body(match.group(1))

    return extract_shopping_items(text)


def extract_shopping_items(text: str) -> str:
    patterns = (
        r"(?:auf den einkaufszettel|auf die einkaufsliste)\s+(.+)$",
        r"(?:setze|setz|packe|pack|schreibe|schreib)\s+(.+?)\s+(?:auf den einkaufszettel|auf die einkaufsliste)",
        r"(?:füge|fuege)\s+(.+?)\s+(?:zum|zur|auf den|auf die)\s+(?:einkaufszettel|einkaufsliste)",
        r"(?:einkaufszettel|einkaufsliste).*(?:mit|drauf|rein|hinzufügen|hinzufuegen|kaufen)\s+(.+)$",
        r"(?:kauf(?:e)?\s+)(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_note_body(match.group(1))

    return ""


_NOTE_TITLE_FILLER = r"(?:bitte|mal|neu|neue|notiz|zettel)"


def clean_note_title(text: str) -> str:
    # Nur am Anfang/Ende der erfassten Titel-Gruppe strippen, nicht ueberall im
    # Text - vorher wurde z.B. "notiz" auch aus der MITTE eines Titels entfernt,
    # der das Wort legitim enthielt. Live beobachtet 2026-08-19: "Erstelle eine
    # Notiz mit dem Titel 'Wichtige Notiz fuer Team'" wurde zu "Wichtige fuer
    # Team" gespeichert - und der passende Loesch-Befehl mit dem urspruenglichen
    # Titel fand die Notiz danach nicht mehr wieder. Diese Fuellwoerter leaken
    # aus dem Befehlsrahmen realistischerweise nur an den Raendern der erfassten
    # Gruppe herein, nie in der Mitte eines gewollten Titels.
    title = text.strip()
    title = re.sub(rf"^(?:{_NOTE_TITLE_FILLER}\s+)+", "", title, flags=re.IGNORECASE)
    title = re.sub(rf"(?:\s+{_NOTE_TITLE_FILLER})+$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title)
    return title.strip(" .,!?:;") or "Neue Notiz"


def clean_note_body(text: str) -> str:
    body = re.sub(r"\b(?:bitte|mal|auf den einkaufszettel|auf die einkaufsliste)\b", " ", text, flags=re.IGNORECASE)
    body = re.sub(r"\s+", " ", body)
    return body.strip(" .,!?:;")


def extract_mail_delete_target(text: str) -> str | None:
    """Erkennt einen freien Absender-/Betreff-Namen in einer Loesch-Anfrage,
    der KEINER der drei fest hinterlegten target_aliases (Indeed/PayPal/
    Stepstone) entspricht - z.B. "Loesche die Mail von Anthropic". Vorher
    fiel ein unbekannter Name still auf die zuletzt gelesenen/zusammen-
    gefassten Mails zurueck, was voellig unbezogene Mails geloescht haette
    (live entdeckt, siehe docs/current-system-assessment.md, Abschnitt 41)."""
    match = re.search(r"(?:mails?|nachrichten?)\s+von\s+(.+?)(?:[.?!]|$)", text, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip(" .,!?")
    candidate = re.sub(
        r"\s+(?:löschen|loeschen|entfernen|weg|bitte|in\s+den\s+papierkorb).*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" .,!?")
    return candidate or None


def handle_mail_delete_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    question_about_done = any(
        term in normalized
        for term in (
            "hast du",
            "wurde",
            "wurden",
            "schon gelöscht",
            "schon geloescht",
        )
    )
    clear_delete_command = any(
        term in normalized
        for term in (
            "ich bestätige",
            "ich bestaetige",
            "bestätige",
            "bestaetige",
            "kannst du",
            "bitte",
            "leg",
            "lege",
            "lösche",
            "loesche",
            "lösch bitte",
            "loesch bitte",
            "in den papierkorb",
        )
    )
    if question_about_done and not clear_delete_command:
        return (
            "Ich führe bei einer Nachfrage nichts aus. "
            "Wenn Sie möchten, sagen Sie klar: Lege Stepstone und Indeed in den Papierkorb."
        )

    delete_terms = (
        "lösch",
        "loesch",
        "löschen",
        "loeschen",
        "papierkorb",
        "trash",
        "weg damit",
        "entfern",
        "entfernen",
    )
    if not any(term in normalized for term in delete_terms):
        return None

    target_aliases = {
        "Indeed": (
            "indeed",
            "indied",
            "indie",
            "indy",
        ),
        "PayPal": (
            "paypal",
            "pay pal",
            "paypol",
            "pay poll",
        ),
        "Stepstone": (
            "stepstone",
            "step stone",
            "steps",
            "stepston",
            "stepson",
            "stonne",
            "statson",
            "städtson",
            "stetson",
        ),
    }
    selected_targets = [
        target
        for target, aliases in target_aliases.items()
        if any(alias in normalized for alias in aliases)
    ]
    if not selected_targets:
        # Erst versuchen, einen freien Namen ("...von Anthropic") zu erkennen und
        # ECHT im Postfach zu suchen, statt sofort auf zuletzt gelesene/
        # zusammengefasste Mails auszuweichen - die koennen von etwas voellig
        # anderem stammen als das, was gerade gemeint war.
        extracted_target = extract_mail_delete_target(text)
        if extracted_target:
            if memory is None:
                return f"Ich würde Mails von {extracted_target} nur nach Ihrer Bestätigung löschen."
            try:
                inbox_account, inbox_mailbox = resolve_mail_inbox()
                matches = search_messages_by_terms(
                    [extracted_target],
                    account_name=inbox_account,
                    mailbox_name=inbox_mailbox,
                )
            except MailAccessError as exc:
                return str(exc)
            except Exception as exc:
                print("Mail Suche Fehler:", type(exc).__name__)
                matches = []
            if not matches:
                return (
                    f"Ich finde keine Mails von {extracted_target} in Ihrem Postfach. "
                    "Meinen Sie einen anderen Namen, oder soll ich anders suchen?"
                )
            match_ids = [message.message_id for message in matches if message.message_id]
            sample = "; ".join(message.subject for message in matches[:3] if message.subject)
            count_word = "eine Mail" if len(matches) == 1 else f"{len(matches)} Mails"
            return ACTION_ENGINE.propose(
                memory,
                "pending_mail_delete",
                ActionProposal(
                    action_type="mail_delete",
                    execution_data={
                        "selected_targets": [extracted_target],
                        "search_terms": [],
                        "message_ids": match_ids,
                        "subjects": [message.subject for message in matches],
                        "senders": [message.sender for message in matches],
                    },
                    confirm_prompt=(
                        f"Ich habe {count_word} von {extracted_target} gefunden, "
                        f"u. a.: {sample}. Soll ich die wirklich in den Papierkorb legen? "
                        "Sag ja oder abbrechen."
                    ),
                ),
            )

        # Kein erkennbarer Absender/Name in der Anfrage ueberhaupt (z.B. nur
        # "loesch die mail") - erst jetzt auf die zuletzt gelesenen/
        # zusammengefassten Mails zurueckfallen, mit ehrlich benannten
        # Betreffs in der Bestaetigung statt der vagen Pauschalformulierung.
        if memory is None:
            return None
        settings = memory.get("settings") or {}
        last_mail_summary = settings.get("last_mail_summary")
        last_summary_ids = []
        last_summary_subjects = []
        if isinstance(last_mail_summary, dict):
            last_summary_ids = [
                str(item)
                for item in last_mail_summary.get("message_ids") or []
                if str(item).strip()
            ]
            last_summary_subjects = list(last_mail_summary.get("subjects") or [])
        if last_summary_ids:
            sample = "; ".join(str(subject) for subject in last_summary_subjects[:3] if subject)
            sample_note = f" (u. a.: {sample})" if sample else ""
            return ACTION_ENGINE.propose(
                memory,
                "pending_mail_delete",
                ActionProposal(
                    action_type="mail_delete",
                    execution_data={
                        "selected_targets": ["letzte gelesene Mails"],
                        "search_terms": [],
                        "message_ids": last_summary_ids,
                        "subjects": last_summary_subjects,
                        "senders": list(last_mail_summary.get("senders") or []),
                    },
                    confirm_prompt=(
                        f"Sie haben keinen Namen genannt, daher nehme ich die zuletzt gelesenen "
                        f"Mails{sample_note}. Soll ich sie wirklich in den Papierkorb legen? "
                        "Sag ja oder abbrechen."
                    ),
                ),
            )
        return "Wessen Mails soll ich löschen? Sag mir den Absender oder das Thema."

    search_terms_by_target = {
        "Indeed": ["Indeed", "indeed"],
        "PayPal": ["PayPal", "paypal", "noreply@news.paypal.com", "service@paypal"],
        "Stepstone": ["Stepstone", "stepstone", "StepStone", "Stepsdown", "stepsdown"],
    }
    search_terms = []
    for target in selected_targets:
        search_terms.extend(search_terms_by_target[target])

    targets_text = " und ".join(selected_targets)
    if memory is None:
        return (
            f"Ich würde Mails von {targets_text} nur nach Ihrer Bestätigung verschieben. "
            "Sag es mir noch einmal, dann räume ich auf."
        )

    return ACTION_ENGINE.propose(
        memory,
        "pending_mail_delete",
        ActionProposal(
            action_type="mail_delete",
            execution_data={
                "selected_targets": selected_targets,
                "search_terms": search_terms,
            },
            confirm_prompt=(
                f"Ich habe noch nichts gelöscht. Soll ich Mails von {targets_text} wirklich in den Papierkorb legen? "
                "Sag ja oder abbrechen."
            ),
        ),
    )


def execute_mail_delete(data: dict) -> str:
    search_terms = list(data.get("search_terms") or [])
    selected_targets = list(data.get("selected_targets") or [])
    message_ids = [str(item) for item in data.get("message_ids") or [] if str(item).strip()]
    targets_text = " und ".join(str(target) for target in selected_targets) or "diese Absender"
    if message_ids:
        error_note = ""
        try:
            inbox_account, inbox_mailbox = resolve_mail_inbox()
            moved_count = move_messages_to_trash(
                message_ids,
                account_name=inbox_account,
                mailbox_name=inbox_mailbox,
            )
        except MailAccessError as exc:
            return str(exc)
        except Exception as exc:
            print("Apple-Mail Papierkorb Fehler:", type(exc).__name__)
            error_note = str(exc)
            moved_count = 0

        if not moved_count:
            fallback_terms = []
            for subject in list(data.get("subjects") or []):
                cleaned = clean_spoken_answer(str(subject))
                if cleaned:
                    fallback_terms.append(cleaned)
            for sender in list(data.get("senders") or []):
                cleaned = clean_spoken_answer(str(sender))
                if cleaned:
                    fallback_terms.append(cleaned)
            if fallback_terms:
                try:
                    inbox_account, inbox_mailbox = resolve_mail_inbox()
                    moved_messages = move_matching_messages_to_trash(
                        fallback_terms,
                        max_messages=max(MAIL_MAX_MESSAGES, 50),
                        account_name=inbox_account,
                        mailbox_name=inbox_mailbox,
                    )
                    if moved_messages:
                        return f"Erledigt. Ich habe {len(moved_messages)} gelesene Mail(s) in den Papierkorb gelegt."
                except MailAccessError as exc:
                    return str(exc)
                except Exception as exc:
                    print("Apple-Mail Papierkorb Fallback Fehler:", type(exc).__name__)
                    error_note = error_note or str(exc)

            if error_note:
                return (
                    "Ich konnte die zuletzt gelesenen Mails nicht sauber verschieben. "
                    f"Technisch: {error_note}"
                )
            return (
                "Ich konnte die zuletzt gelesenen Mails nicht mehr sauber zuordnen. "
                "Wenn Sie möchten, nenne ich sie Ihnen noch einmal und wir räumen dann gezielt auf."
            )
        return f"Erledigt. Ich habe {moved_count} gelesene Mail(s) in den Papierkorb gelegt."
    try:
        inbox_account, inbox_mailbox = resolve_mail_inbox()
        moved_messages = move_matching_messages_to_trash(
            search_terms,
            max_messages=max(MAIL_MAX_MESSAGES, 50),
            account_name=inbox_account,
            mailbox_name=inbox_mailbox,
        )
    except MailAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Apple-Mail Papierkorb Fehler:", type(exc).__name__)
        return "Ich konnte die Mail-Löschaktion gerade nicht sauber ausführen."

    if not moved_messages:
        return (
            f"Ich habe im aktuellen Posteingang keine passenden Mails von {targets_text} gefunden. "
            "Ich habe deshalb nichts verschoben."
        )

    moved_subjects = "; ".join(
        f"{message.sender or 'Unbekannt'}: {message.subject}"
        for message in moved_messages[:3]
    )
    return (
        f"Erledigt. Ich habe {len(moved_messages)} Mail(s) in den Papierkorb gelegt: "
        f"{moved_subjects}."
    )


ACTION_ENGINE.register("mail_delete", execute_mail_delete)


def handle_mail_document_export_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    document_terms = (
        "rechnung",
        "rechnungen",
        "versicherung",
        "versicherungen",
        "abo",
        "abos",
        "abonnement",
        "abonnements",
    )
    mail_context = any(term in normalized for term in ("mail", "mails", "email", "emails", "posteingang", "mailfach"))
    # "desktop"/"schreibtisch"/"ordner" war frueher PFLICHT, obwohl das
    # Zielverzeichnis in export_categorized_mail_documents() ohnehin immer fest
    # auf den Schreibtisch zeigt (nie aus dem Text geparst) - eine ganz
    # natuerliche Anfrage wie "Kopiere meine Rechnungen aus den Mails" (ohne
    # das Wort "Schreibtisch" zu nennen) fiel dadurch komplett durch und landete
    # im werkzeuglosen Chat, der stattdessen nur eine allgemeine Mail-
    # Zusammenfassung gab. Live beobachtet 2026-08-19.
    action_context = any(
        term in normalized
        for term in (
            "kopier",
            "kopiere",
            "speicher",
            "speichere",
            "exportier",
            "exportiere",
            "leg",
            "lege",
            "sortier",
            "sortiere",
            "ablegen",
            "ablege",
        )
    )
    if not (mail_context and action_context):
        return None
    if not any(term in normalized for term in document_terms):
        return None

    categories = extract_mail_document_categories(text)
    if not categories:
        categories = ["rechnungen", "versicherungen", "abonnements"]

    category_text = format_mail_document_categories(categories)
    if memory is None:
        return f"Ich würde {category_text} aus Ihren Mails auf den Schreibtisch kopieren."

    max_messages = int(CONFIG.get("mail_document_export_max_messages", 80))
    return ACTION_ENGINE.propose(
        memory,
        "pending_mail_document_export",
        ActionProposal(
            action_type="mail_document_export",
            execution_data={
                "categories": categories,
                "max_messages": max_messages,
            },
            confirm_prompt=(
                f"Ich habe noch nichts kopiert. Soll ich {category_text} aus den letzten "
                f"{max_messages} Mails auf Ihren Schreibtisch kopieren?"
            ),
        ),
    )


def extract_mail_document_categories(text: str) -> list[str]:
    normalized = normalize_text(text)
    categories: list[str] = []
    if any(term in normalized for term in ("rechnung", "rechnungen", "beleg", "belege", "invoice")):
        categories.append("rechnungen")
    if any(term in normalized for term in ("versicherung", "versicherungen", "police", "policen")):
        categories.append("versicherungen")
    if any(term in normalized for term in ("abo", "abos", "abonnement", "abonnements", "subscription")):
        categories.append("abonnements")
    return normalize_document_categories(categories)


def format_mail_document_categories(categories: list[str]) -> str:
    labels = {
        "rechnungen": "Rechnungen",
        "versicherungen": "Versicherungen",
        "abonnements": "Abonnements",
    }
    selected = [labels.get(category, category) for category in normalize_document_categories(categories)]
    if not selected:
        selected = ["Rechnungen", "Versicherungen", "Abonnements"]
    if len(selected) == 1:
        return selected[0]
    return ", ".join(selected[:-1]) + " und " + selected[-1]


def run_mail_document_export(categories: list[str], max_messages: int = 80) -> str:
    inbox_account, inbox_mailbox = resolve_mail_inbox()
    results = export_categorized_mail_documents(
        categories=categories,
        max_messages=max_messages,
        account_name=inbox_account,
        mailbox_name=inbox_mailbox,
    )
    if not results:
        return "Ich habe keine passenden Mail-Dokumente gefunden."

    parts = []
    total_files = 0
    total_notes = 0
    for result in results:
        saved_count = len(result.saved_files)
        note_count = len(result.note_files)
        total_files += saved_count
        total_notes += note_count
        folder_name = Path(result.folder).name
        if result.matched_messages == 0:
            parts.append(f"{folder_name}: keine passenden Mails gefunden")
        elif saved_count > 0:
            parts.append(f"{folder_name}: {saved_count} Anhang/Anhänge gespeichert")
        elif note_count > 0:
            parts.append(f"{folder_name}: keine Anhänge gefunden, {note_count} Mail-Notiz(en) gespeichert")
        else:
            parts.append(f"{folder_name}: passende Mails gefunden, aber nichts speicherbares")

    if total_files == 0 and total_notes == 0:
        return "Ich habe keine passenden Anhänge oder Mail-Notizen zum Kopieren gefunden. " + "; ".join(parts) + "."

    return "Erledigt. " + "; ".join(parts) + "."


def execute_mail_document_export(data: dict) -> str:
    categories = list(data.get("categories") or [])
    max_messages = int(data.get("max_messages") or 80)
    try:
        return run_mail_document_export(categories, max_messages=max_messages)
    except MailAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Mail-Dokumentenexport Fehler:", type(exc).__name__)
        return "Ich konnte die Mail-Dokumente nicht kopieren."


ACTION_ENGINE.register("mail_document_export", execute_mail_document_export)


_MAIL_SENDER_SEARCH_HINTS = (
    "gibt es", "ist eine", "stand in", "durchsuch", "hat sich", "hat mir",
    "hat ihnen", "hat dir", "geantwortet", "gemeldet",
)


def _extract_mail_sender_query(text: str) -> str | None:
    """Erkennt einen Absendernamen in einer Such-/Existenzfrage ("Gibt es eine
    Mail von Julia?", "Hat sich der Chef schon gemeldet?", "Durchsuch mein
    Postfach nach Julia."), damit handle_mail_command() gezielt in den bereits
    geladenen `messages` filtern kann, statt jede Formulierung blind an die
    generische Themen-Zusammenfassung durchzureichen."""
    normalized = normalize_text(text)
    if not any(hint in normalized for hint in _MAIL_SENDER_SEARCH_HINTS):
        return None

    match = re.search(r"\bvon\s+(?:dem\s+|der\s+|einem\s+|einer\s+)?(.+?)(?:[.?!]|$)", text, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip(" .,!?:;\"'")
        if name and normalize_text(name) not in {"mir", "ihnen", "dir", "uns"}:
            return name

    match = re.search(r"hat\s+(?:sich\s+)?(.+?)\s+(?:mir\s+|ihnen\s+|dir\s+)?(?:schon\s+)?(?:gemeldet|geantwortet)", text, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip(" .,!?:;\"'")
        if name:
            return name

    match = re.search(r"durchsuch\w*.*?\bnach\s+(.+?)[.?!]*$", text, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip(" .,!?:;\"'")
        if name:
            return name

    return None


def handle_mail_command(
    llm: LLMClient,
    text: str,
    force: bool = False,
    memory: Memory | None = None,
) -> str | None:
    normalized = normalize_text(text)
    mail_terms = (
        "mail",
        "mails",
        "maze",
        "maiz",
        "mate",
        "mates",
        "metz",
        "email",
        "emails",
        "e mail",
        "e mails",
        "posteingang",
        "postfach",
        "mailpostfach",
        "mailfach",
        "apple mail",
        "inbox",
        "archiv",
        "archive",
        "junk",
        "papierkorb",
        "gesendet",
    )
    action_terms = (
        "prüf",
        "pruef",
        "check",
        "status",
        "verbindung",
        "funktioniert",
        "kommt raus",
        "raus",
        "schau",
        "reinschauen",
        "anschauen",
        "lies",
        "lese",
        "grüß",
        "gruess",
        "gruss",
        "gib mir",
        "was ist neu",
        "updates",
        "neue",
        "ungelesene",
        "welche",
        "was habe ich",
        "was hab ich",
        "habe ich",
        "hab ich",
        "zeige",
        "zeig",
        "liste",
        "auflisten",
        "passe",
        "fass",
        "fasse",
        "fassen",
        "zusammenfass",
        "zusammenfassen",
        "zusammenfassung",
        "ordner",
        "scan",
        "scanne",
        "diagnose",
        "zugriff",
        "zugreifen",
        "mailfach",
        "kategorisier",
        "kategorisieren",
        "sortier",
        "sortieren",
        "lösch",
        "loesch",
        "löschen",
        "loeschen",
        "papierkorb",
        "trash",
        "entfern",
        "entfernen",
    )
    direct_mail_phrases = {
        "apple mail",
        "mail",
        "mails",
        "email",
        "emails",
        "posteingang",
        "postfach",
        "mailfach",
        "mailpostfach",
    }
    scan_mail_intent = any(term in normalized for term in ("scan", "scanne", "diagnose")) and any(
        term in normalized
        for term in (
            "mail",
            "mails",
            "email",
            "emails",
            "e mail",
            "e mails",
            "mail ordner",
            "mailordner",
            "mailfach",
            "postfach",
            "posteingang",
            "apple mail",
        )
    )
    folder_mail_intent = any(
        term in normalized
        for term in ("archiv", "archive", "inbox", "posteingang", "junk", "papierkorb", "gesendet")
    )

    if not scan_mail_intent and not any(term in normalized for term in mail_terms):
        if not force:
            return None

    if (
        not force
        and
        not scan_mail_intent
        and not folder_mail_intent
        and normalized not in direct_mail_phrases
        and not any(term in normalized for term in action_terms)
    ):
        return None

    if not MAIL_ENABLED:
        return "Mail-Zugriff ist in der Konfiguration deaktiviert."

    delete_answer = handle_mail_delete_command(text, memory=memory)
    if delete_answer is not None:
        return delete_answer

    status_terms = (
        "status",
        "verbindung",
        "funktioniert",
        "kommt raus",
        "was kommt raus",
        "check",
        "prüf",
        "pruef",
    )
    wants_status = any(
        term in normalized
        for term in status_terms
    ) and any(term in normalized for term in ("mail", "icloud", "inbox", "postfach", "posteingang"))

    if wants_status or (force and any(term in normalized for term in status_terms)):
        return check_mail_status()

    if any(term in normalized for term in ("ordner", "mail ordner", "mailordner", "scan", "scanne", "diagnose")):
        try:
            mailboxes = list_mailboxes(max_mailboxes=25)
        except MailAccessError as exc:
            return str(exc)
        except Exception as exc:
            print("Apple-Mail Ordner-Scan Fehler:", type(exc).__name__)
            return "Ich konnte die Apple-Mail-Ordner nicht lesen."

        if not mailboxes:
            return "Apple Mail antwortet, aber ich sehe keine Mail-Ordner."

        non_empty = [mailbox for mailbox in mailboxes if mailbox.message_count > 0]
        visible = non_empty[:8] if non_empty else mailboxes[:8]
        mailbox_lines = "; ".join(
            f"{mailbox.account}: {mailbox.mailbox} ({mailbox.message_count})"
            for mailbox in visible
        )

        if non_empty:
            return f"Ich sehe Nachrichten in diesen Mail-Ordnern: {mailbox_lines}."

        return f"Ich sehe Mail-Ordner, aber ohne Nachrichten: {mailbox_lines}."

    target_account, target_mailbox = resolve_mail_inbox()
    time_hint = ""
    if any(term in normalized for term in ("24 stunden", "vierundzwanzig stunden", "letzten tag", "heute")):
        time_hint = "Beruecksichtige in deiner Zusammenfassung besonders die letzten 24 Stunden."
    elif any(term in normalized for term in ("7 tage", "sieben tage", "letzte woche", "diese woche")):
        time_hint = "Beruecksichtige in deiner Zusammenfassung besonders die letzten 7 Tage."

    if "archiv" in normalized or "archive" in normalized:
        target_account = "iCloud"
        target_mailbox = "Archive"
    elif "junk" in normalized or "spam" in normalized or "werbung" in normalized:
        target_account = "iCloud"
        target_mailbox = "Junk"
    elif "papierkorb" in normalized or "gelöscht" in normalized or "geloescht" in normalized or "deleted" in normalized:
        target_account = "iCloud"
        target_mailbox = "Deleted Messages"
    elif "gesendet" in normalized or "sent" in normalized:
        target_account = "iCloud"
        target_mailbox = "Sent Messages"

    try:
        messages = list_inbox_messages(
            max_messages=MAIL_MAX_MESSAGES,
            account_name=target_account,
            mailbox_name=target_mailbox,
            include_preview=False,
        )
    except MailAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Apple-Mail Fehler:", type(exc).__name__)
        return "Ich konnte Apple Mail nicht lesen."

    if not messages:
        return (
            f"Apple Mail sieht den Ordner {target_account} {target_mailbox}, "
            "aber die Betreffzeilen sind gerade auf Tauchgang."
        )

    # Deterministische Kurzschluesse fuer Fragen, die eine konkrete Antwort statt
    # einer Themen-Zusammenfassung brauchen. Vorher liefen ALLE Mail-Formulierungen
    # (Absendersuche, Mengenfrage, Sortierwunsch, ...) blind in dieselbe generische
    # LLM-Zusammenfassung, egal was gefragt war - live beobachtet 2026-08-19 in
    # einem 2266-Saetze-Testdurchlauf: "Wie viele ungelesene Mails habe ich?" und
    # "Gibt es eine Mail von Julia?" bekamen beide dieselbe unbezogene Antwort.
    if any(term in normalized for term in ("wie viele", "anzahl")):
        try:
            unread = unread_inbox_count(account_name=target_account, mailbox_name=target_mailbox)
        except MailAccessError as exc:
            return str(exc)
        except Exception as exc:
            print("Apple-Mail Anzahl Fehler:", type(exc).__name__)
            unread = None
        if "ungelesen" in normalized and unread is not None:
            return f"Sie haben {unread} ungelesene Mail(s) in {target_account} {target_mailbox}, Sir."
        if unread is not None:
            return (
                f"In {target_account} {target_mailbox} sind {unread} ungelesene Mail(s). "
                f"Ich habe mir die letzten {len(messages)} Nachrichten insgesamt angesehen."
            )

    sender_query = _extract_mail_sender_query(text)
    if sender_query:
        normalized_query = normalize_text(sender_query)
        sender_matches = [m for m in messages if normalized_query in normalize_text(m.sender or "")]
        if sender_matches:
            subjects = "; ".join(m.subject for m in sender_matches[:3] if m.subject)
            return (
                f"Ja, ich sehe {len(sender_matches)} Mail(s) von {sender_query} unter den letzten "
                f"{len(messages)} Nachrichten: {subjects}."
            )
        return (
            f"Unter den letzten {len(messages)} Nachrichten in {target_account} {target_mailbox} "
            f"sehe ich keine Mail von {sender_query}."
        )

    settings = memory.get("settings") or {}
    settings["last_mail_summary"] = {
        "account": target_account,
        "mailbox": target_mailbox,
        "message_ids": [message.message_id for message in messages],
        "subjects": [message.subject for message in messages],
        "senders": [message.sender for message in messages],
        "sigs": [
            {
                "message_id": message.message_id,
                "sender": message.sender,
                "subject": message.subject,
            }
            for message in messages
        ],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    memory.set("settings", settings)

    mail_briefing = build_mail_summary_digest(messages, account_name=target_account, mailbox_name=target_mailbox)

    summary = summarize_mail_digest_via_llm(llm, mail_briefing, len(messages), time_hint=time_hint, user_question=text)
    if summary is None:
        return "Ich habe Mails gefunden, aber daraus gerade keine saubere Zusammenfassung bauen können."
    return summary


def check_mail_status() -> str:
    inbox_account, inbox_mailbox = resolve_mail_inbox()
    try:
        mailboxes = list_mailboxes(max_mailboxes=25)
        messages = list_inbox_messages(
            max_messages=3,
            account_name=inbox_account,
            mailbox_name=inbox_mailbox,
        )
    except MailAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Apple-Mail Status Fehler:", type(exc).__name__)
        return "Ich konnte den Apple-Mail-Status nicht prüfen."

    inbox_summary = next(
        (
            mailbox
            for mailbox in mailboxes
            if mailbox.account == inbox_account and mailbox.mailbox == inbox_mailbox
        ),
        None,
    )

    # inbox_account/inbox_mailbox statt hartkodiert "iCloud INBOX" - resolve_mail_inbox()
    # kann je nach Konfiguration/Auto-Erkennung auch ein anderes Konto liefern, die
    # Meldung soll dann trotzdem stimmen statt faelschlich immer "iCloud" zu nennen.
    if inbox_summary is None:
        return f"Apple Mail antwortet, aber {inbox_account} {inbox_mailbox} macht Verstecken."

    if not messages:
        return (
            f"Apple Mail antwortet und {inbox_account} {inbox_mailbox} ist sichtbar mit "
            f"{inbox_summary.message_count} Nachrichten. Die Betreffzeilen sind aber noch schüchtern."
        )

    subjects = "; ".join(
        f"{message.sender or 'Unbekannt'}: {message.subject}" for message in messages[:3]
    )
    return (
        f"Apple Mail funktioniert. {inbox_account} {inbox_mailbox} ist sichtbar mit "
        f"{inbox_summary.message_count} Nachrichten. Erste Übersichten: {subjects}. Sauber."
    )


def is_mail_time_followup(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        term in normalized
        for term in (
            "24 stunden",
            "vierundzwanzig stunden",
            "letzten 24",
            "letzte 24",
            "letzten tag",
            "heute",
            "7 tage",
            "sieben tage",
            "letzte woche",
            "diese woche",
        )
    )


def is_mail_status_followup(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        term in normalized
        for term in (
            "was kommt raus",
            "kommt raus",
            "status",
            "check",
            "prüf",
            "pruef",
            "funktioniert",
            "verbindung",
        )
    )


def handle_background_mail_command(
    text: str,
    mail_worker: MailBackgroundWorker | None,
) -> str | None:
    if mail_worker is None:
        return None

    normalized = normalize_text(text)
    if not any(
        term in normalized
        for term in (
            "mail",
            "mails",
            "maze",
            "maiz",
            "email",
            "emails",
            "e mail",
            "e mails",
            "mailupdate",
            "posteingang",
            "postfach",
        )
    ):
        return None

    wants_overnight = any(term in normalized for term in ("über nacht", "ueber nacht", "nachts", "nacht"))
    wants_background = any(term in normalized for term in ("hintergrund", "vorbereiten", "vorbereit", "automatisch"))
    wants_morning = any(term in normalized for term in ("morgen", "früh", "frueh", "morgen update", "morgenbriefing"))
    # "neue mails"/"neues" traf faelschlich auch gezielte Fragen wie "Gibt es was
    # Neues von Julia im Postfach?" oder "Wie viele ungelesene Mails habe ich?" -
    # diese Funktion laeuft im Dispatch VOR handle_mail_command() (siehe
    # answer_message()) und blockierte dessen Absendersuche/Mengenfrage-Logik
    # komplett mit dem generischen, gecachten Hintergrund-Update. Live
    # beobachtet 2026-08-20 beim Verifizieren des Mehrfach-Audits.
    looks_like_specific_question = bool(_extract_mail_sender_query(text)) or "wie viele" in normalized or "anzahl" in normalized
    wants_update = not looks_like_specific_question and any(
        term in normalized for term in ("update", "was ist neu", "neue mails", "neues")
    )
    wants_scan = any(term in normalized for term in ("scann", "scan", "lies", "lese", "prüf", "pruef", "schau"))

    if wants_overnight and wants_scan:
        return mail_worker.enable_overnight_scan()

    if wants_background and any(term in normalized for term in ("läuft", "laeuft", "status", "aktiv", "wie weit")):
        return mail_worker.status_answer()

    if wants_background and wants_scan:
        return mail_worker.request_scan(reason="manual")

    if wants_morning or wants_update:
        cached = mail_worker.cached_update()
        if cached:
            return cached

        if wants_background:
            return mail_worker.request_scan(reason="manual")

        return mail_worker.scan_now(reason="manual")

    return None


def _format_event_time(raw_start: str) -> str:
    if " um " in raw_start:
        time_part = raw_start.rsplit(" um ", 1)[-1].strip()
        return time_part[:5] if len(time_part) >= 5 else time_part
    return raw_start


def answer_calendar_query(text: str, normalized: str) -> str:
    wants_reminders = "erinner" in normalized and "termin" not in normalized and "kalender" not in normalized
    only_today = "heute" in normalized and "morgen" not in normalized and "woche" not in normalized
    # Live entdeckter Bug (2026-08-13): "morgen" und "diese Woche" lieferten bisher
    # wortgleich dieselbe, ungefilterte Liste wie eine Anfrage ganz ohne Zeitangabe -
    # nur "heute" filterte tatsaechlich. Siehe docs/current-system-assessment.md,
    # Abschnitt 41.
    only_tomorrow = (
        not only_today
        and any(term in normalized for term in ("morgen", "morgigen"))
        and "übermorgen" not in normalized
        and "uebermorgen" not in normalized
    )
    only_this_week = not only_today and not only_tomorrow and any(
        term in normalized for term in ("diese woche", "der woche", "woche an", "diese ganze woche")
    )

    try:
        if wants_reminders:
            items = list_open_reminders(limit=5).get("items", [])
            if not items:
                return "Ich sehe aktuell keine offenen Erinnerungen."
            lines = [str(item.get("title") or "Erinnerung") for item in items]
            return "Offene Erinnerungen: " + "; ".join(lines) + "."

        until = None
        query_limit = 5
        now = datetime.now()
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59)
        if only_today:
            until = end_of_day
        elif only_tomorrow:
            until = end_of_day + timedelta(days=2)
            query_limit = 15
        elif only_this_week:
            days_until_sunday = 6 - now.weekday()  # Montag=0 ... Sonntag=6
            until = end_of_day + timedelta(days=days_until_sunday)
            query_limit = 25

        items = list_upcoming_calendar_items(limit=query_limit, until=until).get("items", [])
        if only_today:
            # Zusaetzlich zur AppleScript-seitigen until-Vorfilterung (grob, haengt am
            # Ende an einem locale-formatierten Datumsvergleich) wird hier noch einmal
            # anhand des echten, numerisch geparsten start_dt gefiltert - robust,
            # unabhaengig vom Systemdatumsformat. Behebt den gemeldeten Bug, dass "was
            # steht heute an" teils Termine aus dem ganzen Jahr zeigte.
            items = events_on_date(items)
        elif only_tomorrow:
            items = events_on_date(items, on=now + timedelta(days=1))

        if not items:
            if only_today:
                return "Für heute sehe ich keine Termine."
            if only_tomorrow:
                return "Für morgen sehe ich keine Termine."
            if only_this_week:
                return "Für diese Woche sehe ich keine Termine mehr."
            return "Ich sehe aktuell keine anstehenden Termine."

        lines = [f"{item.get('title') or 'Termin'} um {_format_event_time(item.get('start', ''))} Uhr" for item in items]
        if only_today:
            prefix = "Heute steht an: "
        elif only_tomorrow:
            prefix = "Morgen steht an: "
        elif only_this_week:
            prefix = "Diese Woche steht an: "
        else:
            prefix = "Ihre nächsten Termine: "
        return prefix + "; ".join(lines) + "."
    except CalendarAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Kalender Fehler:", type(exc).__name__)
        return "Ich konnte Ihren Kalender gerade nicht lesen."


_CALENDAR_DELETE_VERBS = (
    "lösche",
    "loesche",
    "löschen",
    "loeschen",
    "entferne",
    "entfernen",
    "lösch",
    "loesch",
    "sage ab",
    "sag ab",
    "storniere",
)


def _extract_calendar_title_for_delete(text: str) -> tuple[str | None, bool]:
    """Extrahiert Titel + Art (Erinnerung vs. Termin/Kalendereintrag) aus einer
    Loesch-Anfrage ("Lösche den Termin X", "Entferne die Erinnerung Y") - im
    Gegensatz zu extract_calendar_title() (auf Erstell-Saetze zugeschnitten,
    strippt nur Erstell-Verben) wird hier gezielt nach dem Nomen direkt nach
    "termin"/"kalendereintrag"/"erinnerung" gesucht. Analog zu
    _extract_note_title_for_delete()."""
    normalized = normalize_text(text)
    is_reminder = "erinnerung" in normalized and "termin" not in normalized and "kalender" not in normalized
    noun_pattern = "erinnerung" if is_reminder else "(?:termin|kalendereintrag)"
    match = re.search(
        rf"{noun_pattern}\s+(?:namens\s+|mit\s+dem\s+titel\s+)?(?:(?:der|die|den)\s+)?(.+?)$",
        normalized,
    )
    if not match:
        return None, is_reminder
    title = match.group(1).strip(" .,!?:;")
    return (title or None), is_reminder


def handle_calendar_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    domain_match = has_domain(text, "calendar")
    is_query = looks_like_calendar_query(text)
    if not is_query and domain_match:
        # Kein eindeutiges Erstell-Verb, aber klingt nach einer Frage (Fragezeichen
        # oder ein Frage-Satzanfang aus QUESTION_SHAPE_PREFIXES) -> eher lesen als
        # ungefragt den Erstellen-Flow starten. Bewusst NICHT create_terms
        # wiederverwendet, weil dort "termin" selbst mit drinsteht (ein Substantiv,
        # kein Erstell-Verb) und sonst jede Termin-Frage als Erstell-Absicht
        # durchginge. Live-Bug aus der Runde-2-Simulation, 2026-08-13: "Wann ist
        # eigentlich mein nächster Termin?" fragte statt einer Antwort nach
        # Datum/Uhrzeit, weil hier bisher nur "hab ich"/"habe ich"/"steht" erkannt
        # wurden. Siehe docs/current-system-assessment.md, Abschnitt 42.
        # "trag"/"trage" bewusst NICHT als blosser Wortstamm - der ist Teil von
        # "eingetragen" ("ist am Wochenende was eingetragen?" ist eine Frage,
        # kein Erstell-Wunsch, wuerde mit dem blossen Stamm aber faelschlich
        # als einer erkannt).
        has_create_verb = any(
            term in normalized
            for term in ("erstelle", "erstell", "setz", "setze", "trag ein", "trage ein", "einzutragen", "erinnere mich")
        )
        looks_like_question = (
            any(term in normalized for term in ("hab ich", "habe ich", "steht"))
            or text.strip().endswith("?")
            or normalized.startswith(QUESTION_SHAPE_PREFIXES)
        )
        if not has_create_verb and looks_like_question:
            is_query = True
    if not domain_match and not is_query:
        return None

    if is_query:
        return answer_calendar_query(text, normalized)

    status_terms = (
        "zugriff",
        "status",
        "funktioniert",
        "automatisch",
        "automatik",
        "rechnungen",
        "rechnung",
        "mails",
        "mail",
    )
    create_terms = (
        "erstelle",
        "erstell",
        "mach",
        "mache",
        "setz",
        "setze",
        "trag",
        "trage",
        "ein",
        "erinnere mich",
        "termin",
        "kalendereintrag",
        "erinnerung",
    )

    if any(term in normalized for term in status_terms) and not any(term in normalized for term in create_terms):
        if not bool(CONFIG.get("auto_calendar_from_mail_enabled", True)):
            return "Die automatische Kalender- und Erinnerungslogik ist aus."

        return (
            "Kalender- und Erinnerungsautomatik ist aktiv. "
            "Bei klaren Mails mit Rechnung, Frist oder Termin lege ich automatisch etwas an. Ziemlich fleißig, ich weiß."
        )

    if any(term in normalized for term in _CALENDAR_DELETE_VERBS):
        delete_title, delete_is_reminder = _extract_calendar_title_for_delete(text)
        if not delete_title:
            return "Erinnerung" if delete_is_reminder else "Welchen Termin soll ich löschen?"
        if memory is None:
            return None
        target = "Erinnerung" if delete_is_reminder else "Termin"
        return ACTION_ENGINE.propose(
            memory,
            "pending_calendar_delete",
            ActionProposal(
                action_type="calendar_delete",
                execution_data={"kind": "reminder" if delete_is_reminder else "calendar", "title": delete_title},
                confirm_prompt=(
                    f"Soll ich {'die' if delete_is_reminder else 'den'} {target} {delete_title} wirklich löschen? "
                    "Sag ja oder abbrechen."
                ),
            ),
        )

    parsed = _extract_datetime(text, CONFIG)
    if parsed is None:
        return "Für Kalender oder Erinnerung brauche ich noch Datum oder Uhrzeit."

    when, has_time = parsed
    title = extract_calendar_title(text)
    if not title:
        title = "Erinnerung" if "erinner" in normalized else "Termin"

    is_reminder = "erinner" in normalized and "termin" not in normalized and "kalender" not in normalized
    if memory is not None:
        # "die Erinnerung" (feminin) vs. "den Kalendereintrag" (maskulin,
        # Akkusativ) - vorher hartkodiert "die {target}" fuer beide Faelle,
        # was bei Kalendereintraegen grammatikalisch falsch war ("Soll ich die
        # Kalendereintrag ... erstellen?"). Live beobachtet 2026-08-19.
        target = "Erinnerung" if is_reminder else "Kalendereintrag"
        article = "die" if is_reminder else "den"
        return ACTION_ENGINE.propose(
            memory,
            "pending_calendar_create",
            ActionProposal(
                action_type="calendar_create",
                execution_data={
                    "kind": "reminder" if is_reminder else "calendar",
                    "title": title,
                    "when": when.isoformat(),
                    "has_time": has_time,
                },
                confirm_prompt=(
                    f"Ich habe noch nichts angelegt. Soll ich {article} {target} {title} "
                    f"für {when.strftime('%d.%m.%Y %H:%M')} erstellen?"
                ),
            ),
        )

    try:
        if is_reminder:
            create_reminder(
                title,
                when,
                list_name=CONFIG.get("reminders_list_name"),
                notes="Von Jarvis per Sprache erstellt.",
            )
            return f"Erledigt. Erinnerung {title} steht."

        create_calendar_event(
            title,
            when,
            duration_minutes=int(CONFIG.get("auto_calendar_event_duration_minutes", 60)),
            calendar_name=CONFIG.get("calendar_name"),
            notes="Von Jarvis per Sprache erstellt.",
        )
        if has_time:
            return f"Erledigt. Termin {title} ist drin."
        return f"Erledigt. Termin {title} ist mit Standardzeit drin."
    except CalendarAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Kalender Fehler:", type(exc).__name__)
        return "Kalender oder Erinnerung wollten gerade nicht."


def execute_calendar_create(data: dict) -> str:
    kind = str(data.get("kind") or "calendar")
    title = str(data.get("title") or "Termin").strip()
    try:
        when = datetime.fromisoformat(str(data.get("when")))
        if kind == "reminder":
            create_reminder(
                title,
                when,
                list_name=CONFIG.get("reminders_list_name"),
                notes="Von Jarvis per Sprache erstellt.",
            )
            privacy_log("reminders", "create", success=True)
            return f"Erledigt. Ich habe die Erinnerung {title} gesetzt."

        create_calendar_event(
            title,
            when,
            duration_minutes=int(CONFIG.get("auto_calendar_event_duration_minutes", 60)),
            calendar_name=CONFIG.get("calendar_name"),
            notes="Von Jarvis per Sprache erstellt.",
        )
        privacy_log("calendar", "create", success=True)
        return f"Erledigt. Ich habe den Kalendereintrag {title} angelegt."
    except CalendarAccessError as exc:
        privacy_log("calendar", "create", success=False)
        return str(exc)
    except Exception as exc:
        privacy_log("calendar", "create", success=False)
        print("Kalender Fehler:", type(exc).__name__)
        return "Ich konnte Kalender oder Erinnerungen nicht bearbeiten."


ACTION_ENGINE.register("calendar_create", execute_calendar_create)


def execute_calendar_delete(data: dict) -> str:
    kind = str(data.get("kind") or "calendar")
    title = str(data.get("title") or "").strip()
    try:
        if kind == "reminder":
            delete_reminder(title, list_name=CONFIG.get("reminders_list_name"))
            privacy_log("reminders", "delete", success=True)
            return f"Erledigt. Ich habe die Erinnerung {title} gelöscht."

        delete_calendar_event(title, calendar_name=CONFIG.get("calendar_name"))
        privacy_log("calendar", "delete", success=True)
        return f"Erledigt. Ich habe den Termin {title} gelöscht."
    except CalendarAccessError as exc:
        privacy_log("calendar", "delete", success=False)
        return str(exc)
    except Exception as exc:
        privacy_log("calendar", "delete", success=False)
        print("Kalender Loesch-Fehler:", type(exc).__name__)
        return "Ich konnte den Termin oder die Erinnerung nicht löschen."


ACTION_ENGINE.register("calendar_delete", execute_calendar_delete)


def extract_calendar_title(text: str) -> str:
    cleaned = strip_wake_word_from_text(text)
    normalized = normalize_text(cleaned)
    if "erinner" in normalized:
        reminder_clause = re.search(r"\bdass\s+(.+?)[.?!]*$", cleaned, flags=re.IGNORECASE)
        if reminder_clause:
            title = clean_calendar_title(reminder_clause.group(1))
            if title:
                return title

    purpose_match = re.search(
        r"\b(?:an|wegen|für|fuer|zu)\s+(.+?)[.?!]*$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if purpose_match:
        title = clean_calendar_title(purpose_match.group(1))
        if title:
            return title

    cleaned = re.sub(
        r"\b(?:kalender|kalendereintrag|termin|termineintrag|erinnerung|erinnerungen|erinnere mich|bitte|mal|mir|einen|eine|kurz|kurze|kurzen|den|die|das|für mich|fuer mich|namens|kannst du|könntest du|koenntest du|kannst|könntest|koenntest)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        # "erstelle/erstell" (Imperativ) UND "erstellen" (Infinitiv, z.B. "...
        # Termin fuer heute erstellen") - Live beobachtet 2026-08-19: die
        # Infinitiv-Form fehlte, "Kannst du mir einen Termin fuer heute
        # erstellen" ergab dadurch den unsinnigen Titel "Kannst du fuer".
        r"\b(?:erstelle|erstell|erstellen|anlegen|anzulegen|eintragen|einzutragen|mach|mache|machen|setz|setze|setzen|trag|trage|schreib|schreibe|ein|an|du)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return clean_calendar_title(cleaned)


def clean_calendar_title(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:heute|morgen|übermorgen|uebermorgen|nächsten|naechsten|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:am|um)\s+\d{1,2}(?::\d{2})?\s*(?:uhr)?\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}[.\/-]\d{1,2}(?:[.\/-]\d{2,4})?\b", " ", cleaned)
    cleaned = re.sub(r"^\s*(?:ich|mich|mir|daran|dass)\s+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bteste\b", "testen", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+muss\s*$", "", cleaned, flags=re.IGNORECASE)
    # extract_calendar_title()'s purpose_match-Regex ("für/an/wegen/zu X")
    # faengt bei Saetzen ohne echten Titel manchmal ein am Satzende
    # haengengebliebenes Erstell-Verb als vermeintliche Absicht ein - "Termin
    # fuer heute erstellen" ergab nach dem Entfernen von "heute" sonst den
    # Titel "erstellen", sichtbar in der kaputten Bestaetigung "Kalendereintrag
    # erstellen fuer ... erstellen?" (das Wort doppelt). Live beobachtet
    # 2026-08-19. Nach dem Entfernen faellt der Titel korrekt leer aus und die
    # bestehende Fallback-Logik in handle_calendar_command() nutzt "Termin".
    cleaned = re.sub(
        r"\b(?:erstelle|erstell|erstellen|anlegen|anzulegen|eintragen|einzutragen|machen|setzen)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .,!?:;\"'")
    # Generisches Sicherheitsnetz statt weiterer Einzelwort-Ausnahmen: bleibt
    # nach allen obigen Bereinigungen nur noch eine blosse Praeposition/
    # Fuellwort ohne echtes Inhaltswort uebrig (z.B. "für", "zu", "an" allein),
    # ist das kein sinnvoller Titel, sondern ein Extraktions-Artefakt. Leerer
    # Rueckgabewert laesst die Fallback-Logik in handle_calendar_command()
    # sauber "Termin"/"Erinnerung" einsetzen, statt einer kaputten
    # Praeposition als Titel. Live beobachtet 2026-08-19: "Kannst du mir einen
    # Termin fuer heute erstellen" hinterliess nach dem Entfernen von "heute"/
    # "erstellen" noch das einzelne Wort "für" als vermeintlichen Titel.
    if normalize_text(cleaned) in {"für", "fuer", "zu", "an", "wegen", "mit", "bei", "um", "am", "im"}:
        return ""
    return cleaned


def handle_contact_command(text: str, memory: Memory | None = None) -> str | None:
    if not CONTACTS_ENABLED:
        return None

    normalized = normalize_text(text)
    call_terms = ("ruf", "rufe", "rufen", "hof", "anruf", "anrufen", "telefonier", "telefoniere")

    wants_contacts = has_domain(text, "contacts")
    wants_call = any(term in normalized for term in call_terms)

    if not wants_contacts and not wants_call:
        return None

    if wants_call:
        contact_name = extract_call_contact_name(text)
        if not contact_name:
            return "Wen soll ich anrufen?"

        try:
            matches = find_contacts(contact_name)
        except ContactAccessError as exc:
            return str(exc)
        except Exception as exc:
            print("Kontakte Fehler:", type(exc).__name__)
            return "Ich konnte Kontakte nicht lesen."

        if not matches:
            return f"Ich finde keinen Kontakt mit dem Namen {contact_name}."

        if len(matches) > 1:
            names = ", ".join(contact.name for contact in matches[:3])
            return f"Ich finde mehrere passende Kontakte: {names}. Sag bitte den Namen genauer."

        resolved_contact = matches[0]
        resolved_name = resolved_contact.name
        if memory is None:
            return f"Ich würde {resolved_name} nur nach Ihrer Bestätigung anrufen."

        settings = memory.get("settings") or {}
        if len(resolved_contact.phones) > 1:
            endings = ", ".join(mask_phone_end(phone) for phone in resolved_contact.phones[:4])
            settings["pending_call_choice"] = {
                "name": resolved_name,
                "phones": resolved_contact.phones,
            }
            memory.set("settings", settings)
            return (
                f"Ich habe {resolved_name} gefunden, aber mehrere Nummern. "
                f"Ich sehe diese Endungen: {endings}. Welche soll ich nehmen?"
            )

        return ACTION_ENGINE.propose(
            memory,
            "pending_call_contact",
            ActionProposal(
                action_type="call_contact",
                execution_data={"name": resolved_name},
                confirm_prompt=f"Ich habe {resolved_name} gefunden. Soll ich den Anruf wirklich starten? Sag ja zum Anrufen oder abbrechen.",
            ),
        )

    if any(term in normalized for term in ("sehen", "anzeigen", "zeige", "liste", "hast du zugriff", "zugriff")):
        try:
            contacts = list_contacts(limit=8)
        except ContactAccessError as exc:
            return str(exc)
        except Exception as exc:
            print("Kontakte Fehler:", type(exc).__name__)
            return "Ich konnte Kontakte nicht lesen."

        if not contacts:
            return "Ich finde keine Kontakte mit Nummer."

        names = ", ".join(contact.name for contact in contacts[:5])
        return f"Ich sehe zum Beispiel: {names}."

    # "von|für|fuer" bewusst optional gemacht - "suche den Kontakt Leon" oder
    # "hast du einen Kontakt namens Leon" (ohne Praeposition zwischen "Kontakt"
    # und dem Namen) fielen bisher komplett durch, obwohl has_domain() sie
    # korrekt als Kontakte-Domaene erkannte - die Funktion gab am Ende None
    # zurueck, was Jarvis in eine verwirrende "Meinten Sie gerade Ihre
    # Kontakte?"-Rueckfrage schickte statt direkt zu suchen. Live beobachtet
    # 2026-08-18.
    # "X in meinem Adressbuch" nennt den Namen VOR dem Domaenen-Wort, anders als
    # alle anderen Muster hier ("Kontakt von X", "Kontaktdaten von X", ...) - live
    # beobachtet 2026-08-19: "Hast du Julia in meinem Adressbuch?" wurde von
    # keinem bestehenden Muster erfasst und landete in der generischen
    # Domaenen-Rueckfrage, obwohl has_domain() "Adressbuch" laengst korrekt
    # erkannt hatte.
    adressbuch_match = re.search(
        r"(?:hast du|haben sie)\s+(.+?)\s+in\s+(?:meinem|meinen|ihrem|ihren)\s+adressbuch",
        text,
        flags=re.IGNORECASE,
    )
    if adressbuch_match:
        name_query = adressbuch_match.group(1).strip(" .,!?:;")
        try:
            matches = find_contacts(name_query)
        except ContactAccessError as exc:
            return str(exc)

        if not matches:
            return f"Ich finde keinen Kontakt mit dem Namen {name_query} in Ihrem Adressbuch."

        names = ", ".join(contact.name for contact in matches[:3])
        return f"Ja, ich finde: {names}."

    search_match = re.search(
        r"(?:kontakt|kontakte|telefonnummer|nummer|kontaktdaten)\s+(?:von\s+|für\s+|fuer\s+|namens\s+)?(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if search_match:
        name_query = search_match.group(1).strip(" .,!?:;")
        try:
            matches = find_contacts(name_query)
        except ContactAccessError as exc:
            return str(exc)

        if not matches:
            return f"Ich finde keinen Kontakt mit dem Namen {name_query}."

        names = ", ".join(contact.name for contact in matches[:3])
        return f"Ich finde diese passenden Kontakte: {names}."

    return None


def execute_call_contact(data: dict) -> str:
    contact_name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not contact_name:
        return "Der Kontaktname fehlt. Ich starte keinen Anruf."

    try:
        if phone:
            return call_phone_number(contact_name, phone)
        return call_contact_by_name(contact_name)
    except ContactAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Kontakte/Anruf Fehler:", type(exc).__name__)
        return "Ich konnte den Anruf nicht starten."


ACTION_ENGINE.register("call_contact", execute_call_contact)


def extract_call_contact_name(text: str) -> str:
    patterns = (
        r"(?:ruf|rufe|rufen|hof|anruf|anrufen|telefonier|telefoniere)\s+(?:bitte\s+)?(?:mal\s+)?(?:den\s+|die\s+|das\s+)?(.+?)(?:\s+an)?[.?!]*$",
        r"(?:kannst du|bitte)\s+(.+?)\s+(?:anrufen|rufen|telefonieren)[.?!]*$",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            name = match.group(1)
            name = re.sub(r"\b(?:bitte|mal|für mich|fuer mich|kontakt|nummer)\b", " ", name, flags=re.IGNORECASE)
            name = re.sub(r"\s+", " ", name)
            return name.strip(" .,!?:;")

    return ""


def extract_phone_hint(text: str) -> str:
    normalized = normalize_text(text)
    word_digits = {
        "null": "0",
        "eins": "1",
        "ein": "1",
        "eine": "1",
        "zwei": "2",
        "drei": "3",
        "vier": "4",
        "fünf": "5",
        "fuenf": "5",
        "sechs": "6",
        "sieben": "7",
        "acht": "8",
        "neun": "9",
    }
    for word, digit in word_digits.items():
        normalized = re.sub(rf"\b{word}\b", digit, normalized)

    def repeat_digit(match: re.Match[str]) -> str:
        count = int(match.group(1))
        digit = match.group(2)
        return digit * max(1, min(count, 12))

    normalized = re.sub(
        r"\b(\d{1,2})\s*mal\s*(?:die\s*)?(\d)\b",
        repeat_digit,
        normalized,
    )
    return "".join(char for char in normalized if char.isdigit())


def normalize_phone_digits(phone: str) -> str:
    return "".join(char for char in str(phone) if char.isdigit())


def mask_phone_end(phone: str) -> str:
    digits = normalize_phone_digits(phone)
    if not digits:
        return "unbekannt"
    return "Endung " + digits[-4:]


def handle_desktop_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("desktop", "schreibtisch")):
        return None
    # Reiner Teilstring-Vergleich statt Wortgrenze traf faelschlich auch Dateien,
    # deren Name zufaellig "mail" als Teilstring enthaelt (z.B. "Thumbnail.png",
    # "Mailand-Urlaub.jpg") und blockierte eine ganz normale Datei-Anfrage dafuer.
    # Live beobachtet 2026-08-20 im Mehrfach-Audit.
    if re.search(r"\b(?:mail|mails|email|emails|posteingang|mailfach)\b", normalized):
        return None

    try:
        bulk_move = extract_bulk_file_move(text)
        if bulk_move:
            query, target_folder = bulk_move
            if memory is None:
                return f"Ich würde alle Dateien mit {query} im Namen in den Schreibtisch-Ordner {target_folder} schieben."

            return ACTION_ENGINE.propose(
                memory,
                "pending_desktop_move_many",
                ActionProposal(
                    action_type="desktop_move_many",
                    execution_data={
                        "query": query,
                        "target": target_folder,
                    },
                    confirm_prompt=(
                        f"Ich habe noch nichts verschoben. Soll ich alle Dateien mit {query} "
                        f"im Namen in den Schreibtisch-Ordner {target_folder} schieben?"
                    ),
                ),
            )

        move_match = re.search(
            r"(?:verschieb|verschiebe|pack|packe|leg|lege)\s+(.+?)\s+(?:in|nach|zu)\s+(?:den\s+|dem\s+|der\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in)\s+(?:meinem\s+|meinen\s+|dem\s+|der\s+)?(?:desktop|schreibtisch))?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if move_match:
            source_name = clean_desktop_name(move_match.group(1))
            target_folder = clean_desktop_name(move_match.group(2))
            if not source_name or not target_folder:
                return "Was soll ich wohin auf Ihrem Schreibtisch verschieben?"

            if memory is None:
                return f"Ich würde {source_name} in den Schreibtisch-Ordner {target_folder} schieben."

            return ACTION_ENGINE.propose(
                memory,
                "pending_desktop_move",
                ActionProposal(
                    action_type="desktop_move",
                    execution_data={
                        "source": source_name,
                        "target": target_folder,
                    },
                    confirm_prompt=(
                        f"Ich habe noch nichts verschoben. Soll ich {source_name} "
                        f"in den Schreibtisch-Ordner {target_folder} schieben?"
                    ),
                ),
            )

        create_match = re.search(
            r"(?:erstelle|erstell|mach|mache|leg|lege)\s+(?:mir\s+)?(?:einen\s+|eine\s+|neuen\s+|neue\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in)\s+(?:meinem\s+|meinen\s+)?(?:desktop|schreibtisch))?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if create_match and "ordner" in normalized:
            folder_name = extract_folder_name_from_command(text, root_hint="desktop")
            if not folder_name:
                return "Wie soll der Ordner heißen?"
            return create_desktop_folder(folder_name)

        search_match = re.search(
            r"(?:such|suche|finde|zeig|zeige).*(?:auf|am|in)\s+(?:meinem\s+|meinen\s+|dem\s+|der\s+)?(?:desktop|schreibtisch)\s+(?:nach\s+)?(.+?)[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if search_match:
            return search_desktop(search_match.group(1))

        if any(
            term in normalized
            for term in (
                "was ist",
                "was liegt",
                "was befindet",
                "zeige",
                "zeig",
                "liste",
                "auflisten",
                "überblick",
                "ueberblick",
                "sehen",
                "siehst",
                "inhalt",
                "ordner",
                "dateien",
            )
        ):
            return summarize_desktop()

    except DesktopAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Desktop Fehler:", type(exc).__name__)
        return "Ich konnte Ihren Schreibtisch nicht lesen."

    return None


def execute_desktop_move(data: dict) -> str:
    source_name = str(data.get("source") or "").strip()
    target_folder = str(data.get("target") or "").strip()
    if not source_name or not target_folder:
        return "Mir fehlt Quelle oder Zielordner. Ich verschiebe nichts."

    try:
        return move_desktop_item(source_name, target_folder)
    except DesktopAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Desktop Verschieben Fehler:", type(exc).__name__)
        return "Ich konnte das auf dem Schreibtisch nicht verschieben."


def execute_desktop_move_many(data: dict) -> str:
    query = str(data.get("query") or "").strip()
    target_folder = str(data.get("target") or "").strip()
    if not query or not target_folder:
        return "Mir fehlt Suchbegriff oder Zielordner. Ich verschiebe nichts."

    try:
        return move_desktop_items_matching(query, target_folder)
    except DesktopAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Desktop Sammelverschieben Fehler:", type(exc).__name__)
        return "Ich konnte die Dateien auf dem Schreibtisch nicht verschieben."


ACTION_ENGINE.register("desktop_move", execute_desktop_move)
ACTION_ENGINE.register("desktop_move_many", execute_desktop_move_many)


def handle_file_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)

    # Speicherplatz-Aufraeum-Anfragen ("welche Dateien koennen wir loeschen,
    # die mir mehr Speicherplatz bringen") landeten bisher fälschlich im
    # generischen Datei-Such-Fallback weiter unten und lieferten dessen
    # "nichts gefunden"-Vorlage mit der eingesetzten Rohanfrage - erkennbar
    # kaputt. Enge Erkennung: BEIDE Wortgruppen muessen zutreffen, damit
    # normale Datei-Suchen/-Verschiebungen nicht faelschlich hier landen.
    # Siehe plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md.
    # Erweiterung Runde-2-Simulation (2026-08-13): "Ich brauch dringend mehr
    # Speicherplatz ..., was weg könnte" und "Meine Festplatte ist ziemlich
    # voll, ... die nur rumliegen" fielen durch - zum einen weil
    # "festplatte voll" nur als direkt benachbarte Woerter zaehlte und "weg
    # koennte"/"rumliegen" gar nicht als Aufraeum-Signal bekannt waren, zum
    # anderen weil BEIDE Saetze den weiter unten stehenden
    # file_context/root_context-Filter gar nicht erst passierten (keines der
    # Woerter "datei"/"ordner"/"desktop"/... kommt darin vor) - die Funktion
    # gab also schon vorher None zurueck, bevor die Aufraeum-Erkennung
    # ueberhaupt lief. cleanup_intent wird deshalb jetzt VOR diesem Filter
    # geprueft, nicht mehr danach. Siehe
    # docs/current-system-assessment.md, Abschnitt 42.
    cleanup_intent = (
        any(
            term in normalized
            for term in ("speicherplatz", "speicher freigeben", "festplatte voll", "festplatte", "speicher voll", "mehr speicher")
        )
        and any(
            term in normalized
            for term in (
                "löschen", "loeschen", "aufräumen", "aufraeumen", "freigeben", "sparen", "papierkorb",
                "weg könnte", "weg koennte", "weg kann", "rumliegen", "nicht mehr brauch", "nicht gebraucht",
                "nicht benötigt", "nicht benoetigt", "los werden",
            )
        )
    )
    if cleanup_intent:
        cleanup_text, cleanup_candidates = suggest_cleanup_files(config=CONFIG)
        if cleanup_candidates and memory is not None:
            settings = memory.get("settings") or {}
            settings["pending_cleanup_confirmation"] = {
                "items": cleanup_candidates,
                "set_at": time.time(),
            }
            memory.set("settings", settings)
        return cleanup_text

    file_context = has_domain(text, "files")
    root_context = any(
        term in normalized
        for term in (
            "desktop",
            "schreibtisch",
            "dokumente",
            "downloads",
            "download",
            "jarvis",
            "projekt",
            "code",
            "home",
            "benutzerordner",
            "alle dateien",
            "dateien",
        )
    )
    if not file_context and not root_context:
        return None
    # Reiner Teilstring-Vergleich statt Wortgrenze traf faelschlich auch Dateien,
    # deren Name zufaellig "mail" als Teilstring enthaelt (z.B. "Thumbnail.png",
    # "Mailand-Urlaub.jpg") und blockierte eine ganz normale Datei-Anfrage dafuer.
    # Live beobachtet 2026-08-20 im Mehrfach-Audit.
    if re.search(r"\b(?:mail|mails|email|emails|posteingang|mailfach)\b", normalized):
        return None

    root_hint = detect_root_hint(text)

    try:
        # Datei-Loeschen gab es bisher gar nicht: "Lösche die Datei X" fiel
        # bis zum fallback_query-Zweig weiter unten durch, der den kompletten
        # Rohsatz (inkl. "Lösche") als Suchbegriff an search_files() gab - eine
        # erkennbar kaputte "nichts gefunden"-Antwort statt einer echten
        # Loeschung. Live beobachtet 2026-08-19. move_to_trash() existierte
        # bereits (genutzt vom Speicherplatz-Aufraeumen), war aber nie an eine
        # gezielte Einzeldatei-Loeschung per Namen angebunden. Verschiebt in
        # den Papierkorb (rueckgaengig machbar), loescht nie endgueltig.
        delete_match = re.search(
            r"(?:lösche|loesche|lösch|loesch|entferne|entfern|schmeiß|schmeiss)\s+(?:bitte\s+)?(?:die\s+|den\s+|das\s+)?(?:datei\s+)?(.+?)"
            r"(?:\s+(?:auf|am|in|unter|von|vom)\s+(?:meinem\s+|meinen\s+|meiner\s+|dem\s+|der\s+)?"
            r"(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|jarvis|projekt|code))?"
            r"(?:\s+weg)?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if not delete_match:
            # Verb-finale Formulierungen ("Kannst du X löschen?", "Ich brauch X
            # nicht mehr, lösch die.") haben das Verb NICHT am Satzanfang, das
            # obige Muster faengt sie deshalb nicht ab. Live beobachtet
            # 2026-08-20 im Mehrfach-Audit.
            delete_match = re.search(
                r"(?:kannst du|könntest du|koenntest du)\s+(?:bitte\s+)?(?:die\s+|den\s+|das\s+)?(?:datei\s+)?(.+?)\s+(?:löschen|loeschen)\b",
                text,
                flags=re.IGNORECASE,
            )
        if delete_match:
            file_name = clean_file_name(delete_match.group(1))
            if not file_name:
                return "Welche Datei soll ich löschen?"
            if memory is None:
                return f"Ich würde {file_name} in den Papierkorb legen."
            return ACTION_ENGINE.propose(
                memory,
                "pending_file_action",
                ActionProposal(
                    action_type="file_action",
                    execution_data={
                        "action": "delete",
                        "source": file_name,
                        "target": "",
                        "root": root_hint,
                    },
                    confirm_prompt=(
                        f"Ich habe noch nichts gelöscht. Soll ich {file_name} wirklich in den "
                        "Papierkorb legen? Sag ja oder abbrechen."
                    ),
                ),
            )

        bulk_move = extract_bulk_file_move(text)
        if bulk_move and not any(term in normalized for term in ("kopier", "kopiere", "kopieren")):
            query, target_folder = bulk_move
            if memory is None:
                return f"Ich würde alle Dateien mit {query} im Namen in den Ordner {target_folder} verschieben."

            return ACTION_ENGINE.propose(
                memory,
                "pending_file_action",
                ActionProposal(
                    action_type="file_action",
                    execution_data={
                        "action": "move_matching",
                        "query": query,
                        "target": target_folder,
                        "root": root_hint,
                    },
                    confirm_prompt=f"Ich habe noch nichts geändert. Soll ich alle Dateien mit {query} im Namen in den Ordner {target_folder} verschieben?",
                ),
            )

        action_match = re.search(
            r"(?:kopier|kopiere|verschieb|verschiebe|pack|packe|leg|lege)\s+(.+?)\s+(?:in|nach|zu)\s+(?:den\s+|dem\s+|der\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in|aus|von)\s+.+)?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if action_match:
            source_name = clean_file_name(action_match.group(1))
            target_folder = clean_file_name(action_match.group(2))
            action = "copy" if any(term in normalized for term in ("kopier", "kopiere")) else "move"
            verb = "kopieren" if action == "copy" else "verschieben"
            if not source_name or not target_folder:
                return "Was soll ich wohin verschieben oder kopieren?"

            if memory is None:
                return f"Ich würde {source_name} in den Ordner {target_folder} {verb}."

            return ACTION_ENGINE.propose(
                memory,
                "pending_file_action",
                ActionProposal(
                    action_type="file_action",
                    execution_data={
                        "action": action,
                        "source": source_name,
                        "target": target_folder,
                        "root": root_hint,
                    },
                    confirm_prompt=f"Ich habe noch nichts geändert. Soll ich {source_name} in den Ordner {target_folder} {verb}?",
                ),
            )

        create_match = re.search(
            r"(?:erstelle|erstell|mach|mache|leg|lege)\s+(?:mir\s+)?(?:einen\s+|eine\s+|neuen\s+|neue\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in|unter)\s+.+)?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if create_match and "ordner" in normalized:
            folder_name = extract_folder_name_from_command(text, root_hint=root_hint)
            if not folder_name:
                return "Wie soll der Ordner heißen?"
            return create_folder(folder_name, root_hint=root_hint, config=CONFIG)

        search_match = re.search(
            r"(?:such|suche|finde|zeig|zeige).*(?:nach\s+)?(.+?)(?:\s+(?:in|unter|auf|am)\s+.+)?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if search_match and any(term in normalized for term in ("such", "suche", "finde")):
            query = extract_file_search_query(text)
            if not query:
                return "Wonach soll ich suchen?"
            return search_files(query, root_hint=root_hint, config=CONFIG)

        wants_overview = any(
            term in normalized
            for term in (
                "was ist",
                "was liegt",
                "was befindet",
                "zeige",
                "zeig",
                "liste",
                "auflisten",
                "überblick",
                "ueberblick",
                "sehen",
                "siehst",
                "inhalt",
            )
        )
        if wants_overview:
            return summarize_folder(root_hint=root_hint, config=CONFIG)

        fallback_query = remove_domain_words(text, "files")
        if fallback_query and fallback_query not in {"ordner", "datei", "dateien"}:
            return search_files(fallback_query, root_hint=root_hint, config=CONFIG)

        if file_context or root_context:
            return summarize_folder(root_hint=root_hint, config=CONFIG)

    except FileAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Dateizugriff Fehler:", type(exc).__name__)
        return "Ich konnte die Dateien nicht lesen."

    return None


def execute_file_action(data: dict) -> str:
    action = str(data.get("action") or "").strip()
    source = str(data.get("source") or "").strip()
    query = str(data.get("query") or "").strip()
    target = str(data.get("target") or "").strip()
    root_hint = str(data.get("root") or "").strip()
    if (
        not action
        or (action not in ("move_matching", "delete") and not target)
        or (action != "move_matching" and not source)
        or (action == "move_matching" and not query)
    ):
        return "Mir fehlt noch ein Baustein. Ich ändere nichts."

    try:
        if action == "delete":
            path = find_item(source, root_hint=root_hint, config=CONFIG)
            if path is None:
                return f"Ich habe {source} nicht eindeutig gefunden. Ich habe nichts gelöscht."
            moved, skipped = move_to_trash([path])
            if moved:
                return f"Erledigt. Ich habe {source} in den Papierkorb gelegt."
            return f"Ich konnte {source} nicht in den Papierkorb legen."
        if action == "copy":
            return copy_item(source, target, root_hint=root_hint, config=CONFIG)
        if action == "move":
            return move_item(source, target, root_hint=root_hint, config=CONFIG)
        if action == "move_matching":
            return move_items_matching(query, target, root_hint=root_hint, config=CONFIG)
        return "Diese Dateiaktion kenne ich noch nicht. Klingt aber sportlich."
    except FileAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Dateiaktion Fehler:", type(exc).__name__)
        return "Ich konnte die Dateiaktion nicht ausführen."


ACTION_ENGINE.register("file_action", execute_file_action)


def handle_photo_command(
    text: str,
    photo_worker: PhotoBackgroundWorker | None,
    memory: Memory | None = None,
) -> str | None:
    if not PHOTOS_ENABLED or photo_worker is None:
        return None

    normalized = normalize_text(text)
    wants_photo_index_stats = any(term in normalized for term in ("index statistik", "indexstatistik", "foto statistik", "fotostatistik"))
    if not has_domain(text, "photos") and not wants_photo_index_stats:
        return None

    if any(
        term in normalized
        for term in (
            "freigabe",
            "freige",
            "freigeben",
            "berechtigung",
            "erlaub",
            "zugriff erlauben",
            "fordere",
            "vordere",
            "folterer",
        )
    ):
        return photo_worker.request_permission()

    if any(
        term in normalized
        for term in (
            "analysiere meine fotos",
            "analysier meine fotos",
            "analysiere die fotos",
            "fotoanalyse",
            "openai vision",
            "mit openai analysieren",
            "bilder genauer analysieren",
            "fotos genauer analysieren",
        )
    ):
        return photo_worker.request_vision_analysis()

    if any(term in normalized for term in ("index statistik", "indexstatistik", "foto statistik", "fotostatistik", "datenbank", "db groesse", "db größe")):
        return photo_worker.index_statistics()

    if any(term in normalized for term in ("wie weit", "fortschritt", "progress", "stand")) and any(term in normalized for term in ("fotoindex", "foto index", "index")):
        return photo_worker.progress_answer()

    # "Wie viele Fotos hast du schon indiziert?" fragt nach dem GESAMT-Stand des
    # Index, nicht nach einem inhaltlichen Suchbegriff - live entdeckter Bug:
    # extract_photo_count_query() fand kein Praeposition-Muster (kein "von"/"mit"
    # o.ae.), liess die Restwoerter "hast du schon indiziert" als vermeintlichen
    # Suchbegriff stehen und lieferte eine nonsensische Antwort ("508 passende
    # Foto(s) fuer hast du schon indiziert"). Muss VOR extract_photo_count_query
    # abgefangen werden. Siehe docs/current-system-assessment.md, Abschnitt 41.
    # Erweiterung Runde-2-Simulation (2026-08-13): "Wie viele Fotos hast du
    # eigentlich mittlerweile durchsucht?" nutzt statt "indiziert" das
    # umgangssprachliche "durchsucht"/"gescannt" - fiel bisher durch und
    # landete in einer sinnlosen Bildersuche nach den Fragewoertern selbst.
    # Siehe docs/current-system-assessment.md, Abschnitt 42.
    if any(term in normalized for term in ("wie viele", "wieviele", "anzahl")) and any(
        term in normalized
        for term in (
            "indiziert", "im index", "fotoindex", "foto index",
            "durchsucht", "gescannt", "erfasst", "durchgesehen", "schon durch", "fertig mit",
        )
    ):
        return photo_worker.status()

    count_query = extract_photo_count_query(text)
    if count_query:
        return photo_worker.count_search(count_query)

    if any(term in normalized for term in ("zugriff", "status", "funktioniert", "index")):
        return photo_worker.status()

    if any(
        term in normalized
        for term in (
            "was siehst",
            "was sehe",
            "was ist auf",
            "was sind auf",
            "welche fotos",
            "welche bilder",
            "überblick",
            "ueberblick",
            "zusammenfassung",
            "zusammenfassen",
            "beschreib",
            "beschreibe",
        )
    ):
        return photo_worker.summary()

    if any(term in normalized for term in ("scann", "scan", "durchsuch", "durchsuchen", "hintergrund", "indexier")):
        return photo_worker.request_scan()

    wants_search = any(
        term in normalized
        for term in (
            "such",
            "suche",
            "finde",
            "zeig",
            "zeige",
            "raus",
            "heraus",
            "album",
            "iphone",
            "icloud",
            "ordner",
            "schreibtisch",
            "desktop",
        )
    )
    if not wants_search:
        fallback_query = remove_domain_words(text, "photos")
        if fallback_query:
            if memory is not None:
                file_permission = ensure_privacy_domain_permission(
                    memory,
                    "files",
                    "Jarvis würde passende Foto-Vorschauen in einen neuen Ordner auf Ihrem Schreibtisch exportieren.",
                )
                if file_permission is not None:
                    return file_permission
            try:
                return photo_worker.search_to_desktop_folder(fallback_query)
            except PhotosAccessError as exc:
                return str(exc)
            except Exception as exc:
                print("Fotos Fehler:", type(exc).__name__)
                return "Ich konnte Fotos nicht durchsuchen."
        return photo_worker.status()

    query = extract_photo_query(text)
    if not query:
        return "Wonach soll ich in Ihren Fotos suchen?"

    if memory is not None:
        file_permission = ensure_privacy_domain_permission(
            memory,
            "files",
            "Jarvis würde passende Foto-Vorschauen in einen neuen Ordner auf Ihrem Schreibtisch exportieren.",
        )
        if file_permission is not None:
            return file_permission

    try:
        return photo_worker.search_to_desktop_folder(query)
    except PhotosAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Fotos Fehler:", type(exc).__name__)
        return "Ich konnte Fotos nicht durchsuchen."


def handle_screen_command(text: str, memory: Memory | None = None) -> str | None:
    """Vision Engine (Phase F): ein einzelner Screenshot auf Zuruf, lokal per
    Ollama-Vision-Modell analysiert, danach sofort gelöscht - kein Dauer-Capture,
    kein Speichern des Bildes selbst. Nimmt nur das aktive Fenster auf (nicht den
    ganzen Bildschirm), damit andere offene Fenster nie mit erfasst werden - fällt
    nur zurück auf den ganzen Bildschirm, wenn das aktive Fenster technisch nicht
    ermittelt werden kann (siehe screen_client.capture_active_window_screenshot).

    Die Bildbeschreibung wird automatisch als Fakt vorgemerkt (status=
    "pending_confirmation", niedrigere confidence) - wie die LLM-Auto-Extraktion
    in extract_auto_memory_facts()/_run_llm_memory_extraction(): kein Zuruf wie
    "merk dir das" nötig, aber auch nicht sofort als bestätigt gesetzt, weil eine
    einzelne Bildbeschreibung ebenso fehlerhaft sein kann. Der Nutzer sieht und
    bestätigt/verwirft das Ergebnis in der Gedächtnis-Ansicht."""
    if not has_domain(text, "screen"):
        return None

    from local_vision_service import LocalVisionError, LocalVisionService
    from screen_client import ScreenAccessError, capture_active_window_screenshot, discard_screenshot

    service = LocalVisionService(CONFIG)
    status = service.status()
    if not status.available:
        return status.message

    try:
        screenshot_path, active_app = capture_active_window_screenshot()
    except ScreenAccessError as exc:
        return str(exc)

    try:
        result = service.describe_screen(screenshot_path)
    except LocalVisionError as exc:
        return f"Ich konnte den Screenshot nicht analysieren: {exc}"
    except Exception as exc:
        print("Bildschirm-Vision Fehler:", type(exc).__name__)
        return "Ich konnte den Screenshot gerade nicht analysieren."
    finally:
        discard_screenshot(screenshot_path)

    description = result.get("description") or ""
    # Der von System Events ermittelte App-Name ist zuverlässiger als die Vermutung
    # des Vision-Modells aus dem Bildinhalt - wird bevorzugt, wenn vorhanden.
    app = active_app or (result.get("app") or "")
    if not description:
        return "Ich habe das aktive Fenster aufgenommen, konnte aber nichts Eindeutiges erkennen."

    summary = f"In {app}: {description}" if app else f"Auf Ihrem Bildschirm: {description}"

    if memory is not None:
        fact_subject = f"{configured_user_name()} hatte {app + ' ' if app else ''}offen: {description}"
        content = normalize_memory_fact(fact_subject)
        if content:
            category, sensitivity = classify_memory_category(content)
            memory_system = JarvisMemorySystem(memory)
            memory_system.maybe_remember(
                content,
                category=category,
                source="auto-vision",
                confidence=0.6,
                sensitivity=sensitivity,
                status="pending_confirmation",
            )

    return summary


def handle_camera_command(text: str, llm: LLMClient) -> str | None:
    """Kamera-Feedback auf Zuruf (siehe
    plans/2026-08-11-jarvis-kamera-feedback.md): ein einzelnes Kamerabild,
    lokal per Ollama-Vision-Modell zu Erscheinungsbild/Outfit analysiert,
    danach IMMER geloescht (auch bei einem Analyse-Fehler, siehe finally) -
    anders als bei Screenshots wird hier bewusst NICHT automatisch etwas ins
    Gedaechtnis vorgemerkt, ein Kamerabild ist unmittelbarer/persoenlicher als
    ein Bildschirmfoto. Nur enge, mehrwortige Ausloese-Saetze (siehe
    DOMAIN_TERMS["camera"]), damit sich das nicht mit der Fotos-Domaene
    ueberschneidet. Die rohe Vision-Beschreibung wird ueber
    humanize_camera_feedback_via_llm() in eine persoenliche, direkt
    angesprochene Antwort umformuliert - live von Leon bemaengelt, dass die
    rohe dritte-Person-Bildbeschreibung ohne Anrede/Persoenlichkeit
    unveraendert durchkam."""
    if not has_domain(text, "camera"):
        return None

    from camera_client import CameraAccessError, CameraClient, discard_photo
    from local_vision_service import LocalVisionError, LocalVisionService

    vision_service = LocalVisionService(CONFIG)
    status = vision_service.status()
    if not status.available:
        return status.message

    camera = CameraClient()
    try:
        photo_path = camera.capture_photo()
    except CameraAccessError as exc:
        return str(exc)

    try:
        result = vision_service.describe_camera_photo(photo_path)
    except LocalVisionError as exc:
        return f"Ich konnte das Foto nicht analysieren: {exc}"
    except Exception as exc:
        print("Kamera-Vision Fehler:", type(exc).__name__)
        return "Ich konnte das Foto gerade nicht analysieren."
    finally:
        discard_photo(photo_path)

    description = result.get("description") or ""
    if not description:
        return "Ich habe ein Foto aufgenommen, konnte aber nichts Eindeutiges erkennen."
    return humanize_camera_feedback_via_llm(llm, description) or description


def is_execution_promise(text: str) -> bool:
    normalized = normalize_text(text)
    promise_terms = (
        "ich checke",
        "ich prüfe",
        "ich pruefe",
        "ich teste",
        "ich schaue",
        "ich sehe nach",
        "ich lese",
        "ich starte",
        "ich mache",
        "ich führe",
        "ich fuehre",
        "ich werte",
        "ich fasse",
        "ich melde mich",
        "ich gebe dir gleich",
        "ich kann das prüfen",
        "ich kann das pruefen",
        "soll ich den status",
        "soll ich kurz",
    )
    return any(term in normalized for term in promise_terms)


def execute_promised_action_if_possible(
    llm: LLMClient,
    question: str,
    answer: str,
) -> str | None:
    if not is_execution_promise(answer):
        return None

    context = f"{normalize_text(question)} {normalize_text(answer)}"
    mail_context = any(
        term in context
        for term in (
            "mail",
            "mails",
            "email",
            "emails",
            "apple mail",
            "icloud",
            "inbox",
            "posteingang",
            "postfach",
            "mailfach",
            "archiv",
        )
    )
    status_context = any(
        term in context
        for term in (
            "status",
            "check",
            "prüf",
            "pruef",
            "funktioniert",
            "verbindung",
            "kommt raus",
        )
    )

    if mail_context and status_context:
        return check_mail_status()

    if mail_context:
        if any(term in context for term in ("lösch", "loesch", "delete", "entfern", "verschieb", "move", "send", "sende")):
            planned = PlannedAction(action_type="send_email", summary="Mail-Aktion mit möglicher Änderung oder Versand")
            if requires_confirmation(planned.action_type):
                return confirmation_text(planned)
        mail_answer = handle_mail_command(llm, question, force=True)
        if mail_answer is not None:
            return mail_answer

    internet_context = any(
        term in context
        for term in (
            "internet",
            "online",
            "web",
            "netz",
            "verbindung",
        )
    )
    if internet_context and status_context:
        ok, detail = check_internet_access()
        if ok:
            return f"Internet funktioniert, {configured_user_name()}. Ich habe es gerade geprüft: {detail}"
        return f"Internet spinnt gerade, {configured_user_name()}: {detail}"

    return None


_MUSIC_PLAY_REQUEST_RE = re.compile(r"\b(?:spiel|spiele)\b.*\b(?:von|an)\b", re.IGNORECASE)


def handle_music_command(text: str) -> str | None:
    normalized = normalize_text(text)
    # "Spiel <Songtitel> von <Interpret>" enthaelt oft kein einziges Wort aus
    # DOMAIN_TERMS["music"] (Songtitel/Interpreten lassen sich nicht als feste
    # Stichwortliste pflegen) und fiel deshalb komplett aus has_domain() heraus -
    # landete im werkzeuglosen Chat, der frei erfand, die Wiedergabe laeuft schon.
    # Live beobachtet 2026-08-19: "Spiel Bohemian Rhapsody von Queen." ->
    # "Verstanden, Sir. 'Bohemian Rhapsody' läuft gerade." ohne dass Apple Music
    # je angesprochen wurde. Eng gefasst (braucht "spiel(e)" UND "von"/"an" im
    # selben Satz), um nicht mit "spielen" im Alltagssinn zu kollidieren.
    looks_like_play_request = bool(_MUSIC_PLAY_REQUEST_RE.search(normalized))
    if not has_domain(text, "music") and not looks_like_play_request:
        return None

    if not MUSIC_ENABLED:
        return "Apple-Music-Steuerung ist in der Konfiguration deaktiviert."

    try:
        # Reine Status-/Lese-Frage ("Was läuft gerade?", "Welche Musik läuft?")
        # wurde bisher gar nicht erkannt und fiel bis zum fallback_query-Zweig
        # durch, der sie faelschlich als Suchbegriff fuer play_search()
        # interpretierte - eine Frage loeste damit eine Wiedergabe-Aktion aus
        # statt beantwortet zu werden. Live beobachtet 2026-08-19: "Welche
        # Musik läuft gerade?" ergab "Ich habe den Titel ... nicht gefunden."
        # statt einer Statusantwort. now_playing() existierte bereits fuer die
        # Dashboard-Musik-Karte, war aber nie an den Chat-Pfad angebunden.
        if any(term in normalized for term in ("was läuft", "was laeuft", "welche musik läuft", "welche musik laeuft", "läuft gerade", "laeuft gerade", "aktueller titel", "aktuelle musik", "was wird gerade gespielt", "was spielt gerade")):
            track = now_playing()
            if not track:
                return "Gerade läuft keine Musik."
            artist_part = f" von {track['artist']}" if track.get("artist") else ""
            state = "läuft gerade" if track.get("is_playing") else "ist gerade pausiert"
            return f"{track['title']}{artist_part} {state}."

        if "playlist" in normalized and any(term in normalized for term in ("welche", "liste", "auflisten", "zeig", "zeige")):
            playlists = list_playlists()
            if not playlists:
                return "Ich kann Apple Music öffnen, sehe aber gerade keine Playlists."

            visible = ", ".join(playlists[:8])
            return f"Ich sehe diese Apple-Music-Playlists: {visible}."

        if any(
            term in normalized
            for term in (
                "pause", "pausier", "pausiere", "stopp die musik", "stoppe die musik",
                "musik aus", "musik anhalten", "musik stoppen", "halt die musik an",
            )
        ):
            return pause_music()

        # Bloss "weiter" als Teilstring matchte faelschlich auch auf "weitere",
        # "weiterhin", "weitermachen" usw. (z.B. in einer ganz anderen Antwort
        # ueber "die restlichen Schritte ... weitermachen"). Live beobachtet
        # 2026-08-20 im Mehrfach-Audit.
        if re.search(r"\bweiter\b", normalized) or any(
            term in normalized for term in ("fortsetzen", "spiel weiter", "wiedergabe starten")
        ):
            return play_music()

        if any(term in normalized for term in ("lauter", "leiser")):
            return adjust_volume(louder="lauter" in normalized)

        if any(term in normalized for term in ("nächster", "naechster", "nächste", "naechste", "skip", "überspring", "ueberspring")):
            return next_track()

        if any(term in normalized for term in ("vorheriger", "vorherige", "zurück", "zurueck", "letzter titel")):
            return previous_track()

        playlist_match = re.search(
            r"\b(?:spiel|spiele|starte|öffne|oeffne)\b\s+(?:bitte\s+)?(?:meine\s+|die\s+)?playlist\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if not playlist_match:
            playlist_match = re.search(
                r"playlist\s+(.+?)\s+(?:abspielen|spielen|starten|öffnen|oeffnen)?$",
                normalized,
                flags=re.IGNORECASE,
            )
        if playlist_match:
            playlist_name = _clean_music_query(playlist_match.group(1))
            if playlist_name:
                return play_playlist(playlist_name)

        song_match = re.search(
            r"\b(?:spiel|spiele|starte|öffne|oeffne)\b\s+(?:das\s+)?(?:lied|song|titel)?\s*(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if song_match:
            query = _clean_music_query(song_match.group(1))
            if query and query not in {"musik", "music", "apple music"}:
                return play_search(query)

        fallback_query = _clean_music_query(remove_domain_words(text, "music"))
        if fallback_query and fallback_query not in {"musik", "music", "apple music", "lied", "song", "titel"}:
            return play_search(fallback_query)

        if any(term in normalized for term in ("spiel", "spiele", "starte", "öffne apple music", "oeffne apple music", "mach musik", "musik an")):
            return play_music()

    except MusicAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Apple-Music Fehler:", type(exc).__name__)
        return "Ich konnte Apple Music nicht steuern."

    return None


def _clean_music_query(query: str) -> str:
    query = query.strip(" .,!?:;")
    query = re.sub(r"\b(?:in|auf)\s+apple\s+music\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\b(?:bitte|mal|für mich|fuer mich)\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\b(?:starten|starte|start|spielen|spiele|abspielen|läuft|lauft)\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query)
    return query.strip(" .,!?:;")


def speak(text: str, voice: str | None = None):
    print("Jarvis spricht...")
    tts_started = time.perf_counter()
    VOICE_OUTPUT.speak(text, voice=voice)
    if PERFORMANCE_LOG:
        print(f"Zeit: TTS-Start={time.perf_counter() - tts_started:.2f}s")


def stop_speaking():
    VOICE_OUTPUT.stop()


def wait_until_done_speaking():
    VOICE_OUTPUT.wait()




def run_set_openai_key() -> int:
    try:
        message = prompt_and_store_openai_key()
        removed = remove_openai_key_from_env_file(data_root())
        print(message)
        if removed:
            print("Klartext-Eintrag aus .env entfernt.")
        return 0
    except SecureStorageError as exc:
        print(f"OpenAI API-Key konnte nicht gespeichert werden: {type(exc).__name__}")
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen. Kein API-Key gespeichert.")
        return 1


def run_delete_openai_key() -> int:
    try:
        deleted = delete_openai_api_key()
        print("OpenAI API-Key aus der macOS Keychain gelöscht." if deleted else "Kein OpenAI API-Key in der macOS Keychain gefunden.")
        return 0
    except SecureStorageError as exc:
        print(f"OpenAI API-Key konnte nicht gelöscht werden: {type(exc).__name__}")
        return 1


def run_check_secure_storage() -> int:
    result = check_secure_storage()
    print("Secure Storage Check")
    print(f"Service: {result.get('service')}")
    print(f"Keychain-Test: {'OK' if result.get('write_read_delete_ok') else 'FEHLER'}")
    print(f"OpenAI-Key vorhanden: {'ja' if result.get('openai_key_present') else 'nein'}")
    locations = result.get("plaintext_locations") or []
    if locations:
        print("Klartext-Fundstellen: " + ", ".join(locations))
    else:
        print("Klartext-Fundstellen: keine")
    if result.get("error"):
        print(f"Technischer Fehler: {result.get('error')}")
    return 0 if result.get("write_read_delete_ok") and not locations else 1


def run_privacy_test() -> int:
    print("Jarvis Privacy-Test startet...")
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = ""):
        status = "OK" if condition else "FEHLER"
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
        if not condition:
            failures.append(name if not detail else f"{name}: {detail}")

    try:
        for path in sorted((data_root() / "memory").glob("*.json")) + sorted(data_root().glob("*.json")):
            json.loads(path.read_text(encoding="utf-8"))
        check("JSON-Dateien gültig", True)
    except Exception as exc:
        check("JSON-Dateien gültig", False, type(exc).__name__)

    try:
        root = data_root()
        config_text = (root / "config.json").read_text(encoding="utf-8", errors="ignore")
        env_text = (root / ".env").read_text(encoding="utf-8", errors="ignore") if (root / ".env").exists() else ""
        no_config_key = "openai_api_key" not in config_text.lower() and "api_key" not in config_text.lower() and "sk-" not in config_text
        no_env_key = "OPENAI_API_KEY=" not in env_text and "sk-" not in env_text
        check("Kein API-Key in config.json", no_config_key)
        check("Kein API-Key in .env", no_env_key)
    except Exception as exc:
        check("Kein Klartext-API-Key", False, type(exc).__name__)

    try:
        secure_result = check_secure_storage()
        check("Keychain-Zugriff funktioniert", bool(secure_result.get("write_read_delete_ok")), str(secure_result.get("error") or ""))
        check("Keine Klartext-Secret-Fundstellen", not secure_result.get("plaintext_locations"), ", ".join(secure_result.get("plaintext_locations") or []))
    except Exception as exc:
        check("Keychain-Zugriff funktioniert", False, type(exc).__name__)

    try:
        import importlib
        module_names = [
            "permission_manager",
            "privacy_dashboard",
            "privacy_logger",
            "action_confirmation",
            "secure_storage",
            "audio_stream",
            "stt_engines",
            "llm_client",
            "mail_client",
            "calendar_client",
            "contacts_client",
            "files_client",
            "desktop_client",
            "photos_client",
        ]
        for module_name in module_names:
            importlib.import_module(module_name)
        check("Module importierbar", True)
    except Exception as exc:
        check("Module importierbar", False, f"{type(exc).__name__}: {exc}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        try:
            manager = ModelManager(CONFIG, base)
            model_status = manager.status()
            check("OpenAI standardmäßig deaktiviert", manager.provider == "ollama" and not model_status.openai_enabled)
            check("Ollama installiert", model_status.ollama_installed, "Installiere Ollama von ollama.com" if not model_status.ollama_installed else "")
            check("Ollama erreichbar", model_status.ollama_running, "Starte Ollama mit: ollama serve" if not model_status.ollama_running else "")
            installed = set(model_status.installed_models)
            check("phi4-mini vorhanden", "phi4-mini" in installed, "ollama pull phi4-mini" if "phi4-mini" not in installed else "")
            check("gemma3:4b vorhanden", "gemma3:4b" in installed, "ollama pull gemma3:4b" if "gemma3:4b" not in installed else "")
            check("qwen3:4b vorhanden", "qwen3:4b" in installed, "ollama pull qwen3:4b" if "qwen3:4b" not in installed else "")
            manager.use_local_model("gemma")
            gemma_ok = manager.active_model == "gemma3:4b" and manager.provider == "ollama"
            manager.use_local_model("qwen")
            qwen_ok = manager.active_model == "qwen3:4b" and manager.provider == "ollama"
            manager.use_standard_model()
            standard_ok = manager.active_model == "phi4-mini" and manager.provider == "ollama"
            check("Modellwechsel funktioniert", gemma_ok and qwen_ok and standard_ok)
        except Exception as exc:
            check("Modellverwaltung", False, type(exc).__name__)

        try:
            pm = PermissionManager(base)
            check("Permissions initial blockiert", not any(pm.is_allowed(name) for name in pm.export()))
            pm.grant("mail")
            check("Permission schreiben/lesen", PermissionManager(base).is_allowed("mail"))
            pm.revoke("mail")
            check("Permission deaktivieren", not PermissionManager(base).is_allowed("mail"))
        except Exception as exc:
            check("Permissions lesbar/schreibbar", False, type(exc).__name__)

        try:
            logger = PrivacyLogger(base / "logs")
            logger.log(
                "privacy-test",
                "redaction",
                prompt="Mein geheimer Prompt",
                transcript="Hallo Jarvis",
                api_key="test-secret-token",
                calendar_title="Arzttermin",
                harmless="ok",
            )
            log_text = (base / "logs" / "technical.log").read_text(encoding="utf-8")
            sensitive_absent = all(secret not in log_text for secret in ("Mein geheimer Prompt", "Hallo Jarvis", "test-secret-token", "Arzttermin"))
            redacted_present = "[redacted]" in log_text and "ok" in log_text
            check("Logs redigiert", sensitive_absent and redacted_present)
        except Exception as exc:
            check("Logs redigiert", False, type(exc).__name__)

        try:
            test_memory = Memory(base)

            class TestPermissionManager(PermissionManager):
                def __init__(self, base_path: Path | None = None):
                    super().__init__(base)

            original_pm = globals()["PermissionManager"]
            globals()["PermissionManager"] = TestPermissionManager
            try:
                blocked_mail = ensure_permission(test_memory, "mail", "Test Mail lesen")
                settings_after_mail = test_memory.get("settings") or {}
                settings_after_mail.pop("pending_permission", None)
                test_memory.set("settings", settings_after_mail)
                blocked_files = ensure_permission(test_memory, "files", "Test Datei ändern")
                settings = test_memory.get("settings") or {}
                check("Kritische Aktionen ohne Zustimmung blockiert", bool(blocked_mail) and bool(blocked_files) and isinstance(settings.get("pending_permission"), dict))
            finally:
                globals()["PermissionManager"] = original_pm
        except Exception as exc:
            check("Kritische Aktionen ohne Zustimmung blockiert", False, type(exc).__name__)

        try:
            dashboard = PrivacyDashboard(CONFIG, base)
            export_path = Path(dashboard.export_data())
            check("Datenschutzdaten exportierbar", export_path.exists() and export_path.name.startswith("jarvis_privacy_export_"))
            (base / "conversation.json").write_text(json.dumps([{"role": "user", "content": "secret"}]), encoding="utf-8")
            dashboard.delete_history()
            history = json.loads((base / "conversation.json").read_text(encoding="utf-8"))
            check("Verlauf löschbar", history == [])
            logger = PrivacyLogger(base / "logs")
            logger.log("privacy-test", "clear", harmless="ok")
            dashboard.clear_logs()
            check("Logs löschbar", not any((base / "logs").glob("*.log")))
        except Exception as exc:
            check("Export/Löschung", False, type(exc).__name__)

    if failures:
        print("Privacy-Test abgeschlossen: FEHLER")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Privacy-Test abgeschlossen: OK")
    return 0


@dataclass
class AnswerWorkers:
    """Mutable Container fuer die beiden Hintergrund-Worker, die waehrend
    answer_message() bei Bedarf lazy erzeugt werden (siehe photo_worker/mail_worker
    unten) - main() und local_server.py::_answer_with_core() halten je eine Instanz
    davon ueber die gesamte Laufzeit, damit ein einmal erzeugter Worker wiederverwendet
    statt bei jeder Anfrage neu gestartet wird."""

    photo_worker: Any = None
    mail_worker: Any = None
    model_manager: Any = None


@dataclass
class AnswerResult:
    text: str
    pending_mail_followup: bool
    provider: str
    model: str


def _routing_history(memory: Memory, config: dict[str, Any], transient_history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """History, die NUR fuer die Routing-Entscheidung (llm.plan(), kompaktes Prompt
    ja/nein, force_local) genutzt wird - nicht zu verwechseln mit dem eigentlichen
    Gespraechs-Kontext, den build_input() unabhaengig davon selbst aus dem Gedaechtnis
    zusammenstellt. Der Server bekommt seine transient_history vom Client (der
    Swift-App) mitgeliefert; die CLI hat keinen separaten Client und griff bisher
    fuer genau diese Routing-Entscheidung faelschlich auf eine leere Liste zurueck,
    obwohl dieselbe persistierte Historie wie in build_input() zur Verfuegung steht -
    siehe plans/2026-08-09-jarvis-cli-server-aufraeumen.md, offene Frage 1 (behoben:
    CLI nutzt jetzt dieselbe Quelle)."""
    if transient_history is not None:
        return transient_history
    if not bool(config.get("privacy_store_conversation", False)):
        return []
    try:
        return ConversationManager().as_messages(recent_limit=RECENT_CONTEXT_MESSAGES)
    except Exception:
        return []


def answer_message(
    question: str,
    memory: Memory,
    llm: LLMClient,
    config: dict[str, Any],
    *,
    workers: AnswerWorkers,
    pending_mail_followup: bool = False,
    transient_history: list[dict[str, str]] | None = None,
    on_llm_chunk: Callable[[str], None] | None = None,
) -> AnswerResult:
    """Gemeinsame Antwort-Logik fuer beide Aufrufer (main()'s CLI-Schleife und
    local_server.py::_answer_with_core(), das die App nutzt) - siehe
    plans/2026-08-09-jarvis-cli-server-aufraeumen.md. Besitzt die komplette
    Domaenen-Erkennungs-Kette (Stufe 1 Stichworte, Stufe 2 Modell-Klassifikation,
    Websuche, finaler LLM-Aufruf); jeder Aufrufer bleibt nur noch fuer eigene I/O
    zustaendig (CLI: print/speak/record_exchange; Server: HTTP-Response/Streaming/
    _finalize_answer) sowie fuer aufrufer-spezifische Vorab-Kurzbefehle (CLI:
    route_fast_intent; Server: Dashboard-Statusfragen), die bewusst
    NICHT Teil dieser Funktion sind, weil sie nur fuer den jeweiligen Aufrufer Sinn
    ergeben. `config` wird explizit uebergeben statt das Modul-globale CONFIG zu
    nutzen, weil local_server.py sein eigenes, unabhaengig geladenes Config-Dict
    zur Laufzeit mutiert (z.B. fast_voice_mode) - ein globaler Zugriff wuerde genau
    das Dual-Instance-Cache-Problem reproduzieren, das diese Sitzung mehrfach an
    anderer Stelle behoben hat."""
    voice_mode = normalize_voice_mode(str((memory.get("settings") or {}).get("voice_mode") or ""))
    force_local = voice_mode_forces_local_only(voice_mode)
    routing_history = _routing_history(memory, config, transient_history)
    route = llm.plan(routing_history, user_text=question, force_local=force_local)

    def _result(text: Any, mail_followup: bool = pending_mail_followup) -> AnswerResult:
        # Zentraler, einziger Ausgangspunkt fuer JEDE Antwort aus dieser Funktion
        # (Mail, Kalender, Notizen, Dateien, Kamera, Bildschirm, Pending-Flows,
        # allgemeiner Chat, ...) - strip_first_name_address() hier statt in jedem
        # einzelnen Handler anzuwenden schliesst den Vorname-Leak systemisch:
        # mehrere fest formulierte Antworten (handle_project_command,
        # handle_local_command, handle_system_command) nutzten Leons Vornamen
        # bisher direkt und ungefiltert, weil sie NICHT durch den finalen
        # allgemeinen Chat-Pfad liefen, wo die Bereinigung vorher nur passierte.
        # Aufruf hier ist idempotent - Handler, die bereits selbst bereinigen
        # (Kamera-Feedback, Mail-Zusammenfassung), aendern sich dadurch nicht.
        # Siehe docs/current-system-assessment.md, Abschnitt 41.
        # strip_invented_formal_address() greift hier aus demselben Grund zentral:
        # erfundene Anreden wie "Herr Müller" (das kleine Modell dichtet sich einen
        # Nachnamen dazu) sollen aus JEDEM Antwortpfad verschwinden, nicht nur aus
        # dem allgemeinen Chat.
        cleaned_text = strip_invented_formal_address(
            strip_first_name_address(str(text), configured_user_name()),
            configured_user_address(),
        )
        return AnswerResult(text=cleaned_text, pending_mail_followup=mail_followup, provider=route.provider, model=route.model)

    if is_end_command(question):
        return _result("Alles klar. Ich bin wieder still, bis Sie Jarvis sagen.")

    # Tagesbriefing bewusst VOR der direct_handlers-Kette (wie main() das vor
    # der Zusammenfuehrung bereits als eigenen Vorab-Check tat) statt als
    # regulaerer Domaenen-Handler weiter unten - Briefings sollen auch dann
    # sofort greifen, wenn zufaellig eine pending_note/pending_action-Anfrage
    # offen ist. Bisher lief dieser Check nur in main() (CLI), NICHT im
    # Server-/App-Pfad - deshalb erfand die App bei "Morgen Briefing" frei
    # Inhalte, statt echte Kalender-/Aufgaben-/Mail-Daten zu nutzen.
    briefing_answer = handle_daily_briefing_command(memory, question)
    if briefing_answer is not None:
        return _result(briefing_answer)

    # Eine offene Kalender-Vorschlags-Bestaetigung (siehe
    # pending_mail_calendar_confirmation weiter unten in handle_pending_action_flow)
    # braucht einen MailBackgroundWorker, auch wenn die Antwort selbst kein
    # "mail"-Domaenen-Wort enthaelt (z.B. "das bestaetige ich nicht") - die
    # normale Lazy-Init weiter unten (has_domain(question, "mail")) greift hier
    # zu spaet, da handle_pending_action_flow bereits vorher in direct_handlers
    # laeuft. Siehe plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.
    if (
        workers.mail_worker is None
        and isinstance((memory.get("settings") or {}).get("pending_mail_calendar_confirmation"), dict)
        and has_permission("mail")
    ):
        workers.mail_worker = MailBackgroundWorker(config, llm)
        workers.mail_worker.start()

    # record_mode steuert bewusst pro Handler, ob/wie record_exchange() aufgerufen
    # wird - das ist die einzige Stelle, an der main() und _answer_with_core() vor
    # der Zusammenfuehrung tatsaechlich unterschiedlich handelten (main() liess
    # System-/Praeferenz-/Stil-/Projekt-/Lokal-/Datenschutz-Antworten bewusst
    # ungespeichert, waehrend der Server sie ueber _finalize_answer immer speicherte).
    # Uebernommen wurde main()s bewusstere, zurueckhaltendere Variante - siehe
    # plans/2026-08-09-jarvis-cli-server-aufraeumen.md.
    direct_handlers: list[tuple[str, tuple, dict, str]] = [
        ("handle_system_command", (question,), {}, "none"),
        ("handle_preference_command", (memory, question), {}, "none"),
        ("handle_style_command", (memory, question), {}, "none"),
        ("handle_personality_command", (memory, question), {}, "none"),
        ("handle_self_preference_command", (memory, question), {}, "none"),
        ("handle_project_command", (question,), {}, "none"),
        ("handle_local_command", (question,), {}, "none"),
        ("handle_privacy_command", (memory, question), {}, "none"),
        ("handle_model_command", (question,), {"memory": memory, "model_manager": workers.model_manager}, "no_auto_memory"),
        ("handle_memory_command", (memory, question), {}, "no_auto_memory"),
        ("handle_pending_note_flow", (memory, question), {}, "normal"),
        ("handle_pending_domain_clarification_flow", (memory, question), {"photo_worker": workers.photo_worker}, "normal"),
        ("handle_pending_action_flow", (memory, question), {"photo_worker": workers.photo_worker, "mail_worker": workers.mail_worker}, "normal"),
    ]
    if has_pending_action(memory):
        pending_action_handler = direct_handlers.pop()
        local_command_index = next(i for i, entry in enumerate(direct_handlers) if entry[0] == "handle_local_command")
        direct_handlers.insert(local_command_index, pending_action_handler)

    module = sys.modules[__name__]
    for name, args, kwargs, record_mode in direct_handlers:
        handler = getattr(module, name)
        declined_mail_permission = False
        if name == "handle_pending_action_flow":
            settings_before = memory.get("settings") or {}
            pending_permission_before = settings_before.get("pending_permission")
            declined_mail_permission = (
                isinstance(pending_permission_before, dict)
                and pending_permission_before.get("permission") == "mail"
            )
        answer = handler(*args, **kwargs)
        if answer is not None:
            mail_followup = pending_mail_followup
            if declined_mail_permission and not has_permission("mail"):
                mail_followup = False
            if record_mode == "normal":
                record_exchange(memory, question, answer)
            elif record_mode == "no_auto_memory":
                record_exchange(memory, question, answer, auto_memory=False)
            return _result(answer, mail_followup)

    # Baustein E (mehrstufige Auftraege, siehe
    # plans/2026-08-09-jarvis-mehrstufige-auftraege.md) - bewusst als eigene Stufe VOR
    # der normalen Einzelschritt-Domaenenerkennung, aber nur aktiv, wenn schon die
    # Stichwort-Erkennung mind. zwei Domaenen im selben Satz sieht
    # (looks_like_multistep_request). Findet der Planer keinen gueltigen Plan (None),
    # faellt die Anfrage unveraendert in den bestehenden Einzelschritt-Weg unten durch
    # - nie raten.
    if looks_like_multistep_request(question):
        steps = plan_multistep(
            llm,
            question,
            max_steps=int(config.get("multistep_planner_max_steps", 4)),
            max_output_tokens=int(config.get("multistep_planner_max_output_tokens", 300)),
        )
        if steps:
            answer = execute_multistep_plan(steps, memory, photo_worker=workers.photo_worker)
            record_exchange(memory, question, answer)
            return _result(answer)

    # Baustein D (Verhaltensmuster erkennen, siehe
    # plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md) - zaehlt NUR welche
    # Faehigkeit erkannt wurde und wann (Wochentag/grobe Tageszeit), NIE den
    # Anfrage-Wortlaut. Nur aktiv, wenn die eigene, standardmaessig deaktivierte
    # Berechtigung "usage_patterns" erteilt ist.
    if has_permission("usage_patterns"):
        record_pattern_event_if_matched(question)

    notes_permission = ensure_privacy_domain_permission(memory, "notes", "Jarvis würde eine Notiz über Apple Notes erstellen oder ändern.") if has_domain(question, "notes") else None
    if notes_permission is not None:
        return _result(notes_permission)
    notes_answer = handle_notes_command(memory, question)
    if notes_answer is not None:
        record_exchange(memory, question, notes_answer)
        return _result(notes_answer)

    # Aufgaben (task_manager.py) liegen rein in Jarvis' eigenem Speicher, keine
    # macOS-Berechtigung noetig - anders als Notizen/Kalender/Mail also kein
    # ensure_privacy_domain_permission()-Gate davor.
    tasks_answer = handle_tasks_command(memory, question)
    if tasks_answer is not None:
        record_exchange(memory, question, tasks_answer)
        return _result(tasks_answer)

    calendar_permission = None
    if has_domain(question, "calendar") or looks_like_calendar_query(question):
        calendar_permission = ensure_privacy_domain_permission(memory, "calendar", "Jarvis würde Kalenderdaten verwenden.")
        if calendar_permission is None and "erinner" in normalize_text(question):
            calendar_permission = ensure_privacy_domain_permission(memory, "reminders", "Jarvis würde eine Erinnerung verwenden.")
    if calendar_permission is not None:
        return _result(calendar_permission)
    calendar_answer = handle_calendar_command(question, memory=memory)
    if calendar_answer is not None:
        record_exchange(memory, question, calendar_answer)
        return _result(calendar_answer)

    normalized_question = normalize_text(question)
    file_permission = ensure_privacy_domain_permission(memory, "files", "Jarvis würde Ihren Schreibtisch oder Dateien lokal lesen oder ändern.") if has_domain(question, "files") or "desktop" in normalized_question or "schreibtisch" in normalized_question else None
    if file_permission is not None:
        return _result(file_permission)
    for file_handler in (handle_desktop_command, handle_file_command):
        answer = file_handler(question, memory=memory)
        if answer is not None:
            record_exchange(memory, question, answer)
            return _result(answer, mail_followup=False)

    photo_permission = ensure_privacy_domain_permission(memory, "photos", "Jarvis würde Ihre Fotos-App oder den lokalen Fotoindex verwenden.") if has_domain(question, "photos") else None
    if photo_permission is None and has_domain(question, "photos") and any(term in normalized_question for term in ("openai", "vision", "analysiere", "analysieren", "was siehst")):
        photo_permission = ensure_cloud_llm_permission(memory, question)
    if photo_permission is not None:
        return _result(photo_permission)
    if workers.photo_worker is None and has_domain(question, "photos") and has_permission("photos"):
        workers.photo_worker = PhotoBackgroundWorker(config)
        workers.photo_worker.start()
    photo_answer = handle_photo_command(question, workers.photo_worker, memory=memory)
    if photo_answer is not None:
        record_exchange(memory, question, photo_answer)
        return _result(photo_answer, mail_followup=False)

    screen_permission = ensure_privacy_domain_permission(memory, "screen", "Jarvis würde einen einzelnen Screenshot deines aktiven Fensters aufnehmen und lokal analysieren.") if has_domain(question, "screen") else None
    if screen_permission is not None:
        return _result(screen_permission)
    screen_answer = handle_screen_command(question, memory=memory) if has_permission("screen") else None
    if screen_answer is not None:
        record_exchange(memory, question, screen_answer)
        return _result(screen_answer, mail_followup=False)

    camera_permission = ensure_privacy_domain_permission(memory, "camera", "Jarvis würde ein einzelnes Kamerabild aufnehmen, lokal analysieren und danach sofort löschen.") if has_domain(question, "camera") else None
    if camera_permission is not None:
        return _result(camera_permission)
    camera_answer = handle_camera_command(question, llm) if has_permission("camera") else None
    if camera_answer is not None:
        record_exchange(memory, question, camera_answer)
        return _result(camera_answer, mail_followup=False)

    mail_export_permission = ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Mail-Übersichten lesen und passende Anhänge oder Notizen auf den Schreibtisch kopieren.") if has_domain(question, "mail") else None
    if mail_export_permission is not None:
        return _result(mail_export_permission)
    mail_document_export_answer = handle_mail_document_export_command(question, memory=memory)
    if mail_document_export_answer is not None:
        record_exchange(memory, question, mail_document_export_answer)
        return _result(mail_document_export_answer, mail_followup=False)

    if workers.mail_worker is None and has_domain(question, "mail") and has_permission("mail"):
        workers.mail_worker = MailBackgroundWorker(config, llm)
        workers.mail_worker.start()
    background_mail_answer = handle_background_mail_command(question, workers.mail_worker)
    if background_mail_answer is not None:
        record_exchange(memory, question, background_mail_answer)
        return _result(background_mail_answer, mail_followup=True)

    mail_followup_intent = pending_mail_followup and (
        is_mail_time_followup(question) or is_mail_status_followup(question)
    )
    mail_permission = ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Apple Mail lokal lesen oder bearbeiten.") if has_domain(question, "mail") or mail_followup_intent else None
    if mail_permission is not None:
        return _result(mail_permission)
    mail_settings_before = memory.get("settings") or {}
    had_pending_mail_delete = isinstance(mail_settings_before.get("pending_mail_delete"), dict)
    mail_answer = handle_mail_command(llm, question, force=mail_followup_intent, memory=memory)
    if mail_answer is not None:
        record_exchange(memory, question, mail_answer)
        return _result(mail_answer, mail_followup=False if had_pending_mail_delete else True)

    contact_permission = ensure_privacy_domain_permission(memory, "contacts", "Jarvis würde Kontakte lesen oder einen Anruf vorbereiten.") if has_domain(question, "contacts") else None
    if contact_permission is not None:
        return _result(contact_permission)
    contact_answer = handle_contact_command(question, memory=memory)
    if contact_answer is not None:
        record_exchange(memory, question, contact_answer)
        return _result(contact_answer, mail_followup=False)

    music_permission = ensure_privacy_domain_permission(memory, "music", "Jarvis würde Apple Music oder die Musik-Wiedergabe steuern.") if has_domain(question, "music") else None
    if music_permission is not None:
        return _result(music_permission)
    music_answer = handle_music_command(question)
    if music_answer is not None:
        record_exchange(memory, question, music_answer)
        return _result(music_answer, mail_followup=False)

    # Stufe 2 der Absichtserkennung (siehe plans/2026-08-08-jarvis-intelligenz-
    # verbessern.md, erweitert um plans/2026-08-16-jarvis-stufe2-klassifikation-
    # direkt-beantworten.md): keiner der obigen Stichwort-Treffer (auch nicht
    # fuzzy) hat gegriffen. Findet die Modell-Klassifikation GENAU EINE plausible
    # Faehigkeit, antwortet Jarvis jetzt direkt darueber (statt nur nachzufragen),
    # sofern der zustaendige Handler daraus etwas Konkretes machen kann - sonst,
    # und bei zwei plausiblen Faehigkeiten (echte Mehrdeutigkeit), weiterhin eine
    # Rueckfrage. Findet die Klassifikation gar nichts, faellt der Code normal
    # weiter in den Chat-Zweig unten.
    domain_clarification = maybe_ask_domain_clarification(
        llm, memory, question, photo_worker=workers.photo_worker, config=config
    )
    if domain_clarification is not None:
        record_exchange(memory, question, domain_clarification)
        return _result(domain_clarification)

    web_context = None
    if (
        bool(config.get("web_search_enabled", True))
        and not voice_mode_disables_web_search(voice_mode)
        and should_use_web_search(question)
    ):
        internet_permission = ensure_privacy_domain_permission(memory, "internet", "Jarvis würde eine Websuche im Internet ausführen.")
        if internet_permission is not None:
            return _result(internet_permission)
        try:
            search_query = build_search_query(question)
            results = search_web(search_query, max_results=int(config.get("web_search_max_results", 3)))
            if results:
                web_context = format_search_results(results)
        except Exception:
            web_context = None

    llm_permission = ensure_cloud_llm_permission(memory, question)
    if llm_permission is not None:
        return _result(llm_permission)

    try:
        messages = build_input(memory, question, web_context, transient_history=transient_history, compact=route.compact_prompt)
    except TypeError:
        messages = build_input(memory, question, web_context)
    messages = normalize_jarvis_messages(
        messages,
        recent_limit=min(int(config.get("recent_context_messages", 6)) + 1, 7),
    )

    if callable(on_llm_chunk):
        answer = llm.ask_stream(
            messages,
            max_output_tokens=route.max_output_tokens,
            user_text=question,
            route=route,
            on_chunk=on_llm_chunk,
            force_local=force_local,
        )
    else:
        answer = llm.ask(messages, max_output_tokens=route.max_output_tokens, user_text=question, route=route, force_local=force_local)
    answer = clean_ai_answer(answer)
    if not wants_first_name_permission(question):
        answer = strip_first_name_address(answer, configured_user_name())
    promised = execute_promised_action_if_possible(llm, question, answer)
    if promised is not None:
        answer = promised
    record_exchange(memory, question, answer)
    return _result(answer, mail_followup="mail" in normalize_text(question))


def main():
    llm = LLMClient(CONFIG)
    memory = Memory()
    permission_manager = PermissionManager()

    print("Hinweis: Jarvis ist ein KI-System. Sie interagieren mit automatisierter KI-Unterstützung; wichtige Aktionen werden erst nach Ihrer Bestätigung ausgeführt.")
    if permissions_required() and not permission_manager.is_allowed("microphone"):
        print("Jarvis braucht Mikrofonzugriff, um Ihre Sprachbefehle zu erkennen.")
        consent = input("Mikrofon für Jarvis erlauben? Tippe ja oder nein: ").strip().lower()
        if consent in {"ja", "j", "yes", "y"}:
            permission_manager.grant("microphone")
            privacy_log("permission", "granted", permission="microphone")
        else:
            print("Ohne Mikrofonfreigabe startet Jarvis nicht.")
            return

    workers = AnswerWorkers(
        mail_worker=MailBackgroundWorker(CONFIG, llm) if has_permission("mail") else None,
        photo_worker=PhotoBackgroundWorker(CONFIG) if has_permission("photos") else None,
    )
    if workers.mail_worker is not None:
        workers.mail_worker.start()
    if workers.photo_worker is not None:
        workers.photo_worker.start()
    try:
        stt_engine = create_stt_engine(CONFIG)
    except STTEngineError as exc:
        if workers.mail_worker is not None:
            workers.mail_worker.stop()
        if workers.photo_worker is not None:
            workers.photo_worker.stop()
        print(f"STT konnte nicht gestartet werden: {type(exc).__name__}")
        print("Installiere Moonshine mit: .venv/bin/python -m pip install moonshine-onnx")
        return
    settings = memory.get("settings") or {}
    voice = os.getenv("JARVIS_VOICE", CONFIG.get("voice", settings.get("voice")))
    conversation_active = False
    pending_mail_followup = False
    listener = StreamingAudioListener(
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        input_device=get_input_device(),
        chunk_seconds=CHUNK_SECONDS,
        silence_limit=SILENCE_LIMIT,
        volume_threshold=VOLUME_THRESHOLD,
        min_speech_seconds=MIN_SPEECH_SECONDS,
        min_audio_peak=MIN_AUDIO_PEAK,
        max_recording_seconds=min(MAX_RECORDING_SECONDS, int(CONFIG.get("voice_listen_max_seconds", 10))),
        is_speaking=lambda: VOICE_OUTPUT.is_speaking,
    )

    print(f"JARVIS gestartet. Version: {JARVIS_VERSION}")
    print(f"Datei: {Path(__file__).resolve()}")
    print(
        "Audio-Konfig: "
        f"chunk_seconds={CHUNK_SECONDS} | "
        f"silence_limit={SILENCE_LIMIT} | "
        f"volume_threshold={VOLUME_THRESHOLD} | "
        f"min_audio_peak={MIN_AUDIO_PEAK} | "
        f"gain={AUDIO_GAIN_TARGET}"
    )
    print(f"STT Engine: {stt_engine.name}")
    print(f"KI-Anbieter: {ModelManager(CONFIG).provider}")

    while True:
        wait_until_done_speaking()

        try:
            transcribe_started = time.perf_counter()
            if hasattr(stt_engine, "listen_and_transcribe"):
                spoken_text, audio_stats = stt_engine.listen_and_transcribe()
            else:
                utterance = listener.listen_for_utterance()
                if utterance is None:
                    print("Keine Sprache erkannt.")
                    continue

                audio = prepare_audio_for_stt(utterance.audio)
                audio_stats = utterance.stats
                spoken_text = stt_engine.transcribe(audio)

            transcribe_seconds = time.perf_counter() - transcribe_started
            print(f"Transkript: {console_text(spoken_text, 'transcript')}")

            if not spoken_text:
                continue

            pending_action_waits = has_pending_action(memory)
            if should_ignore_transcript(spoken_text, audio_stats) and not (
                pending_action_waits and is_short_confirmation(spoken_text)
            ):
                print(f"Stille/Noise ignoriert: {console_text(spoken_text, 'transcript')}")
                continue

            print(f"\n{configured_user_name()}: {console_text(spoken_text, 'prompt')}")

            if spoken_text.lower().strip() in {"exit", "quit", "stop", "beenden"}:
                stop_speaking()
                break

            if conversation_active:
                _, question = remove_wake_word(spoken_text)
                question = question or spoken_text
            else:
                wake_word_found, question = remove_wake_word(spoken_text)
                if wake_word_found or (pending_action_waits and is_short_confirmation(spoken_text)):
                    conversation_active = True

            if not conversation_active:
                print("Aktivierungswort nicht erkannt -> ignoriert")
                continue

            if not question:
                question = "Ja?"

            stop_speaking()

            if is_end_command(question):
                # CLI-eigener Nebeneffekt (conversation_active=False, "wieder auf
                # Weckwort warten") - bleibt bewusst ein eigener Vorab-Check statt
                # sich auf answer_message()s eigene is_end_command-Pruefung zu
                # verlassen, die diesen Zustand nicht kennt (existiert nur im
                # Server-Pfad als reine Text-Antwort ohne conversation_active).
                answer = "Alles klar. Ich bin wieder still, bis Sie Jarvis sagen."
                conversation_active = False
                print(f"\nJARVIS: {console_text(answer, 'answer')}")
                speak(answer, voice=voice)
                continue

            fast_intent_answer = route_fast_intent(question)
            if fast_intent_answer is not None:
                print(f"\nJARVIS: {console_text(fast_intent_answer, 'answer')}")
                speak(fast_intent_answer, voice=voice)
                continue

            answer_started = time.perf_counter()
            result = answer_message(
                question,
                memory,
                llm,
                CONFIG,
                workers=workers,
                pending_mail_followup=pending_mail_followup,
            )
            answer_seconds = time.perf_counter() - answer_started
            pending_mail_followup = result.pending_mail_followup
            answer = result.text
            if PERFORMANCE_LOG:
                print(f"Zeit: Whisper={transcribe_seconds:.2f}s | Antwort={answer_seconds:.2f}s")

            print(f"\nJARVIS: {console_text(answer, 'answer')}")
            speak(answer, voice=voice)

        except KeyboardInterrupt:
            if workers.mail_worker is not None:
                workers.mail_worker.stop()
            if workers.photo_worker is not None:
                workers.photo_worker.stop()
            break
        except Exception as exc:
            print("Fehler:", type(exc).__name__)


if __name__ == "__main__":
    if "--set-openai-key" in sys.argv:
        raise SystemExit(run_set_openai_key())
    if "--delete-openai-key" in sys.argv:
        raise SystemExit(run_delete_openai_key())
    if "--check-secure-storage" in sys.argv:
        raise SystemExit(run_check_secure_storage())
    if "--privacy-test" in sys.argv:
        raise SystemExit(run_privacy_test())
    if "--local-server" in sys.argv:
        from local_server import run as run_local_server
        run_local_server()
    elif "--remote-worker" in sys.argv:
        from remote_worker_server import run as run_remote_worker
        run_remote_worker()
    else:
        main()
