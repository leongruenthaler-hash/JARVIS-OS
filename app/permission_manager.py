from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from data_dir import data_root
from privacy_logger import PrivacyLogger


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
    "screen": "Jarvis macht nur nach deiner Freigabe einen einzelnen Screenshot deines aktiven Fensters (nicht der ganzen Bildschirm-Ansicht), analysiert ihn lokal und löscht ihn danach sofort wieder.",
    "music": "Jarvis steuert Musik nur, wenn du Musikfunktionen ausdrücklich nutzt.",
    "internet": "Jarvis nutzt Internetzugriff nur für Websuche oder externe Dienste, wenn du zustimmst.",
    "external_api": "Jarvis sendet Daten an externe APIs nur nach aktiver Zustimmung.",
    "cloud_llm": "Jarvis sendet Prompts an Cloud-KI nur nach aktiver Zustimmung. Sensible Inhalte werden vorher angekündigt.",
    "memory": "Jarvis speichert Langzeit-Erinnerungen und Gesprächsverlauf nur, wenn du diese Speicherung erlaubst.",
}


@dataclass
class PermissionState:
    allowed: bool = False
    # True once the user (or an on-demand probe) has actually engaged with this
    # permission - distinguishes "never touched" from "explicitly turned off",
    # so callers can tell "not yet requested" apart from "denied".
    requested: bool = False
    explanation_shown: bool = False
    updated_at: str | None = None


class PermissionManager:
    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "privacy_permissions.json"
        self.data = self._load()
        self._audit_logger = PrivacyLogger(self.base_path / "logs", enabled=self._logging_enabled())

    @staticmethod
    def _logging_enabled() -> bool:
        # Same privacy_logging_enabled flag jarvis.py's own PRIVACY_LOGGER respects -
        # reused, not a new setting. Best-effort: if config.json can't be read for any
        # reason, default to logging on rather than silently losing audit coverage.
        try:
            from settings import load_config
            return bool(load_config().get("privacy_logging_enabled", True))
        except Exception:
            return True

    def _audit(self, permission: str, *, old_allowed: bool, new_allowed: bool, old_requested: bool, new_requested: bool, source: str):
        try:
            self._audit_logger.log(
                "permission_manager",
                "state_change",
                permission=permission,
                old_allowed=old_allowed,
                new_allowed=new_allowed,
                old_requested=old_requested,
                new_requested=new_requested,
                source=source,
            )
        except Exception:
            pass

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = {name: PermissionState().__dict__ for name in PERMISSION_DEFINITIONS}
            self._save(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("privacy_permissions.json is not a JSON object")
        except (json.JSONDecodeError, ValueError):
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

    def is_requested(self, permission: str) -> bool:
        return bool(self.data.get(permission, {}).get("requested", False))

    def explanation(self, permission: str) -> str:
        return PERMISSION_DEFINITIONS.get(permission, "Jarvis braucht diese Berechtigung für die angefragte Funktion.")

    def grant(self, permission: str, source: str = "unknown"):
        if permission not in PERMISSION_DEFINITIONS:
            raise ValueError(f"Unbekannte Berechtigung: {permission}")
        self._set(permission, True, source=source)

    def revoke(self, permission: str, source: str = "unknown"):
        if permission not in PERMISSION_DEFINITIONS:
            raise ValueError(f"Unbekannte Berechtigung: {permission}")
        self._set(permission, False, source=source)

    def mark_explanation_shown(self, permission: str):
        state = self.data.setdefault(permission, PermissionState().__dict__)
        state["explanation_shown"] = True
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    def _set(self, permission: str, allowed: bool, source: str = "unknown"):
        state = self.data.setdefault(permission, PermissionState().__dict__)
        old_allowed = bool(state.get("allowed", False))
        old_requested = bool(state.get("requested", False))
        state["allowed"] = bool(allowed)
        state["requested"] = True
        state["explanation_shown"] = True
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        self._audit(
            permission,
            old_allowed=old_allowed,
            new_allowed=bool(allowed),
            old_requested=old_requested,
            new_requested=True,
            source=source,
        )

    def reset_to_not_requested(self, permission: str, source: str = "session_reset"):
        """Internal-bookkeeping-only reset: clears Jarvis's own "may I attempt
        this" state back to untouched. Does NOT and CANNOT revoke the actual
        macOS system permission grant (TCC) - that lives entirely outside this
        JSON file and is unaffected."""
        state = self.data.setdefault(permission, PermissionState().__dict__)
        old_allowed = bool(state.get("allowed", False))
        old_requested = bool(state.get("requested", False))
        state["allowed"] = False
        state["requested"] = False
        state["explanation_shown"] = False
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        self._audit(
            permission,
            old_allowed=old_allowed,
            new_allowed=False,
            old_requested=old_requested,
            new_requested=False,
            source=source,
        )

    def export(self) -> dict[str, Any]:
        return {
            name: {
                "allowed": bool(self.data.get(name, {}).get("allowed", False)),
                "requested": bool(self.data.get(name, {}).get("requested", False)),
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
