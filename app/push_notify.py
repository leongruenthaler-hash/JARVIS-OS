from __future__ import annotations

"""Push-Benachrichtigungen ans iPhone ueber einen selbst gehosteten ntfy-Server
(erreichbar per Tailscale) - siehe plans/... "Push-Kanal (Tailscale + ntfy)".

Gleiches Robustheits-Muster wie remote_worker_client.py::_request(): kurzer
Timeout + Sentinel (False) statt Exception nach aussen. Der ntfy-Server ist
ein optionales, jederzeit unerreichbares Zusatzgeraet (Mac Mini aus, Tailscale
weg, noch nicht eingerichtet) - kein Aufrufer darf deswegen haengen, abstuerzen
oder den eigentlichen Chat-Bestaetigungsfluss verzoegern/blockieren. Ein Push
ist immer nur ein Zusatzkanal, nie der garantierte Weg.
"""

import urllib.error
import urllib.request
from typing import Any

_DEFAULT_TIMEOUT_SECONDS = 3.0


def is_configured(config: dict[str, Any]) -> bool:
    return bool(str(config.get("ntfy_host") or "").strip()) and bool(str(config.get("ntfy_topic") or "").strip())


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
        port = int(config.get("ntfy_port", 80))
        topic = str(config.get("ntfy_topic") or "").strip()
        target = f"http://{host}:{port}/{topic}"

        headers = {"Title": title, "Priority": priority}
        if url:
            headers["Click"] = url
        if tags:
            headers["Tags"] = tags

        request = urllib.request.Request(target, data=message.encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, TypeError):
        return False
