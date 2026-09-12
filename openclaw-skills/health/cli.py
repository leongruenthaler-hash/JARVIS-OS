#!/usr/bin/env python3
"""Duenner CLI-Wrapper um den Jarvis-Gesundheits-Proxy
(scripts/health_proxy_server.py), damit Jarvis in Chat und Automationen auf
Leons Apple-Health/Watch-Daten zugreifen kann (2026-09-12).

Laeuft auf demselben Mac Mini wie der Proxy selbst - liest dessen Token
direkt aus ~/.jarvis_health_proxy_token (kein eigenes Setup noetig, anders
als z.B. tuya-vacuum: der Proxy und dieser Skill teilen sich dieselbe
Maschine, das Tuya-Cloud-Konto dagegen ist ein externer Dienst).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".jarvis_health_proxy_token"
BASE_URL = "http://127.0.0.1:18801"


def _token() -> str:
    if not TOKEN_FILE.exists():
        print(json.dumps({"error": "Gesundheits-Proxy laeuft nicht oder Token fehlt."}))
        sys.exit(1)
    return TOKEN_FILE.read_text().strip()


def status() -> None:
    request = urllib.request.Request(
        f"{BASE_URL}/api/health/snapshot",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(json.dumps({"error": f"Gesundheits-Proxy nicht erreichbar: {exc}"}))
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "status":
        print(json.dumps({"error": "Nutzung: cli.py status"}))
        sys.exit(1)
    status()


if __name__ == "__main__":
    main()
