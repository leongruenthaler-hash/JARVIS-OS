#!/usr/bin/env python3
"""Duenner CLI-Wrapper um die Tuya Cloud API, um Leons Tikom-Staubsaugerroboter
("Staubi", Tuya-Geraetetyp "Roboter") per Jarvis-Sprachbefehl zu steuern
(2026-09-12, "Jarvis, mach mir bitte das Wohnzimmer sauber").

Direkter Tuya-Cloud-API-Zugriff statt Home Assistant als Zwischenschicht -
Nutzerentscheidung, da nur EIN Geraet gesteuert werden soll und kein
Home-Assistant-Server existiert. Authentifizierung ueber ein selbst
angelegtes Tuya-IoT-Cloud-Projekt (siehe Konfiguration unten), Konto per
QR-Code mit der Smart-Life-App verknuepft.

Konfiguration liegt eigenstaendig unter ~/.openclaw/jarvis-tuya-data/config.json
(client_id/client_secret/base_url/device_id) - `setup` legt sie einmalig an.

Tuya-Signaturverfahren (2020-Business-API, offiziell dokumentiert):
  str_to_sign = METHOD + "\n" + SHA256(body).hexdigest() + "\n" + "" + "\n" + path_mit_query
  sign_str    = client_id + [access_token] + t + nonce + str_to_sign
  sign        = HMAC-SHA256(sign_str, client_secret).hexdigest().upper()
Access-Token wird gecacht und automatisch erneuert (Tuya-Tokens laufen nach
ca. 2h ab, expire_time kommt in der Token-Antwort mit).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".openclaw" / "jarvis-tuya-data"
CONFIG_PATH = DATA_DIR / "config.json"
TOKEN_CACHE_PATH = DATA_DIR / "token_cache.json"

_TIMEOUT_SECONDS = 15.0


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


def _load_token_cache() -> dict[str, Any]:
    if not TOKEN_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_token_cache(cache: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    try:
        TOKEN_CACHE_PATH.chmod(0o600)
    except OSError:
        pass


class TuyaError(RuntimeError):
    pass


def _sign(client_id: str, client_secret: str, t: str, nonce: str, str_to_sign: str, access_token: str = "") -> str:
    sign_str = client_id + access_token + t + nonce + str_to_sign
    return hmac.new(
        client_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256
    ).hexdigest().upper()


def _request(
    config: dict[str, Any],
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    access_token: str = "",
) -> dict[str, Any]:
    base_url = str(config.get("base_url") or "").rstrip("/")
    client_id = str(config.get("client_id") or "")
    client_secret = str(config.get("client_secret") or "")
    if not base_url or not client_id or not client_secret:
        raise TuyaError("Noch nicht eingerichtet - zuerst 'setup' ausfuehren.")

    body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else b""
    content_sha256 = hashlib.sha256(body_bytes).hexdigest()
    t = str(int(time.time() * 1000))
    nonce = secrets.token_hex(8)
    str_to_sign = f"{method}\n{content_sha256}\n\n{path}"
    sign = _sign(client_id, client_secret, t, nonce, str_to_sign, access_token=access_token)

    headers = {
        "client_id": client_id,
        "sign": sign,
        "t": t,
        "nonce": nonce,
        "sign_method": "HMAC-SHA256",
        "Content-Type": "application/json",
    }
    if access_token:
        headers["access_token"] = access_token

    request = urllib.request.Request(
        base_url + path, data=body_bytes or None, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    payload = json.loads(raw or b"{}")
    if not payload.get("success", False):
        raise TuyaError(f"Tuya-API-Fehler: {payload.get('msg') or payload}")
    return payload


def _get_access_token(config: dict[str, Any]) -> str:
    cache = _load_token_cache()
    now_ms = time.time() * 1000
    if cache.get("access_token") and float(cache.get("expires_at_ms", 0)) > now_ms + 30_000:
        return str(cache["access_token"])

    payload = _request(config, "GET", "/v1.0/token?grant_type=1")
    result = payload.get("result") or {}
    access_token = str(result.get("access_token") or "")
    expire_seconds = int(result.get("expire_time") or 7200)
    if not access_token:
        raise TuyaError("Kein Access-Token in der Tuya-Antwort erhalten.")
    _save_token_cache({
        "access_token": access_token,
        "expires_at_ms": now_ms + (expire_seconds * 1000),
    })
    return access_token


def _authed_request(config: dict[str, Any], method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _get_access_token(config)
    return _request(config, method, path, body=body, access_token=token)


def cmd_setup(args: argparse.Namespace) -> None:
    config = _load_config()
    config["client_id"] = args.client_id
    config["client_secret"] = args.client_secret
    config["base_url"] = args.base_url
    if args.device_id:
        config["device_id"] = args.device_id
    _save_config(config)
    _save_token_cache({})  # erzwingt frischen Token-Abruf nach Config-Aenderung

    try:
        _get_access_token(config)
        print(json.dumps({"configured": True, "token_ok": True}, ensure_ascii=False))
    except TuyaError as exc:
        print(json.dumps({"configured": True, "token_ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def cmd_status(args: argparse.Namespace) -> None:
    config = _load_config()
    device_id = args.device_id or config.get("device_id")
    if not device_id:
        print(json.dumps({"error": "Keine device_id konfiguriert oder uebergeben."}, ensure_ascii=False))
        raise SystemExit(1)
    try:
        payload = _authed_request(config, "GET", f"/v1.0/devices/{device_id}/status")
        print(json.dumps(payload.get("result", []), ensure_ascii=False, indent=2))
    except TuyaError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def cmd_specs(args: argparse.Namespace) -> None:
    config = _load_config()
    device_id = args.device_id or config.get("device_id")
    if not device_id:
        print(json.dumps({"error": "Keine device_id konfiguriert oder uebergeben."}, ensure_ascii=False))
        raise SystemExit(1)
    try:
        payload = _authed_request(config, "GET", f"/v1.0/devices/{device_id}/specifications")
        print(json.dumps(payload.get("result", {}), ensure_ascii=False, indent=2))
    except TuyaError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def _send_commands(config: dict[str, Any], device_id: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _authed_request(config, "POST", f"/v1.0/devices/{device_id}/commands", body={"commands": commands})
    return {"sent": True, "result": payload.get("result")}


def _resolve_device_id(args: argparse.Namespace, config: dict[str, Any]) -> str:
    device_id = getattr(args, "device_id", None) or config.get("device_id")
    if not device_id:
        print(json.dumps({"error": "Keine device_id konfiguriert oder uebergeben."}, ensure_ascii=False))
        raise SystemExit(1)
    return str(device_id)


def cmd_clean(args: argparse.Namespace) -> None:
    """Startet die komplette Reinigung (Modus 'smart' - deckt die ganze
    gespeicherte Karte ab). Raumgenaue Reinigung ist bei diesem Geraet ueber
    die dokumentierte API nicht verlaesslich moeglich, siehe Modulkommentar."""
    config = _load_config()
    device_id = _resolve_device_id(args, config)
    try:
        result = _send_commands(config, device_id, [
            {"code": "mode", "value": "smart"},
            {"code": "power_go", "value": True},
        ])
        print(json.dumps(result, ensure_ascii=False))
    except TuyaError as exc:
        print(json.dumps({"sent": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def cmd_pause(args: argparse.Namespace) -> None:
    config = _load_config()
    device_id = _resolve_device_id(args, config)
    try:
        result = _send_commands(config, device_id, [{"code": "pause", "value": True}])
        print(json.dumps(result, ensure_ascii=False))
    except TuyaError as exc:
        print(json.dumps({"sent": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def cmd_dock(args: argparse.Namespace) -> None:
    """Schickt den Roboter zurueck zur Ladestation."""
    config = _load_config()
    device_id = _resolve_device_id(args, config)
    try:
        result = _send_commands(config, device_id, [{"code": "switch_charge", "value": True}])
        print(json.dumps(result, ensure_ascii=False))
    except TuyaError as exc:
        print(json.dumps({"sent": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def cmd_command(args: argparse.Namespace) -> None:
    config = _load_config()
    device_id = args.device_id or config.get("device_id")
    if not device_id:
        print(json.dumps({"error": "Keine device_id konfiguriert oder uebergeben."}, ensure_ascii=False))
        raise SystemExit(1)
    try:
        commands = json.loads(args.commands)
        if not isinstance(commands, list):
            raise ValueError("commands muss eine JSON-Liste von {\"code\":...,\"value\":...} sein.")
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": f"Ungueltiges --commands JSON: {exc}"}, ensure_ascii=False))
        raise SystemExit(1)

    try:
        payload = _authed_request(
            config, "POST", f"/v1.0/devices/{device_id}/commands", body={"commands": commands}
        )
        print(json.dumps({"sent": True, "result": payload.get("result")}, ensure_ascii=False))
    except TuyaError as exc:
        print(json.dumps({"sent": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tuya-Cloud-API-Wrapper fuer Jarvis (Staubsaugerroboter)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Tuya-Cloud-Zugangsdaten einmalig hinterlegen")
    setup_parser.add_argument("--client-id", required=True)
    setup_parser.add_argument("--client-secret", required=True)
    setup_parser.add_argument("--base-url", required=True, help="z.B. https://openapi.tuyaeu.com")
    setup_parser.add_argument("--device-id", help="Standard-Geraet fuer spaetere Befehle ohne --device-id")
    setup_parser.set_defaults(func=cmd_setup)

    status_parser = subparsers.add_parser("status", help="Aktuellen Geraetestatus (alle DPs) abrufen")
    status_parser.add_argument("--device-id")
    status_parser.set_defaults(func=cmd_status)

    specs_parser = subparsers.add_parser("specs", help="Unterstuetzte Funktionen/DPs des Geraets abrufen")
    specs_parser.add_argument("--device-id")
    specs_parser.set_defaults(func=cmd_specs)

    clean_parser = subparsers.add_parser("clean", help="Komplette Reinigung starten (Modus 'smart')")
    clean_parser.add_argument("--device-id")
    clean_parser.set_defaults(func=cmd_clean)

    pause_parser = subparsers.add_parser("pause", help="Reinigung pausieren")
    pause_parser.add_argument("--device-id")
    pause_parser.set_defaults(func=cmd_pause)

    dock_parser = subparsers.add_parser("dock", help="Zurueck zur Ladestation schicken")
    dock_parser.add_argument("--device-id")
    dock_parser.set_defaults(func=cmd_dock)

    command_parser = subparsers.add_parser("command", help="Einen oder mehrere rohe Befehle senden (Fallback)")
    command_parser.add_argument("--device-id")
    command_parser.add_argument(
        "--commands", required=True,
        help='JSON-Liste, z.B. \'[{"code":"switch","value":true}]\'',
    )
    command_parser.set_defaults(func=cmd_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
