#!/usr/bin/env python3
"""Eigenstaendiger Kalender/Erinnerungen-Proxy fuer JarvisApp (2026-09-12) -
ersetzt den Teil des alten Backends (app/local_server.py), der bisher
/api/calendar/overview bediente. Gleiches Muster wie scripts/music_proxy_server.py:
importiert app/calendar_client.py direkt vom Repo-Checkout, portiert nur den
Dashboard-Uebersichts-Endpunkt (naechste Termine + offene Erinnerungen).

Absichtlich NICHT portiert: Termine/Erinnerungen anlegen/loeschen - laeuft
bereits vollstaendig ueber OpenClaw-Chat + den installierten
"apple-calendar-macos"-aehnlichen Skill-Pfad (appState.send()), kein eigener
REST-Endpunkt noetig. Kalender und Erinnerungen haben getrennte
Datenschutz-Freigaben ("calendar"/"reminders"), genau wie im alten Backend.

Installation auf dem Mac Mini: siehe scripts/calendar_proxy_launch.sh und
scripts/com.leon.jarvis.calendarproxy.plist im selben Ordner.
"""
from __future__ import annotations

import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from calendar_client import list_open_reminders, list_upcoming_calendar_items  # noqa: E402
from permission_manager import PermissionManager  # noqa: E402

PORT = 18798
TOKEN_FILE = Path.home() / ".jarvis_calendar_proxy_token"


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


def _safe_error(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def calendar_overview() -> dict[str, Any]:
    """Direkter Port von JarvisLocalServer.calendar_overview (app/local_server.py:896-934)."""
    permissions = PermissionManager()

    if permissions.is_allowed("calendar"):
        try:
            upcoming = list_upcoming_calendar_items(limit=5).get("items", [])
            calendar_error = ""
        except Exception as exc:  # noqa: BLE001
            upcoming = []
            calendar_error = _safe_error(exc)
        calendar_message = "Nächste Termine geladen." if upcoming else "Keine kommenden Termine gefunden."
    else:
        upcoming, calendar_error = [], ""
        calendar_message = "Kalender-Zugriff noch nicht aktiviert."

    if permissions.is_allowed("reminders"):
        try:
            reminders = list_open_reminders(limit=5).get("items", [])
            reminder_error = ""
        except Exception as exc:  # noqa: BLE001
            reminders = []
            reminder_error = _safe_error(exc)
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


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        # default=str faengt die rohen datetime-Objekte ab, die
        # calendar_client._parse_calendar_items() zusaetzlich zu den schon
        # vorhandenen String-Feldern in "start_dt"/"end_dt" einfuegt (ein
        # bereits im alten Backend bestehender Bug - dessen json.dumps() ohne
        # default= haette hier identisch mit TypeError abgestuerzt, siehe
        # app/local_server.py:2762). JarvisApp's CalendarOverviewItem ignoriert
        # unbekannte Felder ohnehin (Decodable-Default), verwendet also nur
        # calendar/list/title/start/end/due - der stringifizierte Rest ist
        # harmlos totes Gewicht im Payload.
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        try:
            if self.path == "/api/calendar/overview":
                self._send_json(200, calendar_overview())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[calendar-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Kalender-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
