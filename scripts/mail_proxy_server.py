#!/usr/bin/env python3
"""Eigenstaendiger Mail-Proxy fuer JarvisApp (2026-09-12) - Ersatz fuer den Teil
des alten Backends (app/local_server.py), der bisher /api/mail/overview und
/api/mail/scan-folders bediente. Gleiches Muster wie scripts/photos_proxy_server.py:
importiert app/mail_client.py und app/permission_manager.py direkt vom
Repo-Checkout, portiert die Fortschritts-Orchestrierung aus JarvisLocalServer
(_run_mail_folder_scan, mail_overview, app/local_server.py:786-950) als eigene,
schlanke Funktionen hierher.

Absichtlich NICHT portiert (bleibt Sache des jarvis-mail-Freitextchats via
OpenClaw + apple-mail-macos-Skill, wie bisher performMailCommand): Freitext-
Suche, Antwort-Entwuerfe, Dokument-Export - inhaltsbasierte Anfragen profitieren
von einem LLM-Skill-Aufruf statt einem eigenen REST-Endpunkt.

NEU gegenueber dem alten Backend (Nutzerwunsch 2026-09-11/12): der alte
MailBackgroundWorker (app/background_tasks.py) fasste Mails nur in EINER
gebuendelten Uebersicht zusammen. Das wird hier nicht 1:1 portiert - stattdessen
liest eine neue OpenClaw-Automation (nicht Teil dieser Datei, siehe
openclaw-workspace/AGENTS.md-Notiz "mail-summary-watch") ueber /api/mail/
unsummarized nach, welche ungelesenen Mails noch keine Zusammenfassung haben,
formuliert PRO MAIL eine eigene kurze Zusammenfassung und legt sie einzeln
per POST /api/mail/summaries ab - jede Mail bekommt also ihren eigenen
sichtbaren Eintrag statt einem Sammel-Text.

Installation auf dem Mac Mini: siehe scripts/mail_proxy_launch.sh und
scripts/com.leon.jarvis.mailproxy.plist im selben Ordner.
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
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from data_dir import data_root  # noqa: E402
from mail_client import (  # noqa: E402
    MailAccessError,
    list_inbox_messages,
    list_mailboxes,
    unread_inbox_count,
)
from permission_manager import PermissionManager  # noqa: E402

PORT = 18796
TOKEN_FILE = Path.home() / ".jarvis_mail_proxy_token"
SUMMARIES_FILE = data_root() / "memory" / "mail_summaries.json"
MAX_STORED_SUMMARIES = 200


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


def _permissions() -> PermissionManager:
    # Function-scoped wie im alten Backend (app/permission_manager.py:15-24) -
    # jeder Aufruf laedt/speichert frisch von der Festplatte, kein geteilter
    # In-Prozess-Zustand noetig.
    return PermissionManager()


# ---------------------------------------------------------------------------
# Fortschritts-Form - identisch zu JarvisLocalServer._scan_progress, damit
# ScanProgress auf der Swift-Seite unveraendert passt.
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


_SCAN_STATUS_FILE = data_root() / "memory" / "mail_scan_status.json"
_scan_lock = threading.Lock()
_scan_thread: threading.Thread | None = None


def _save_scan_status(status: dict[str, Any]) -> None:
    _SCAN_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SCAN_STATUS_FILE.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_scan_status() -> dict[str, Any]:
    if _SCAN_STATUS_FILE.exists():
        try:
            payload = json.loads(_SCAN_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return _scan_progress("idle", "Noch kein Mail-Ordner-Scan gelaufen.")


# ---------------------------------------------------------------------------
# Direkter Port von JarvisLocalServer.mail_overview (app/local_server.py:936-950).
# ---------------------------------------------------------------------------

def mail_overview() -> dict[str, Any]:
    if not _permissions().is_allowed("mail"):
        return {"unread_count": 0, "messages": [], "message": "Mail-Zugriff noch nicht aktiviert.", "error": ""}
    try:
        unread = unread_inbox_count()
        recent = list_inbox_messages(max_messages=3)
        return {
            "unread_count": unread,
            "messages": [{"sender": m.sender, "subject": m.subject} for m in recent],
            "message": "Mail-Übersicht geladen." if recent or unread else "Keine Mails gefunden.",
            "error": "",
        }
    except MailAccessError as exc:
        return {"unread_count": 0, "messages": [], "message": "Mail-Übersicht konnte nicht geladen werden.", "error": _safe_error(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"unread_count": 0, "messages": [], "message": "Mail-Übersicht konnte nicht geladen werden.", "error": _safe_error(exc)}


# ---------------------------------------------------------------------------
# Direkter Port von JarvisLocalServer.start_mail_folder_scan/_run_mail_folder_scan
# (app/local_server.py:786-834).
# ---------------------------------------------------------------------------

def start_mail_folder_scan() -> dict[str, Any]:
    global _scan_thread
    started_at = _now()
    _save_scan_status(_scan_progress("preparing", "Apple-Mail-Ordner werden vorbereitet.", started_at=started_at))
    with _scan_lock:
        if _scan_thread is not None and _scan_thread.is_alive():
            return _load_scan_status()
        _scan_thread = threading.Thread(target=_run_mail_folder_scan, args=(started_at,), daemon=True)
        _scan_thread.start()
    return _load_scan_status()


def _run_mail_folder_scan(started_at: str) -> None:
    try:
        _save_scan_status(_scan_progress("scanning", "Apple-Mail-Ordner werden gescannt.", started_at=started_at))
        mailboxes = list_mailboxes(max_mailboxes=200)
        total_messages = sum(max(0, int(box.message_count)) for box in mailboxes)
        status = _scan_progress(
            "completed",
            "Mail-Ordner-Scan fertig.",
            current_item=len(mailboxes),
            total_items=len(mailboxes),
            started_at=started_at,
            finished_at=_now(),
            stats={
                "folders_found": len(mailboxes),
                "folders_scanned": len(mailboxes),
                "mails_found": total_messages,
                "mails_indexed": total_messages,
                "current_folder": mailboxes[-1].mailbox if mailboxes else "",
                "last_successful_scan": _now(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        status = _scan_progress(
            "failed", "Mail-Ordner-Scan fehlgeschlagen.",
            started_at=started_at, finished_at=_now(), error_message=_safe_error(exc),
        )
    _save_scan_status(status)


# ---------------------------------------------------------------------------
# NEU: Mail-Zusammenfassungen, je eine pro Mail (Nutzerwunsch 2026-09-12) -
# gefuellt von der neuen OpenClaw-Automation, nicht von diesem Prozess selbst.
# ---------------------------------------------------------------------------

_summaries_lock = threading.Lock()


def _load_summaries() -> list[dict[str, Any]]:
    if SUMMARIES_FILE.exists():
        try:
            payload = json.loads(SUMMARIES_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return payload
        except Exception:
            pass
    return []


def _save_summaries(entries: list[dict[str, Any]]) -> None:
    SUMMARIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARIES_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def list_summaries(limit: int = 50) -> list[dict[str, Any]]:
    with _summaries_lock:
        entries = _load_summaries()
    ordered = sorted(entries, key=lambda e: str(e.get("created_at") or ""), reverse=True)
    return ordered[: max(0, int(limit))]


def add_summary(entry: dict[str, Any]) -> dict[str, Any]:
    message_id = str(entry.get("message_id") or "").strip()
    if not message_id:
        raise ValueError("message_id fehlt.")
    record = {
        "message_id": message_id,
        "sender": str(entry.get("sender") or ""),
        "subject": str(entry.get("subject") or ""),
        "received": str(entry.get("received") or ""),
        "summary": str(entry.get("summary") or ""),
        "created_at": _now(),
    }
    with _summaries_lock:
        entries = [e for e in _load_summaries() if str(e.get("message_id")) != message_id]
        entries.append(record)
        entries.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)
        entries = entries[:MAX_STORED_SUMMARIES]
        _save_summaries(entries)
    return record


def unsummarized_messages(max_messages: int = 20) -> list[dict[str, Any]]:
    """Fuer die OpenClaw-Automation: die neuesten Inbox-Mails (mit echtem
    Vorschautext, include_preview=True - list_unread_messages() im alten
    Backend liefert trotz ihres Namens weder eine Ungelesen-Filterung noch
    einen Vorschautext, siehe app/mail_client.py:453f., deshalb hier bewusst
    direkt list_inbox_messages() statt der irrefuehrend benannten Funktion),
    die noch keine gespeicherte Zusammenfassung haben (per message_id
    abgeglichen gegen mail_summaries.json)."""
    if not _permissions().is_allowed("mail"):
        return []
    with _summaries_lock:
        known_ids = {str(e.get("message_id")) for e in _load_summaries()}
    try:
        recent = list_inbox_messages(max_messages=max_messages, preview_chars=700, include_preview=True)
    except Exception:
        return []
    return [
        {
            "message_id": m.message_id,
            "sender": m.sender,
            "subject": m.subject,
            "received": m.received,
            "preview": m.preview,
        }
        for m in recent
        if m.message_id not in known_ids
    ]


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _send_json(self, status: int, payload: Any) -> None:
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
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/mail/overview":
                self._send_json(200, mail_overview())
            elif parsed.path == "/api/mail/scan-status":
                self._send_json(200, _load_scan_status())
            elif parsed.path == "/api/mail/summaries":
                limit = int((query.get("limit") or ["50"])[0])
                self._send_json(200, {"entries": list_summaries(limit=limit)})
            elif parsed.path == "/api/mail/unsummarized":
                max_messages = int((query.get("max") or ["20"])[0])
                self._send_json(200, {"messages": unsummarized_messages(max_messages=max_messages)})
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        body = self._read_json_body()
        try:
            if self.path == "/api/mail/scan-folders":
                self._send_json(200, start_mail_folder_scan())
            elif self.path == "/api/mail/summaries":
                self._send_json(200, add_summary(body))
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except ValueError as exc:
            self._send_json(400, {"error": _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[mail-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Mail-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
