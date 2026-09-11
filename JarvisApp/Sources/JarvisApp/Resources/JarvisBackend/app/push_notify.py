from __future__ import annotations

"""Push-Benachrichtigungen ans iPhone ueber ntfy - siehe plans/...
"Push-Kanal (Tailscale + ntfy)". Standard ist der oeffentliche ntfy.sh-Server
(Homebrews "ntfy"-Paket enthaelt nur den Client, keinen Server - Self-Hosting
haette Docker o.ae. gebraucht, siehe Session-Notizen 2026-08-27) - Sicherheit
kommt ueber ein langes, zufaelliges Topic (nur wer den Namen kennt, kann
mitlesen) und zwingend TLS. Ein spaeter selbst gehosteter Server (z.B. per
Docker im Tailnet) laesst sich ueber `ntfy_scheme`/`ntfy_port` weiterhin
konfigurieren.

Gleiches Robustheits-Muster wie remote_worker_client.py::_request(): kurzer
Timeout + Sentinel (False) statt Exception nach aussen. Der ntfy-Server ist
ein optionales, jederzeit unerreichbares Zusatzgeraet (kein Internet, Server
down, noch nicht eingerichtet) - kein Aufrufer darf deswegen haengen,
abstuerzen oder den eigentlichen Chat-Bestaetigungsfluss verzoegern/
blockieren. Ein Push ist immer nur ein Zusatzkanal, nie der garantierte Weg.
"""

import ipaddress
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from data_dir import data_root

_DEFAULT_TIMEOUT_SECONDS = 3.0

NTFY_TOPIC_FILENAME = "ntfy_topic.token"


def load_or_create_ntfy_topic(base_path: Path | None = None) -> str:
    """Erzeugt beim allerersten Aufruf ein langes, zufaelliges ntfy-Topic und haelt
    es danach dauerhaft in einer eigenen, gitignoreden Datei unter data_root() fest
    - NIE in config.json (das ist eingecheckt, siehe .gitignore und Plan
    "Jarvis proaktiv machen" Abschnitt "Sicherheits-Erkenntnis"). Bei einem
    oeffentlichen ntfy.sh-Server ist der Topic-Name das einzige Geheimnis (wer ihn
    kennt, kann mitlesen), deshalb getrennt von der restlichen, versionierten
    Konfiguration - selbes Muster wie local_server.py::_load_or_create_auth_token().
    Der Aufrufer traegt das Ergebnis bewusst nur in eine LOKALE Kopie des Config-
    Dicts ein (siehe JarvisLocalServer._config_with_ntfy_topic()), niemals in
    self.config selbst, sonst wuerde ein spaeteres save_config() das Geheimnis doch
    ins getrackte config.json zurueckschreiben."""
    path = (base_path or data_root()) / NTFY_TOPIC_FILENAME
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    topic = f"jarvis-{secrets.token_hex(24)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(topic, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return topic


def is_configured(config: dict[str, Any]) -> bool:
    return bool(str(config.get("ntfy_host") or "").strip()) and bool(str(config.get("ntfy_topic") or "").strip())


def _default_scheme(host: str) -> str:
    """https fuer einen echten Hostnamen (z.B. ntfy.sh) - http fuer eine nackte
    IP-Adresse, dem typischen selbst gehosteten Fall im privaten Netz (z.B.
    ueber Tailscale), wo praktisch nie ein gueltiges TLS-Zertifikat existiert.
    Ohne diese Unterscheidung wuerde ein pauschaler https-Default JEDE
    zukuenftige Selbst-Hosting-Einrichtung stillschweigend brechen, nicht nur
    bestehende Configs (Codex-Review 2026-08-27).

    BEKANNTE EINSCHRAENKUNG: ein selbst gehosteter Server unter einem
    Hostnamen statt einer nackten IP (z.B. ein Tailscale-MagicDNS-Name wie
    "mac-mini.tailXXXX.ts.net") faellt hier auf https, obwohl er ohne
    zusaetzliches Tailscale-eigenes TLS-Setup ("tailscale cert") ebenfalls
    kein gueltiges Zertifikat hat - fuer diesen Fall muss ntfy_scheme="http"
    explizit gesetzt werden. Nicht geloest, weil es aktuell keine solche
    Konfiguration gibt (dieses Feature nutzt den oeffentlichen ntfy.sh) und
    eine generische Hostname-Heuristik (Tailscale/mDNS/.local vs. echte
    oeffentliche Domain) ohne konkreten Anwendungsfall Spekulation waere
    (Codex-Review 2026-08-27)."""
    try:
        ipaddress.ip_address(host)
        return "http"
    except ValueError:
        return "https"


_PRIORITY_TO_INT = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}


def _priority_to_int(priority: str) -> int:
    return _PRIORITY_TO_INT.get(priority.strip().lower(), 3)


def send_push(
    config: dict[str, Any],
    title: str,
    message: str,
    *,
    url: str | None = None,
    priority: str = "default",
    tags: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Schickt eine Push-Nachricht an das private ntfy-Topic. `url` wird als
    "Click"-Ziel gesetzt - beim Antippen der Push-Nachricht auf dem iPhone
    oeffnet Safari direkt diese Seite (z.B. die vorausgefuellte TheFork-Seite),
    statt nur die App zu oeffnen. Gibt True nur bei erfolgreichem Versand
    zurueck; ein False bedeutet "nicht konfiguriert oder nicht erreichbar",
    niemals eine geworfene Exception."""
    if not is_configured(config):
        return False

    # Alles Fehleranfaellige (Port-Parsing, Header-/Request-Konstruktion, Versand)
    # bewusst in EINEM try-Block - urspruenglich lag das Port-Parsing davor und
    # konnte bei einem von Hand falsch eingetragenen config.json-Wert (z.B.
    # ntfy_port als Text statt Zahl) ungefangen nach aussen durchschlagen und
    # damit genau den Chat-/Proaktivitaets-Fluss abbrechen, den dieser Helfer
    # laut eigenem Versprechen nie stoeren darf (Codex-Review 2026-08-23).
    try:
        host = str(config.get("ntfy_host") or "").strip()
        topic = str(config.get("ntfy_topic") or "").strip()
        scheme = str(config.get("ntfy_scheme") or "").strip().lower()
        if scheme not in ("http", "https"):
            scheme = _default_scheme(host)
        port = int(config.get("ntfy_port", 443 if scheme == "https" else 80))
        default_port = 443 if scheme == "https" else 80
        netloc = host if port == default_port else f"{host}:{port}"
        # JSON-Publish statt Title/Tags als rohe HTTP-Header (2026-09-11-Fix): ntfy
        # unterstuetzt UTF-8 in Headern laut eigener Doku nicht in jeder
        # Bibliothek/Sprache zuverlaessig - live beobachtet genau dieses Problem mit
        # deutschen Umlauten im Titel (siehe whatsapp-bridge/index.mjs::sendNtfyPush
        # fuer denselben Fix). POST an die Basis-URL statt /<topic>, topic als Feld
        # im JSON-Body - der ganze Payload ist dann regulaeres UTF-8-JSON, kein Header.
        target = f"{scheme}://{netloc}/"
        payload: dict[str, Any] = {"topic": topic, "message": message, "title": title, "priority": _priority_to_int(priority)}
        if url:
            payload["click"] = url
        if tags:
            payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            target, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, TypeError):
        return False
