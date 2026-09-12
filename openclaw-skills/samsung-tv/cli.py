#!/usr/bin/env python3
"""Duenner CLI-Wrapper um die SmartThings-Cloud-API, damit Jarvis Leons
Samsung-Fernseher ("65\" QLED") steuern kann - genau dieselbe API, die auch
die SmartThings-App auf seinem iPhone benutzt (2026-09-12, Nutzerwunsch
"kann Jarvis das auch, was die SmartThings-App kann").

Direkter Cloud-API-Zugriff (Personal Access Token, kein Home Assistant) -
gleiches Muster wie openclaw-skills/tuya-vacuum, aus denselben Gruenden: nur
EIN Geraet, kein Home-Assistant-Server vorhanden.

Konfiguration liegt eigenstaendig unter
~/.openclaw/jarvis-smartthings-data/config.json (token + device_id) -
`setup` legt sie einmalig an.

WICHTIG: SmartThings Personal Access Tokens koennen ablaufen (je nach
Auswahl bei der Erstellung) - ein 401 hier bedeutet meist "Token abgelaufen,
neuen unter account.smartthings.com/tokens erzeugen", nicht einen Bug in
diesem Skript.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".openclaw" / "jarvis-smartthings-data"
CONFIG_FILE = CONFIG_DIR / "config.json"
API_BASE = "https://api.smartthings.com/v1"

# custom.launchapp's namensbasierte Aufloesung funktioniert nicht fuer jede
# App zuverlaessig - Netflix per Name getestet und funktioniert, Disney+/
# Prime Video/Apple Music/Spotify/YouTube/Apple TV per Name NICHT
# (SmartThings meldet "COMPLETED", startet aber tatsaechlich nichts) - live
# beobachtet und live pro App im Wohnzimmer verifiziert (Leon hat jede
# einzelne App am Bildschirm bestaetigt), 2026-09-12. Fuer bekannte,
# namentlich unsichere Apps stattdessen die feste numerische Samsung-App-ID
# mitschicken. Nur Eintraege aufnehmen, die tatsaechlich live verifiziert
# wurden - eine geratene falsche ID waere schlimmer als gar keine (startet
# ggf. gar nichts, ohne dass es sofort auffaellt) - z.B. brauchte Prime Video
# drei falsche IDs, bis die richtige (3201910019365, nicht die weit
# verbreitete 3201512006785) gefunden war.
KNOWN_APP_IDS = {
    "disney+": "3201901017640",
    "disney plus": "3201901017640",
    "youtube": "111299001912",
    "amazon prime video": "3201910019365",
    "prime video": "3201910019365",
    "spotify": "3201606009684",
    "apple tv": "3201807016597",
    "apple music": "3201908019041",
}

# Live per `samsungvd.mediaInputSource`-Status ausgelesen (2026-09-12) - die
# Anzeigenamen, die Leon tatsaechlich benutzt ("PC" fuer den Mac Mini, "TV"
# fuer den TV-Tuner), nicht die internen SmartThings-IDs. Aendert sich Leons
# Verkabelung, muss diese Tabelle neu ausgelesen werden (Skript-Befehl
# `input-sources` zeigt den aktuellen Stand).
KNOWN_INPUT_SOURCES = {
    "pc": "HDMI1",
    "mac mini": "HDMI1",
    "tv": "dtv",
    "fernseher": "dtv",
    "dht-s217": "HDMI3",
    "soundbar": "HDMI3",
    "denon": "HDMI3",
}


def _load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        print(json.dumps({"error": "Nicht eingerichtet - zuerst 'setup --token <token> --device-id <id>' ausfuehren."}))
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text())


def setup(token: str, device_id: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"token": token, "device_id": device_id}))
    CONFIG_FILE.chmod(0o600)
    print(json.dumps({"ok": True}))


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    config = _load_config()
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {config['token']}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            print(json.dumps({"error": "SmartThings-Token abgelaufen oder ungueltig - neuen Token unter account.smartthings.com/tokens erzeugen."}))
        else:
            print(json.dumps({"error": f"SmartThings-Fehler ({exc.code}): {detail}"}))
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(json.dumps({"error": f"SmartThings nicht erreichbar: {exc}"}))
        sys.exit(1)


def _command(capability: str, command: str, arguments: list[Any] | None = None) -> None:
    device_id = _load_config()["device_id"]
    body = {"commands": [{"component": "main", "capability": capability, "command": command, "arguments": arguments or []}]}
    result = _request("POST", f"/devices/{device_id}/commands", body)
    print(json.dumps(result, ensure_ascii=False))


def status() -> None:
    device_id = _load_config()["device_id"]
    result = _request("GET", f"/devices/{device_id}/status")
    main = result.get("components", {}).get("main", {})
    summary = {
        "power": main.get("switch", {}).get("switch", {}).get("value"),
        "volume": main.get("audioVolume", {}).get("volume", {}).get("value"),
        "muted": main.get("audioMute", {}).get("mute", {}).get("value"),
        "input_source": main.get("samsungvd.mediaInputSource", {}).get("inputSource", {}).get("value"),
        "tv_channel": main.get("tvChannel", {}).get("tvChannel", {}).get("value"),
    }
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup")
    setup_parser.add_argument("--token", required=True)
    setup_parser.add_argument("--device-id", required=True)

    subparsers.add_parser("status")
    subparsers.add_parser("on")
    subparsers.add_parser("off")
    subparsers.add_parser("volume-up")
    subparsers.add_parser("volume-down")
    subparsers.add_parser("mute")
    subparsers.add_parser("unmute")
    subparsers.add_parser("play")
    subparsers.add_parser("pause")
    subparsers.add_parser("channel-up")
    subparsers.add_parser("channel-down")

    volume_parser = subparsers.add_parser("set-volume")
    volume_parser.add_argument("level", type=int, help="0-100")

    input_parser = subparsers.add_parser("input")
    input_parser.add_argument("source", help="z.B. PC, TV, DHT-S217 (Anzeigename) oder direkt HDMI1/dtv (interne ID)")

    channel_parser = subparsers.add_parser("channel")
    channel_parser.add_argument("number")

    app_parser = subparsers.add_parser("launch-app")
    app_parser.add_argument("name", help="App-Name (z.B. Netflix, YouTube) - SmartThings versucht den Namen aufzuloesen")

    keys_parser = subparsers.add_parser("keys")
    keys_parser.add_argument(
        "sequence",
        nargs="+",
        help="Eine oder mehrere Fernbedienungstasten nacheinander (UP/DOWN/LEFT/RIGHT/OK/BACK/EXIT/MENU/HOME/MUTE/PLAY/PAUSE/STOP/REWIND/FF/PLAY_BACK/SOURCE), z.B. 'keys LEFT LEFT OK'",
    )

    subparsers.add_parser("open-netflix")

    args = parser.parse_args()

    if args.command == "setup":
        setup(args.token, args.device_id)
    elif args.command == "status":
        status()
    elif args.command == "on":
        _command("switch", "on")
    elif args.command == "off":
        _command("switch", "off")
    elif args.command == "volume-up":
        _command("audioVolume", "volumeUp")
    elif args.command == "volume-down":
        _command("audioVolume", "volumeDown")
    elif args.command == "set-volume":
        _command("audioVolume", "setVolume", [args.level])
    elif args.command == "mute":
        _command("audioMute", "mute")
    elif args.command == "unmute":
        _command("audioMute", "unmute")
    elif args.command == "play":
        _command("mediaPlayback", "play")
    elif args.command == "pause":
        _command("mediaPlayback", "pause")
    elif args.command == "channel-up":
        _command("tvChannel", "channelUp")
    elif args.command == "channel-down":
        _command("tvChannel", "channelDown")
    elif args.command == "channel":
        _command("tvChannel", "setTvChannel", [args.number])
    elif args.command == "input":
        source_id = KNOWN_INPUT_SOURCES.get(args.source.strip().lower(), args.source)
        _command("samsungvd.mediaInputSource", "setInputSource", [source_id])
    elif args.command == "launch-app":
        known_id = KNOWN_APP_IDS.get(args.name.strip().lower())
        if known_id:
            _command("custom.launchapp", "launchApp", [known_id, ""])
        else:
            _command("custom.launchapp", "launchApp", [None, args.name])
    elif args.command == "keys":
        for key in args.sequence:
            _command("samsungvd.remoteControl", "send", [key.upper(), "PRESS_AND_RELEASED"])
            # Kurze Pause zwischen den Tastendruecken - ohne die kommen
            # mehrere schnell nacheinander abgesetzte Befehle auf dem
            # Fernseher teils gar nicht oder in falscher Reihenfolge an
            # (aehnliches Timing-Problem wie bei physischen Fernbedienungen).
            time.sleep(0.6)
    elif args.command == "open-netflix":
        # Live kalibriert 2026-09-12: Leons Profil "Leon Gruenthaler" ist auf
        # diesem Fernseher das oben/zuerst fokussierte Profil in der
        # (vertikalen!) Profilliste - ein einzelnes OK direkt nach dem
        # Laden reicht, JEDE zusaetzliche LEFT/RIGHT-Navigation landet
        # stattdessen auf dem kleinen Stift-("Profil bearbeiten")-Icon
        # daneben und oeffnet versehentlich den Bearbeiten-Dialog.
        _command("custom.launchapp", "launchApp", [None, "Netflix"])
        time.sleep(4)
        _command("samsungvd.remoteControl", "send", ["OK", "PRESS_AND_RELEASED"])


if __name__ == "__main__":
    main()
