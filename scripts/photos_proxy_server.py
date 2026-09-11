#!/usr/bin/env python3
"""Eigenstaendiger Fotos-Proxy fuer JarvisApp (2026-09-11) - Ersatz fuer den
Teil des alten Backends (app/local_server.py), der bisher
/api/photos/permission-status|permission|scan|reset|vision-status|
vision/analyze|vision/reset bediente. Gleiches Muster wie
scripts/files_proxy_server.py: importiert app/photos_client.py (die echte
PhotoIndex-Klasse, kompletter macOS-Fotos-Zugriff ueber den Swift-Helfer)
direkt vom Repo-Checkout, portiert aber die Fortschritts-/Threading-
Orchestrierung aus JarvisLocalServer (_photos_status/_photos_vision_status/
_save_photo_progress/_save_local_photo_vision_progress/start_photo_index_scan/
start_local_photo_vision_analysis, app/local_server.py) als eigene, schlanke
Funktionen hierher.

Absichtlich NICHT portiert (bleibt Sache des jarvis-photos OpenClaw-Skills
via Chat, wie bei Mail/apple-mail-macos): Freitextsuche
("Jarvis, zeig mir Fotos mit...", performPhotoCommand -> chat), Album-
Erstellung, Desktop-Export, OpenAI-Vision-Analyse - photos_client.py deckt
das ab, aber es ist inhaltsbasierte Suche/Interpretation, kein
deterministischer Statusabruf, profitiert also von einem LLM-Skill-Aufruf
statt einem eigenen REST-Endpunkt.

Installation auf dem Mac Mini: siehe scripts/photos_proxy_launch.sh und
scripts/com.leon.jarvis.photosproxy.plist im selben Ordner.
"""
from __future__ import annotations

import json
import secrets
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from photos_client import PhotoIndex, PhotosAccessError  # noqa: E402
from settings import load_config  # noqa: E402

PORT = 18793
TOKEN_FILE = Path.home() / ".jarvis_photos_proxy_token"
CONFIG = load_config()


def _load_or_create_token() -> str:
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token


TOKEN = _load_or_create_token()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_error(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def _index() -> PhotoIndex:
    return PhotoIndex(CONFIG)


# ---------------------------------------------------------------------------
# Fortschritts-Form - identisch zu JarvisLocalServer._scan_progress
# (app/local_server.py), damit ScanProgress auf der Swift-Seite unveraendert
# passt.
# ---------------------------------------------------------------------------

def _scan_progress(
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


def _save_photo_progress(progress: dict[str, Any]) -> None:
    index = _index()
    cache = index._load_cache()
    cache["progress"] = progress
    index._save_cache(cache)


def _save_local_vision_progress(progress: dict[str, Any]) -> None:
    index = _index()
    index.local_vision_progress_path.write_text(
        json.dumps(progress, indent=4, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Direkter Port von JarvisLocalServer._photos_status/_photos_vision_status
# (app/local_server.py:1526-1616).
# ---------------------------------------------------------------------------

def photos_status() -> dict[str, Any]:
    index = _index()
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
    live_error = progress.get("errorMessage")
    is_actively_running = status_name in {"scanning", "indexing"}
    error_message = live_error if (live_error or is_actively_running) else cache.get("last_error")
    return _scan_progress(
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


def photos_vision_status() -> dict[str, Any]:
    index = _index()
    cache = index._load_cache()
    entries = list(cache.get("entries", []) or [])
    local_count = len([entry for entry in entries if str(entry.get("local_vision_analyzed_at") or "").strip()])
    pending_count = len([
        entry
        for entry in entries
        if str(entry.get("mediaType") or "image") == "image"
        and not str(entry.get("local_vision_analyzed_at") or "").strip()
    ])
    progress: dict[str, Any] = {}
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
    return _scan_progress(
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


# ---------------------------------------------------------------------------
# Scan/Berechtigung/Vision - direkter Port von JarvisLocalServer.
# start_photo_index_scan/_run_photo_index_scan/photo_permission_status/
# request_photo_permission/reset_photo_index/local_photo_vision_status/
# start_local_photo_vision_analysis/_run_local_photo_vision_analysis/
# reset_local_photo_vision (app/local_server.py:841-1099).
# ---------------------------------------------------------------------------

_photo_scan_lock = threading.Lock()
_photo_scan_thread: threading.Thread | None = None
_photo_vision_thread: threading.Thread | None = None


def start_photo_index_scan() -> dict[str, Any]:
    global _photo_scan_thread
    index = _index()
    started_at = _now()
    try:
        index.progress_path.unlink()
    except OSError:
        pass
    _save_photo_progress(_scan_progress("preparing", "Fotoindex wird vorbereitet.", started_at=started_at))
    with _photo_scan_lock:
        if _photo_scan_thread is not None and _photo_scan_thread.is_alive():
            return photos_status()
        _photo_scan_thread = threading.Thread(target=_run_photo_index_scan, args=(started_at,), daemon=True)
        _photo_scan_thread.start()
    return photos_status()


def _run_photo_index_scan(started_at: str) -> None:
    index = _index()
    try:
        count = index.scan()
        status = photos_status()
        status["status"] = "completed"
        status["currentLabel"] = "Fotoindex fertig."
        status["currentItem"] = int(status.get("totalItems") or count)
        status["finishedAt"] = _now()
        _save_photo_progress(status)
    except Exception as exc:
        status = _scan_progress(
            "failed", "Fotoindex fehlgeschlagen.",
            started_at=started_at, finished_at=_now(), error_message=_safe_error(exc),
        )
        _save_photo_progress(status)


def photo_permission_status() -> dict[str, Any]:
    return {"status": _index().permission_status()}


def request_photo_permission() -> dict[str, Any]:
    return {"message": _index().request_permission(), "progress": photos_status()}


def reset_photo_index() -> dict[str, Any]:
    index = _index()
    if index.cache_path.exists():
        index.cache_path.unlink()
    status = photos_status()
    status["currentLabel"] = "Fotoindex wurde zurückgesetzt."
    return status


def local_photo_vision_status() -> dict[str, Any]:
    return _index().local_vision_status()


def start_local_photo_vision_analysis(max_items: int | None = None) -> dict[str, Any]:
    global _photo_vision_thread
    index = _index()
    started_at = _now()
    try:
        index.local_vision_progress_path.unlink()
    except OSError:
        pass
    _save_local_vision_progress(
        _scan_progress(
            "preparing", "Lokale Fotoanalyse wird vorbereitet.", started_at=started_at,
            stats={"model": index.local_vision_status().get("model", "")},
        )
    )
    with _photo_scan_lock:
        if _photo_vision_thread is not None and _photo_vision_thread.is_alive():
            return photos_vision_status()
        _photo_vision_thread = threading.Thread(
            target=_run_local_photo_vision_analysis, args=(max_items,), daemon=True,
        )
        _photo_vision_thread.start()
    return photos_vision_status()


def _run_local_photo_vision_analysis(max_items: int | None = None) -> None:
    index = _index()
    try:
        index.analyze_with_local_vision(max_items=max_items)
    except Exception as exc:
        status = _scan_progress(
            "failed", "Lokale Fotoanalyse fehlgeschlagen.",
            finished_at=_now(), error_message=_safe_error(exc),
            stats={"model": index.local_vision_status().get("model", ""), "errors": 1},
        )
        _save_local_vision_progress(status)


def reset_local_photo_vision() -> dict[str, Any]:
    index = _index()
    removed = index.reset_local_vision_descriptions()
    status = _scan_progress(
        "idle", f"Lokale KI-Beschreibungen gelöscht: {removed}.",
        stats={"local_descriptions": 0, "removed": removed},
    )
    _save_local_vision_progress(status)
    return status


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        try:
            if self.path == "/api/photos/status":
                self._send_json(200, photos_status())
            elif self.path == "/api/photos/permission-status":
                self._send_json(200, photo_permission_status())
            elif self.path == "/api/photos/vision-status":
                self._send_json(200, local_photo_vision_status())
            elif self.path == "/api/photos/vision-progress":
                self._send_json(200, photos_vision_status())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except PhotosAccessError as exc:
            self._send_json(502, {"error": _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        body = self._read_json_body()
        try:
            if self.path == "/api/photos/scan":
                self._send_json(200, start_photo_index_scan())
            elif self.path == "/api/photos/permission":
                self._send_json(200, request_photo_permission())
            elif self.path == "/api/photos/reset":
                self._send_json(200, reset_photo_index())
            elif self.path == "/api/photos/vision/analyze":
                max_items = body.get("max_items")
                self._send_json(200, start_local_photo_vision_analysis(max_items=max_items))
            elif self.path == "/api/photos/vision/reset":
                self._send_json(200, reset_local_photo_vision())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except PhotosAccessError as exc:
            self._send_json(502, {"error": _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001 - als 502 durchreichen statt den Prozess zu killen
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[photos-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Fotos-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
