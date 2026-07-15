from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

from audio_stream import StreamingAudioListener, warm_audio_pipeline
from background_tasks import MailBackgroundWorker
from calendar_client import list_open_reminders, list_upcoming_calendar_items
from fast_intent_router import FastIntentRouter
from core.conversation_manager import ConversationManager
from core.daily_briefing import build_daily_briefing
from files_client import configured_roots, move_indexed_matches_to_folder, normalize_name, search_file_index_entries, search_files
from llm_client import LLMClient
from jarvis_personality import JARVIS_SYSTEM_PROMPT, message_shape, normalize_jarvis_messages, text_summary
from mail_client import list_inbox_messages, list_mailboxes
from memory import Memory
from model_manager import ModelManager, ollama_base_url
from model_router import ModelRouter
from photos_client import PhotoIndex
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
            "Öffne Systemeinstellungen > Ton > Eingabe und wähle dein MacBook-Mikrofon aus. Prüfe zusätzlich "
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
        self._tts_speaking = threading.Event()
        self.mail_worker = None
        self.photo_worker = None
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
        return {"answer": answer, "source": self._last_answer_source, "model": self._last_answer_model}

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
        try:
            upcoming = list_upcoming_calendar_items(limit=5).get("items", [])
            calendar_error = ""
        except Exception as exc:
            upcoming = []
            calendar_error = str(exc)

        try:
            reminders = list_open_reminders(limit=5).get("items", [])
            reminder_error = ""
        except Exception as exc:
            reminders = []
            reminder_error = str(exc)

        return {
            "calendar": {
                "items": upcoming,
                "count": len(upcoming),
                "message": "Nächste Termine geladen." if upcoming else "Keine kommenden Termine gefunden.",
                "error": calendar_error,
            },
            "reminders": {
                "items": reminders,
                "count": len(reminders),
                "message": "Offene Erinnerungen geladen." if reminders else "Keine offenen Erinnerungen gefunden.",
                "error": reminder_error,
            },
        }

    def daily_briefing(self) -> dict[str, Any]:
        try:
            calendar_items = list_upcoming_calendar_items(limit=5).get("items", [])
        except Exception:
            calendar_items = []
        try:
            reminder_items = list_open_reminders(limit=5).get("items", [])
        except Exception:
            reminder_items = []

        briefing = build_daily_briefing(
            calendar_items=calendar_items,
            reminders=reminder_items,
            mail_summary=self._mail_background_status().get("message", ""),
            system_summary=f"Modell: {self.models.active_model}. Provider: {self.models.provider}.",
        )
        return {
            "briefing": briefing,
            "calendar_count": len(calendar_items),
            "reminders_count": len(reminder_items),
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
                except Exception:
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

    def _ensure_mail_worker(self) -> MailBackgroundWorker:
        if self.mail_worker is None:
            self.mail_worker = MailBackgroundWorker(self.config)
            self.mail_worker.start()
        return self.mail_worker

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
        payload = self._scan_progress(
            status_name,
            str(progress.get("currentLabel") or ("Fotoindex bereit." if entries else "Noch kein Fotoindex.")),
            current_item=current,
            total_items=total_items,
            started_at=progress.get("startedAt") or cache.get("scan_started_at"),
            finished_at=progress.get("finishedAt") or cache.get("last_scan_at"),
            error_message=cache.get("last_error") or progress.get("errorMessage"),
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
                    "answer": "Ich habe dich akustisch gehört, aber keinen Text verstanden.",
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
        route = self.llm.plan(transient_history or [], user_text=question)

        try:
            if hasattr(core, "is_end_command") and core.is_end_command(question):
                return "Alles klar. Ich bin wieder still, bis du Jarvis sagst."

            fast = self._handle_fast_commands(question)
            if fast is not None:
                return self._finalize_answer(core, question, fast)

            photo_fast = self._handle_local_photo_vision_command(question)
            if photo_fast is not None:
                return photo_fast

            direct_handlers = [
                ("handle_system_command", (question,), {}),
                ("handle_preference_command", (memory, question), {}),
                ("handle_style_command", (memory, question), {}),
                ("handle_project_command", (question,), {}),
                ("handle_local_command", (question,), {}),
                ("handle_privacy_command", (memory, question), {}),
                ("handle_model_command", (question,), {"memory": memory}),
                ("handle_memory_command", (memory, question), {}),
                ("handle_pending_note_flow", (memory, question), {}),
                ("handle_pending_action_flow", (memory, question), {"photo_worker": self.photo_worker}),
            ]
            if hasattr(core, "has_pending_action") and core.has_pending_action(memory):
                pending_action_handler = direct_handlers.pop()
                local_command_index = next(i for i, entry in enumerate(direct_handlers) if entry[0] == "handle_local_command")
                direct_handlers.insert(local_command_index, pending_action_handler)

            for name, args, kwargs in direct_handlers:
                handler = getattr(core, name, None)
                if handler is None:
                    continue
                answer = handler(*args, **kwargs)
                if answer is not None:
                    answer = self._finalize_answer(core, question, answer)
                    return str(answer)

            if hasattr(core, "has_domain") and hasattr(core, "has_permission"):
                notes_permission = core.ensure_privacy_domain_permission(memory, "notes", "Jarvis würde eine Notiz über Apple Notes erstellen oder ändern.") if core.has_domain(question, "notes") else None
                if notes_permission is not None:
                    return str(notes_permission)
                notes_handler = getattr(core, "handle_notes_command", None)
                if notes_handler is not None:
                    answer = notes_handler(memory, question)
                    if answer is not None:
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                calendar_permission = None
                if core.has_domain(question, "calendar") or core.looks_like_calendar_query(question):
                    calendar_permission = core.ensure_privacy_domain_permission(memory, "calendar", "Jarvis würde Kalenderdaten verwenden.")
                    if calendar_permission is None and "erinner" in core.normalize_text(question):
                        calendar_permission = core.ensure_privacy_domain_permission(memory, "reminders", "Jarvis würde eine Erinnerung verwenden.")
                if calendar_permission is not None:
                    return str(calendar_permission)
                calendar_handler = getattr(core, "handle_calendar_command", None)
                if calendar_handler is not None:
                    answer = calendar_handler(question, memory=memory)
                    if answer is not None:
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                normalized_question = core.normalize_text(question) if hasattr(core, "normalize_text") else question.lower()
                file_permission = core.ensure_privacy_domain_permission(memory, "files", "Jarvis würde deinen Schreibtisch oder Dateien lokal lesen oder ändern.") if core.has_domain(question, "files") or "desktop" in normalized_question or "schreibtisch" in normalized_question else None
                if file_permission is not None:
                    return str(file_permission)
                for file_handler_name in ("handle_desktop_command", "handle_file_command"):
                    handler = getattr(core, file_handler_name, None)
                    if handler is not None:
                        answer = handler(question, memory=memory)
                        if answer is not None:
                            self.pending_mail_followup = False
                            answer = self._finalize_answer(core, question, answer)
                            return str(answer)

                photo_permission = core.ensure_privacy_domain_permission(memory, "photos", "Jarvis würde deine Fotos-App oder den lokalen Fotoindex verwenden.") if core.has_domain(question, "photos") else None
                if photo_permission is None and core.has_domain(question, "photos") and any(term in normalized_question for term in ("openai", "vision", "analysiere", "analysieren", "was siehst")):
                    photo_permission = core.ensure_cloud_llm_permission(memory, question)
                if photo_permission is not None:
                    return str(photo_permission)

                if core.has_domain(question, "photos") and self.photo_worker is None and core.has_permission("photos"):
                    worker_cls = getattr(core, "PhotoBackgroundWorker", None)
                    if worker_cls is not None:
                        self.photo_worker = worker_cls(self.config)
                        self.photo_worker.start()
                photo_handler = getattr(core, "handle_photo_command", None)
                if photo_handler is not None:
                    answer = photo_handler(question, self.photo_worker, memory=memory)
                    if answer is not None:
                        self.pending_mail_followup = False
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                mail_export_permission = core.ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Mail-Übersichten lesen und passende Anhänge oder Notizen auf den Schreibtisch kopieren.") if core.has_domain(question, "mail") else None
                if mail_export_permission is not None:
                    return str(mail_export_permission)
                mail_document_export_handler = getattr(core, "handle_mail_document_export_command", None)
                if mail_document_export_handler is not None:
                    answer = mail_document_export_handler(question, memory=memory)
                    if answer is not None:
                        self.pending_mail_followup = False
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                if core.has_domain(question, "mail") and self.mail_worker is None and core.has_permission("mail"):
                    worker_cls = getattr(core, "MailBackgroundWorker", None)
                    if worker_cls is not None:
                        self.mail_worker = worker_cls(self.config)
                        self.mail_worker.start()
                background_mail_handler = getattr(core, "handle_background_mail_command", None)
                if background_mail_handler is not None:
                    answer = background_mail_handler(question, self.mail_worker)
                    if answer is not None:
                        self.pending_mail_followup = True
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                mail_permission = core.ensure_privacy_domain_permission(memory, "mail", "Jarvis würde Apple Mail lokal lesen oder bearbeiten.") if core.has_domain(question, "mail") or self.pending_mail_followup else None
                if mail_permission is not None:
                    return str(mail_permission)
                mail_handler = getattr(core, "handle_mail_command", None)
                if mail_handler is not None:
                    mail_settings_before = memory.get("settings") or {}
                    had_pending_mail_delete = isinstance(mail_settings_before.get("pending_mail_delete"), dict)
                    mail_followup_intent = (
                        hasattr(core, "is_mail_time_followup")
                        and hasattr(core, "is_mail_status_followup")
                        and (core.is_mail_time_followup(question) or core.is_mail_status_followup(question))
                    )
                    answer = mail_handler(self.llm, question, force=self.pending_mail_followup and mail_followup_intent, memory=memory)
                    if answer is not None:
                        self.pending_mail_followup = False if had_pending_mail_delete else True
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                contact_permission = core.ensure_privacy_domain_permission(memory, "contacts", "Jarvis würde Kontakte lesen oder einen Anruf vorbereiten.") if core.has_domain(question, "contacts") else None
                if contact_permission is not None:
                    return str(contact_permission)
                contact_handler = getattr(core, "handle_contact_command", None)
                if contact_handler is not None:
                    answer = contact_handler(question, memory=memory)
                    if answer is not None:
                        self.pending_mail_followup = False
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

                music_permission = core.ensure_privacy_domain_permission(memory, "music", "Jarvis würde Apple Music oder die Musik-Wiedergabe steuern.") if core.has_domain(question, "music") else None
                if music_permission is not None:
                    return str(music_permission)
                music_handler = getattr(core, "handle_music_command", None)
                if music_handler is not None:
                    answer = music_handler(question)
                    if answer is not None:
                        self.pending_mail_followup = False
                        answer = self._finalize_answer(core, question, answer)
                        return str(answer)

            web_context = None
            if bool(self.config.get("web_search_enabled", True)) and hasattr(core, "should_use_web_search") and core.should_use_web_search(question):
                permission = core.ensure_privacy_domain_permission(memory, "internet", "Jarvis würde eine Websuche im Internet ausführen.")
                if permission is not None:
                    return str(permission)
                try:
                    search_query = core.build_search_query(question)
                    results = core.search_web(search_query, max_results=int(self.config.get("web_search_max_results", 3)))
                    if results:
                        web_context = core.format_search_results(results)
                except Exception:
                    web_context = None

            if hasattr(core, "ensure_cloud_llm_permission"):
                permission = core.ensure_cloud_llm_permission(memory, question)
                if permission is not None:
                    return str(permission)

            if hasattr(core, "build_input"):
                try:
                    messages = core.build_input(memory, question, web_context, transient_history=transient_history, compact=route.compact_prompt)
                except TypeError:
                    messages = core.build_input(memory, question, web_context)
            else:
                messages = [
                    {"role": "system", "content": JARVIS_SYSTEM_PROMPT},
                    *(transient_history or []),
                    {"role": "user", "content": question},
                ]
            messages = normalize_jarvis_messages(
                messages,
                recent_limit=min(int(self.config.get("recent_context_messages", 6)) + 1, 7),
            )
            self._pipeline_log("finalPrompt/messages", messages=messages)
            print("VoicePerformanceEvent: llmResponseStarted", file=sys.stderr)
            self._last_answer_source = route.provider
            self._last_answer_model = route.model

            first_chunk_sent = False

            def _forward_chunk(chunk: str) -> None:
                nonlocal first_chunk_sent
                if not first_chunk_sent:
                    print("VoicePerformanceEvent: firstLLMToken", file=sys.stderr)
                    first_chunk_sent = True
                if callable(on_llm_chunk):
                    on_llm_chunk(chunk)

            if callable(on_llm_chunk):
                answer = self.llm.ask_stream(
                    messages,
                    max_output_tokens=route.max_output_tokens,
                    user_text=question,
                    route=route,
                    on_chunk=_forward_chunk,
                )
            else:
                answer = self.llm.ask(messages, max_output_tokens=route.max_output_tokens, user_text=question, route=route)
            print("VoicePerformanceEvent: llmResponseFinished", file=sys.stderr)
            if hasattr(core, "clean_ai_answer"):
                answer = core.clean_ai_answer(answer)
            promised = core.execute_promised_action_if_possible(self.llm, question, answer) if hasattr(core, "execute_promised_action_if_possible") else None
            if promised is not None:
                answer = promised
            self.pending_mail_followup = "mail" in question.lower() or "mail" in str(answer).lower()
            answer = self._finalize_answer(core, question, answer)
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


    def _finalize_answer(self, core, question: str, answer: Any) -> str:
        text = str(answer or "").strip()
        if hasattr(core, "clean_ai_answer"):
            try:
                text = core.clean_ai_answer(text)
            except Exception:
                pass
        print("VoicePerformanceEvent: llmResponseFinished", file=sys.stderr)
        self._pipeline_log("assistantResponse", text=text)
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
            except Exception:
                pass

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
        if "welches modell" in normalized or "modell nutzt" in normalized:
            return self.models.status_text()
        if "standardmodell" in normalized or "standard modell" in normalized:
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
            return f"Ich analysiere deine Fotos lokal mit {status.get('model')}. Keine Bilder verlassen deinen Mac."

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

    def do_GET(self):
        path = urlparse(self.path).path
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
            elif path == "/api/photos/vision-status":
                self._json(200, SERVER.local_photo_vision_status())
            elif path == "/api/calendar/overview":
                self._json(200, SERVER.calendar_overview())
            elif path == "/api/conversation-history":
                self._json(200, SERVER.conversation_history())
            else:
                self._json(404, {"error": "not_found"})
        except Exception as exc:
            self._json(500, {"error": _safe_error(exc), "detail": _safe_error_detail(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
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
                if SERVER._audio_listener is not None:
                    SERVER._audio_listener.stop_stream()
                    SERVER._audio_listener = None
                self._json(200, {"ok": True, "enabled": enabled})
            elif path == "/api/settings/store-conversation":
                enabled = bool(payload.get("enabled"))
                SERVER.config["privacy_store_conversation"] = enabled
                save_config(SERVER.config)
                self._json(200, {"ok": True, "enabled": enabled})
            elif path == "/api/scan-status":
                self._json(200, SERVER.scan_status_payload())
            elif path == "/api/mail/scan-folders":
                self._json(200, SERVER.start_mail_folder_scan())
            elif path == "/api/mail/background-start":
                self._json(200, SERVER.start_mail_background_scan())
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
                    SERVER.permissions.grant(permission)
                else:
                    SERVER.permissions.revoke(permission)
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
            streamed_answer = str(SERVER.chat(message, history=history).get("answer", ""))
            for index, word in enumerate(streamed_answer.split(" ")):
                chunk = word if index == 0 else " " + word
                self._write_stream_chunk(chunk)
        finally:
            done = json.dumps({"chunk": "", "done": True}, ensure_ascii=False).encode("utf-8") + b"\n"
            self.wfile.write(done)
            self.wfile.flush()

    def _write_stream_chunk(self, chunk: str) -> None:
        data = json.dumps({"chunk": chunk, "done": False}, ensure_ascii=False).encode("utf-8") + b"\n"
        self.wfile.write(data)
        self.wfile.flush()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        body = self.rfile.read(length)
        try:
            data = json.loads(body.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _json(self, status: int, payload: dict[str, Any]):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run(host: str = "127.0.0.1", port: int = 8765):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Jarvis Local Server läuft auf http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
