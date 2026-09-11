#!/usr/bin/env python3
"""Duenner CLI-Wrapper fuer Push-Benachrichtigungen ans iPhone ueber ntfy
(2026-09-11, OpenClaw-Skill) - der Kern-Sendecode ist ein direkter Port von
JARVIS-OS/app/push_notify.py (identische Logik: oeffentlicher ntfy.sh-Server
per Default, Sicherheit ueber ein langes, zufaelliges Topic statt eines
Accounts, Self-Hosting weiterhin ueber --host/--scheme/--port moeglich).

Grund fuer diesen Skill: die "calendar-30min-reminder"-Automation (und jede
andere Automation) liefert bisher nur per "announce" in die Session, in der
sie erstellt wurde - ist diese Session gerade nicht aktiv/beobachtet, geht die
Nachricht klanglos verloren (live beobachtet 2026-09-11: lastDeliveryStatus
"not-delivered", deliverySuppressionReason "silent"). Dieser Skill gibt jeder
Automation/jedem Agenten-Turn einen echten, sitzungsunabhaengigen Zustellweg:
eine Push-Benachrichtigung, die auf Leons iPhone ankommt, egal in welchem Chat
(oder ob ueberhaupt einer) gerade gesprochen wird.

Konfiguration liegt eigenstaendig unter ~/.openclaw/jarvis-ntfy-data/config.json
(kein Zugriff auf das alte Backend noetig) - `setup` legt das private Topic
einmalig an, `send` verschickt darueber.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".openclaw" / "jarvis-ntfy-data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_HOST = "ntfy.sh"
_TIMEOUT_SECONDS = 10.0


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def _default_scheme(host: str) -> str:
    # Direkter Port von app/push_notify.py::_default_scheme - siehe dort fuer
    # die volle Begruendung (nackte IP -> http, echter Hostname -> https).
    try:
        ipaddress.ip_address(host)
        return "http"
    except ValueError:
        return "https"


def cmd_setup(args: argparse.Namespace) -> None:
    config = _load_config()
    if args.host:
        config["ntfy_host"] = args.host
    if args.scheme:
        config["ntfy_scheme"] = args.scheme
    if args.port:
        config["ntfy_port"] = args.port
    if args.topic:
        config["ntfy_topic"] = args.topic

    config.setdefault("ntfy_host", DEFAULT_HOST)
    if not str(config.get("ntfy_topic") or "").strip():
        config["ntfy_topic"] = f"jarvis-{secrets.token_hex(24)}"
    _save_config(config)

    host = str(config["ntfy_host"])
    topic = str(config["ntfy_topic"])
    scheme = str(config.get("ntfy_scheme") or _default_scheme(host))
    subscribe_url = f"{scheme}://{host}/{topic}"
    print(json.dumps({
        "configured": True,
        "host": host,
        "topic": topic,
        "subscribe_url": subscribe_url,
        "instructions": (
            "Ntfy-App auf dem iPhone installieren (App Store), dann in der App "
            f"unter '+' dieses Topic abonnieren: {topic} (Server: {scheme}://{host}). "
            "Danach kommen Nachrichten von diesem Skill als Push-Benachrichtigung an."
        ),
    }, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    config = _load_config()
    configured = bool(str(config.get("ntfy_host") or "").strip()) and bool(str(config.get("ntfy_topic") or "").strip())
    print(json.dumps({
        "configured": configured,
        "host": config.get("ntfy_host"),
        "topic": config.get("ntfy_topic"),
    }, ensure_ascii=False, indent=2))


def cmd_send(args: argparse.Namespace) -> None:
    config = _load_config()
    host = str(config.get("ntfy_host") or "").strip()
    topic = str(config.get("ntfy_topic") or "").strip()
    if not host or not topic:
        print(json.dumps({"sent": False, "error": "Noch nicht eingerichtet - zuerst 'setup' ausfuehren."}, ensure_ascii=False))
        raise SystemExit(1)

    scheme = str(config.get("ntfy_scheme") or "").strip().lower()
    if scheme not in ("http", "https"):
        scheme = _default_scheme(host)
    port = int(config.get("ntfy_port", 443 if scheme == "https" else 80))
    default_port = 443 if scheme == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    target = f"{scheme}://{netloc}/{topic}"

    headers = {"Title": args.title, "Priority": args.priority}
    if args.url:
        headers["Click"] = args.url
    if args.tags:
        headers["Tags"] = args.tags

    try:
        request = urllib.request.Request(target, data=args.message.encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            ok = 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"sent": False, "error": str(exc) or type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1)

    print(json.dumps({"sent": ok}, ensure_ascii=False))
    if not ok:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis Push-Benachrichtigungen ueber ntfy (OpenClaw-Skill)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Privates ntfy-Topic einmalig anlegen (oder Server-Optionen aendern)")
    setup_parser.add_argument("--host", help=f"ntfy-Server-Host, Standard {DEFAULT_HOST}")
    setup_parser.add_argument("--scheme", choices=["http", "https"], help="http/https, Standard automatisch anhand des Hosts")
    setup_parser.add_argument("--port", type=int, help="Abweichender Port, falls der Server nicht auf dem Standardport laeuft")
    setup_parser.add_argument("--topic", help="Bestehendes Topic wiederverwenden statt ein neues zu erzeugen")
    setup_parser.set_defaults(func=cmd_setup)

    subparsers.add_parser("status", help="Zeigt an, ob und wohin bereits eingerichtet ist").set_defaults(func=cmd_status)

    send_parser = subparsers.add_parser("send", help="Push-Nachricht verschicken")
    send_parser.add_argument("--title", required=True, help="Titel der Push-Benachrichtigung")
    send_parser.add_argument("--message", required=True, help="Nachrichtentext")
    send_parser.add_argument("--priority", default="default", choices=["min", "low", "default", "high", "urgent"])
    send_parser.add_argument("--tags", help="Kommagetrennte ntfy-Emoji-Tags, z.B. 'calendar,bell'")
    send_parser.add_argument("--url", help="Ziel-URL, die beim Antippen der Benachrichtigung geoeffnet wird")
    send_parser.set_defaults(func=cmd_send)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
