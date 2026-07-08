from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PERMISSION_DEFINITIONS: dict[str, str] = {
    "microphone": "Jarvis braucht das Mikrofon, um deine Sprachbefehle lokal zu erkennen.",
    "camera": "Jarvis darf die Kamera nur nutzen, wenn du eine sichtbare Kamerafunktion startest.",
    "location": "Jarvis darf Standortdaten nur nutzen, wenn du eine ortsbezogene Funktion ausdrücklich aktivierst.",
    "mail": "Jarvis liest Apple-Mail-Übersichten nur, um deine angefragten Mail-Aufgaben auszuführen.",
    "calendar": "Jarvis nutzt Kalender nur, um Termine anzuzeigen oder nach deiner Bestätigung anzulegen.",
    "reminders": "Jarvis nutzt Erinnerungen nur, um Erinnerungen nach deiner Bestätigung anzulegen oder zu verwalten.",
    "contacts": "Jarvis nutzt Kontakte nur, um angefragte Kontakte zu finden oder Anrufe vorzubereiten.",
    "notes": "Jarvis nutzt Notizen nur, um angefragte Notizen zu erstellen, zu lesen oder zu ändern.",
    "files": "Jarvis nutzt Dateien nur, um angefragte Ordner und Dateien lokal zu suchen, zu kopieren oder zu verschieben.",
    "photos": "Jarvis nutzt Fotos nur, um deine Fotomediathek nach deiner Freigabe zu durchsuchen oder Alben zu erstellen.",
    "music": "Jarvis steuert Musik nur, wenn du Musikfunktionen ausdrücklich nutzt.",
    "internet": "Jarvis nutzt Internetzugriff nur für Websuche oder externe Dienste, wenn du zustimmst.",
    "external_api": "Jarvis sendet Daten an externe APIs nur nach aktiver Zustimmung.",
    "cloud_llm": "Jarvis sendet Prompts an Cloud-KI nur nach aktiver Zustimmung. Sensible Inhalte werden vorher angekündigt.",
    "memory": "Jarvis speichert Langzeit-Erinnerungen und Gesprächsverlauf nur, wenn du diese Speicherung erlaubst.",
}


@dataclass
class PermissionState:
    allowed: bool = False
    explanation_shown: bool = False
    updated_at: str | None = None


class PermissionManager:
    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path(__file__).resolve().parent.parent / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "privacy_permissions.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = {name: PermissionState().__dict__ for name in PERMISSION_DEFINITIONS}
            self._save(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken = self.path.with_suffix(".json.broken")
            self.path.rename(broken)
            data = {name: PermissionState().__dict__ for name in PERMISSION_DEFINITIONS}
        for name in PERMISSION_DEFINITIONS:
            data.setdefault(name, PermissionState().__dict__)
        self._save(data)
        return data

    def _save(self, data: dict[str, Any] | None = None):
        payload = data if data is not None else self.data
        self.base_path.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            dir=str(self.base_path),
            text=True,
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=4))
            tmp.replace(self.path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def is_allowed(self, permission: str) -> bool:
        return bool(self.data.get(permission, {}).get("allowed", False))

    def explanation(self, permission: str) -> str:
        return PERMISSION_DEFINITIONS.get(permission, "Jarvis braucht diese Berechtigung für die angefragte Funktion.")

    def grant(self, permission: str):
        self._set(permission, True)

    def revoke(self, permission: str):
        self._set(permission, False)

    def mark_explanation_shown(self, permission: str):
        state = self.data.setdefault(permission, PermissionState().__dict__)
        state["explanation_shown"] = True
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    def _set(self, permission: str, allowed: bool):
        state = self.data.setdefault(permission, PermissionState().__dict__)
        state["allowed"] = bool(allowed)
        state["explanation_shown"] = True
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    def export(self) -> dict[str, Any]:
        return {
            name: {
                "allowed": bool(self.data.get(name, {}).get("allowed", False)),
                "explanation": explanation,
                "updated_at": self.data.get(name, {}).get("updated_at"),
            }
            for name, explanation in PERMISSION_DEFINITIONS.items()
        }

    def summary(self) -> str:
        active = [name for name in PERMISSION_DEFINITIONS if self.is_allowed(name)]
        inactive = [name for name in PERMISSION_DEFINITIONS if not self.is_allowed(name)]
        return (
            "Aktive Berechtigungen: " + (", ".join(active) if active else "keine") + ". "
            "Deaktiviert: " + (", ".join(inactive) if inactive else "keine") + "."
        )
