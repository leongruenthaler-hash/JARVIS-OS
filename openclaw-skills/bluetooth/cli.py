#!/usr/bin/env python3
"""Duenner CLI-Wrapper um blueutil (Homebrew, macOS-Bluetooth-CLI), damit
Jarvis sich per Sprachbefehl mit bereits gekoppelten Bluetooth-Geraeten
verbinden/trennen kann (2026-09-12, "Jarvis, verbinde dich mit Logitech BT
Adapter/der Denon Soundbar").

WICHTIG: blueutil braucht die macOS-Bluetooth-Berechtigung (TCC) fuer den
aufrufenden Prozess - eine normale interaktive SSH-Sitzung hat diese NICHT
(meldet dann faelschlich "Power is required to be on", auch wenn Bluetooth
laeuft) und Verbindungsversuche schlagen fehl. Der OpenClaw-Gateway-Prozess
(also genau der Kontext, in dem dieses Skript per exec-Tool laeuft) hat die
Berechtigung bereits, live verifiziert 2026-09-12.

Nur bereits gekoppelte Geraete koennen verbunden werden - ein neues Geraet
(z.B. ein frisch angeschlossener Bluetooth-Adapter) muss zuerst einmal
manuell ueber die Systemeinstellungen gekoppelt werden, das kann dieses
Skript nicht (kein automatisches Pairing/PIN-Eingabe ueber die CLI moeglich).
"""
from __future__ import annotations

import json
import subprocess
import sys

BLUEUTIL = "/opt/homebrew/bin/blueutil"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([BLUEUTIL, *args], capture_output=True, text=True, timeout=15)


def _paired_devices() -> list[dict]:
    result = _run(["--paired", "--format", "json"])
    if result.returncode != 0:
        print(json.dumps({"error": result.stderr.strip() or "blueutil fehlgeschlagen."}))
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def _find_device(query: str) -> dict | None:
    query_lower = query.strip().lower()
    devices = _paired_devices()
    # Erst exakte Übereinstimmung (case-insensitiv), dann Teilstring-Suche in
    # beide Richtungen - "Logitech BT Adapter" vs. gespeichertem Namen "BT
    # Adapter" oder umgekehrt sollen beide matchen, ohne dass Leon den Namen
    # exakt wie im System hinterlegt aussprechen muss.
    for device in devices:
        if device.get("name", "").lower() == query_lower:
            return device
    for device in devices:
        name = device.get("name", "").lower()
        if query_lower in name or name in query_lower:
            return device
    return None


def list_devices() -> None:
    print(json.dumps(_paired_devices(), ensure_ascii=False))


def connect(query: str) -> None:
    device = _find_device(query)
    if device is None:
        print(json.dumps({"ok": False, "error": f"Kein gekoppeltes Geraet gefunden, das zu '{query}' passt."}))
        sys.exit(1)
    result = _run(["--connect", device["address"]])
    if result.returncode != 0:
        print(json.dumps({"ok": False, "device": device["name"], "error": result.stderr.strip() or result.stdout.strip()}))
        sys.exit(1)
    print(json.dumps({"ok": True, "device": device["name"], "address": device["address"]}))


def disconnect(query: str) -> None:
    device = _find_device(query)
    if device is None:
        print(json.dumps({"ok": False, "error": f"Kein gekoppeltes Geraet gefunden, das zu '{query}' passt."}))
        sys.exit(1)
    result = _run(["--disconnect", device["address"]])
    if result.returncode != 0:
        print(json.dumps({"ok": False, "device": device["name"], "error": result.stderr.strip() or result.stdout.strip()}))
        sys.exit(1)
    print(json.dumps({"ok": True, "device": device["name"], "address": device["address"]}))


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Nutzung: cli.py list|connect <name>|disconnect <name>"}))
        sys.exit(1)
    command = sys.argv[1]
    if command == "list":
        list_devices()
    elif command == "connect" and len(sys.argv) >= 3:
        connect(" ".join(sys.argv[2:]))
    elif command == "disconnect" and len(sys.argv) >= 3:
        disconnect(" ".join(sys.argv[2:]))
    else:
        print(json.dumps({"error": "Nutzung: cli.py list|connect <name>|disconnect <name>"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
