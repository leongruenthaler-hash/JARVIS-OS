#!/usr/bin/env python3
"""Eigenstaendiger Musik-Proxy fuer JarvisApp (2026-09-12) - ersetzt den Teil
des alten Backends (app/local_server.py), der bisher /api/music/overview
bediente. Gleiches Muster wie scripts/mail_proxy_server.py: importiert
app/music_client.py direkt vom Repo-Checkout, portiert nur den
Dashboard-Uebersichts-Endpunkt.

Absichtlich NICHT portiert: Wiedergabe-Steuerung (Play/Pause/naechster Titel/
Playlist/Suche) - laeuft bereits vollstaendig ueber den installierten
OpenClaw-Skill "managing-apple-music" (clawtunes) via Chat, kein eigener
REST-Endpunkt noetig.

Installation auf dem Mac Mini: siehe scripts/music_proxy_launch.sh und
scripts/com.leon.jarvis.musicproxy.plist im selben Ordner.
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

from music_client import MusicAccessError, now_playing  # noqa: E402
from permission_manager import PermissionManager  # noqa: E402

PORT = 18797
TOKEN_FILE = Path.home() / ".jarvis_music_proxy_token"


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


def music_overview() -> dict[str, Any]:
    """Direkter Port von JarvisLocalServer.music_overview (app/local_server.py:955-969)."""
    if not PermissionManager().is_allowed("music"):
        return {"track": None, "message": "Musik-Zugriff noch nicht aktiviert.", "error": ""}
    try:
        track = now_playing()
        message = "Wiedergabe läuft." if track else "Gerade läuft nichts."
        return {"track": track, "message": message, "error": ""}
    except MusicAccessError as exc:
        return {"track": None, "message": "Musik-Status konnte nicht geladen werden.", "error": _safe_error(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"track": None, "message": "Musik-Status konnte nicht geladen werden.", "error": _safe_error(exc)}


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

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        if self.path == "/api/music/overview":
            self._send_json(200, music_overview())
        else:
            self._send_json(404, {"error": "Unbekannter Pfad."})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[music-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Musik-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
