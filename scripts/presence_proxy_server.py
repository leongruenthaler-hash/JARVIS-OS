#!/usr/bin/env python3
"""Eigenstaendiger Ankunfts-Proxy fuer JarvisMobile (2026-09-12) - nimmt
entgegen, wenn LocationManager.swift per GPS-Geofence erkennt, dass Leon zu
Hause ankommt, und loest daraufhin eine gesprochene Begruessung auf dem Mac
Mini aus (Nutzerwunsch: "Jarvis soll merken, wann ich nach Hause komme und
mich mit seinem Standard-Humor begruessen").

Gleiches Push-statt-Pull-Muster wie scripts/health_proxy_server.py: die
eigentliche Erkennung (GPS) kann nur auf dem iPhone passieren, dieser Proxy
nimmt nur das fertige Ereignis entgegen.

Erzeugt bei jedem Ankunfts-Ereignis einen frischen, sich selbst loeschenden
Einmal-Cronjob (`openclaw cron create --at 1s ... --delete-after-run`) -
kein dauerhafter Job noetig, das Ereignis ist ohnehin unregelmaessig und
einmalig pro Ankunft. Der Cronjob formuliert die Begruessung selbst (in
Jarvis' etablierter Persona) und spricht sie per macOS `say` laut auf den
Mac-Mini-Lautsprechern aus - live verifizierte deutsche Stimme
"Markus (Enhanced)".

Installation auf dem Mac Mini: siehe scripts/presence_proxy_launch.sh und
scripts/com.leon.jarvis.presenceproxy.plist im selben Ordner.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PORT = 18802
TOKEN_FILE = Path.home() / ".jarvis_presence_proxy_token"
OPENCLAW_PATH = os.environ.get("OPENCLAW_BIN", "/opt/homebrew/bin/openclaw")
SUBPROCESS_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
}

GREETING_PROMPT = (
    "Leon ist gerade per GPS-Geofence als zu Hause angekommen erkannt worden "
    "(automatisches Ereignis, kein Chat mit ihm). Formuliere eine kurze "
    "Willkommens-Begruessung in deinem etablierten Jarvis-Stil (trocken-"
    "sarkastisch, aber freundlich, 'sir' ansprechen, 1-2 Saetze, Deutsch, "
    "kein Markdown). Fuehre dann per exec GENAU diese zwei Kommandos "
    "nacheinander aus (Anfuehrungszeichen im Text escapen):\n"
    "1. osascript -e \"set volume output volume 80\"\n"
    "   (Systemlautstaerke war beim ersten Live-Test zu leise, deshalb "
    "vorher anheben)\n"
    "2. say -v \"Markus (Enhanced)\" \"<deine Begruessung>\"\n"
    "Antworte selbst danach exakt mit NO_REPLY - das hier ist kein Chat, "
    "niemand liest eine normale Antwort."
)


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


def trigger_greeting() -> dict[str, Any]:
    result = subprocess.run(
        [
            OPENCLAW_PATH, "cron", "create",
            "--name", "home-arrival-greeting",
            "--at", "1s",
            "--message", GREETING_PROMPT,
            "--session", "isolated",
            "--model", "openai/gpt-5-nano",
            "--no-deliver",
            "--light-context",
            "--tools", "exec",
            "--delete-after-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=SUBPROCESS_ENV,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    return {"ok": True}


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

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        try:
            if self.path == "/api/presence/arrived":
                self._send_json(200, trigger_greeting())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": str(exc) or type(exc).__name__})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[presence-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Ankunfts-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisMobile -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
