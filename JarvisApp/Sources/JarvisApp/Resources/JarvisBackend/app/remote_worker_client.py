from __future__ import annotations

"""MacBook-seitiger Client fuer den headless Mac-Mini-Worker
(remote_worker_server.py) - siehe plans/... "Jarvis Mac-Mini-Worker".

Kurzer Timeout + Sentinel statt Exception nach aussen: der Mac Mini ist ein
optionales, jederzeit unerreichbares Zusatzgeraet (ausgeschaltet, Netzwerk weg,
im Standby) - jede Aufruferin muss damit sauber weiterleben koennen, statt zu
haengen oder abzustuerzen. Gleiches Robustheits-Muster wie der Kontakte-
Warmlauf-Ping und das Fotoindex-Checkpointing bei Timeout (photos_client.py).
"""

import json
import urllib.error
import urllib.request
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 3.0


def _request(config: dict[str, Any], path: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    host = str(config.get("remote_worker_host") or "").strip()
    token = str(config.get("remote_worker_token") or "").strip()
    if not host or not token:
        return None

    port = int(config.get("remote_worker_port", 8766))
    url = f"http://{host}:{port}{path}"
    request = urllib.request.Request(url, headers={"X-Jarvis-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
        return None


def is_configured(config: dict[str, Any]) -> bool:
    return bool(str(config.get("remote_worker_host") or "").strip()) and bool(
        str(config.get("remote_worker_token") or "").strip()
    )


def fetch_scan_status(config: dict[str, Any]) -> dict[str, Any] | None:
    """Liefert {"photos": ..., "photos_vision": ..., "mail_background": ...} vom
    Mac Mini, oder None wenn nicht konfiguriert/nicht erreichbar - der Aufrufer
    (local_server.py::scan_status_payload) faellt dann auf lokale Werte zurueck."""
    return _request(config, "/api/scan-status")


def search_photos(config: dict[str, Any], query: str, max_results: int | None = None) -> list[dict[str, Any]] | None:
    """Liefert eine Liste von {"filename", "createdAt", "mediaType", "labels",
    "score"} vom Mac-Mini-Index, oder None bei Nichterreichbarkeit. Bewusst
    OHNE "id" (PHAsset.localIdentifier) - der ist zwischen den Photos-
    Bibliotheken der beiden Maschinen nicht zuverlaessig portabel; die
    aufrufende Seite gleicht stattdessen ueber filename+createdAt ab (siehe
    photos_client.py::_export_preview_by_attrs)."""
    from urllib.parse import urlencode

    query_string = urlencode({"q": query, **({"max": max_results} if max_results else {})})
    result = _request(config, f"/api/photos/search?{query_string}")
    if result is None:
        return None
    matches = result.get("matches")
    return matches if isinstance(matches, list) else []
