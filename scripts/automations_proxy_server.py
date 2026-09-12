#!/usr/bin/env python3
"""Eigenstaendiger Automationen-Proxy fuer JarvisApp (2026-09-12) - ersetzt den
bisherigen Inhalt der "Aufgaben"-Ansicht (interne, nie wirklich genutzte
To-Do-Liste aus app/core/task_manager.py) durch eine Liste der echten OpenClaw-
Automationen (Cronjobs wie "mail-summary-watch", "calendar-30min-reminder",
proaktive Watch-Automationen etc.).

Anders als die uebrigen Proxys hier importiert dieser NICHT app/*.py - es gibt
keine Python-API fuer OpenClaw-Automationen. Stattdessen ruft er per
subprocess das bereits installierte "openclaw"-CLI auf (`openclaw cron list
--all --json`), das selbst mit dem lokalen Gateway spricht. "openclaw" ist ein
`#!/usr/bin/env node`-Skript unter /opt/homebrew/bin - braucht node auf PATH,
das ein LaunchAgent (KEIN Login-Shell-Profil) nicht automatisch mitbringt,
daher der explizite PATH unten.

Rein lesend (Nutzerwunsch 2026-09-12: erstmal nur anzeigen, keine Steuerung) -
Aktivieren/Deaktivieren/manuelles Ausloesen einzelner Automationen bleibt
bewusst Sache von `openclaw cron edit/run` im Terminal, kein REST-Endpunkt.

Installation auf dem Mac Mini: siehe scripts/automations_proxy_launch.sh und
scripts/com.leon.jarvis.automationsproxy.plist im selben Ordner.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PORT = 18800
TOKEN_FILE = Path.home() / ".jarvis_automations_proxy_token"
OPENCLAW_PATH = os.environ.get("OPENCLAW_BIN", "/opt/homebrew/bin/openclaw")
SUBPROCESS_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
}


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


def _schedule_summary(schedule: dict[str, Any]) -> str:
    kind = schedule.get("kind")
    if kind == "every":
        every_ms = schedule.get("everyMs") or 0
        minutes = every_ms / 60000
        if minutes >= 60 and minutes % 60 == 0:
            return f"alle {int(minutes // 60)} Std."
        return f"alle {int(minutes)} Min."
    if kind == "cron":
        expr = schedule.get("expr") or ""
        tz = schedule.get("tz")
        return f"Cron: {expr}" + (f" ({tz})" if tz else "")
    return kind or "unbekannt"


def list_automations() -> dict[str, Any]:
    """Ruft `openclaw cron list --all --json` per subprocess auf (kein
    Python-API-Aequivalent vorhanden) und reduziert jeden Job auf die Felder,
    die die JarvisApp-Ansicht tatsaechlich braucht."""
    result = subprocess.run(
        [OPENCLAW_PATH, "cron", "list", "--all", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        env=SUBPROCESS_ENV,
        check=True,
    )
    raw = json.loads(result.stdout)
    jobs = []
    for job in raw.get("jobs", []):
        state = job.get("state", {})
        jobs.append(
            {
                "id": job.get("id"),
                "name": job.get("displayName") or job.get("name") or job.get("id"),
                "description": job.get("description") or "",
                "enabled": bool(job.get("enabled", True)),
                "schedule": _schedule_summary(job.get("schedule") or {}),
                "status": job.get("status") or state.get("lastStatus") or "unbekannt",
                "last_run_at_ms": job.get("lastRunAtMs"),
                "next_run_at_ms": job.get("nextRunAtMs"),
                "last_error": job.get("lastRunError") or state.get("lastError"),
            }
        )
    return {"automations": jobs, "total": len(jobs)}


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

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        try:
            if self.path == "/api/automations":
                self._send_json(200, list_automations())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except subprocess.CalledProcessError as exc:
            self._send_json(502, {"error": exc.stderr or _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[automations-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Automationen-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
