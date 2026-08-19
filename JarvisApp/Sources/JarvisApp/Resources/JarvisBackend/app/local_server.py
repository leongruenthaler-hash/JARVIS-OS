from __future__ import annotations

import hmac
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import numpy as np

from audio_stream import StreamingAudioListener, warm_audio_pipeline
from background_tasks import MailBackgroundWorker
from news_background_worker import NewsBackgroundWorker
from calendar_client import events_on_date, list_open_reminders, list_upcoming_calendar_items
from data_dir import data_root
from fast_intent_router import FastIntentRouter
from core.conversation_manager import ConversationManager
from core.daily_briefing import build_daily_briefing
from core.proactivity_engine import PROACTIVITY_ENGINE
from core.task_manager import TaskManager
from core.usage_patterns import recurring_patterns
from core.voice_performance import VOICE_PERFORMANCE_LOG
from core import (
    VOICE_MODES,
    normalize_voice_mode,
    voice_mode_disables_web_search,
    voice_mode_suppresses_voice_output,
    voice_mode_forces_local_only,
)
from files_client import configured_roots, move_indexed_matches_to_folder, normalize_name, search_file_index_entries, search_files
from llm_client import LLMClient
from jarvis_personality import JARVIS_SYSTEM_PROMPT, message_shape, normalize_jarvis_messages, text_summary
from mail_client import create_reply_draft, list_inbox_messages, list_mailboxes, unread_inbox_count
from memory import Memory
from model_manager import ModelManager, ollama_base_url
from model_router import ModelRouter
from music_client import now_playing as music_now_playing
from photos_client import PhotoBackgroundWorker, PhotoIndex
from voice_profile import VoiceProfileError, VoiceProfileStore, DEFAULT_SPEAKER_THRESHOLD
from permission_manager import PermissionManager
from privacy_dashboard import PrivacyDashboard
from privacy_logger import PrivacyLogger
from secure_storage import (
    SecureStorageError,
    check_secure_storage,
    delete_openai_api_key,
    set_openai_api_key,
)
from settings import load_config, save_config
from stt_engines import create_stt_engine

# Shared secret between this process and the Swift app, required on every request except
# /api/health. Without it, any webpage open in the user's browser could otherwise send
# blind requests to 127.0.0.1:8765 (grant itself Mail/Calendar/Photos access, swap the
# OpenAI key, delete the privacy log, move indexed files, ...) since a local HTTP server
# has no other way to distinguish "the Jarvis app" from "any other local process/page".
# Regenerated every process start and persisted (0600) so the Swift app can read it back.
AUTH_TOKEN: str | None = None
AUTH_TOKEN_FILENAME = "local_server.token"


def _generate_auth_token() -> str:
    global AUTH_TOKEN
    AUTH_TOKEN = secrets.token_hex(32)
    token_path = data_root() / AUTH_TOKEN_FILENAME
    try:
        token_path.write_text(AUTH_TOKEN, encoding="utf-8")
        token_path.chmod(0o600)
    except OSError as exc:
        print(f"Warning: could not persist local server auth token: {exc}", file=sys.stderr)
    return AUTH_TOKEN

ROOT = Path(__file__).resolve().parent.parent
CONFIG = load_config()

VOICE_BOOTSTRAP_STATUS_PATH = Path("/tmp/jarvis_app_voice_bootstrap_status.txt")


def _write_voice_bootstrap_status(stage: str, message: str) -> None:
    """Atomically writes a single `<ts>|<stage>|<message>` line the Swift app polls
    while the STT engine loads for the first time (model download + first-run
    compilation can take 1-2 minutes) - same format/pattern as the venv/CLT bootstrap
    status file in LocalServerController.swift."""
    tmp_path = VOICE_BOOTSTRAP_STATUS_PATH.with_suffix(".tmp")
    tmp_path.write_text(f"{int(time.time())}|{stage}|{message}\n", encoding="utf-8")
    tmp_path.replace(VOICE_BOOTSTRAP_STATUS_PATH)


def _clear_voice_bootstrap_status() -> None:
    VOICE_BOOTSTRAP_STATUS_PATH.unlink(missing_ok=True)


def datetime_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def datetime_now_from_timestamp(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def _safe_error(exc: Exception) -> str:
    return type(exc).__name__


def _minutes_since(iso_timestamp: str | None) -> float:
    if not iso_timestamp:
        return float("inf")
    from datetime import datetime

    try:
        return (datetime.now() - datetime.fromisoformat(str(iso_timestamp))).total_seconds() / 60
    except ValueError:
        return float("inf")


def _safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        missing = getattr(exc, "filename", None) or str(exc)
        print(f"Missing file path: {missing}", file=sys.stderr)
        return f"FileNotFoundError: missing_path={missing}"
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    return f"{type(exc).__name__}: {text}"


def _safe_detail(exc: Exception) -> str:
    return _safe_error_detail(exc)


def _speech_error_message(exc: Exception) -> str:
    detail = _safe_error_detail(exc)
    lowered = detail.lower()
    if "device -1" in lowered or "error querying device" in lowered:
        return (
            "Die Sprachaufnahme konnte nicht gestartet werden, weil Python kein gültiges Standard-Mikrofon findet. "
            "Öffnen Sie Systemeinstellungen > Ton > Eingabe und wählen Sie Ihr MacBook-Mikrofon aus. Prüfen Sie zusätzlich "
            f"Datenschutz & Sicherheit > Mikrofon für Xcode, Terminal und Python. Technisch: {detail}"
        )
    if "inputstream" in lowered or "portaudio" in lowered or "sounddevice" in lowered:
        return (
            "Die Sprachaufnahme konnte nicht gestartet werden. macOS hat das Mikrofon oder das Eingabegerät "
            f"nicht freigegeben oder PortAudio kann es nicht öffnen. Prüfe Systemeinstellungen > Datenschutz & Sicherheit > Mikrofon "
            f"für Xcode, Terminal beziehungsweise Python. Technisch: {detail}"
        )
    if "permission" in lowered or "not permitted" in lowered or "operation not permitted" in lowered:
        return (
            "Die Sprachaufnahme wurde von macOS blockiert. Erlaube Mikrofonzugriff für die App, Xcode, "
            f"Terminal oder Python. Technisch: {detail}"
        )
    if "swift" in lowered or "apple speech" in lowered:
        return f"Apple Speech konnte nicht initialisiert werden. Technisch: {detail}"
    return f"Die Sprachaufnahme konnte nicht gestartet werden. Technisch: {detail}"


class JarvisLocalServer:
    def __init__(self):
        self.config = CONFIG
        self.memory = Memory()
        self.tasks = TaskManager(self.memory)
        self.llm = LLMClient(self.config)
        self.models = ModelManager(self.config)
        self.model_router = ModelRouter(self.config, self.models)
        self.fast_intent_router = FastIntentRouter()
        self.permissions = PermissionManager()
        self.dashboard = PrivacyDashboard(self.config)
        self.pipeline_logger = PrivacyLogger(enabled=bool(self.config.get("privacy_logging_enabled", True)))
        self._stt_engine = None
        self._stt_lock = threading.Lock()
        self._partial_transcript_busy = False
        self._last_partial_transcript = ""
        self._listen_lock = threading.Lock()
        self._listen_cancel_event = threading.Event()
        self._audio_listener = None
        self._audio_listener_lock = threading.Lock()
        self._tts_speaking = threading.Event()
        self.mail_worker = None
        self.news_worker = None
        self.photo_worker = None
        self.voice_profile = VoiceProfileStore()
        self.pending_mail_followup = False
        self._mail_scan_status_path = ROOT / "memory" / "mail_scan_status.json"
        self._file_scan_status_path = ROOT / "memory" / "file_scan_status.json"
        self._file_index_path = ROOT / "memory" / "file_index.json"
        self._mail_scan_lock = threading.Lock()
        self._mail_scan_thread = None
        self._file_scan_lock = threading.Lock()
        self._file_scan_thread = None
        self._photo_scan_lock = threading.Lock()
        self._photo_scan_thread = None
        self._photo_vision_thread = None
        self._model_pull_status_path = ROOT / "memory" / "model_pull_status.json"
        self._model_pull_lock = threading.Lock()
        self._model_pull_thread = None
        self._last_answer_source = "local"
        self._last_answer_model = self.models.active_model

    def conversation_history(self) -> dict[str, Any]:
        enabled = bool(self.config.get("privacy_store_conversation", False))
        turns = ConversationManager().turns if enabled else []
        return {
            "recording_enabled": enabled,
            "turns": [
                {"role": turn.role, "content": turn.content, "created_at": turn.created_at}
                for turn in turns
            ],
        }

    def list_memory_facts(self, query: dict[str, Any]) -> dict[str, Any]:
        """Memory management view (Phase B). Deliberately not gated behind the
        "memory" permission the way auto-storage is - that permission controls
        whether Jarvis may keep *writing* new facts and conversation history, not
        whether the user may see/edit/delete what's already stored. Hiding a
        user's own data behind a toggle for storing *more* of it would be the
        wrong default."""
        search = str(query.get("search") or "").strip()
        category = str(query.get("category") or "").strip()
        include_expired = bool(query.get("include_expired", True))
        include_rejected = bool(query.get("include_rejected", True))
        limit = max(1, min(int(query.get("limit") or 200), 500))

        if search:
            facts = self.memory.search_facts(search)
        else:
            facts = self.memory.all_facts(include_expired=include_expired, include_rejected=include_rejected)

        if category:
            facts = [f for f in facts if str(f.get("category") or "") == category]

        facts.sort(key=lambda f: str(f.get("updated_at") or f.get("created_at") or ""), reverse=True)
        return {"facts": facts[:limit], "total": len(facts)}

    def recent_activity(self, query: dict[str, Any]) -> dict[str, Any]:
        """Live-Zugriffs-Feed fuer die Gedaechtnis-Kern-Ansicht (Phase F-Folgeschritt):
        gibt zurueck, worauf Jarvis seit `since` tatsaechlich zugegriffen hat (Foto,
        Datei, Gedaechtnis-Fakt) - siehe app/core/activity_log.py. Nicht hinter der
        "memory"-Berechtigung, aus demselben Grund wie list_memory_facts oben:
        sichtbar machen ist kein zusaetzliches Speichern."""
        from core.activity_log import recent_activity as fetch_recent_activity

        try:
            since = float(query.get("since") or 0)
        except (TypeError, ValueError):
            since = 0.0
        return {"events": fetch_recent_activity(since)}

    def update_memory_fact(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact_id = str(payload.get("id") or "")
        if not fact_id:
            return {"ok": False, "error": "missing_id"}
        fields = {
            key: value
            for key, value in payload.items()
            if key in {"content", "category", "scope", "sensitivity", "retention_policy", "expires_at", "tags", "status"}
        }
        ok = self.memory.update_fact(fact_id, **fields)
        return {"ok": ok, "fact": self.memory.get_fact_by_id(fact_id) if ok else None}

    def confirm_memory_fact(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact_id = str(payload.get("id") or "")
        if not fact_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.memory.confirm_fact(fact_id)}

    def reject_memory_fact(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact_id = str(payload.get("id") or "")
        if not fact_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.memory.reject_fact(fact_id)}

    def delete_memory_fact(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact_id = str(payload.get("id") or "")
        if not fact_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.memory.delete_fact_by_id(fact_id)}

    def list_tasks(self, query: dict[str, Any]) -> dict[str, Any]:
        status = str(query.get("status") or "").strip() or None
        project = str(query.get("project") or "").strip() or None
        include_rejected = str(query.get("include_rejected") or "").lower() in ("1", "true")
        tasks = self.tasks.list_tasks(status=status, project=project, include_rejected=include_rejected)
        return {"tasks": tasks, "total": len(tasks), "blocked": [task["id"] for task in self.tasks.blocked_tasks()]}

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        if not title:
            return {"ok": False, "error": "missing_title"}
        # list(x) on a non-list JSON value silently mangles it instead of raising:
        # a string "urgent" becomes ['u','r','g','e','n','t'], a dict becomes its
        # keys. Only accept an actual JSON array here, otherwise fall back to [].
        raw_tags = payload.get("tags")
        raw_depends_on = payload.get("depends_on")
        tags = list(raw_tags) if isinstance(raw_tags, list) else []
        depends_on = list(raw_depends_on) if isinstance(raw_depends_on, list) else []
        try:
            task = self.tasks.create_task(
                title,
                project=payload.get("project"),
                priority=str(payload.get("priority") or "mittel"),
                deadline=payload.get("deadline"),
                tags=tags,
                depends_on=depends_on,
                source="manual",
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "task": task}

    def update_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("id") or "")
        if not task_id:
            return {"ok": False, "error": "missing_id"}
        fields = {
            key: value
            for key, value in payload.items()
            if key in {"title", "project", "priority", "deadline", "tags", "depends_on", "status"}
        }
        ok = self.tasks.update_task(task_id, **fields)
        return {"ok": ok, "task": self.tasks.get_task(task_id) if ok else None}

    def confirm_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("id") or "")
        if not task_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.tasks.confirm_task(task_id)}

    def reject_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("id") or "")
        if not task_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.tasks.reject_task(task_id)}

    def delete_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("id") or "")
        if not task_id:
            return {"ok": False, "error": "missing_id"}
        return {"ok": self.tasks.delete_task(task_id)}

    def record_voice_performance(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = VOICE_PERFORMANCE_LOG.record(payload)
        return {"ok": entry is not None}

    def voice_performance_stats(self, query: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(query.get("limit") or 50), 200))
        return VOICE_PERFORMANCE_LOG.stats(limit=limit)

    def voice_mode_status(self) -> dict[str, Any]:
        mode = normalize_voice_mode(str((self.memory.get("settings") or {}).get("voice_mode") or ""))
        return {"mode": mode, "available_modes": list(VOICE_MODES)}

    def set_voice_mode(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = normalize_voice_mode(str(payload.get("mode") or ""))
        settings = self.memory.get("settings") or {}
        settings["voice_mode"] = mode
        self.memory.set("settings", settings)
        return {"ok": True, "mode": mode}

    def create_mail_reply_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Öffnet einen Antwort-Entwurf in Mail.app - sendet nichts, der Nutzer prüft
        und verschickt selbst. Gated hinter der mail-Berechtigung wie jeder andere
        Mail-Zugriff (siehe DATA_FLOW.md)."""
        if not self.permissions.is_allowed("mail"):
            return {"ok": False, "error": "mail_permission_required"}
        message_id = str(payload.get("message_id") or "")
        body = str(payload.get("body") or "")
        if not message_id or not body:
            return {"ok": False, "error": "missing_message_id_or_body"}
        try:
            opened = create_reply_draft(
                message_id,
                body,
                account_name=payload.get("account_name"),
                mailbox_name=payload.get("mailbox_name"),
            )
        except Exception as exc:
            return {"ok": False, "error": _safe_error(exc)}
        return {"ok": opened}

    def health(self) -> dict[str, Any]:
        model_status = self.models.status()
        return {
            "ok": True,
            "name": "Jarvis Local Server",
            "provider": model_status.provider,
            "active_model": model_status.active_model,
            "openai_enabled": model_status.openai_enabled,
            "ollama_installed": model_status.ollama_installed,
            "ollama_running": model_status.ollama_running,
        }

    def chat(self, message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            user_name = str(self.config.get("creator_name") or "Nutzer").strip() or "Nutzer"
            return {"answer": f"Ich brauche eine konkrete Eingabe, {user_name}.", "source": "local", "model": self.models.active_model}

        self._pipeline_log("userMessage", text=text, history=history)
        answer = self._answer_with_core(text, transient_history=self._clean_history(history))
        voice_mode = normalize_voice_mode(str((self.memory.get("settings") or {}).get("voice_mode") or ""))
        return {
            "answer": answer,
            "source": self._last_answer_source,
            "model": self._last_answer_model,
            "voice_output_suppressed": voice_mode_suppresses_voice_output(voice_mode),
        }

    def scan_status_payload(self) -> dict[str, Any]:
        return {
            "mail_scan": self._load_scan_status(
                self._mail_scan_status_path,
                fallback=self._scan_progress("idle", "Noch kein Mail-Scan ausgeführt."),
            ),
            "mail_background": self._mail_background_status(),
            "photos": self._photos_status(),
            "photos_vision": self._photos_vision_status(),
            "files": self._files_status(),
            "model_pull": self._load_scan_status(
                self._model_pull_status_path,
                fallback=self._scan_progress("idle", "Kein Modell-Download aktiv."),
            ),
        }

    PULLABLE_MODELS = {"gemma3:4b", "qwen3:4b"}

    def start_model_pull(self, model: str) -> dict[str, Any]:
        normalized = str(model or "").strip()
        if normalized not in self.PULLABLE_MODELS:
            return self._scan_progress(
                "failed",
                f"{normalized or 'Dieses Modell'} kann nicht per Ein-Klick-Download geladen werden.",
                error_message="unsupported_model",
            )

        started_at = datetime_now()
        self._save_scan_status(
            self._model_pull_status_path,
            self._scan_progress(
                "downloading",
                f"Download von {normalized} wird vorbereitet.",
                started_at=started_at,
                stats={"model": normalized},
            ),
        )
        with self._model_pull_lock:
            if self._model_pull_thread is not None and self._model_pull_thread.is_alive():
                return self._load_scan_status(
                    self._model_pull_status_path,
                    fallback=self._scan_progress("downloading", "Download läuft bereits.", stats={"model": normalized}),
                )
            self._model_pull_thread = threading.Thread(
                target=self._run_model_pull, args=(normalized, started_at), daemon=True
            )
            self._model_pull_thread.start()
        return self._load_scan_status(
            self._model_pull_status_path,
            self._scan_progress("downloading", f"Download von {normalized} wird vorbereitet.", stats={"model": normalized}),
        )

    def _run_model_pull(self, model: str, started_at: str) -> None:
        layer_progress: dict[str, tuple[int, int]] = {}
        try:
            request = urllib.request.Request(
                f"{ollama_base_url()}/api/pull",
                data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1800) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status_text = str(payload.get("status") or "")
                    digest = payload.get("digest")
                    if digest:
                        layer_progress[str(digest)] = (
                            int(payload.get("completed") or 0),
                            int(payload.get("total") or 0),
                        )

                    total_all = sum(total for _, total in layer_progress.values())
                    completed_all = sum(completed for completed, _ in layer_progress.values())
                    is_done = status_text == "success"

                    self._save_scan_status(
                        self._model_pull_status_path,
                        self._scan_progress(
                            "completed" if is_done else "downloading",
                            status_text or f"Lädt {model} herunter.",
                            current_item=completed_all,
                            total_items=total_all,
                            started_at=started_at,
                            finished_at=datetime_now() if is_done else None,
                            stats={"model": model},
                        ),
                    )
        except Exception as exc:
            self._save_scan_status(
                self._model_pull_status_path,
                self._scan_progress(
                    "failed",
                    f"Download von {model} fehlgeschlagen.",
                    started_at=started_at,
                    finished_at=datetime_now(),
                    error_message=str(exc) or type(exc).__name__,
                    stats={"model": model},
                ),
            )

    def start_mail_folder_scan(self) -> dict[str, Any]:
        started_at = datetime_now()
        self._save_scan_status(
            self._mail_scan_status_path,
            self._scan_progress("preparing", "Apple-Mail-Ordner werden vorbereitet.", started_at=started_at),
        )
        with self._mail_scan_lock:
            if self._mail_scan_thread is not None and self._mail_scan_thread.is_alive():
                return self._load_scan_status(
                    self._mail_scan_status_path,
                    fallback=self._scan_progress("scanning", "Mail-Scan läuft bereits."),
                )
            self._mail_scan_thread = threading.Thread(target=self._run_mail_folder_scan, args=(started_at,), daemon=True)
            self._mail_scan_thread.start()
        return self._load_scan_status(self._mail_scan_status_path, self._scan_progress("preparing", "Apple-Mail-Ordner werden vorbereitet."))

    def _run_mail_folder_scan(self, started_at: str) -> None:
        try:
            self._save_scan_status(
                self._mail_scan_status_path,
                self._scan_progress("scanning", "Apple-Mail-Ordner werden gescannt.", started_at=started_at),
            )
            mailboxes = list_mailboxes(max_mailboxes=200)
            total_messages = sum(max(0, int(mailbox.message_count)) for mailbox in mailboxes)
            status = self._scan_progress(
                "completed",
                "Mail-Ordner-Scan fertig.",
                current_item=len(mailboxes),
                total_items=len(mailboxes),
                started_at=started_at,
                finished_at=datetime_now(),
                stats={
                    "folders_found": len(mailboxes),
                    "folders_scanned": len(mailboxes),
                    "mails_found": total_messages,
                    "mails_indexed": total_messages,
                    "current_folder": mailboxes[-1].mailbox if mailboxes else "",
                    "last_successful_scan": datetime_now(),
                },
            )
        except Exception as exc:
            status = self._scan_progress(
                "failed",
                "Mail-Ordner-Scan fehlgeschlagen.",
                started_at=started_at,
                finished_at=datetime_now(),
                error_message=str(exc) or type(exc).__name__,
            )
        self._save_scan_status(self._mail_scan_status_path, status)

    def start_mail_background_scan(self) -> dict[str, Any]:
        worker = self._ensure_mail_worker()
        worker.request_scan(reason="manual")
        return self._mail_background_status()

    def start_photo_index_scan(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        started_at = datetime_now()
        try:
            index.progress_path.unlink()
        except OSError:
            pass
        self._save_photo_progress(self._scan_progress("preparing", "Fotoindex wird vorbereitet.", started_at=started_at))
        with self._photo_scan_lock:
            if self._photo_scan_thread is not None and self._photo_scan_thread.is_alive():
                return self._photos_status()
            self._photo_scan_thread = threading.Thread(target=self._run_photo_index_scan, args=(started_at,), daemon=True)
            self._photo_scan_thread.start()
        return self._photos_status()

    def _run_photo_index_scan(self, started_at: str) -> None:
        index = PhotoIndex(self.config)
        try:
            count = index.scan()
            status = self._photos_status()
            status["status"] = "completed"
            status["currentLabel"] = "Fotoindex fertig."
            status["currentItem"] = int(status.get("totalItems") or count)
            status["finishedAt"] = datetime_now()
            self._save_photo_progress(status)
        except Exception as exc:
            status = self._scan_progress(
                "failed",
                "Fotoindex fehlgeschlagen.",
                started_at=started_at,
                finished_at=datetime_now(),
                error_message=str(exc) or type(exc).__name__,
            )
            self._save_photo_progress(status)

    def photo_permission_status(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        return {"status": index.permission_status()}

    def request_photo_permission(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        return {"message": index.request_permission(), "progress": self._photos_status()}

    def reset_photo_index(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        if index.cache_path.exists():
            index.cache_path.unlink()
        status = self._photos_status()
        status["currentLabel"] = "Fotoindex wurde zurückgesetzt."
        return status

    def local_photo_vision_status(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        return index.local_vision_status()

    def calendar_overview(self) -> dict[str, Any]:
        if self.permissions.is_allowed("calendar"):
            try:
                upcoming = list_upcoming_calendar_items(limit=5).get("items", [])
                calendar_error = ""
            except Exception as exc:
                upcoming = []
                calendar_error = str(exc)
            calendar_message = "Nächste Termine geladen." if upcoming else "Keine kommenden Termine gefunden."
        else:
            upcoming, calendar_error = [], ""
            calendar_message = "Kalender-Zugriff noch nicht aktiviert."

        if self.permissions.is_allowed("reminders"):
            try:
                reminders = list_open_reminders(limit=5).get("items", [])
                reminder_error = ""
            except Exception as exc:
                reminders = []
                reminder_error = str(exc)
            reminder_message = "Offene Erinnerungen geladen." if reminders else "Keine offenen Erinnerungen gefunden."
        else:
            reminders, reminder_error = [], ""
            reminder_message = "Erinnerungen-Zugriff noch nicht aktiviert."

        return {
            "calendar": {
                "items": upcoming,
                "count": len(upcoming),
                "message": calendar_message,
                "error": calendar_error,
            },
            "reminders": {
                "items": reminders,
                "count": len(reminders),
                "message": reminder_message,
                "error": reminder_error,
            },
        }

    def mail_overview(self) -> dict[str, Any]:
        """Dashboard Mail card data - unread count + a couple of recent subjects.
        Gated behind is_allowed("mail") the same way calendar_overview() is gated,
        so this never fires Mail.app AppleScript before the user has explicitly
        opted in via Datenschutz."""
        if not self.permissions.is_allowed("mail"):
            return {"unread_count": 0, "messages": [], "message": "Mail-Zugriff noch nicht aktiviert.", "error": ""}
        try:
            unread = unread_inbox_count()
            recent = list_inbox_messages(max_messages=3)
            return {
                "unread_count": unread,
                "messages": [{"sender": m.sender, "subject": m.subject} for m in recent],
                "message": f"{unread} ungelesen." if unread else "Keine ungelesenen Mails.",
                "error": "",
            }
        except Exception as exc:
            return {"unread_count": 0, "messages": [], "message": "Mail konnte nicht geladen werden.", "error": str(exc)}

    def music_overview(self) -> dict[str, Any]:
        """Dashboard Musik card data. Gated behind is_allowed("music") the same way
        calendar_overview()/mail_overview() are gated - the private MediaRemote API
        NowPlayingService.swift used before this couldn't work at all for a third-party
        app (mediaremoted rejects it with "Operation not permitted", confirmed via
        Console - see project memory), so this replaces it with the same AppleScript
        approach music_client.py already used for playback control."""
        if not self.permissions.is_allowed("music"):
            return {"track": None, "message": "Musik-Zugriff noch nicht aktiviert.", "error": ""}
        try:
            track = music_now_playing()
            message = "Wiedergabe läuft." if track else "Gerade läuft nichts."
            return {"track": track, "message": message, "error": ""}
        except Exception as exc:
            return {"track": None, "message": "Musik-Status konnte nicht geladen werden.", "error": str(exc)}

    def daily_briefing(self) -> dict[str, Any]:
        # Each integration only gets touched (live AppleScript) once its own
        # Datenschutz toggle is on - a briefing request must never be what
        # silently first-triggers Kalender/Erinnerungen/Mail access.
        if self.permissions.is_allowed("calendar"):
            try:
                from datetime import datetime

                until = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
                # "heutige Termine", nicht "naechste 5 Termine" - Aufgabe 3 aus
                # plans/2026-08-08-jarvis-tagesbriefing-ausbauen.md. events_on_date()
                # filtert zusaetzlich robust anhand start_dt, das AppleScript-until
                # bleibt nur die grobe Vorfilterung.
                calendar_items = events_on_date(
                    list_upcoming_calendar_items(limit=20, until=until).get("items", [])
                )
            except Exception:
                calendar_items = []
        else:
            calendar_items = []

        if self.permissions.is_allowed("reminders"):
            try:
                reminder_items = list_open_reminders(limit=5).get("items", [])
            except Exception:
                reminder_items = []
        else:
            reminder_items = []

        try:
            # Aufgaben sind rein lokale, interne Daten (kein macOS-Automation-Zugriff
            # wie Mail/Kalender), deshalb kein eigenes Permission-Gate - "vorgeschlagen"
            # (noch unbestaetigt) bewusst ausgeschlossen, siehe Plan Design-Entscheidung 1.
            open_tasks = self.tasks.list_tasks(status="offen") + self.tasks.list_tasks(status="in_arbeit")
        except Exception:
            open_tasks = []

        mail_summary = self._mail_background_status().get("message", "") if self.permissions.is_allowed("mail") else ""

        # Reads the events already surfaced by the periodic /api/proactivity/events
        # poll (recent_history()), rather than calling evaluate() again here - evaluate()
        # applies cooldown/throttle as a side effect (marks events "shown"), so calling
        # it from two different endpoints would make whichever fires first silently
        # swallow the notification for the other.
        try:
            recent_proactive = [
                entry
                for entry in PROACTIVITY_ENGINE.recent_history(limit=20)
                if _minutes_since(entry.get("created_at")) <= 30
            ]
        except Exception:
            recent_proactive = []
        proactivity_summary = ""
        if recent_proactive:
            noun = "Hinweis" if len(recent_proactive) == 1 else "Hinweise"
            proactivity_summary = f"{len(recent_proactive)} proaktive(r) {noun}: " + "; ".join(
                str(entry.get("message") or "") for entry in recent_proactive[:3]
            )

        briefing = build_daily_briefing(
            calendar_items=calendar_items,
            reminders=reminder_items,
            tasks=open_tasks,
            mail_summary=mail_summary,
            system_summary=f"Modell: {self.models.active_model}. Provider: {self.models.provider}.",
        )
        if proactivity_summary:
            briefing = f"{briefing} {proactivity_summary}."
        return {
            "briefing": briefing,
            "calendar_count": len(calendar_items),
            "reminders_count": len(reminder_items),
            "tasks_count": len(open_tasks),
            "calendar_allowed": self.permissions.is_allowed("calendar"),
            "reminders_allowed": self.permissions.is_allowed("reminders"),
            "proactive_events": recent_proactive,
        }

    def start_local_photo_vision_analysis(self, max_items: int | None = None) -> dict[str, Any]:
        started_at = datetime_now()
        index = PhotoIndex(self.config)
        try:
            index.local_vision_progress_path.unlink()
        except OSError:
            pass
        self._save_local_photo_vision_progress(
            self._scan_progress(
                "preparing",
                "Lokale Fotoanalyse wird vorbereitet.",
                started_at=started_at,
                stats={"model": index.local_vision_status().get("model", "")},
            )
        )
        with self._photo_scan_lock:
            vision_thread = getattr(self, "_photo_vision_thread", None)
            if vision_thread is not None and vision_thread.is_alive():
                return self._photos_vision_status()
            self._photo_vision_thread = threading.Thread(
                target=self._run_local_photo_vision_analysis,
                args=(max_items,),
                daemon=True,
            )
            self._photo_vision_thread.start()
        return self._photos_vision_status()

    def _run_local_photo_vision_analysis(self, max_items: int | None = None) -> None:
        index = PhotoIndex(self.config)
        try:
            index.analyze_with_local_vision(max_items=max_items)
        except Exception as exc:
            status = self._scan_progress(
                "failed",
                "Lokale Fotoanalyse fehlgeschlagen.",
                finished_at=datetime_now(),
                error_message=str(exc) or type(exc).__name__,
                stats={"model": index.local_vision_status().get("model", ""), "errors": 1},
            )
            self._save_local_photo_vision_progress(status)

    def reset_local_photo_vision(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        removed = index.reset_local_vision_descriptions()
        status = self._scan_progress(
            "idle",
            f"Lokale KI-Beschreibungen gelöscht: {removed}.",
            stats={"local_descriptions": 0, "removed": removed},
        )
        self._save_local_photo_vision_progress(status)
        return status

    def start_file_index_scan(self) -> dict[str, Any]:
        started_at = datetime_now()
        self._save_scan_status(
            self._file_scan_status_path,
            self._scan_progress("preparing", "Dateiwurzeln werden vorbereitet.", started_at=started_at),
        )
        with self._file_scan_lock:
            if self._file_scan_thread is not None and self._file_scan_thread.is_alive():
                return self._files_status()
            self._file_scan_thread = threading.Thread(target=self._run_file_index_scan, args=(started_at,), daemon=True)
            self._file_scan_thread.start()
        return self._files_status()

    def reset_file_index(self) -> dict[str, Any]:
        for path in (self._file_index_path, self._file_scan_status_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        status = self._scan_progress("idle", "Dateiindex wurde zurückgesetzt.")
        self._save_scan_status(self._file_scan_status_path, status)
        return status

    def search_file_index_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        root_name = str(payload.get("root") or "").strip() or None
        results = search_file_index_entries(query, root_name=root_name, max_results=40) or []
        message = search_files(query, root_hint=root_name or "home", config=self.config, max_results=12)
        return {"query": query, "message": message, "results": results}

    def move_file_search_results(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        target_folder = str(payload.get("target_folder") or "").strip()
        root = str(payload.get("root") or "desktop").strip()
        message = move_indexed_matches_to_folder(query, target_folder, root_hint=root, config=self.config)
        return {"message": message, "progress": self._files_status()}

    def _run_file_index_scan(self, started_at: str) -> None:
        started = time.monotonic()
        try:
            roots = self._file_scan_roots()
            total_items = 0
            root_summaries: list[dict[str, Any]] = []
            self._save_scan_status(
                self._file_scan_status_path,
                self._scan_progress(
                    "preparing",
                    "Dateien werden gezählt.",
                    started_at=started_at,
                    stats={"roots_found": len(roots), "roots_scanned": 0},
                ),
            )
            for name, root in roots:
                count = 0
                try:
                    for _path in self._iter_file_index_paths(root):
                        count += 1
                except Exception as exc:
                    # Previously silent: a real permission/IO error here looked
                    # identical to "this folder is genuinely empty" (count stayed 0).
                    print(f"Datei-Index: Zählung für {root} fehlgeschlagen: {_safe_error(exc)}", file=sys.stderr)
                    count = 0
                total_items += count
                root_summaries.append({"name": name, "path": str(root), "count": count})

            entries: list[dict[str, Any]] = []
            folders_found = 0
            files_found = 0
            bytes_total = 0
            extension_counts: dict[str, int] = {}
            roots_scanned = 0
            current_item = 0

            for root_info, (_name, root) in zip(root_summaries, roots):
                roots_scanned += 1
                label = f"Scanne {root_info['name']}"
                self._save_scan_status(
                    self._file_scan_status_path,
                    self._scan_progress(
                        "scanning",
                        label,
                        current_item=current_item,
                        total_items=total_items,
                        started_at=started_at,
                        stats={
                            "roots_found": len(roots),
                            "roots_scanned": roots_scanned - 1,
                            "files_found": files_found,
                            "folders_found": folders_found,
                            "current_root": root_info["path"],
                        },
                    ),
                )
                for path in self._iter_file_index_paths(root):
                    current_item += 1
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    is_dir = path.is_dir()
                    if is_dir:
                        folders_found += 1
                    else:
                        files_found += 1
                        bytes_total += int(stat.st_size)
                        suffix = path.suffix.lower().lstrip(".") or "ohne_endung"
                        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1

                    relative = ""
                    try:
                        relative = str(path.relative_to(root))
                    except ValueError:
                        relative = path.name
                    entries.append(
                        {
                            "root": root_info["name"],
                            "name": path.name,
                            "kind": "folder" if is_dir else "file",
                            "relative_path": relative,
                            "path": str(path),
                            "size": int(stat.st_size),
                            "modified": datetime_now_from_timestamp(stat.st_mtime),
                            "extension": path.suffix.lower().lstrip("."),
                        }
                    )
                    if current_item == 1 or current_item % 25 == 0:
                        self._save_scan_status(
                            self._file_scan_status_path,
                            self._scan_progress(
                                "indexing",
                                f"Indexiere {path.name}",
                                current_item=current_item,
                                total_items=total_items,
                                started_at=started_at,
                                stats={
                                    "roots_found": len(roots),
                                    "roots_scanned": roots_scanned,
                                    "files_found": files_found,
                                    "folders_found": folders_found,
                                    "items_indexed": len(entries),
                                    "current_root": root_info["path"],
                                    "current_item": path.name,
                                    "total_bytes": bytes_total,
                                },
                            ),
                        )

            finished_at = datetime_now()
            duration_seconds = round(time.monotonic() - started, 2)
            top_extensions = ", ".join(
                f"{ext}: {count}"
                for ext, count in sorted(extension_counts.items(), key=lambda item: item[1], reverse=True)[:8]
            )
            index_payload = {
                "last_scan_at": finished_at,
                "scan_started_at": started_at,
                "roots": root_summaries,
                "entries": entries,
                "stats": {
                    "roots_found": len(roots),
                    "roots_scanned": len(roots),
                    "files_found": files_found,
                    "folders_found": folders_found,
                    "items_indexed": len(entries),
                    "total_bytes": bytes_total,
                    "top_extensions": top_extensions,
                    "duration_seconds": duration_seconds,
                },
            }
            self._file_index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file_index_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(index_payload, indent=4, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._file_index_path)

            status = self._scan_progress(
                "completed",
                "Dateiindex fertig.",
                current_item=len(entries),
                total_items=max(total_items, len(entries)),
                started_at=started_at,
                finished_at=finished_at,
                stats={
                    **index_payload["stats"],
                    "last_successful_scan": finished_at,
                    "database_bytes": self._file_index_path.stat().st_size if self._file_index_path.exists() else 0,
                },
            )
        except Exception as exc:
            status = self._scan_progress(
                "failed",
                "Dateiindex fehlgeschlagen.",
                started_at=started_at,
                finished_at=datetime_now(),
                error_message=str(exc) or type(exc).__name__,
            )
        self._save_scan_status(self._file_scan_status_path, status)

    def probe_permission(self, permission: str) -> None:
        """Makes exactly one minimal live call for a freshly-granted integration,
        so the native macOS consent dialog appears right now - at the moment the
        user opted in via the Datenschutz toggle - instead of silently the next
        time some background call happens to touch it. Best-effort: swallows
        errors, since a macOS "Don't Allow" here is a legitimate outcome, not a
        bug, and must not break the toggle response."""
        try:
            if permission == "calendar":
                list_upcoming_calendar_items(limit=1)
            elif permission == "reminders":
                list_open_reminders(limit=1)
            elif permission == "mail":
                list_mailboxes()
            elif permission == "contacts":
                from contacts_client import list_contacts
                list_contacts(limit=1)
            elif permission == "music":
                from music_client import list_playlists
                list_playlists(limit=1)
            # "notes" has no side-effect-free read - its first real create/append
            # command is what triggers the OS prompt instead, which still matches
            # "on first actual use".
        except Exception:
            pass

    def _ensure_mail_worker(self) -> MailBackgroundWorker:
        if self.mail_worker is None:
            self.mail_worker = MailBackgroundWorker(self.config, self.llm)
            self.mail_worker.start()
        return self.mail_worker

    def _ensure_news_worker(self) -> NewsBackgroundWorker:
        if self.news_worker is None:
            self.news_worker = NewsBackgroundWorker(self.config, self.llm)
            self.news_worker.start()
        return self.news_worker

    def _ensure_photo_worker(self) -> PhotoBackgroundWorker:
        if self.photo_worker is None:
            self.photo_worker = PhotoBackgroundWorker(self.config)
            self.photo_worker.start()
        return self.photo_worker

    def pending_calendar_actions(self) -> dict[str, Any]:
        return {"actions": self._ensure_mail_worker().pending_calendar_actions()}

    def resolve_calendar_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_key = str(payload.get("action_key") or "")
        if not action_key:
            return {"ok": False, "error": "missing_action_key"}
        return self._ensure_mail_worker().resolve_pending_calendar_action(
            action_key, approve=bool(payload.get("approve"))
        )

    def _proactivity_context(self) -> dict[str, Any]:
        """Only ever reads data sources the user has already consented to via the
        Permission Manager - proactivity must never be what silently first-triggers
        a Mail/Calendar access the user hasn't opted into."""
        pending_calendar_actions: list[dict[str, Any]] = []
        new_mail_messages: list[dict[str, Any]] = []
        if self.permissions.is_allowed("mail"):
            try:
                pending_calendar_actions = self._ensure_mail_worker().pending_calendar_actions()
                new_mail_messages = self._mail_background_status().get("new_messages", []) or []
            except Exception:
                pass

        pending_confirmation_facts = [
            fact
            for fact in self.memory.all_facts(include_expired=True, include_rejected=True)
            if fact.get("status") == "pending_confirmation"
        ]

        # Kalender-Nudges (rule_calendar_event_starting_soon/_overlap, siehe
        # plans/2026-08-08-jarvis-termin-nudges.md) - nur lesen, wenn die
        # Kalender-Permission bereits erteilt ist, exakt wie beim Mail-Block oben:
        # Proactivity darf nie der erste, stille Ausloeser fuer einen Kalenderzugriff
        # sein.
        upcoming_calendar_events: list[dict[str, Any]] = []
        if self.permissions.is_allowed("calendar"):
            try:
                from datetime import datetime, timedelta

                lookahead_hours = float(self.config.get("proactivity_calendar_lookahead_hours", 6))
                until = datetime.now() + timedelta(hours=lookahead_hours)
                upcoming_calendar_events = list_upcoming_calendar_items(limit=20, until=until).get("items", [])
            except Exception:
                pass

        # Baustein D (Verhaltensmuster erkennen), siehe
        # plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md - nur lesen, wenn die
        # eigene, standardmaessig deaktivierte "usage_patterns"-Berechtigung erteilt
        # ist. Liefert bereits fertig ausgewertete Muster (Kategorie + grobe Zeit),
        # nie Rohdaten/Text.
        recurring_usage_patterns: list[dict[str, Any]] = []
        if self.permissions.is_allowed("usage_patterns"):
            try:
                min_weeks = int(self.config.get("proactivity_pattern_min_weeks", 3))
                lookback_weeks = int(self.config.get("proactivity_pattern_lookback_weeks", 4))
                recurring_usage_patterns = recurring_patterns(min_weeks=min_weeks, lookback_weeks=lookback_weeks)
            except Exception:
                pass

        # Baustein "Wichtige Nachrichten", siehe
        # plans/2026-08-09-jarvis-news-baustein.md - nur lesen, wenn die
        # "internet"-Berechtigung bereits erteilt ist, exakt wie bei den anderen
        # Bloecken oben: Proaktivitaet darf nie der erste stille Ausloeser fuer
        # einen noch nicht erteilten Zugriff sein. drain_important_news() leert
        # die Warteliste beim Lesen - jede Meldung wird also genau einmal
        # weitergereicht, nicht bei jedem Poll erneut.
        important_news: list[dict[str, Any]] = []
        if self.permissions.is_allowed("internet"):
            try:
                important_news = self._ensure_news_worker().drain_important_news()
            except Exception:
                pass

        # Nur den Worker starten (nächtlicher Fotoscan + lokale Vision-Analyse,
        # siehe plans/2026-08-10-jarvis-foto-vision-lokal-aktivieren.md) - dieselbe
        # "beim ersten erlaubten Poll starten"-Stelle wird hier auch als
        # Startpunkt mitgenutzt, exakt wie bei den Blöcken oben nur lesend, wenn
        # die Berechtigung bereits erteilt ist. Seit
        # plans/2026-08-16-jarvis-proaktive-abschluss-meldung.md liefert der
        # zuletzt gespeicherte Lauf-Status auch etwas in den Proaktivitäts-Feed
        # (rule_photo_vision_analysis_completed in proactivity_rules.py).
        photo_vision_run: dict[str, Any] = {}
        if self.permissions.is_allowed("photos"):
            try:
                worker = self._ensure_photo_worker()
                photo_vision_run = worker.index.local_vision_run_summary()
            except Exception:
                pass

        return {
            "config": self.config,
            "pending_calendar_actions": pending_calendar_actions,
            "new_mail_messages": new_mail_messages,
            "pending_confirmation_facts": pending_confirmation_facts,
            "upcoming_calendar_events": upcoming_calendar_events,
            "recurring_usage_patterns": recurring_usage_patterns,
            "important_news": important_news,
            "photo_vision_run": photo_vision_run,
        }

    def proactivity_events(self) -> dict[str, Any]:
        events = PROACTIVITY_ENGINE.evaluate(self._proactivity_context(), self.config)
        # Sobald die "Kalender-Vorschlaege warten auf Bestaetigung"-Meldung tatsaechlich
        # ausgeliefert wird, einen Merker hinterlegen, an den ein spaeterer freier
        # Chat-Satz ("das bestaetige ich nicht") anknuepfen kann - siehe
        # plans/2026-08-13-jarvis-kalender-vorschlaege-per-chat-bestaetigen.md.
        # handle_pending_action_flow() in jarvis.py liest/loescht diesen Schluessel.
        for event in events:
            if event.dedup_key == "pending_calendar_actions":
                action_keys = event.data.get("action_keys") or []
                if action_keys:
                    settings = self.memory.get("settings") or {}
                    settings["pending_mail_calendar_confirmation"] = {
                        "action_keys": action_keys,
                        "set_at": time.time(),
                    }
                    self.memory.set("settings", settings)
        return {"events": [event.to_dict() for event in events]}

    def proactivity_history(self) -> dict[str, Any]:
        return {"events": PROACTIVITY_ENGINE.recent_history()}

    def snooze_proactivity_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedup_key = str(payload.get("dedup_key") or "")
        if not dedup_key:
            return {"ok": False, "error": "missing_dedup_key"}
        PROACTIVITY_ENGINE.snooze(dedup_key, minutes=int(payload.get("minutes") or 60))
        return {"ok": True}

    def dismiss_proactivity_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedup_key = str(payload.get("dedup_key") or "")
        if not dedup_key:
            return {"ok": False, "error": "missing_dedup_key"}
        PROACTIVITY_ENGINE.dismiss_forever(dedup_key)
        return {"ok": True}

    def _mail_background_status(self) -> dict[str, Any]:
        worker = self._ensure_mail_worker()
        cache = worker._load_cache()
        is_active = worker.thread is not None and worker.thread.is_alive()
        is_scanning = worker.scan_thread is not None and worker.scan_thread.is_alive()
        status_name = "scanning" if is_scanning else ("idle" if is_active else "cancelled")
        known = len(cache.get("known_message_ids", []) or [])
        new_count = len(cache.get("new_messages", []) or [])
        stats = {
            "background_active": is_active,
            "background_scanning": is_scanning,
            "last_scan": cache.get("last_scan_at", ""),
            "next_update": self.config.get("background_mail_morning_time", "07:00"),
            "new_mails": new_count,
            "mails_indexed": known,
            "last_error": cache.get("last_error", ""),
        }
        return self._scan_progress(
            status_name,
            "Mail-Hintergrundscan läuft." if is_scanning else ("Mail-Hintergrundscan aktiv." if is_active else "Mail-Hintergrundscan pausiert."),
            current_item=known,
            total_items=max(known, 1),
            started_at=cache.get("last_scan_at"),
            finished_at=cache.get("last_scan_at"),
            error_message=cache.get("last_error") or None,
            stats=stats,
        )

    def _photos_status(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        cache = index._load_cache()
        entries = list(cache.get("entries", []) or [])
        stats = dict(cache.get("stats") or {})
        progress = dict(cache.get("progress") or {})
        if index.progress_path.exists():
            try:
                file_progress = json.loads(index.progress_path.read_text(encoding="utf-8"))
                if isinstance(file_progress, dict):
                    progress = file_progress
            except Exception:
                pass
        total = int(stats.get("photos_found") or len(entries))
        videos = int(stats.get("videos_found") or 0)
        label_count = len({
            str(label)
            for entry in entries
            for label in (entry.get("labels", []) or [])
            if str(label).strip()
        })
        status_name = str(progress.get("status") or ("completed" if cache.get("last_scan_at") else "idle"))
        current = int(progress.get("currentItem") or len(entries))
        total_items = int(progress.get("totalItems") or max(total + videos, len(entries), 0))
        # cache["last_error"] blieb bisher stehen, bis der naechste Scan
        # VOLLSTAENDIG durchgelaufen war, und wurde hier unbedingt vor dem
        # frischen progress.get("errorMessage") geprueft - waehrend ein neuer,
        # erfolgreich laufender Scan (status "scanning"/"indexing", kein
        # aktueller Fehler) noch nicht fertig war, zeigte das Dashboard also
        # weiterhin den ALTEN Fehler eines frueheren, laengst ueberholten
        # Versuchs an ("Fotoindex fehlgeschlagen"), obwohl der aktuelle Scan
        # tatsaechlich fehlerfrei voranschritt. Live beobachtet 2026-08-19:
        # ein Scan lief sichtbar bei Item 28/3798 ohne Fehler, das Dashboard
        # zeigte trotzdem "Fehler: Fotos-Freigabe wurde noch nicht angefragt"
        # von einem Versuch Minuten zuvor. Der alte last_error ist nur noch
        # relevant, wenn gerade NICHT aktiv gescannt wird.
        live_error = progress.get("errorMessage")
        is_actively_running = status_name in {"scanning", "indexing"}
        error_message = live_error if (live_error or is_actively_running) else cache.get("last_error")
        payload = self._scan_progress(
            status_name,
            str(progress.get("currentLabel") or ("Fotoindex bereit." if entries else "Noch kein Fotoindex.")),
            current_item=current,
            total_items=total_items,
            started_at=progress.get("startedAt") or cache.get("scan_started_at"),
            finished_at=progress.get("finishedAt") or cache.get("last_scan_at"),
            error_message=error_message,
            stats={
                "photos_found": total,
                "photos_indexed": len([entry for entry in entries if str(entry.get("mediaType") or "image") == "image"]),
                "videos_found": videos,
                "labels_recognized": label_count,
                "current_photo": progress.get("current_photo", ""),
                "last_successful_scan": cache.get("last_scan_at", ""),
                "database_bytes": index.cache_path.stat().st_size if index.cache_path.exists() else 0,
                "last_results": cache.get("last_results", []),
            },
        )
        return payload

    def _photos_vision_status(self) -> dict[str, Any]:
        index = PhotoIndex(self.config)
        cache = index._load_cache()
        entries = list(cache.get("entries", []) or [])
        local_count = len([entry for entry in entries if str(entry.get("local_vision_analyzed_at") or "").strip()])
        pending_count = len([
            entry
            for entry in entries
            if str(entry.get("mediaType") or "image") == "image"
            and not str(entry.get("local_vision_analyzed_at") or "").strip()
        ])
        progress = {}
        if index.local_vision_progress_path.exists():
            try:
                payload = json.loads(index.local_vision_progress_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    progress = payload
            except Exception:
                progress = {}
        vision_status = index.local_vision_status()
        status_name = str(progress.get("status") or ("completed" if local_count else "idle"))
        current = int(progress.get("currentItem") or local_count)
        total = int(progress.get("totalItems") or max(local_count + pending_count, local_count, 0))
        stats = dict(progress.get("stats") or {})
        return self._scan_progress(
            status_name,
            str(progress.get("currentLabel") or ("Lokale Fotoanalyse bereit." if local_count else vision_status.get("message", "Noch keine lokale Fotoanalyse."))),
            current_item=current,
            total_items=total,
            started_at=progress.get("startedAt") or cache.get("last_local_vision_scan_at"),
            finished_at=progress.get("finishedAt") or cache.get("last_local_vision_scan_at"),
            error_message=progress.get("errorMessage") or cache.get("last_local_vision_error") or None,
            stats={
                "model": vision_status.get("model", ""),
                "model_available": bool(vision_status.get("available")),
                "model_message": vision_status.get("message", ""),
                "analyzed": local_count,
                "pending": pending_count,
                "local_descriptions": local_count,
                "errors": stats.get("errors", 0),
                "current_photo": stats.get("current_photo", ""),
                "last_successful_scan": cache.get("last_local_vision_scan_at", ""),
            },
        )

    def _save_local_photo_vision_progress(self, progress: dict[str, Any]) -> None:
        index = PhotoIndex(self.config)
        index.local_vision_progress_path.write_text(json.dumps(progress, indent=4, ensure_ascii=False), encoding="utf-8")

    def _files_status(self) -> dict[str, Any]:
        fallback = self._scan_progress("idle", "Noch kein Dateiindex.")
        status = self._load_scan_status(self._file_scan_status_path, fallback)
        if not self._file_index_path.exists():
            return status
        try:
            index = json.loads(self._file_index_path.read_text(encoding="utf-8"))
            if not isinstance(index, dict):
                return status
            stats = dict(index.get("stats") or {})
            entries = list(index.get("entries") or [])
            status_stats = dict(status.get("stats") or {})
            status["stats"] = {
                **stats,
                **status_stats,
                "last_successful_scan": index.get("last_scan_at", ""),
                "database_bytes": self._file_index_path.stat().st_size,
                "index_entries": len(entries),
            }
            if status.get("status") in {"idle", "completed"}:
                status["status"] = "completed"
                status["currentLabel"] = "Dateiindex bereit."
                status["currentItem"] = int(stats.get("items_indexed") or len(entries))
                status["totalItems"] = int(stats.get("items_indexed") or len(entries))
                status["percentage"] = 100.0 if entries else 0.0
                status["finishedAt"] = index.get("last_scan_at")
        except Exception:
            pass
        return status

    def _file_scan_roots(self) -> list[tuple[str, Path]]:
        roots = configured_roots(self.config)
        preferred_names = ["desktop", "documents", "downloads", "jarvis"]
        result: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for name in preferred_names:
            path = roots.get(name)
            if path is None:
                continue
            resolved = str(path.expanduser().resolve())
            if resolved in seen or not path.exists() or not path.is_dir():
                continue
            result.append((name, path))
            seen.add(resolved)
        for path_text in self.config.get("file_access_roots", []) or []:
            path = Path(str(path_text)).expanduser()
            if not path.exists() or not path.is_dir():
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            result.append((normalize_name(path.name) or path.name, path))
            seen.add(resolved)
        return result

    def _iter_file_index_paths(self, root: Path):
        excluded_names = {
            ".git",
            ".venv",
            "__pycache__",
            ".cache",
            ".build",
            "DerivedData",
            "node_modules",
            "Library",
            "System",
            "Applications",
            "Volumes",
        }
        excluded_suffixes = {
            ".app",
            ".framework",
            ".xcframework",
            ".sdk",
            ".xcodeproj",
            ".xcworkspace",
            ".playground",
            ".bundle",
            ".plugin",
        }
        resolved_root = root.resolve()
        pending = [resolved_root]

        while pending:
            current = pending.pop()
            try:
                children = list(current.iterdir())
            except OSError:
                continue

            for child in children:
                try:
                    relative = child.relative_to(resolved_root)
                except ValueError:
                    continue

                if any(part.startswith(".") for part in relative.parts):
                    continue
                if child.name in excluded_names:
                    continue
                if any(child.name.endswith(suffix) for suffix in excluded_suffixes):
                    continue

                yield child

                try:
                    if child.is_dir():
                        pending.append(child)
                except OSError:
                    continue

    def _save_photo_progress(self, progress: dict[str, Any]) -> None:
        index = PhotoIndex(self.config)
        cache = index._load_cache()
        cache["progress"] = progress
        index._save_cache(cache)

    def _load_scan_status(self, path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return fallback
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else fallback
        except Exception:
            return fallback

    def _save_scan_status(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _scan_progress(
        self,
        status: str,
        label: str,
        *,
        current_item: int = 0,
        total_items: int = 0,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        percentage = 0.0
        if total_items > 0:
            percentage = min(100.0, max(0.0, (float(current_item) / float(total_items)) * 100.0))
        return {
            "status": status,
            "currentItem": int(current_item),
            "totalItems": int(total_items),
            "percentage": percentage,
            "currentLabel": label,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "errorMessage": error_message,
            "stats": stats or {},
        }


    def enroll_voice_profile(self, audio_paths: list[str]) -> dict[str, Any]:
        """Einlernen der eigenen Stimme ueber die Einstellungen (nicht per
        Sprachbefehl - Leons ausdruecklicher Wunsch), siehe
        plans/2026-08-10-jarvis-sprecher-verifikation-weckwort.md. Nimmt mehrere
        kurze, bereits lokal aufgenommene WAV-Dateipfade entgegen (dieselbe
        AudioCaptureService-Aufnahme, die auch der Immer-Zuhoer-Modus nutzt)."""
        try:
            return self.voice_profile.enroll(audio_paths)
        except VoiceProfileError as exc:
            return {"ok": False, "error": str(exc)}

    def verify_voice_profile(self, audio_path: str) -> dict[str, Any]:
        """Prueft, ob eine kurze Aufnahme zu Leons eingelerntem Stimmprofil passt -
        aufgerufen vom Immer-Zuhoer-Modus direkt nach einem Weckwort-Treffer, BEVOR
        das Gespraech beginnt. Ohne eingelerntes Profil liefert
        VoiceProfileStore.verify() immer match=True - das Feature blockiert nie
        versehentlich jemanden, der es nicht aktiv eingerichtet hat."""
        threshold = float(self.config.get("speaker_verification_threshold", DEFAULT_SPEAKER_THRESHOLD))
        try:
            result = self.voice_profile.verify(audio_path, threshold=threshold)
            print(f"Sprecher-Verifikation: score={result.get('score')} threshold={threshold} match={result.get('match')}", flush=True)
            return result
        except VoiceProfileError as exc:
            # Ein Verifikations-Fehler (z.B. kaputte Aufnahme) darf Leon nicht
            # aussperren - im Zweifel durchlassen statt eine echte Anfrage von ihm
            # selbst stillschweigend zu blockieren.
            return {"match": True, "score": None, "reason": "error", "error": str(exc)}

    def reset_voice_profile(self) -> dict[str, Any]:
        return {"ok": self.voice_profile.reset()}

    def transcribe_voice(self, audio_path: str, sample_rate: float | None = None) -> dict[str, Any]:
        path = Path(str(audio_path or "")).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()

        try:
            if not path.exists():
                raise FileNotFoundError(str(path))

            def _load_audio(file_path: Path) -> tuple[np.ndarray, float]:
                with wave.open(str(file_path), "rb") as wav_file:
                    channels = wav_file.getnchannels()
                    frame_rate = float(wav_file.getframerate())
                    sample_width = wav_file.getsampwidth()
                    frames = wav_file.readframes(wav_file.getnframes())

                if sample_width == 2:
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                elif sample_width == 4:
                    audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    raise ValueError(f"Unsupported sample width: {sample_width}")

                if channels > 1:
                    audio = audio.reshape(-1, channels).mean(axis=1)

                if sample_rate and frame_rate and abs(frame_rate - float(sample_rate)) > 1.0 and audio.size > 16:
                    target_rate = float(sample_rate)
                    source_rate = frame_rate
                    duration = audio.size / source_rate
                    target_size = max(1, int(round(duration * target_rate)))
                    source_positions = np.linspace(0.0, duration, num=audio.size, endpoint=False)
                    target_positions = np.linspace(0.0, duration, num=target_size, endpoint=False)
                    audio = np.interp(target_positions, source_positions, audio).astype(np.float32)
                    frame_rate = target_rate

                return np.clip(audio.astype(np.float32), -1.0, 1.0), frame_rate

            audio, loaded_rate = _load_audio(path)
            engine = self._get_stt_engine()
            prepare = getattr(sys.modules.get("jarvis"), "prepare_audio_for_stt", None)
            if callable(prepare):
                audio = prepare(audio)
            else:
                audio = np.asarray(audio, dtype=np.float32)
            transcript = str(engine.transcribe(audio) or "").strip()
            self._pipeline_log("voiceTranscribed", path=str(path), transcript=transcript, sample_rate=loaded_rate)
            return {
                "transcript": transcript,
                "duration": len(audio) / float(loaded_rate or 16000.0),
                "speech_duration": len(audio) / float(loaded_rate or 16000.0),
                "sample_rate": loaded_rate,
                "source": self._last_answer_source,
                "model": self._last_answer_model,
            }
        except Exception as exc:
            self._pipeline_log(
                "voiceTranscribeError",
                path=str(path),
                error=_safe_detail(exc),
            )
            return {
                "transcript": "",
                "duration": 0.0,
                "speech_duration": 0.0,
                "sample_rate": float(sample_rate or 16000.0),
                "source": "local",
                "model": self.models.active_model,
                "error": _safe_detail(exc),
            }

    def listen_once(self, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if not self._listen_lock.acquire(blocking=False):
            return {
                "transcript": "",
                "answer": "Ich höre bereits zu. Multitasking beim Zuhören klingt heldenhaft, endet aber meistens in Chaos.",
                "status": "busy",
            }

        try:
            self._listen_cancel_event.clear()
            print("VoicePerformanceEvent: microphonePermission delegated_to_macos_python", file=sys.stderr)
            stt_engine = self._get_stt_engine()
            listener = self._get_audio_listener()
            self._last_partial_transcript = ""

            def _emit_partial_transcript(audio_preview, preview_stats: dict[str, float]) -> None:
                if not bool(self.config.get("live_transcript_enabled", True)):
                    return
                if self._listen_cancel_event.is_set() or self._partial_transcript_busy:
                    return
                self._partial_transcript_busy = True

                def worker() -> None:
                    acquired = False
                    try:
                        acquired = self._stt_lock.acquire(blocking=False)
                        if not acquired or self._listen_cancel_event.is_set():
                            return
                        core = self._core_module()
                        preview_audio = (
                            core.prepare_audio_for_stt(audio_preview)
                            if hasattr(core, "prepare_audio_for_stt")
                            else audio_preview
                        )
                        partial_text = str(stt_engine.transcribe(preview_audio) or "").strip()
                        partial_text = " ".join(partial_text.split())
                        if not partial_text or partial_text == self._last_partial_transcript:
                            return
                        self._last_partial_transcript = partial_text
                        payload = json.dumps(
                            {
                                "text": partial_text,
                                "duration": round(float(preview_stats.get("duration", 0.0)), 2),
                            },
                            ensure_ascii=False,
                        )
                        print(f"JarvisPartialTranscript: {payload}", file=sys.stderr, flush=True)
                    except Exception as exc:
                        print(f"JarvisPartialTranscriptError: {type(exc).__name__}", file=sys.stderr, flush=True)
                    finally:
                        if acquired:
                            self._stt_lock.release()
                        self._partial_transcript_busy = False

                threading.Thread(target=worker, daemon=True).start()

            utterance = listener.listen_for_utterance(on_audio_update=_emit_partial_transcript)
            if self._listen_cancel_event.is_set():
                return {"transcript": "", "answer": "", "status": "cancelled", "source": "local", "model": self.models.active_model}
            if utterance is None:
                return {"transcript": "", "answer": "Ich habe keine Sprache erkannt.", "status": "no_speech"}

            core = self._core_module()
            audio = core.prepare_audio_for_stt(utterance.audio) if hasattr(core, "prepare_audio_for_stt") else utterance.audio
            stats = utterance.stats
            with self._stt_lock:
                transcript = stt_engine.transcribe(audio)
            if self._listen_cancel_event.is_set():
                return {"transcript": "", "answer": "", "status": "cancelled", "source": "local", "model": self.models.active_model}

            transcript = str(transcript or "").strip()
            if transcript:
                self._last_partial_transcript = transcript
                payload = json.dumps({"text": transcript, "final": True}, ensure_ascii=False)
                print(f"JarvisFinalTranscript: {payload}", file=sys.stderr, flush=True)
            print("VoicePerformanceEvent: transcriptionDone", file=sys.stderr)
            self._pipeline_log("transcribedText", text=transcript, history=history)
            if not transcript:
                return {
                    "transcript": "",
                    "answer": "Ich habe Sie akustisch gehört, aber keinen Text verstanden.",
                    "status": "empty",
                    "source": "local",
                    "model": self.models.active_model,
                }

            def _emit_answer_chunk(chunk: str) -> None:
                payload = json.dumps({"chunk": str(chunk)}, ensure_ascii=False)
                print(f"JarvisStreamChunk: {payload}", file=sys.stderr, flush=True)

            answer = self._answer_with_core(
                transcript,
                transient_history=self._clean_history(history),
                on_llm_chunk=_emit_answer_chunk,
            )
            if self._listen_cancel_event.is_set():
                return {"transcript": "", "answer": "", "status": "cancelled", "source": "local", "model": self.models.active_model}
            return {
                "transcript": transcript,
                "answer": answer,
                "status": "ok",
                "stats": stats,
                "source": self._last_answer_source,
                "model": self._last_answer_model,
            }
        except Exception as exc:
            return {
                "transcript": "",
                "answer": _speech_error_message(exc),
                "status": _safe_error(exc),
                "source": "local",
                "model": self.models.active_model,
            }
        finally:
            self._listen_lock.release()

    def prewarm_voice_pipeline(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            self._get_stt_engine()
            audio = self._get_audio_listener().warm()
            return {
                "ok": bool(audio.get("ok")),
                "duration": round(time.perf_counter() - started, 3),
                "message": "Spracherkennung vorgewärmt.",
            }
        except Exception as exc:
            return {
                "ok": False,
                "duration": round(time.perf_counter() - started, 3),
                "message": _safe_error_detail(exc),
            }

    def cancel_listening(self) -> dict[str, Any]:
        try:
            self._listen_cancel_event.set()
            if self._audio_listener is not None:
                self._audio_listener.cancel_current_listen()
            return {"ok": True, "message": "Zuhören gestoppt."}
        except Exception as exc:
            return {"ok": False, "message": _safe_error_detail(exc)}

    def _get_stt_engine(self):
        # Double-checked locking: without self._stt_lock here, two overlapping
        # requests that both find self._stt_engine is None (e.g. /api/voice/prewarm
        # racing /api/listen right after startup) would each construct their own
        # STT engine - wasted model load work, and whichever assignment "wins" leaks
        # the other, already-initialized engine instance.
        if self._stt_engine is not None:
            return self._stt_engine
        with self._stt_lock:
            if self._stt_engine is None:
                _write_voice_bootstrap_status(
                    "loading_stt_model",
                    "Einmalige Vorbereitung: Sprachmodell wird geladen (kann beim ersten "
                    "Mal 1-2 Minuten dauern, danach deutlich schneller).",
                )
                try:
                    self._stt_engine = create_stt_engine(self.config)
                finally:
                    _clear_voice_bootstrap_status()
        return self._stt_engine

    def _get_audio_listener(self):
        # Same double-checked-locking concern as _get_stt_engine: without a lock,
        # concurrent callers (prewarm vs. listen_once) could each construct their
        # own StreamingAudioListener, and the discarded one may still hold an open
        # audio input stream/device handle.
        if self._audio_listener is not None:
            return self._audio_listener

        with self._audio_listener_lock:
            if self._audio_listener is not None:
                return self._audio_listener

            core = self._core_module()
            try:
                input_device = core.get_input_device() if hasattr(core, "get_input_device") else self.config.get("input_device")
            except Exception:
                input_device = self.config.get("input_device")

            self._audio_listener = StreamingAudioListener(
                samplerate=int(self.config.get("samplerate", 16000)),
                channels=1,
                input_device=input_device,
                chunk_seconds=float(self.config.get("chunk_seconds", 0.3)),
                silence_limit=float(self.config.get("silence_limit", 0.55)),
                volume_threshold=float(self.config.get("volume_threshold", 0.006)),
                min_speech_seconds=float(self.config.get("min_speech_seconds", 0.45)),
                min_audio_peak=float(self.config.get("min_audio_peak", 0.006)),
                max_recording_seconds=min(
                    float(self.config.get("max_recording_seconds", 20)),
                    float(self.config.get("voice_listen_max_seconds", 10)),
                ),
                partial_transcript_interval_seconds=float(self.config.get("partial_transcript_interval_seconds", 1.15)),
                partial_transcript_min_audio_seconds=float(self.config.get("partial_transcript_min_audio_seconds", 1.0)),
                partial_transcript_max_audio_seconds=float(self.config.get("partial_transcript_max_audio_seconds", 6.0)),
                is_speaking=self._tts_speaking.is_set,
            )
        return self._audio_listener

    def set_voice_speaking(self, speaking: bool) -> dict[str, Any]:
        if speaking:
            self._tts_speaking.set()
        else:
            self._tts_speaking.clear()
        return {"ok": True, "speaking": bool(speaking)}

    def _core_module(self):
        main_module = sys.modules.get("__main__")
        if main_module is not None and hasattr(main_module, "handle_model_command"):
            return main_module

        import jarvis as jarvis_core

        return jarvis_core

    def _clean_question(self, text: str) -> str:
        core = self._core_module()
        if hasattr(core, "remove_wake_word"):
            found, question = core.remove_wake_word(text)
            if found:
                return question or "Ja?"
        return text

    def _answer_with_core(
        self,
        text: str,
        transient_history: list[dict[str, str]] | None = None,
        on_llm_chunk=None,
    ) -> str:
        core = self._core_module()
        memory = self.memory
        question = self._clean_question(text)
        if not question.strip():
            question = "Ja?"
        self._last_answer_source = "local"
        self._last_answer_model = self.models.active_model

        try:
            if hasattr(core, "is_end_command") and core.is_end_command(question):
                return "Alles klar. Ich bin wieder still, bis Sie Jarvis sagen."

            if hasattr(core, "route_fast_intent"):
                fast_intent = core.route_fast_intent(question)
                if fast_intent is not None:
                    return self._finalize_answer(core, question, fast_intent)

            fast = self._handle_fast_commands(question)
            if fast is not None:
                return self._finalize_answer(core, question, fast)

            photo_fast = self._handle_local_photo_vision_command(question)
            if photo_fast is not None:
                return photo_fast

            # Gemeinsame Domaenen-Erkennungs-Kette mit main() (jarvis.py) - siehe
            # plans/2026-08-09-jarvis-cli-server-aufraeumen.md. Alles, was hier noch
            # steht, ist bewusst Server-spezifisch geblieben: Dashboard-Kurzbefehle
            # oben, Streaming/Pipeline-Logging/Worker-Zustand unten.
            workers = core.AnswerWorkers(
                photo_worker=self.photo_worker,
                mail_worker=self.mail_worker,
                model_manager=self.models,
            )

            first_chunk_sent = False

            def _forward_chunk(chunk: str) -> None:
                nonlocal first_chunk_sent
                if not first_chunk_sent:
                    print("VoicePerformanceEvent: firstLLMToken", file=sys.stderr)
                    first_chunk_sent = True
                if callable(on_llm_chunk):
                    on_llm_chunk(chunk)

            print("VoicePerformanceEvent: llmResponseStarted", file=sys.stderr)
            result = core.answer_message(
                question,
                memory,
                self.llm,
                self.config,
                workers=workers,
                pending_mail_followup=self.pending_mail_followup,
                transient_history=transient_history,
                on_llm_chunk=_forward_chunk if callable(on_llm_chunk) else None,
            )
            self.photo_worker = workers.photo_worker
            self.mail_worker = workers.mail_worker
            self.pending_mail_followup = result.pending_mail_followup
            self._last_answer_source = result.provider
            self._last_answer_model = result.model
            print("VoicePerformanceEvent: llmResponseFinished", file=sys.stderr)
            # answer_message() already called record_exchange() itself (with the
            # correct per-handler auto_memory behavior) - _finalize_answer() must not
            # record a second time here.
            answer = self._finalize_answer(core, question, result.text, record=False)
            return str(answer)
        except Exception as exc:
            fast = self._handle_fast_commands(question)
            if fast is not None:
                return fast
            detail = str(exc).strip()
            if isinstance(exc, FileNotFoundError):
                missing = getattr(exc, "filename", None) or detail
                self._pipeline_log("missingFilePath", text=str(missing))
                return f"Mir fehlt lokal eine Datei oder ein Pfad: {missing}"
            if isinstance(exc, RuntimeError) and detail:
                return f"Ich erreiche das lokale Modell gerade nicht sauber. {detail}"
            return f"Ich konnte die Anfrage gerade nicht sauber ausführen. Technisch war es: {_safe_error(exc)}."


    def _finalize_answer(self, core, question: str, answer: Any, *, record: bool = True) -> str:
        text = str(answer or "").strip()
        if hasattr(core, "clean_ai_answer"):
            try:
                text = core.clean_ai_answer(text)
            except Exception:
                pass
        print("VoicePerformanceEvent: llmResponseFinished", file=sys.stderr)
        self._pipeline_log("assistantResponse", text=text)
        if record:
            self._record_exchange(core, question, text)
        return text

    def _clean_history(self, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
        if not isinstance(history, list):
            return []
        cleaned: list[dict[str, str]] = []
        for item in history[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or item.get("text") or "").strip()
            if role == "jarvis":
                role = "assistant"
            if role not in {"user", "assistant"} or not content:
                continue
            cleaned.append({"role": role, "content": content})
        return cleaned

    def _pipeline_log(
        self,
        event: str,
        *,
        text: str | None = None,
        transcript: str | None = None,
        history: list[dict[str, str]] | None = None,
        messages: list[dict[str, str]] | None = None,
        path: str | None = None,
        error: str | None = None,
        model: str | None = None,
        sample_rate: float | None = None,
    ) -> None:
        try:
            metadata: dict[str, Any] = {}
            if text is not None:
                metadata["text_summary"] = text_summary(text)
            if transcript is not None:
                metadata["transcript_summary"] = text_summary(transcript)
            if history is not None:
                metadata["history_count"] = len(history)
            if messages is not None:
                metadata["message_shape"] = message_shape(messages)
            if path is not None:
                metadata["path"] = path
            if error is not None:
                metadata["error"] = error
            if model is not None:
                metadata["model"] = model
            if sample_rate is not None:
                metadata["sample_rate"] = round(float(sample_rate), 2)
            self.pipeline_logger.log("chat_voice_pipeline", event, success=True, **metadata)
            printable = ", ".join(f"{key}={value}" for key, value in metadata.items())
            print(f"Pipeline: {event} {printable}", file=sys.stderr)
        except Exception:
            pass

    def _record_exchange(self, core, question: str, answer: str):
        if hasattr(core, "record_exchange"):
            try:
                core.record_exchange(self.memory, question, str(answer))
            except Exception as exc:
                # Previously silent: conversation history would just quietly stop
                # growing with no error surfaced anywhere.
                print(f"Gesprächsverlauf konnte nicht gespeichert werden: {_safe_error(exc)}", file=sys.stderr)

    def _handle_fast_commands(self, text: str) -> str | None:
        normalized = text.lower()
        if "datenschutz" in normalized or "privacy" in normalized:
            return self.dashboard.status()
        if "dateiindex" in normalized or ("datei" in normalized and ("index" in normalized or "scan" in normalized or "weit" in normalized)):
            status = self._files_status()
            stats = dict(status.get("stats") or {})
            label = str(status.get("currentLabel") or "Dateiindex bereit.")
            percentage = float(status.get("percentage") or 0.0)
            indexed = int(stats.get("items_indexed") or stats.get("index_entries") or status.get("currentItem") or 0)
            total = int(status.get("totalItems") or indexed)
            files = int(stats.get("files_found") or 0)
            folders = int(stats.get("folders_found") or 0)
            if total > 0 and status.get("status") in {"preparing", "scanning", "indexing"}:
                return f"Der Dateiindex ist bei {percentage:.0f} Prozent. {indexed} von {total} Einträgen sind verarbeitet."
            return f"{label} Ich sehe im Index {files} Dateien und {folders} Ordner."
        # "fotoindex" bewusst als eigener, VOR _handle_local_photo_vision_command
        # geprueft und daher vorrangiger Zweig: dessen is_photo_context-
        # Gate matcht schon auf das blosse Teilwort "foto" in "fotoindex" und
        # dessen "wie weit"-Zweig lieferte bisher immer den Fortschritt der
        # LOKALEN VISION-ANALYSE (ein separates Feature) statt des eigentlich
        # gefragten Such-Fotoindex-Fortschritts (_photos_status(), analog zu
        # _files_status() oben) - zwei unterschiedliche Konzepte, die durch das
        # gemeinsame Wort "Foto" kollidierten. Live beobachtet 2026-08-19: "Wie
        # weit ist der Fotoindex?" antwortete mit "Lokale Fotoanalyse
        # fehlgeschlagen. Lokal analysiert: 0 Bilder." statt dem echten
        # Index-Fortschritt.
        # "scann"/"scan" bewusst NICHT allein als Ausloeser - "Scanne meine
        # Fotos im Hintergrund" (ein Befehl, kein Statuscheck) enthaelt als
        # Teilstring "scan" und wurde dadurch faelschlich hier als
        # Statusabfrage abgefangen statt den eigentlichen Scan zu starten
        # (photo_worker.request_scan() in handle_photos_command). Live
        # beobachtet 2026-08-19, direkt beim Testen dieses Fixes.
        if "fotoindex" in normalized or ("foto" in normalized and ("wie weit" in normalized or "fortschritt" in normalized or "prozent" in normalized or ("index" in normalized and "scan" not in normalized))):
            status = self._photos_status()
            stats = dict(status.get("stats") or {})
            label = str(status.get("currentLabel") or "Fotoindex bereit.")
            percentage = float(status.get("percentage") or 0.0)
            indexed = int(status.get("currentItem") or stats.get("photos_indexed") or 0)
            total = int(status.get("totalItems") or indexed)
            photos = int(stats.get("photos_found") or 0)
            videos = int(stats.get("videos_found") or 0)
            if total > 0 and status.get("status") in {"preparing", "scanning", "indexing"}:
                return f"Der Fotoindex ist bei {percentage:.0f} Prozent. {indexed} von {total} Einträgen sind verarbeitet."
            return f"{label} Ich sehe im Index {photos} Fotos und {videos} Videos."
        if "welches modell" in normalized or "modell nutzt" in normalized:
            return self.models.status_text()
        if "standardmodell" in normalized or "standard modell" in normalized or "phi4" in normalized or "phi 4" in normalized or "phi-4" in normalized:
            return self.models.use_standard_model()
        if "gemma" in normalized:
            return self.models.use_local_model("gemma3:4b")
        if "qwen" in normalized:
            return self.models.use_local_model("qwen3:4b")
        if "arbeite lokal" in normalized or "lokal" in normalized and "openai" in normalized:
            return self.models.work_locally()
        if "nutze openai" in normalized or "openai aktiv" in normalized:
            return self.models.use_openai()
        return None

    def _handle_local_photo_vision_command(self, text: str) -> str | None:
        normalized = text.lower()
        is_photo_context = any(term in normalized for term in ("foto", "fotos", "bild", "bilder", "photo", "vision"))
        if not is_photo_context:
            return None

        if "openai" in normalized or "cloud" in normalized:
            return None

        if "vision" in normalized and any(term in normalized for term in ("modell", "status", "prüf", "pruef", "check")):
            status = self.local_photo_vision_status()
            return str(status.get("message") or "Lokaler Vision-Status konnte nicht gelesen werden.")

        if "analysier" in normalized or "analysiere" in normalized or "lokal" in normalized and "analyse" in normalized:
            status = self.local_photo_vision_status()
            if not bool(status.get("available")):
                return str(status.get("message") or "Es ist noch kein lokales Vision-Modell installiert.")
            self.start_local_photo_vision_analysis()
            return f"Ich analysiere Ihre Fotos lokal mit {status.get('model')}. Keine Bilder verlassen Ihren Mac."

        if "wie weit" in normalized or "fortschritt" in normalized or "fotoanalyse" in normalized:
            progress = self._photos_vision_status()
            stats = dict(progress.get("stats") or {})
            percentage = float(progress.get("percentage") or 0.0)
            current = int(progress.get("currentItem") or stats.get("analyzed") or 0)
            total = int(progress.get("totalItems") or current)
            label = str(progress.get("currentLabel") or "Lokale Fotoanalyse bereit.")
            model = str(stats.get("model") or "")
            if total > 0 and progress.get("status") in {"preparing", "scanning", "indexing"}:
                return f"Die lokale Fotoanalyse ist bei {percentage:.0f} Prozent. {current} von {total} Bildern sind verarbeitet. Modell: {model}."
            return f"{label} Lokal analysiert: {stats.get('analyzed', 0)} Bilder. Noch offen: {stats.get('pending', 0)}."

        if "was ist auf diesem bild" in normalized or "was siehst du auf diesem bild" in normalized:
            return "Wähle bitte erst ein Bild oder eine Trefferliste aus. Danach kann ich genau dieses Foto lokal beschreiben, ohne es in die Cloud zu schicken."

        return None

    def model_payload(self) -> dict[str, Any]:
        status = self.models.status()
        return {
            "provider": status.provider,
            "active_model": status.active_model,
            "mode": self.config.get("model_mode", "performance"),
            "openai_enabled": status.openai_enabled,
            "ollama_installed": status.ollama_installed,
            "ollama_running": status.ollama_running,
            "installed_models": status.installed_models,
            "missing_models": status.missing_models,
            "openai_key_present": status.openai_key_present,
        }

    def set_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "").lower()
        model = str(payload.get("model") or "").lower()
        if provider == "openai":
            message = self.models.use_openai()
        elif model:
            message = self.models.use_local_model(model)
        else:
            message = self.models.work_locally()
        return {"message": message, "status": self.model_payload()}


SERVER = JarvisLocalServer()


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisLocalServer/1.0"

    def _authorized(self) -> bool:
        token = self.headers.get("X-Jarvis-Token", "")
        return bool(AUTH_TOKEN) and hmac.compare_digest(token, AUTH_TOKEN)

    def do_GET(self):
        path = urlparse(self.path).path
        if path != "/api/health" and not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        try:
            if path == "/api/health":
                self._json(200, SERVER.health())
            elif path == "/api/models":
                self._json(200, SERVER.model_payload())
            elif path == "/api/permissions":
                self._json(200, SERVER.permissions.export())
            elif path == "/api/privacy/status":
                self._json(200, {"status": SERVER.dashboard.status()})
            elif path == "/api/secure-storage/check":
                self._json(200, check_secure_storage())
            elif path == "/api/photos/permission-status":
                self._json(200, SERVER.photo_permission_status())
            elif path == "/api/voice/profile/status":
                self._json(200, {"enrolled": SERVER.voice_profile.has_profile()})
            elif path == "/api/photos/vision-status":
                self._json(200, SERVER.local_photo_vision_status())
            elif path == "/api/calendar/overview":
                self._json(200, SERVER.calendar_overview())
            elif path == "/api/mail/overview":
                self._json(200, SERVER.mail_overview())
            elif path == "/api/music/overview":
                self._json(200, SERVER.music_overview())
            elif path == "/api/conversation-history":
                self._json(200, SERVER.conversation_history())
            elif path == "/api/mail/pending-calendar-actions":
                self._json(200, SERVER.pending_calendar_actions())
            elif path == "/api/memory/facts":
                query_params = dict(parse_qsl(urlparse(self.path).query))
                self._json(200, SERVER.list_memory_facts(query_params))
            elif path == "/api/activity/recent":
                query_params = dict(parse_qsl(urlparse(self.path).query))
                self._json(200, SERVER.recent_activity(query_params))
            elif path == "/api/proactivity/events":
                self._json(200, SERVER.proactivity_events())
            elif path == "/api/proactivity/history":
                self._json(200, SERVER.proactivity_history())
            elif path == "/api/tasks":
                query_params = dict(parse_qsl(urlparse(self.path).query))
                self._json(200, SERVER.list_tasks(query_params))
            elif path == "/api/settings/voice-mode":
                self._json(200, SERVER.voice_mode_status())
            elif path == "/api/voice/performance-stats":
                query_params = dict(parse_qsl(urlparse(self.path).query))
                self._json(200, SERVER.voice_performance_stats(query_params))
            else:
                self._json(404, {"error": "not_found"})
        except Exception as exc:
            self._json(500, {"error": _safe_error(exc), "detail": _safe_error_detail(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        payload = self._read_json()
        try:
            if path == "/api/chat":
                self._json(200, SERVER.chat(str(payload.get("message") or ""), history=list(payload.get("history") or [])))
            elif path == "/api/chat/stream":
                self._stream_chat(str(payload.get("message") or ""), history=list(payload.get("history") or []))
            elif path == "/api/listen":
                self._json(200, SERVER.listen_once(history=list(payload.get("history") or [])))
            elif path == "/api/voice/prewarm":
                self._json(200, SERVER.prewarm_voice_pipeline())
            elif path == "/api/voice/cancel-listening":
                self._json(200, SERVER.cancel_listening())
            elif path == "/api/voice/speaking":
                self._json(200, SERVER.set_voice_speaking(bool(payload.get("speaking"))))
            elif path == "/api/voice/transcribe":
                self._json(200, SERVER.transcribe_voice(str(payload.get("audio_path") or ""), payload.get("sample_rate")))
            elif path == "/api/voice/enroll":
                self._json(200, SERVER.enroll_voice_profile(list(payload.get("audio_paths") or [])))
            elif path == "/api/voice/verify":
                self._json(200, SERVER.verify_voice_profile(str(payload.get("audio_path") or "")))
            elif path == "/api/voice/profile/reset":
                self._json(200, SERVER.reset_voice_profile())
            elif path == "/api/models":
                self._json(200, SERVER.set_model(payload))
            elif path == "/api/models/pull":
                self._json(200, SERVER.start_model_pull(str(payload.get("model") or "")))
            elif path == "/api/settings/fast-voice-mode":
                enabled = bool(payload.get("enabled"))
                SERVER.config["fast_voice_mode"] = enabled
                SERVER.config["model_mode"] = "performance" if enabled else SERVER.config.get("model_mode", "performance")
                SERVER.config["ollama_num_predict"] = 48 if enabled else 56
                SERVER.config["openai_max_output_tokens"] = 90 if enabled else 110
                SERVER.config["silence_limit"] = 0.72 if enabled else 0.9
                SERVER.config["voice_listen_max_seconds"] = 9 if enabled else 10
                save_config(SERVER.config)
                with SERVER._audio_listener_lock:
                    if SERVER._audio_listener is not None:
                        SERVER._audio_listener.stop_stream()
                        SERVER._audio_listener = None
                self._json(200, {"ok": True, "enabled": enabled})
            elif path == "/api/settings/store-conversation":
                enabled = bool(payload.get("enabled"))
                SERVER.config["privacy_store_conversation"] = enabled
                save_config(SERVER.config)
                self._json(200, {"ok": True, "enabled": enabled})
            elif path == "/api/settings/voice":
                voice = str(payload.get("voice") or "").strip()
                if voice:
                    SERVER.config["edge_voice"] = voice
                    SERVER.config["voice"] = voice
                    save_config(SERVER.config)
                self._json(200, {"ok": bool(voice), "voice": SERVER.config.get("edge_voice", "de-DE-ConradNeural")})
            elif path == "/api/scan-status":
                self._json(200, SERVER.scan_status_payload())
            elif path == "/api/mail/scan-folders":
                self._json(200, SERVER.start_mail_folder_scan())
            elif path == "/api/mail/background-start":
                self._json(200, SERVER.start_mail_background_scan())
            elif path == "/api/mail/calendar-actions/resolve":
                self._json(200, SERVER.resolve_calendar_action(payload))
            elif path == "/api/memory/facts/update":
                self._json(200, SERVER.update_memory_fact(payload))
            elif path == "/api/memory/facts/confirm":
                self._json(200, SERVER.confirm_memory_fact(payload))
            elif path == "/api/memory/facts/reject":
                self._json(200, SERVER.reject_memory_fact(payload))
            elif path == "/api/memory/facts/delete":
                self._json(200, SERVER.delete_memory_fact(payload))
            elif path == "/api/proactivity/snooze":
                self._json(200, SERVER.snooze_proactivity_event(payload))
            elif path == "/api/proactivity/dismiss":
                self._json(200, SERVER.dismiss_proactivity_event(payload))
            elif path == "/api/tasks/create":
                self._json(200, SERVER.create_task(payload))
            elif path == "/api/tasks/update":
                self._json(200, SERVER.update_task(payload))
            elif path == "/api/tasks/confirm":
                self._json(200, SERVER.confirm_task(payload))
            elif path == "/api/tasks/reject":
                self._json(200, SERVER.reject_task(payload))
            elif path == "/api/tasks/delete":
                self._json(200, SERVER.delete_task(payload))
            elif path == "/api/mail/reply-draft":
                self._json(200, SERVER.create_mail_reply_draft(payload))
            elif path == "/api/settings/voice-mode":
                self._json(200, SERVER.set_voice_mode(payload))
            elif path == "/api/voice/performance-report":
                self._json(200, SERVER.record_voice_performance(payload))
            elif path == "/api/photos/scan":
                self._json(200, SERVER.start_photo_index_scan())
            elif path == "/api/photos/permission":
                self._json(200, SERVER.request_photo_permission())
            elif path == "/api/photos/reset":
                self._json(200, SERVER.reset_photo_index())
            elif path == "/api/photos/vision/analyze":
                self._json(200, SERVER.start_local_photo_vision_analysis())
            elif path == "/api/photos/vision/reset":
                self._json(200, SERVER.reset_local_photo_vision())
            elif path == "/api/calendar/overview":
                self._json(200, SERVER.calendar_overview())
            elif path == "/api/daily-briefing":
                self._json(200, SERVER.daily_briefing())
            elif path == "/api/files/scan":
                self._json(200, SERVER.start_file_index_scan())
            elif path == "/api/files/search":
                self._json(200, SERVER.search_file_index_payload(payload))
            elif path == "/api/files/move-search-results":
                self._json(200, SERVER.move_file_search_results(payload))
            elif path == "/api/files/reset":
                self._json(200, SERVER.reset_file_index())
            elif path == "/api/permissions":
                permission = str(payload.get("permission") or "")
                allowed = bool(payload.get("allowed"))
                if allowed:
                    first_time = not SERVER.permissions.is_requested(permission)
                    SERVER.permissions.grant(permission, source="dashboard_toggle")
                    if first_time:
                        # The toggle flip itself is the explicit user action -
                        # this is the one place a live probe is appropriate.
                        SERVER.probe_permission(permission)
                else:
                    SERVER.permissions.revoke(permission, source="dashboard_toggle")
                self._json(200, {"permissions": SERVER.permissions.export()})
            elif path == "/api/openai-key/set":
                key = str(payload.get("api_key") or "").strip()
                set_openai_api_key(key)
                self._json(200, {"ok": True})
            elif path == "/api/openai-key/delete":
                deleted = delete_openai_api_key()
                self._json(200, {"deleted": deleted})
            elif path == "/api/privacy/export":
                self._json(200, {"path": SERVER.dashboard.export_data()})
            elif path == "/api/privacy/delete-history":
                self._json(200, {"message": SERVER.dashboard.delete_history()})
            elif path == "/api/privacy/clear-logs":
                self._json(200, {"message": SERVER.dashboard.clear_logs()})
            else:
                self._json(404, {"error": "not_found"})
        except SecureStorageError as exc:
            self._json(400, {"error": _safe_error(exc)})
        except Exception as exc:
            self._json(500, {"error": _safe_error(exc), "detail": _safe_error_detail(exc)})

    def log_message(self, format: str, *args):
        # Keep local server logs content-free.
        sys.stderr.write("JarvisLocalServer request\n")

    def _stream_chat(self, message: str, history: list[dict[str, str]] | None = None):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        chunk_sent = False

        def _emit(chunk: str) -> None:
            nonlocal chunk_sent
            if chunk:
                chunk_sent = True
                self._write_stream_chunk(chunk)

        try:
            answer = str(SERVER._answer_with_core(
                message,
                transient_history=SERVER._clean_history(history),
                on_llm_chunk=_emit,
            ))
            if not chunk_sent:
                for index, word in enumerate(answer.split(" ")):
                    chunk = word if index == 0 else " " + word
                    self._write_stream_chunk(chunk)
        except Exception:
            # A failure here can happen AFTER the primary answer already streamed fully
            # (on_llm_chunk already wrote it out) - e.g. clean_ai_answer, a promised-action
            # follow-through, or record_exchange raising during post-processing. Falling
            # back to a fresh, unrelated SERVER.chat() call in that case would append a
            # second, independent answer onto the chunks already sent, gluing two unrelated
            # replies into one message. Only run the fallback if nothing was streamed yet.
            if not chunk_sent:
                streamed_answer = str(SERVER.chat(message, history=history).get("answer", ""))
                for index, word in enumerate(streamed_answer.split(" ")):
                    chunk = word if index == 0 else " " + word
                    self._write_stream_chunk(chunk)
        finally:
            voice_mode = normalize_voice_mode(str((SERVER.memory.get("settings") or {}).get("voice_mode") or ""))
            done = json.dumps(
                {"chunk": "", "done": True, "voice_output_suppressed": voice_mode_suppresses_voice_output(voice_mode)},
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"
            self.wfile.write(done)
            self.wfile.flush()

    def _write_stream_chunk(self, chunk: str) -> None:
        data = json.dumps({"chunk": chunk, "done": False}, ensure_ascii=False).encode("utf-8") + b"\n"
        self.wfile.write(data)
        self.wfile.flush()

    def _read_json(self) -> dict[str, Any]:
        # This is called from do_POST *before* the surrounding try/except, so any
        # exception raised here (bad/missing Content-Length header, a client that
        # disconnects mid-body, invalid UTF-8) would previously propagate unhandled
        # out of do_POST instead of yielding a clean response.
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0:
            return {}
        try:
            body = self.rfile.read(length)
        except (OSError, ConnectionError):
            return {}
        try:
            data = json.loads(body.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _json(self, status: int, payload: dict[str, Any]):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionError, OSError):
            # Client already disconnected (e.g. gave up after a timeout) - nothing left
            # to send back. Without this, do_GET/do_POST's own `except Exception` handler
            # would try to write a 500 to the same dead socket and raise a second,
            # unhandled exception from inside the except block.
            pass


def _warm_up_contacts_app() -> None:
    """Contacts.app braucht offenbar einen ersten AppleScript-Zugriff, um intern
    zu synchronisieren, bevor es zuegig antwortet - der ALLERERSTE echte
    Kontakt-Lookup nach einem App-/Prozessneustart hing dadurch reproduzierbar
    29-45 Sekunden (teils bis zum kompletten Timeout). Live beobachtet
    2026-08-19 in einem 2266-Saetze-Testdurchlauf: die ersten drei
    Kontakt-Anfragen brauchten 29s/45s/45s, alle 117 folgenden < 2s. Ein
    beilaeufiger Warmlauf-Ping in einem Hintergrund-Thread beim Serverstart
    bezahlt diese Kosten schon vorher statt beim ersten echten Nutzer-Request -
    gleiches Prinzip wie prewarm_voice_pipeline() fuer die STT-Engine."""
    try:
        from contacts_client import list_contacts
        list_contacts(limit=1)
    except Exception:
        pass


def run(host: str = "127.0.0.1", port: int = 8765):
    _generate_auth_token()
    threading.Thread(target=_warm_up_contacts_app, daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Jarvis Local Server läuft auf http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
