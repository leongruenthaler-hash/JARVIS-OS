from __future__ import annotations

"""Headless "Mac-Mini-Worker"-Server (siehe plans/... "Jarvis Mac-Mini-Worker").
Laeuft auf einer zweiten, staendig eingeschalteten Maschine (z.B. ein Mac Mini)
und treibt AUSSCHLIESSLICH Hintergrundarbeit: Fotoindex + Fotos-Vision-Analyse +
Mail-Hintergrundscan. Absichtlich ein komplett eigenstaendiges Modul statt einer
Erweiterung von local_server.py::Handler/JarvisLocalServer:

JarvisLocalServer.__init__() baut unbedingt Memory()/TaskManager() (siehe dort) -
genau die Objekte, in denen Gespraechs-/Notiz-/Aufgaben-/Erinnerungs-Zustand
lebt. Diese Sitzung hat mehrfach gezeigt, wie leicht mehrstufiger Zustand
(offene Rueckfragen, die eine spaetere, unabhaengige Nachricht faelschlich als
Antwort verschluckt - siehe die behobenen pending_note/
pending_domain_clarification-Bugs) selbst innerhalb EINES Prozesses kaputtgeht.
Zwei Maschinen, die sich denselben Zustand teilen, wuerden dieses Risiko nur
potenzieren. Deshalb bewusst: dieser Prozess konstruiert Memory/TaskManager/
ConversationManager/PROACTIVITY_ENGINE gar nicht erst - das ist eine
strukturelle Garantie, keine Laufzeit-Konvention, die eine kuenftige neue Route
im großen Handler versehentlich unterlaufen koennte.

Erreichbare Routen (nur diese drei, sonst nichts):
  GET /api/health          - kein Auth noetig, wie beim regulaeren Server
  GET /api/scan-status     - nur photos/photos_vision/mail_background
  GET /api/photos/search   - Fotosuche gegen den lokalen Index dieser Maschine
"""

import hmac
import json
import secrets
import sys
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from background_tasks import MailBackgroundWorker
from data_dir import data_root
from llm_client import LLMClient
from photos_client import PhotoBackgroundWorker, PhotoIndex, expand_photo_query, score_photo_entry
from settings import load_config

PAIRING_TOKEN_FILENAME = "remote_worker_pairing.token"
ACCESS_LOG_FILENAME = "remote_worker_access.log"

# Sperre nach zu vielen fehlgeschlagenen Token-Versuchen pro Quell-IP - simple
# In-Memory-Drosselung, kein Anspruch auf DoS-Haertung, nur ein Schutz gegen
# ploetzliches Token-Erraten aus dem Heimnetz.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_FAILURES = 10

_rate_lock = threading.Lock()
_failure_log: dict[str, deque[float]] = defaultdict(deque)


def _load_or_create_pairing_token() -> str:
    """Anders als AUTH_TOKEN in local_server.py (secrets.token_hex(32), bei
    JEDEM Prozessstart neu erzeugt) wird dieses Token EINMALIG erzeugt und
    danach nie wieder ueberschrieben - es muss ueber Neustarts hinweg stabil
    bleiben, weil es einmalig manuell in die config.json der zweiten Maschine
    (MacBook) eingetragen wird."""
    token_path = data_root() / PAIRING_TOKEN_FILENAME
    if token_path.exists():
        existing = token_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    token = secrets.token_hex(32)
    try:
        token_path.write_text(token, encoding="utf-8")
        token_path.chmod(0o600)
    except OSError as exc:
        print(f"Warning: could not persist pairing token: {exc}", file=sys.stderr)
    return token


PAIRING_TOKEN = _load_or_create_pairing_token()


def _log_access(path: str, source_ip: str, outcome: str) -> None:
    # Bewusst inhaltsfrei (kein Query, kein Body) - nur Pfad, Quelle, Ergebnis.
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "path": path,
        "ip": source_ip,
        "outcome": outcome,
    }
    log_path = data_root() / ACCESS_LOG_FILENAME
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _is_rate_limited(source_ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        recent = _failure_log[source_ip]
        while recent and now - recent[0] > _RATE_LIMIT_WINDOW_SECONDS:
            recent.popleft()
        return len(recent) >= _RATE_LIMIT_MAX_FAILURES


def _record_failure(source_ip: str) -> None:
    with _rate_lock:
        _failure_log[source_ip].append(time.time())


# ---------------------------------------------------------------------------
# Status-Formatierung - bewusst eine schlanke Kopie der gleichnamigen Methoden
# in local_server.py (_scan_progress/_photos_status/_photos_vision_status/
# _mail_background_status), NICHT von dort importiert: local_server.py
# gehoert zum GUI-Prozess und importiert seinerseits Memory/TaskManager auf
# Modulebene, was genau die Isolation dieses Prozesses unterlaufen wuerde, die
# oben im Modul-Docstring begruendet ist. Beide Kopien lesen ausschliesslich
# dieselben, reinen JSON-Cache-Dateien (photos_index.json,
# photos_scan_progress.json, background_mail_cache.json) - bei einer
# Schema-Aenderung dort muessen beide Kopien angepasst werden.
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


def _photos_status(config: dict[str, Any]) -> dict[str, Any]:
    index = PhotoIndex(config)
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
            "photos_indexed": len([e for e in entries if str(e.get("mediaType") or "image") == "image"]),
            "videos_found": videos,
            "labels_recognized": label_count,
            "current_photo": progress.get("current_photo", ""),
            "last_successful_scan": cache.get("last_scan_at", ""),
            "database_bytes": index.cache_path.stat().st_size if index.cache_path.exists() else 0,
        },
    )


def _photos_vision_status(config: dict[str, Any]) -> dict[str, Any]:
    index = PhotoIndex(config)
    cache = index._load_cache()
    entries = list(cache.get("entries", []) or [])
    local_count = len([e for e in entries if str(e.get("local_vision_analyzed_at") or "").strip()])
    pending_count = len([
        e for e in entries
        if str(e.get("mediaType") or "image") == "image" and not str(e.get("local_vision_analyzed_at") or "").strip()
    ])
    progress: dict[str, Any] = {}
    if index.local_vision_progress_path.exists():
        try:
            payload = json.loads(index.local_vision_progress_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                progress = payload
        except Exception:
            progress = {}
    status_name = str(progress.get("status") or ("completed" if local_count else "idle"))
    current = int(progress.get("currentItem") or local_count)
    total = int(progress.get("totalItems") or max(local_count + pending_count, local_count, 0))
    return _scan_progress(
        status_name,
        str(progress.get("currentLabel") or "Lokale Fotoanalyse."),
        current_item=current,
        total_items=total,
        started_at=progress.get("startedAt"),
        finished_at=progress.get("finishedAt"),
        error_message=progress.get("errorMessage"),
        stats=dict(progress.get("stats") or {}),
    )


def _mail_background_status(config: dict[str, Any], mail_worker: MailBackgroundWorker) -> dict[str, Any]:
    cache = mail_worker._load_cache()
    is_active = mail_worker.thread is not None and mail_worker.thread.is_alive()
    is_scanning = mail_worker.scan_thread is not None and mail_worker.scan_thread.is_alive()
    status_name = "scanning" if is_scanning else ("idle" if is_active else "cancelled")
    known = len(cache.get("known_message_ids", []) or [])
    new_count = len(cache.get("new_messages", []) or [])
    return _scan_progress(
        status_name,
        "Mail-Hintergrundscan läuft." if is_scanning else ("Mail-Hintergrundscan aktiv." if is_active else "Mail-Hintergrundscan pausiert."),
        current_item=known,
        total_items=max(known, 1),
        started_at=cache.get("last_scan_at"),
        finished_at=cache.get("last_scan_at"),
        error_message=cache.get("last_error") or None,
        stats={
            "background_active": is_active,
            "background_scanning": is_scanning,
            "last_scan": cache.get("last_scan_at", ""),
            "new_mails": new_count,
            "mails_indexed": known,
            "last_error": cache.get("last_error", ""),
        },
    )


class RemoteWorker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.llm = LLMClient(config)
        self.photo_worker = PhotoBackgroundWorker(config)
        # Zwingend erzwungen, unabhaengig davon, was in der config.json der
        # zweiten Maschine steht - siehe Modul-Docstring/Plan: der Mail-Worker
        # leitet bei jedem Scan sonst eigene pending_calendar_actions her
        # (create_calendar_actions_from_messages(), background_tasks.py) und
        # schreibt sie in seine EIGENE background_mail_cache.json. Zwei
        # unabhaengige, nie abgeglichene pending-Listen auf zwei Maschinen
        # waeren exakt dieselbe Zustands-Leck-Bugklasse wie die heute
        # gefixten pending_note/pending_domain_clarification-Bugs. Dieser
        # Prozess haelt ausschliesslich Nachrichten-Zusammenfassungen warm.
        mail_config = dict(config)
        mail_config["auto_calendar_from_mail_enabled"] = False
        self.mail_worker = MailBackgroundWorker(mail_config, self.llm)

    def start(self) -> None:
        self.photo_worker.start()
        self.mail_worker.start()
        # Nicht bis zur naechsten geplanten Zeit (Standard 03:15) warten -
        # direkt beim ersten Start einen Durchlauf anstossen, damit der Nutzer
        # nicht bis zum naechsten Tag auf einen ersten Index wartet.
        threading.Thread(target=self.photo_worker.request_scan, daemon=True).start()
        threading.Thread(target=lambda: self.mail_worker.request_scan(reason="startup"), daemon=True).start()

    def scan_status(self) -> dict[str, Any]:
        return {
            "photos": _photos_status(self.config),
            "photos_vision": _photos_vision_status(self.config),
            "mail_background": _mail_background_status(self.config, self.mail_worker),
        }

    def search_photos(self, query: str, max_results: int | None = None) -> list[dict[str, Any]]:
        index = PhotoIndex(self.config)
        cache = index._load_cache()
        entries = cache.get("entries", []) or []
        terms = expand_photo_query(query)
        scored = []
        for entry in entries:
            score = score_photo_entry(entry, terms, query)
            if score <= 0:
                continue
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        limit = int(max_results or self.config.get("photos_search_max_results", 25))
        # Bewusst OHNE "id" (PHAsset.localIdentifier) in der Antwort - der ist
        # zwischen zwei getrennten PHPhotoLibrary-Instanzen (selbst bei
        # gleichem iCloud-Account) nicht zuverlaessig portabel. Die
        # anfragende Maschine gleicht stattdessen ueber filename+createdAt ab
        # (siehe photos_client.py::_export_preview_by_attrs).
        return [
            {
                "filename": str(entry.get("filename", "")),
                "createdAt": str(entry.get("createdAt", "")),
                "mediaType": str(entry.get("mediaType", "")),
                "labels": list(entry.get("labels", [])),
                "score": score,
            }
            for score, entry in scored[:limit]
        ]


WORKER: RemoteWorker | None = None


class RemoteWorkerHandler(BaseHTTPRequestHandler):
    server_version = "JarvisRemoteWorker/1.0"

    def log_message(self, format: str, *args):
        sys.stderr.write("JarvisRemoteWorker request\n")

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _authorized(self) -> bool:
        token = self.headers.get("X-Jarvis-Token", "")
        return bool(PAIRING_TOKEN) and hmac.compare_digest(token, PAIRING_TOKEN)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        source_ip = self._client_ip()

        if path == "/api/health":
            self._json(200, {"ok": True, "name": "Jarvis Remote Worker"})
            return

        if _is_rate_limited(source_ip):
            _log_access(path, source_ip, "rate_limited")
            self._json(429, {"error": "rate_limited"})
            return

        if not self._authorized():
            _record_failure(source_ip)
            _log_access(path, source_ip, "unauthorized")
            self._json(401, {"error": "unauthorized"})
            return

        assert WORKER is not None
        try:
            if path == "/api/scan-status":
                _log_access(path, source_ip, "ok")
                self._json(200, WORKER.scan_status())
            elif path == "/api/photos/search":
                query_params = dict(parse_qsl(parsed.query))
                query = str(query_params.get("q") or "")
                max_results = query_params.get("max")
                _log_access(path, source_ip, "ok")
                self._json(200, {"matches": WORKER.search_photos(query, int(max_results) if max_results else None)})
            else:
                _log_access(path, source_ip, "not_found")
                self._json(404, {"error": "not_found"})
        except Exception as exc:
            _log_access(path, source_ip, f"error:{type(exc).__name__}")
            self._json(500, {"error": "internal_error"})


def run(host: str | None = None, port: int | None = None) -> None:
    global WORKER
    config = load_config()
    WORKER = RemoteWorker(config)
    WORKER.start()

    bind_host = host or str(config.get("remote_worker_bind_host", "127.0.0.1"))
    bind_port = port or int(config.get("remote_worker_port", 8766))
    httpd = ThreadingHTTPServer((bind_host, bind_port), RemoteWorkerHandler)
    print(f"Jarvis Remote Worker läuft auf http://{bind_host}:{bind_port}")
    if bind_host not in {"127.0.0.1", "localhost"}:
        print(
            "Achtung: an eine im Netzwerk erreichbare Adresse gebunden - "
            "nur im vertrauenswuerdigen Heimnetz betreiben.",
            file=sys.stderr,
        )
    httpd.serve_forever()


if __name__ == "__main__":
    run()
