from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from data_dir import data_root
from permission_manager import PermissionManager
from privacy_logger import PrivacyLogger
from model_manager import ModelManager
from core.usage_patterns import UsagePatternStore


class PrivacyDashboard:
    def __init__(self, config: dict[str, Any], base_path: Path | None = None):
        self.config = config
        self.base_path = base_path or data_root() / "memory"
        self.permission_manager = PermissionManager(self.base_path)
        self.logger = PrivacyLogger(self.base_path / "logs", enabled=bool(config.get("privacy_logging_enabled", True)))

    def status(self) -> str:
        manager = ModelManager(self.config, self.base_path)
        model_status = manager.status()
        provider = model_status.provider
        cloud_ai = provider.lower() in {"openai", "anthropic", "google"}
        stored_files = [path.name for path in self.base_path.glob("*.json") if path.name != "privacy_permissions.json"]
        local_models = ", ".join(model_status.installed_models) if model_status.installed_models else "keine erkannt"
        missing = ", ".join(model_status.missing_models) if model_status.missing_models else "keine"
        return (
            "Datenschutz-Dashboard. "
            f"Aktives Modell: {model_status.active_model}. KI-Anbieter: {provider}. Cloud-KI: {'ja' if cloud_ai else 'nein'}. "
            f"OpenAI aktiv: {'ja' if model_status.openai_enabled else 'nein'}. "
            f"Lokale Modelle: {local_models}. Fehlende empfohlene Modelle: {missing}. "
            f"Gespeicherte Datenbereiche: {', '.join(stored_files) if stored_files else 'keine'}. "
            f"{self.permission_manager.summary()}"
        )

    def export_data(self) -> str:
        export_dir = self.base_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"jarvis_privacy_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        manager = ModelManager(self.config, self.base_path)
        payload: dict[str, Any] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "permissions": self.permission_manager.export(),
            "config_summary": {
                "ai_provider": manager.provider,
                "active_model": manager.active_model,
                "openai_model": self.config.get("openai_model"),
                "stt_engine": self.config.get("stt_engine"),
                "tts_provider": self.config.get("tts_provider"),
                "web_search_enabled": self.config.get("web_search_enabled"),
                "auto_memory_enabled": self.config.get("auto_memory_enabled"),
            },
            "stored_data": {},
        }
        for path in self.base_path.glob("*.json"):
            if path.name == "privacy_permissions.json":
                continue
            try:
                payload["stored_data"][path.name] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload["stored_data"][path.name] = "[unreadable]"
        export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
        return str(export_path)

    def delete_history(self) -> str:
        for name, empty_value in {
            "conversation.json": [],
            "background_mail_cache.json": {},
        }.items():
            path = self.base_path / name
            if path.exists():
                path.write_text(json.dumps(empty_value, ensure_ascii=False, indent=4), encoding="utf-8")
        return "Verlauf und Hintergrund-Cache wurden gelöscht."

    def delete_all_data(self) -> str:
        preserved = {"privacy_permissions.json"}
        failed = []
        for path in self.base_path.glob("*.json"):
            if path.name in preserved:
                continue
            try:
                path.unlink()
            except OSError:
                failed.append(path.name)
        logs = self.logger.clear()
        if failed:
            return (
                f"Achtung: {len(failed)} Datei(en) konnten nicht gelöscht werden ({', '.join(failed)}). "
                f"Logs gelöscht: {logs}."
            )
        return f"Alle lokalen Jarvis-Daten wurden gelöscht. Logs gelöscht: {logs}."

    def clear_logs(self) -> str:
        count = self.logger.clear()
        return f"Technische Logs gelöscht: {count}."

    def clear_usage_patterns(self) -> str:
        # Baustein D, siehe plans/2026-08-08-jarvis-verhaltensmuster-erkennen.md -
        # eigene, gezielte Loesch-Moeglichkeit fuer die Verhaltensmuster-Zaehlung,
        # unabhaengig von delete_all_data() (das ohnehin auch usage_patterns.json
        # mit loescht, da es einfach jede *.json in base_path erfasst).
        UsagePatternStore(self.base_path).clear()
        return "Erkannte Verhaltensmuster wurden gelöscht."
