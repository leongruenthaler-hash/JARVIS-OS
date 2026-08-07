from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

# Live-Zugriffs-Protokoll fuer die Gedaechtnis-Ansicht (Phase F-Folgeschritt, siehe
# docs/context-and-memory.md): haelt fest, WANN Jarvis tatsaechlich auf ein konkretes
# Foto, eine Datei oder einen Gedaechtnis-Fakt zugreift - nicht bei jedem Auflisten/
# Suchtreffer, nur bei echtem Zugriff auf ein einzelnes Element. Rein in-memory
# (Ringpuffer), kein Datenschutz-relevantes Persistieren noetig - Inhalt ist fluechtig
# und nur fuer die kurze visuelle "gerade passiert"-Anzeige gedacht.

_MAX_EVENTS = 200
_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)


def record_activity(kind: str, label: str, reference: str | None = None) -> None:
    with _lock:
        _events.append(
            {
                "type": kind,
                "label": label,
                "reference": reference,
                "at": time.time(),
            }
        )


def recent_activity(since: float = 0.0) -> list[dict[str, Any]]:
    with _lock:
        return [event for event in _events if event["at"] > since]
