from __future__ import annotations

import json
import os
import sys
import tempfile
import re
import threading
import time
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
    move_item,
    move_items_matching,
    search_files,
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
)
from core.intent_matching import has_domain_fuzzy, normalize_umlauts
from core.multistep_planner import plan_multistep
from memory import Memory
from model_manager import ModelManager
from music_client import (
    MusicAccessError,
    list_playlists,
    next_track,
    pause_music,
    play_music,
    play_playlist,
    play_search,
    previous_track,
)
from notes_client import NotesAccessError, append_to_note, create_note, list_recent_notes
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
        f"Dafür brauche ich deine ausdrückliche Zustimmung für {permission}. "
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
        "Jarvis würde deine Anfrage an eine Cloud-KI senden, um eine Antwort zu erzeugen.",
    )


def ensure_privacy_domain_permission(memory: Memory, permission: str, action_summary: str) -> str | None:
    return ensure_permission(memory, permission, action_summary)


def handle_privacy_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("datenschutz", "privacy", "berechtigung", "berechtigungen", "logs", "verlauf", "daten export", "daten löschen", "daten loeschen")):
        return None

    dashboard = PrivacyDashboard(CONFIG)
    manager = PermissionManager()

    grant_match = re.search(r"(?:erlaube|aktiviere)\s+(mail|kalender|erinnerungen|kontakte|dateien|mikrofon|kamera|standort|internet|fotos|photos|bildschirm|ki|cloud|speicher|memory)", normalized)
    revoke_match = re.search(r"(?:deaktiviere|verbiete|entziehe)\s+(mail|kalender|erinnerungen|kontakte|dateien|mikrofon|kamera|standort|internet|fotos|photos|bildschirm|ki|cloud|speicher|memory)", normalized)
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
            return f"Erlaubt: {permission}. Du kannst diese Berechtigung jederzeit wieder deaktivieren."
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
                "Datenschutz & Sicherheit > Mikrofon und erlaube deinem Terminal den Zugriff. "
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

    words = re.findall(r"[\wäöüÄÖÜß]+", text, flags=re.UNICODE)
    found_index: int | None = None

    for index, word in enumerate(words):
        normalized_word = normalize_text(word)
        if normalized_word in aliases or _looks_like_wake_word(normalized_word):
            found_index = index
            break

    if found_index is None:
        return False, text.strip(" ,.!?;:")

    before_words = words[:found_index]
    if before_words and normalize_text(before_words[-1]) in {"hallo", "hey", "hi"}:
        before_words = before_words[:-1]

    remaining_words = before_words + words[found_index + 1 :]
    cleaned = " ".join(remaining_words).strip(" ,.!?;:")
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
        "erinnerung",
        "erinnerungen",
        "erinnere mich",
        "termine heute",
        "agenda",
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
        "titel",
        "playlist",
        "wiedergabe",
        "abspielen",
        "song spielen",
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
        r"\b(?:bitte|mal|mir|einen|eine|neuen|neue|ordner|folder|erstelle|erstell|mach|mache|leg|lege|auf|am|in|unter|bei|meinem|meinen|meiner)\b",
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

    cleaned = re.sub(r"\b(?:nach|datei|dateien|ordner|bitte|mal|mir)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")



def extract_bulk_file_move(text: str) -> tuple[str, str] | None:
    cleaned = strip_wake_word_from_text(text)
    normalized = normalize_text(cleaned)
    if not any(term in normalized for term in ("datei", "dateien", "dokument", "dokumente", "file", "files")):
        return None
    if not any(term in normalized for term in ("verschieb", "pack", "lege", "leg", "sortier", "räume", "raeume")):
        return None

    target_match = re.search(
        r"(?:in|nach|zu)\s+(?:den\s+|dem\s+|der\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in|unter)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch|dokumente|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code))?[.?!]*$",
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


def looks_like_memory_candidate(text: str) -> bool:
    normalized = normalize_text(strip_wake_word_from_text(text))
    if len(normalized) < 12:
        return False
    if any(marker in normalized for marker in TRANSIENT_MARKERS):
        return False
    if normalized.startswith(TRANSIENT_STARTS):
        return False
    if not should_skip_auto_memory(text):
        return True

    self_reference_markers = ("ich ", "mein ", "meine ", "meiner ", "meinen ", "meinem ")
    return any(marker in normalized for marker in self_reference_markers)


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
    system = (
        "Du bist ein striktes Extraktions-Werkzeug, kein Assistent. Analysiere NUR die folgende "
        f"Nutzeraussage von {user_name} und entscheide, ob sie einen dauerhaften, persönlichen Fakt "
        f"ÜBER {user_name} SELBST enthält (nicht über andere, namentlich genannte Personen).\n"
        "Speichere NIEMALS: Gesundheits- oder Krankheitsdetails, Finanz- oder Kontodaten, Beträge, "
        "Passwörter, Aussagen primär über eine andere Person, oder einmalige/flüchtige Ereignisse "
        "und Beschwerden.\n"
        f"Falls ja, formuliere den Fakt als kurzen, neutralen Satz, der mit '{user_name}' beginnt.\n"
        'Antworte NUR mit kompaktem JSON, ohne weiteren Text: {"has_fact": true, "fact": "..."} '
        'oder {"has_fact": false, "fact": null}. Im Zweifel: has_fact=false.'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]


def _parse_llm_fact_response(raw: str) -> str | None:
    cleaned = str(raw or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
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
        raw = llm.ask(messages, max_output_tokens=80, user_text=user_text, route=route, force_local=force_local)
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



def handle_model_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    if not any(term in normalized for term in ("modell", "gemma", "qwen", "openai", "lokal", "cloud")):
        return None

    manager = ModelManager(CONFIG)

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
            return f"Ja, {configured_user_address()}. Deine Quellen-Präferenz steht auf: Quellen anzeigen."
        return f"Ja, {configured_user_address()}. Quellen lasse ich weg."

    return None


def handle_daily_briefing_command(memory: Memory, text: str) -> str | None:
    normalized = normalize_text(text)
    if "tagesbriefing" not in normalized and "morgenübersicht" not in normalized and "morgenuebersicht" not in normalized and "abendbriefing" not in normalized:
        return None

    calendar_items = []
    reminders = []
    open_tasks = []
    mail_summary = ""
    try:
        # "heutige Termine" statt "naechste 3 Termine" - konsistent mit
        # local_server.py::daily_briefing(), siehe
        # plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md.
        calendar_items = events_on_date(list_upcoming_calendar_items(limit=10).get("items", []))
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

    greeting_phrases = {
        "hallo",
        "hey",
        "hi",
        "guten morgen",
        "guten tag",
        "guten abend",
    }

    if normalized in greeting_phrases:
        return f"Ich bin da, {configured_user_name()}. Was liegt an? Ich bin heute ungewöhnlich wach."

    if normalized in {"ja", "jarvis", "ja jarvis"}:
        return "Was liegt an?"

    thanks_phrases = {
        "danke",
        "danke dir",
        "vielen dank",
        "besten dank",
        "okay danke",
        "ok danke",
    }

    if normalized in thanks_phrases:
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

    if normalized in polite_done_phrases:
        return "Alles klar. Ich halte kurz den Mund."

    if normalized in {"bis später", "bis spaeter", "tschüss", "tschuess"}:
        return f"Bis später, {configured_user_name()}. Ich bleibe so lange brav."

    return None


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
        "pending_mail_document_export",
        "pending_file_action",
        "pending_domain_clarification",
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


def pending_action_matches_text(settings: dict, normalized_text: str) -> bool:
    if any(term in normalized_text for term in ("berechtigung", "erlaub", "freigabe", "zugriff", "bestätig", "bestaetig")):
        return True

    context_by_key = {
        "pending_permission": (),
        "pending_desktop_move": ("desktop", "schreibtisch", "verschieb", "ordner", "datei"),
        "pending_desktop_move_many": ("desktop", "schreibtisch", "verschieb", "ordner", "datei"),
        "pending_calendar_create": ("kalender", "termin", "erinnerung", "erstelle", "morgen", "heute", "uhr"),
        "pending_mail_document_export": ("mail", "mails", "rechnung", "versicherung", "abo", "kopier"),
        "pending_file_action": ("datei", "ordner", "kopier", "verschieb", "lösch", "loesch", "schreibtisch", "desktop"),
        "pending_mail_delete": ("mail", "mails", "papierkorb", "lösch", "loesch", "verschieb"),
        "pending_call_contact": ("anruf", "anrufen", "ruf", "kontakt", "telefon"),
        "pending_call_choice": ("nummer", "endung", "telefon", "kontakt", "anruf"),
    }

    for key, terms in context_by_key.items():
        pending = settings.get(key)
        if not isinstance(pending, dict):
            continue
        pending_text = normalize_text(" ".join(str(value) for value in pending.values()))
        if key == "pending_permission":
            if pending_text and any(word for word in normalized_text.split() if len(word) > 5 and word in pending_text):
                return True
            continue
        if any(term in normalized_text for term in terms):
            return True
        if pending_text and any(word for word in normalized_text.split() if len(word) > 3 and word in pending_text):
            return True

    return False


def handle_memory_command(memory: Memory, text: str) -> str | None:
    normalized = text.strip()
    lowered = normalized.lower()
    memory_system = JarvisMemorySystem(memory)

    if lowered in {"was weißt du über mich", "was weisst du über mich", "was hast du dir gemerkt"}:
        fact_summary = memory_system.facts_summary()
        if fact_summary == "Keine wichtigen Langzeitnotizen.":
            return "Ich habe mir bisher noch keine Langzeit-Erinnerungen gespeichert."

        facts = memory.all_facts()[-10:]
        settings = memory.get("settings") or {}
        settings["pending_memory_list"] = [item.get("content", "") for item in facts]
        memory.set("settings", settings)
        fact_list = "\n".join(f"{index + 1}. {item['content']}" for index, item in enumerate(facts))
        return (
            f"Das habe ich mir gemerkt:\n{fact_list}\n"
            "Sag z. B. 'vergiss Nummer 3', wenn ich mir davon etwas nicht mehr merken soll."
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
        results = memory.search_facts(topic)
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

    state = pending.get("state")
    title = str(pending.get("title") or "").strip()
    body = str(pending.get("body") or "").strip()

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
                "antworte mit 'keine'."
            ),
        },
        {"role": "user", "content": question},
    ]
    try:
        raw = llm.ask(messages, max_output_tokens=20, user_text=question)
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
    "mail": "deine Mails",
    "calendar": "deinen Kalender oder eine Erinnerung",
    "notes": "eine Notiz",
    "files": "deine Dateien oder deinen Schreibtisch",
    "photos": "deine Fotos",
    "screen": "deinen Bildschirm",
    "contacts": "deine Kontakte",
    "music": "die Musik",
    "tasks": "deine Aufgaben",
}


def maybe_ask_domain_clarification(llm: LLMClient, memory: Memory, question: str) -> str | None:
    """Wird nur aufgerufen, wenn Stufe 1 nichts erkannt hat. Statt die Anfrage
    stillschweigend in den werkzeuglosen Chat fallen zu lassen, fragt Jarvis aktiv
    nach, wenn Stufe 2 eine plausible Faehigkeit vermutet - nie eine Vermutung
    stillschweigend ausfuehren (siehe Leons ausdrueckliche Vorgabe: bei
    Unsicherheit immer nachfragen, nie raten)."""
    domains = classify_domain_via_llm(llm, question)
    if not domains:
        return None

    try:
        logger = PrivacyLogger(memory.base_path / "logs")
        logger.log("intent_stage2", "domain_guessed", success=True, domain_count=len(domains))
    except Exception:
        pass

    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": domains, "question": question}
    memory.set("settings", settings)

    if len(domains) == 1:
        guess = _DOMAIN_CLARIFICATION_PHRASES.get(domains[0], domains[0])
        return f"Meintest du gerade {guess}, oder ging es um etwas anderes? Sag kurz, was gemeint war."
    guesses = " oder ".join(_DOMAIN_CLARIFICATION_PHRASES.get(domain, domain) for domain in domains)
    return f"Ging es dabei um {guesses}? Sag kurz, was gemeint war, dann mach ich weiter."


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
        "files": "Jarvis würde deinen Schreibtisch oder Dateien lokal lesen oder ändern.",
        "photos": "Jarvis würde deine Fotos-App oder den lokalen Fotoindex verwenden.",
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
    matched_domains = [domain for domain in DOMAIN_TERMS if has_domain(text, domain)]
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
        return "Alles klar, dann lass ich das - sag gern nochmal genauer, was ich für dich tun soll."

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

    canonical_term = DOMAIN_TERMS.get(chosen, ("",))[0]
    reformulated = f"{canonical_term} {original_question}".strip()
    return _dispatch_confirmed_domain(chosen, reformulated, memory, photo_worker=photo_worker)


def handle_pending_action_flow(
    memory: Memory,
    text: str,
    photo_worker: PhotoBackgroundWorker | None = None,
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
    is_cancel = normalized in cancel_terms or any(term in normalized for term in cancel_terms if len(term) > 4)
    if normalized.startswith(("was ", "welche ", "welcher ", "welches ", "wann ", "wie ", "wo ", "warum ", "wieso ")):
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
                    "Die Berechtigungsanfrage ist inzwischen abgelaufen. Bitte stelle deine Anfrage noch einmal, falls du sie noch erlauben möchtest.",
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
            return "Ich warte auf deine Entscheidung. Sag ja zum Erlauben oder nein zum Abbrechen."
        if permission:
            PermissionManager().grant(permission, source="chat_pending_permission_confirm")
            settings.pop("pending_permission", None)
            memory.set("settings", settings)
            privacy_log("permission", "granted", permission=permission)
            granted_message = f"Erlaubt: {permission}. Bitte stelle deine Anfrage noch einmal, dann führe ich sie kontrolliert aus."
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
            waiting_message="Ich warte noch auf deine Bestätigung. Sag ja zum Verschieben oder abbrechen.",
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
            waiting_message="Ich warte noch auf deine Bestätigung. Sag ja zum Verschieben oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_desktop_move_many", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_calendar_create = settings.get("pending_calendar_create")
    if isinstance(pending_calendar_create, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_calendar_create",
            pending_calendar_create,
            action_type="calendar_create",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich erstelle nichts.",
            waiting_message="Ich warte noch auf deine Bestätigung. Sag ja zum Erstellen oder abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_calendar_create", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

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
            waiting_message="Ich warte auf dein Ja oder Abbrechen.",
        )
        if is_confirm or is_cancel:
            return _continue_multistep_chain_if_pending(memory, "pending_mail_document_export", result, aborted=is_cancel, photo_worker=photo_worker)
        return result

    pending_file_action = settings.get("pending_file_action")
    if isinstance(pending_file_action, dict):
        result = ACTION_ENGINE.resolve(
            memory,
            "pending_file_action",
            pending_file_action,
            action_type="file_action",
            is_confirm=is_confirm,
            is_cancel=is_cancel,
            cancel_message="Alles klar, ich ändere nichts.",
            waiting_message="Ich warte auf dein Ja oder Abbrechen.",
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
            waiting_message="Ich warte noch auf deine Bestätigung. Sag ja zum Ausführen oder abbrechen.",
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
            waiting_message="Ich warte noch auf deine Bestätigung. Sag ja zum Anrufen oder abbrechen.",
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
    "was steht meinen",
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
    return any(trigger in normalized for trigger in _NOTES_READ_TRIGGERS)


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
        return f"Deine letzten Notizen: {items}."

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


_TASKS_PRIORITY_LABELS = {"hoch": "hoch", "mittel": "mittel", "niedrig": "niedrig"}


def handle_tasks_command(memory: Memory, text: str) -> str | None:
    """Bisher hatten interne Aufgaben (task_manager.py, getrennt von Apple
    Reminders) ueberhaupt keinen per Chat erreichbaren Lese-Pfad - eine Frage wie
    "was habe ich fuer offene Aufgaben" fiel komplett durch die Domaenen-Kette und
    landete im werkzeuglosen Chat, der dann frei erfundene, nicht mit den echten
    (leeren oder gefuellten) Aufgaben uebereinstimmende Antworten gab. Rein lesend -
    Aufgaben werden weiterhin nur ueber die App-Oberflaeche oder explizite
    Backend-Aufrufe angelegt/geaendert, nicht ueber diesen Chat-Pfad."""
    if not has_domain(text, "tasks"):
        return None

    tasks = TaskManager(memory).list_tasks(status="offen") + TaskManager(memory).list_tasks(status="in_arbeit")
    if not tasks:
        return "Du hast aktuell keine offenen Aufgaben."

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

    return f"Deine offenen Aufgaben: {summary}."


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
        r"(?:notiz|zettel)\s+(?:mit\s+)?(?:der\s+)?(?:überschrift|ueberschrift|titel)\s+(.+?)(?:\s+(?:und|mit|inhalt|rein|dazu)\s+|$)",
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
        r"(?:mit\s+(?:dem\s+)?(?:inhalt|text)\s+)(.+)$",
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


def clean_note_title(text: str) -> str:
    title = re.sub(r"\b(?:bitte|mal|neu|neue|notiz|zettel)\b", " ", text, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title)
    return title.strip(" .,!?:;") or "Neue Notiz"


def clean_note_body(text: str) -> str:
    body = re.sub(r"\b(?:bitte|mal|auf den einkaufszettel|auf die einkaufsliste)\b", " ", text, flags=re.IGNORECASE)
    body = re.sub(r"\s+", " ", body)
    return body.strip(" .,!?:;")


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
            "Wenn du möchtest, sag klar: Lege Stepstone und Indeed in den Papierkorb."
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
        if memory is None:
            return None
        settings = memory.get("settings") or {}
        last_mail_summary = settings.get("last_mail_summary")
        last_summary_ids = []
        if isinstance(last_mail_summary, dict):
            last_summary_ids = [
                str(item)
                for item in last_mail_summary.get("message_ids") or []
                if str(item).strip()
            ]
        if last_summary_ids:
            return ACTION_ENGINE.propose(
                memory,
                "pending_mail_delete",
                ActionProposal(
                    action_type="mail_delete",
                    execution_data={
                        "selected_targets": ["letzte gelesene Mails"],
                        "search_terms": [],
                        "message_ids": last_summary_ids,
                        "subjects": list(last_mail_summary.get("subjects") or []),
                        "senders": list(last_mail_summary.get("senders") or []),
                    },
                    confirm_prompt=(
                        "Ich nehme die zuletzt gelesenen Mails. "
                        "Soll ich sie wirklich in den Papierkorb legen? Sag ja oder abbrechen."
                    ),
                ),
            )
        return None

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
            f"Ich würde Mails von {targets_text} nur nach deiner Bestätigung verschieben. "
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
            moved_count = move_messages_to_trash(
                message_ids,
                account_name=MAIL_INBOX_ACCOUNT,
                mailbox_name=MAIL_INBOX_MAILBOX,
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
                    moved_messages = move_matching_messages_to_trash(
                        fallback_terms,
                        max_messages=max(MAIL_MAX_MESSAGES, 50),
                        account_name=MAIL_INBOX_ACCOUNT,
                        mailbox_name=MAIL_INBOX_MAILBOX,
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
                "Wenn du willst, nenne ich sie dir noch einmal und wir räumen dann gezielt auf."
            )
        return f"Erledigt. Ich habe {moved_count} gelesene Mail(s) in den Papierkorb gelegt."
    try:
        moved_messages = move_matching_messages_to_trash(
            search_terms,
            max_messages=max(MAIL_MAX_MESSAGES, 50),
            account_name=MAIL_INBOX_ACCOUNT,
            mailbox_name=MAIL_INBOX_MAILBOX,
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
    desktop_context = any(term in normalized for term in ("desktop", "schreibtisch", "ordner"))
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
    if not (mail_context and desktop_context and action_context):
        return None
    if not any(term in normalized for term in document_terms):
        return None

    categories = extract_mail_document_categories(text)
    if not categories:
        categories = ["rechnungen", "versicherungen", "abonnements"]

    category_text = format_mail_document_categories(categories)
    if memory is None:
        return f"Ich würde {category_text} aus deinen Mails auf den Schreibtisch kopieren."

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
                f"{max_messages} Mails auf deinen Schreibtisch kopieren?"
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
    results = export_categorized_mail_documents(
        categories=categories,
        max_messages=max_messages,
        account_name=MAIL_INBOX_ACCOUNT,
        mailbox_name=MAIL_INBOX_MAILBOX,
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

    target_account = MAIL_INBOX_ACCOUNT
    target_mailbox = MAIL_INBOX_MAILBOX
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

    prompt = [
        {
            "role": "system",
            "content": (
                f"Du bist Jarvis, {configured_user_name()}s persönlicher Assistent. "
                "Fasse Apple-Mail-Übersichten auf Deutsch natürlich, knapp und in normaler gesprochener Sprache zusammen. "
                "Antworte so, als würdest du Leon kurz am Schreibtisch informieren, nicht als würdest du jede Zeile vorlesen. "
                "Wichtig: niemals die Mails einzeln als Liste herunterbeten, keine Zeile-für-Zeile-Wiedergabe, "
                "keine langen Aufzählungen, keine Tabellen und kein Markdown. "
                "Gruppiere ähnliche Mails immer nach Thema und nenne nur die Kernaussagen. "
                "Erwähne Absender, Betreff oder Datum nur, wenn es wirklich hilft. "
                "Die Antwort soll wie eine kurze menschliche Zusammenfassung klingen, am besten in 2 bis 3 flüssigen Sätzen. "
                "Wenn mehrere ähnliche Mails dabei sind, fasse sie in einem Satz zusammen. "
                "Dir liegen teils nur Absender, Betreff und ein kurzer Auszug vor; formuliere daraus eine verständliche Lageeinschätzung, "
                "ohne zu behaupten, du hättest den vollständigen Text gelesen. "
                "Schlage bei Bedarf höchstens eine Kategorie vor, zum Beispiel: Wichtig, Rechnung/Finanzen, Termin, Privat, Arbeit, Newsletter, Werbung oder Unklar. "
                "Löschen oder Verschieben nur als Vorschlag, niemals als bereits ausgeführte Aktion. "
                f"Mach das kurz, menschlich und mit dem üblichen trockenen Jarvis-Ton."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Ich habe {len(messages)} Mail(s) gelesen. "
                f"{time_hint} "
                "Bitte gib mir eine natürliche Zusammenfassung nach Themen. "
                "Nicht jede Mail einzeln, sondern die Kernthemen und was daran wichtig ist. "
                "Wenn es mehrere ähnliche Nachrichten gibt, fasse sie gemeinsam zusammen:\n\n"
                f"{mail_briefing}"
            ),
        },
    ]

    answer = llm.ask(
        prompt,
        max_output_tokens=MAIL_SUMMARY_MAX_OUTPUT_TOKENS,
        user_text="mail zusammenfassen und thematisch bündeln",
    )
    if not answer.strip():
        return "Ich habe Mails gefunden, aber daraus gerade keine saubere Zusammenfassung bauen können."
    return clean_mail_answer(answer)


def check_mail_status() -> str:
    try:
        mailboxes = list_mailboxes(max_mailboxes=25)
        messages = list_inbox_messages(
            max_messages=3,
            account_name=MAIL_INBOX_ACCOUNT,
            mailbox_name=MAIL_INBOX_MAILBOX,
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
            if mailbox.account == MAIL_INBOX_ACCOUNT and mailbox.mailbox == MAIL_INBOX_MAILBOX
        ),
        None,
    )

    if inbox_summary is None:
        return "Apple Mail antwortet, aber iCloud INBOX macht Verstecken."

    if not messages:
        return (
            f"Apple Mail antwortet und iCloud INBOX ist sichtbar mit {inbox_summary.message_count} Nachrichten. "
            "Die Betreffzeilen sind aber noch schüchtern."
        )

    subjects = "; ".join(
        f"{message.sender or 'Unbekannt'}: {message.subject}" for message in messages[:3]
    )
    return (
        f"Apple Mail funktioniert. iCloud INBOX ist sichtbar mit "
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
    wants_update = any(term in normalized for term in ("update", "was ist neu", "neue mails", "neues"))
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

    try:
        if wants_reminders:
            items = list_open_reminders(limit=5).get("items", [])
            if not items:
                return "Ich sehe aktuell keine offenen Erinnerungen."
            lines = [str(item.get("title") or "Erinnerung") for item in items]
            return "Offene Erinnerungen: " + "; ".join(lines) + "."

        until = None
        if only_today:
            now = datetime.now()
            until = datetime(now.year, now.month, now.day, 23, 59, 59)

        items = list_upcoming_calendar_items(limit=5, until=until).get("items", [])
        if only_today:
            # Zusaetzlich zur AppleScript-seitigen until-Vorfilterung (grob, haengt am
            # Ende an einem locale-formatierten Datumsvergleich) wird hier noch einmal
            # anhand des echten, numerisch geparsten start_dt gefiltert - robust,
            # unabhaengig vom Systemdatumsformat. Behebt den gemeldeten Bug, dass "was
            # steht heute an" teils Termine aus dem ganzen Jahr zeigte.
            items = events_on_date(items)
        if not items:
            return "Für heute sehe ich keine Termine." if only_today else "Ich sehe aktuell keine anstehenden Termine."

        lines = [f"{item.get('title') or 'Termin'} um {_format_event_time(item.get('start', ''))} Uhr" for item in items]
        prefix = "Heute steht an: " if only_today else "Deine nächsten Termine: "
        return prefix + "; ".join(lines) + "."
    except CalendarAccessError as exc:
        return str(exc)
    except Exception as exc:
        print("Kalender Fehler:", type(exc).__name__)
        return "Ich konnte deinen Kalender gerade nicht lesen."


def handle_calendar_command(text: str, memory: Memory | None = None) -> str | None:
    normalized = normalize_text(text)
    domain_match = has_domain(text, "calendar")
    is_query = looks_like_calendar_query(text)
    if not is_query and domain_match and any(term in normalized for term in ("hab ich", "habe ich", "steht")):
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

    parsed = _extract_datetime(text, CONFIG)
    if parsed is None:
        return "Für Kalender oder Erinnerung brauche ich noch Datum oder Uhrzeit."

    when, has_time = parsed
    title = extract_calendar_title(text)
    if not title:
        title = "Erinnerung" if "erinner" in normalized else "Termin"

    is_reminder = "erinner" in normalized and "termin" not in normalized and "kalender" not in normalized
    if memory is not None:
        target = "Erinnerung" if is_reminder else "Kalendereintrag"
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
                    f"Ich habe noch nichts angelegt. Soll ich die {target} {title} "
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
        r"\b(?:kalender|kalendereintrag|termin|termineintrag|erinnerung|erinnerungen|erinnere mich|bitte|mal|mir|einen|eine|kurz|kurze|kurzen|den|die|das|für mich|fuer mich)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:erstelle|erstell|mach|mache|setz|setze|trag|trage|schreib|schreibe|ein|an)\b",
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
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")


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
            return f"Ich würde {resolved_name} nur nach deiner Bestätigung anrufen."

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

    search_match = re.search(
        r"(?:kontakt|kontakte|telefonnummer|nummer)\s+(?:von|für|fuer)\s+(.+)$",
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
    if any(term in normalized for term in ("mail", "mails", "email", "emails", "posteingang", "mailfach")):
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
            r"(?:verschieb|verschiebe|pack|packe|leg|lege)\s+(.+?)\s+(?:in|nach|zu)\s+(?:den\s+|dem\s+|der\s+)?(?:ordner\s+)?(.+?)(?:\s+(?:auf|am|in)\s+(?:meinem\s+|meinen\s+)?(?:desktop|schreibtisch))?[.?!]*$",
            text,
            flags=re.IGNORECASE,
        )
        if move_match:
            source_name = clean_desktop_name(move_match.group(1))
            target_folder = clean_desktop_name(move_match.group(2))
            if not source_name or not target_folder:
                return "Was soll ich wohin auf deinem Schreibtisch verschieben?"

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
            r"(?:such|suche|finde|zeig|zeige).*(?:auf|am|in)\s+(?:meinem\s+|meinen\s+)?(?:desktop|schreibtisch)\s+(?:nach\s+)?(.+?)[.?!]*$",
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
        return "Ich konnte deinen Schreibtisch nicht lesen."

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
    if any(term in normalized for term in ("mail", "mails", "email", "emails", "posteingang", "mailfach")):
        return None

    root_hint = detect_root_hint(text)

    try:
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
    if not action or not target or (action != "move_matching" and not source) or (action == "move_matching" and not query):
        return "Mir fehlt noch ein Baustein. Ich ändere nichts."

    try:
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
                    "Jarvis würde passende Foto-Vorschauen in einen neuen Ordner auf deinem Schreibtisch exportieren.",
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
        return "Wonach soll ich in deinen Fotos suchen?"

    if memory is not None:
        file_permission = ensure_privacy_domain_permission(
            memory,
            "files",
            "Jarvis würde passende Foto-Vorschauen in einen neuen Ordner auf deinem Schreibtisch exportieren.",
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

    summary = f"In {app}: {description}" if app else f"Auf deinem Bildschirm: {description}"

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


def handle_music_command(text: str) -> str | None:
    normalized = normalize_text(text)
    if not has_domain(text, "music"):
        return None

    if not MUSIC_ENABLED:
        return "Apple-Music-Steuerung ist in der Konfiguration deaktiviert."

    try:
        if "playlist" in normalized and any(term in normalized for term in ("welche", "liste", "auflisten", "zeig", "zeige")):
            playlists = list_playlists()
            if not playlists:
                return "Ich kann Apple Music öffnen, sehe aber gerade keine Playlists."

            visible = ", ".join(playlists[:8])
            return f"Ich sehe diese Apple-Music-Playlists: {visible}."

        if any(term in normalized for term in ("pause", "pausier", "pausiere", "stopp die musik", "stoppe die musik")):
            return pause_music()

        if any(term in normalized for term in ("weiter", "fortsetzen", "spiel weiter", "wiedergabe starten")):
            return play_music()

        if any(term in normalized for term in ("nächster", "naechster", "nächste", "naechste", "skip", "überspring", "ueberspring")):
            return next_track()

        if any(term in normalized for term in ("vorheriger", "vorherige", "zurück", "zurueck", "letzter titel")):
            return previous_track()

        playlist_match = re.search(
            r"(?:spiel|spiele|starte|öffne|oeffne)\s+(?:bitte\s+)?(?:meine\s+|die\s+)?playlist\s+(.+)$",
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
            r"(?:spiel|spiele|starte|öffne|oeffne)\s+(?:das\s+)?(?:lied|song|titel)?\s*(.+)$",
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


def main():
    llm = LLMClient(CONFIG)
    memory = Memory()
    permission_manager = PermissionManager()

    print("Hinweis: Jarvis ist ein KI-System. Du interagierst mit automatisierter KI-Unterstützung; wichtige Aktionen werden erst nach deiner Bestätigung ausgeführt.")
    if permissions_required() and not permission_manager.is_allowed("microphone"):
        print("Jarvis braucht Mikrofonzugriff, um deine Sprachbefehle zu erkennen.")
        consent = input("Mikrofon für Jarvis erlauben? Tippe ja oder nein: ").strip().lower()
        if consent in {"ja", "j", "yes", "y"}:
            permission_manager.grant("microphone")
            privacy_log("permission", "granted", permission="microphone")
        else:
            print("Ohne Mikrofonfreigabe startet Jarvis nicht.")
            return

    mail_worker = MailBackgroundWorker(CONFIG) if has_permission("mail") else None
    photo_worker = PhotoBackgroundWorker(CONFIG) if has_permission("photos") else None
    if mail_worker is not None:
        mail_worker.start()
    if photo_worker is not None:
        photo_worker.start()
    try:
        stt_engine = create_stt_engine(CONFIG)
    except STTEngineError as exc:
        if mail_worker is not None:
            mail_worker.stop()
        if photo_worker is not None:
            photo_worker.stop()
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
                answer = "Alles klar. Ich bin wieder still, bis du Jarvis sagst."
                conversation_active = False
                print(f"\nJARVIS: {console_text(answer, 'answer')}")
                speak(answer, voice=voice)
                continue

            fast_intent_answer = route_fast_intent(question)
            if fast_intent_answer is not None:
                print(f"\nJARVIS: {console_text(fast_intent_answer, 'answer')}")
                speak(fast_intent_answer, voice=voice)
                continue

            system_answer = handle_system_command(question)
            if system_answer is not None:
                print(f"\nJARVIS: {console_text(system_answer, 'answer')}")
                speak(system_answer, voice=voice)
                continue

            briefing_answer = handle_daily_briefing_command(memory, question)
            if briefing_answer is not None:
                print(f"\nJARVIS: {console_text(briefing_answer, 'answer')}")
                speak(briefing_answer, voice=voice)
                continue

            preference_answer = handle_preference_command(memory, question)
            if preference_answer is not None:
                print(f"\nJARVIS: {console_text(preference_answer, 'answer')}")
                speak(preference_answer, voice=voice)
                continue

            style_answer = handle_style_command(memory, question)
            if style_answer is not None:
                print(f"\nJARVIS: {console_text(style_answer, 'answer')}")
                speak(style_answer, voice=voice)
                continue

            project_answer = handle_project_command(question)
            if project_answer is not None:
                print(f"\nJARVIS: {console_text(project_answer, 'answer')}")
                speak(project_answer, voice=voice)
                continue

            if has_pending_action(memory):
                settings_before = memory.get("settings") or {}
                pending_permission_before = settings_before.get("pending_permission")
                declined_mail_permission = (
                    isinstance(pending_permission_before, dict)
                    and pending_permission_before.get("permission") == "mail"
                )
                pending_action_answer = handle_pending_action_flow(memory, question, photo_worker=photo_worker)
                if pending_action_answer is not None:
                    if declined_mail_permission and not has_permission("mail"):
                        pending_mail_followup = False
                    record_exchange(memory, question, pending_action_answer)
                    print(f"\nJARVIS: {console_text(pending_action_answer, 'answer')}")
                    speak(pending_action_answer, voice=voice)
                    continue

            local_answer = handle_local_command(question)
            if local_answer is not None:
                print(f"\nJARVIS: {console_text(local_answer, 'answer')}")
                speak(local_answer, voice=voice)
                continue

            privacy_answer = handle_privacy_command(memory, question)
            if privacy_answer is not None:
                print(f"\nJARVIS: {console_text(privacy_answer, 'answer')}")
                speak(privacy_answer, voice=voice)
                continue

            model_answer = handle_model_command(question, memory=memory)
            if model_answer is not None:
                record_exchange(memory, question, model_answer, auto_memory=False)
                print(f"\nJARVIS: {console_text(model_answer, 'answer')}")
                speak(model_answer, voice=voice)
                continue

            memory_answer = handle_memory_command(memory, question)
            if memory_answer is not None:
                record_exchange(memory, question, memory_answer, auto_memory=False)
                print(f"\nJARVIS: {console_text(memory_answer, 'answer')}")
                speak(memory_answer, voice=voice)
                continue

            pending_note_answer = handle_pending_note_flow(memory, question)
            if pending_note_answer is not None:
                record_exchange(memory, question, pending_note_answer)
                print(f"\nJARVIS: {console_text(pending_note_answer, 'answer')}")
                speak(pending_note_answer, voice=voice)
                continue

            pending_domain_answer = handle_pending_domain_clarification_flow(memory, question, photo_worker=photo_worker)
            if pending_domain_answer is not None:
                record_exchange(memory, question, pending_domain_answer)
                print(f"\nJARVIS: {console_text(pending_domain_answer, 'answer')}")
                speak(pending_domain_answer, voice=voice)
                continue

            if has_permission("usage_patterns"):
                record_pattern_event_if_matched(question)

            if looks_like_multistep_request(question):
                multistep_steps = plan_multistep(
                    llm,
                    question,
                    max_steps=int(CONFIG.get("multistep_planner_max_steps", 4)),
                    max_output_tokens=int(CONFIG.get("multistep_planner_max_output_tokens", 300)),
                )
                if multistep_steps:
                    multistep_answer = execute_multistep_plan(multistep_steps, memory, photo_worker=photo_worker)
                    record_exchange(memory, question, multistep_answer)
                    print(f"\nJARVIS: {console_text(multistep_answer, 'answer')}")
                    speak(multistep_answer, voice=voice)
                    continue

            permission_answer = ensure_privacy_domain_permission(memory, "notes", "Jarvis würde eine Notiz über Apple Notes erstellen oder ändern.") if has_domain(question, "notes") else None
            if permission_answer is not None:
                print(f"\nJARVIS: {console_text(permission_answer, 'answer')}")
                speak(permission_answer, voice=voice)
                continue

            notes_answer = handle_notes_command(memory, question)
            if notes_answer is not None:
                record_exchange(memory, question, notes_answer)
                print(f"\nJARVIS: {console_text(notes_answer, 'answer')}")
                speak(notes_answer, voice=voice)
                continue

            tasks_answer = handle_tasks_command(memory, question)
            if tasks_answer is not None:
                record_exchange(memory, question, tasks_answer)
                print(f"\nJARVIS: {console_text(tasks_answer, 'answer')}")
                speak(tasks_answer, voice=voice)
                continue

            calendar_permission = None
            if has_domain(question, "calendar") or looks_like_calendar_query(question):
                calendar_permission = ensure_privacy_domain_permission(memory, "calendar", "Jarvis würde Kalenderdaten verwenden.")
                if calendar_permission is None and "erinner" in normalize_text(question):
                    calendar_permission = ensure_privacy_domain_permission(memory, "reminders", "Jarvis würde eine Erinnerung verwenden.")
            if calendar_permission is not None:
                print(f"\nJARVIS: {console_text(calendar_permission, 'answer')}")
                speak(calendar_permission, voice=voice)
                continue

            calendar_answer = handle_calendar_command(question, memory=memory)
            if calendar_answer is not None:
                record_exchange(memory, question, calendar_answer)
                print(f"\nJARVIS: {console_text(calendar_answer, 'answer')}")
                speak(calendar_answer, voice=voice)
                continue

            file_permission = ensure_privacy_domain_permission(memory, "files", "Jarvis würde deinen Schreibtisch oder Dateien lokal lesen oder ändern.") if has_domain(question, "files") or "desktop" in normalize_text(question) or "schreibtisch" in normalize_text(question) else None
            if file_permission is not None:
                print(f"\nJARVIS: {console_text(file_permission, 'answer')}")
                speak(file_permission, voice=voice)
                continue

            desktop_answer = handle_desktop_command(question, memory=memory)
            if desktop_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, desktop_answer)
                print(f"\nJARVIS: {console_text(desktop_answer, 'answer')}")
                speak(desktop_answer, voice=voice)
                continue

            file_answer = handle_file_command(question, memory=memory)
            if file_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, file_answer)
                print(f"\nJARVIS: {console_text(file_answer, 'answer')}")
                speak(file_answer, voice=voice)
                continue

            photo_permission = ensure_privacy_domain_permission(memory, "photos", "Jarvis würde deine Fotos-App oder den lokalen Fotoindex verwenden.") if has_domain(question, "photos") else None
            if photo_permission is None and has_domain(question, "photos") and any(term in normalize_text(question) for term in ("openai", "vision", "analysiere", "analysieren", "was siehst")):
                photo_permission = ensure_cloud_llm_permission(memory, question)
            if photo_permission is not None:
                print(f"\nJARVIS: {console_text(photo_permission, 'answer')}")
                speak(photo_permission, voice=voice)
                continue
            if photo_worker is None and has_domain(question, "photos") and has_permission("photos"):
                photo_worker = PhotoBackgroundWorker(CONFIG)
                photo_worker.start()

            photo_answer = handle_photo_command(question, photo_worker, memory=memory)
            if photo_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, photo_answer)
                print(f"\nJARVIS: {console_text(photo_answer, 'answer')}")
                speak(photo_answer, voice=voice)
                continue

            screen_permission = ensure_privacy_domain_permission(memory, "screen", "Jarvis würde einen einzelnen Screenshot deines aktiven Fensters aufnehmen und lokal analysieren.") if has_domain(question, "screen") else None
            if screen_permission is not None:
                print(f"\nJARVIS: {console_text(screen_permission, 'answer')}")
                speak(screen_permission, voice=voice)
                continue

            screen_answer = handle_screen_command(question, memory=memory) if has_permission("screen") else None
            if screen_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, screen_answer)
                print(f"\nJARVIS: {console_text(screen_answer, 'answer')}")
                speak(screen_answer, voice=voice)
                continue

            mail_export_permission = ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Mail-Übersichten lesen und passende Anhänge oder Notizen auf den Schreibtisch kopieren.") if has_domain(question, "mail") else None
            if mail_export_permission is not None:
                print(f"\nJARVIS: {console_text(mail_export_permission, 'answer')}")
                speak(mail_export_permission, voice=voice)
                continue

            mail_document_export_answer = handle_mail_document_export_command(question, memory=memory)
            if mail_document_export_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, mail_document_export_answer)
                print(f"\nJARVIS: {console_text(mail_document_export_answer, 'answer')}")
                speak(mail_document_export_answer, voice=voice)
                continue

            if mail_worker is None and has_domain(question, "mail") and has_permission("mail"):
                mail_worker = MailBackgroundWorker(CONFIG)
                mail_worker.start()

            background_mail_answer = handle_background_mail_command(question, mail_worker)
            if background_mail_answer is not None:
                pending_mail_followup = True
                record_exchange(memory, question, background_mail_answer)
                print(f"\nJARVIS: {console_text(background_mail_answer, 'answer')}")
                speak(background_mail_answer, voice=voice)
                continue

            mail_followup_intent = pending_mail_followup and (
                is_mail_time_followup(question) or is_mail_status_followup(question)
            )
            mail_permission = ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Apple Mail lokal lesen oder bearbeiten.") if has_domain(question, "mail") or mail_followup_intent else None
            if mail_permission is not None:
                print(f"\nJARVIS: {console_text(mail_permission, 'answer')}")
                speak(mail_permission, voice=voice)
                continue

            mail_settings_before = memory.get("settings") or {}
            had_pending_mail_delete = isinstance(mail_settings_before.get("pending_mail_delete"), dict)
            mail_answer = handle_mail_command(
                llm,
                question,
                force=mail_followup_intent,
                memory=memory,
            )
            if mail_answer is not None:
                pending_mail_followup = False if had_pending_mail_delete else True
                record_exchange(memory, question, mail_answer)
                print(f"\nJARVIS: {console_text(mail_answer, 'answer')}")
                speak(mail_answer, voice=voice)
                continue

            contact_permission = ensure_privacy_domain_permission(memory, "contacts", "Jarvis würde Kontakte lesen oder einen Anruf vorbereiten.") if has_domain(question, "contacts") else None
            if contact_permission is not None:
                print(f"\nJARVIS: {console_text(contact_permission, 'answer')}")
                speak(contact_permission, voice=voice)
                continue

            contact_answer = handle_contact_command(question, memory=memory)
            if contact_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, contact_answer)
                print(f"\nJARVIS: {console_text(contact_answer, 'answer')}")
                speak(contact_answer, voice=voice)
                continue

            music_permission = ensure_privacy_domain_permission(memory, "music", "Jarvis würde Apple Music oder die Musik-Wiedergabe steuern.") if has_domain(question, "music") else None
            if music_permission is not None:
                print(f"\nJARVIS: {console_text(music_permission, 'answer')}")
                speak(music_permission, voice=voice)
                continue

            music_answer = handle_music_command(question)
            if music_answer is not None:
                pending_mail_followup = False
                record_exchange(memory, question, music_answer)
                print(f"\nJARVIS: {console_text(music_answer, 'answer')}")
                speak(music_answer, voice=voice)
                continue

            # Stufe 2 der Absichtserkennung, siehe local_server.py::_answer_with_core
            # fuer den ausfuehrlichen Kommentar - identisches Prinzip fuer diesen
            # (separaten, CLI-only) Antwortpfad.
            domain_clarification = maybe_ask_domain_clarification(llm, memory, question)
            if domain_clarification is not None:
                record_exchange(memory, question, domain_clarification)
                print(f"\nJARVIS: {console_text(domain_clarification, 'answer')}")
                speak(domain_clarification, voice=voice)
                continue

            web_context = None
            web_seconds = 0.0
            if WEB_SEARCH_ENABLED and should_use_web_search(question):
                internet_permission = ensure_privacy_domain_permission(memory, "internet", "Jarvis würde eine Websuche im Internet ausführen.")
                if internet_permission is not None:
                    print(f"\nJARVIS: {console_text(internet_permission, 'answer')}")
                    speak(internet_permission, voice=voice)
                    continue
                search_query = build_search_query(question)
                print(f"Websuche: {console_text(search_query, 'search')}")
                try:
                    web_started = time.perf_counter()
                    results = search_web(search_query, max_results=WEB_SEARCH_MAX_RESULTS)
                    web_seconds = time.perf_counter() - web_started
                    if results:
                        web_context = format_search_results(results)
                    else:
                        print("Websuche: keine Ergebnisse gefunden.")
                except Exception as exc:
                    print("Websuche Fehler:", type(exc).__name__)

            llm_permission = ensure_cloud_llm_permission(memory, question)
            if llm_permission is not None:
                print(f"\nJARVIS: {console_text(llm_permission, 'answer')}")
                speak(llm_permission, voice=voice)
                continue

            print("Antwort wird generiert...")
            llm_started = time.perf_counter()
            route = llm.plan([], user_text=question)
            answer = clean_ai_answer(
                llm.ask(
                    build_input(memory, question, web_context, compact=route.compact_prompt),
                    max_output_tokens=route.max_output_tokens if route.provider == "ollama" else OPENAI_MAX_OUTPUT_TOKENS,
                    user_text=question,
                    route=route,
                )
            )
            llm_seconds = time.perf_counter() - llm_started
            promised_action_answer = execute_promised_action_if_possible(llm, question, answer)
            if promised_action_answer is not None:
                answer = promised_action_answer
            pending_mail_followup = "mail" in normalize_text(question)
            if PERFORMANCE_LOG:
                print(
                    "Zeit: "
                    f"Whisper={transcribe_seconds:.2f}s | "
                    f"Web={web_seconds:.2f}s | "
                    f"KI={llm_seconds:.2f}s"
                )
            record_exchange(memory, question, answer)

            print(f"\nJARVIS: {console_text(answer, 'answer')}")
            speak(answer, voice=voice)

        except KeyboardInterrupt:
            if mail_worker is not None:
                mail_worker.stop()
            if photo_worker is not None:
                photo_worker.stop()
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
    else:
        main()
