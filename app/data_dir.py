from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    """Writable data directory for memory/cache/config.

    Set to Application Support by the Swift launcher (JARVIS_DATA_DIR) when
    running from the bundled, read-only app/ copy. Falls back to the
    directory next to app/ for a normal dev checkout.
    """
    override = os.environ.get("JARVIS_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError(
                f"JARVIS_DATA_DIR muss ein absoluter Pfad sein, nicht '{override}' - "
                "sonst landen Zugangsdaten, Speicher und Protokolle an einem vom "
                "aktuellen Arbeitsverzeichnis abhängigen, unvorhersehbaren Ort."
            )
        return path
    return Path(__file__).resolve().parent.parent
