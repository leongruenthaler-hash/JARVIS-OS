#!/usr/bin/env python3
"""Eigenstaendiger Gesundheits-Proxy fuer JarvisMobile (2026-09-12) - im
Gegensatz zu allen anderen Proxys in scripts/ LIEST dieser nichts selbst,
sondern nimmt nur entgegen: HealthKit gibt es nur auf iOS, der Mac Mini kann
Apple-Health/Watch-Daten nicht selbst abfragen. JarvisMobile liest die Werte
per HealthKit auf dem iPhone aus und schickt sie hierher (POST), Jarvis-Chat
und Automationen lesen sie von hier wieder ab (GET) - kein direkter
Python-Import wie bei den anderen Proxys, weil die Datenquelle physisch auf
dem Telefon liegt.

Speichert nur den JEWEILS LETZTEN Snapshot (kein Verlauf) unter
data_root()/memory/health_snapshot.json - fuer Trend-Fragen ("wie war mein
Schlaf diese Woche") muesste JarvisMobile mehrere Naechte im selben Snapshot
mitschicken, siehe HealthSnapshot.swift.

Installation auf dem Mac Mini: siehe scripts/health_proxy_launch.sh und
scripts/com.leon.jarvis.healthproxy.plist im selben Ordner.
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

from data_dir import data_root  # noqa: E402

PORT = 18801
TOKEN_FILE = Path.home() / ".jarvis_health_proxy_token"
SNAPSHOT_PATH = data_root() / "memory" / "health_snapshot.json"


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


def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return {"ok": True}


def load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {"updated_at": None, "message": "Noch keine Gesundheitsdaten empfangen."}
    return json.loads(SNAPSHOT_PATH.read_text())


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
        try:
            if self.path == "/api/health/snapshot":
                self._send_json(200, load_snapshot())
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
            if self.path == "/api/health/update":
                self._send_json(200, save_snapshot(body))
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[health-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Gesundheits-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisMobile -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
