from __future__ import annotations

from pathlib import Path


def data_root() -> Path:
    """Feste, eigenstaendige Datenablage fuer diesen OpenClaw-Skill - unabhaengig
    vom alten JARVIS-OS data_root() (kein lauffaehiger Jarvis-Kernprozess mehr
    vorhanden, dessen Pfadkonvention hier weiterzufuehren waere)."""
    path = Path.home() / ".openclaw" / "jarvis-photos-data"
    path.mkdir(parents=True, exist_ok=True)
    return path
