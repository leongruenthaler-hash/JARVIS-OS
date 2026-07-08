from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {"prompt", "transcript", "email", "mail", "contact", "body", "content", "message", "answer", "api_key", "token", "secret", "password", "calendar", "event"}
SENSITIVE_KEY_PARTS = ("prompt", "transcript", "email", "mail", "contact", "body", "content", "message", "answer", "api", "key", "token", "secret", "password", "calendar", "event")


class PrivacyLogger:
    def __init__(self, base_path: Path | None = None, enabled: bool = True):
        self.base_path = base_path or Path(__file__).resolve().parent.parent / "memory" / "logs"
        self.enabled = enabled
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "technical.log"

    def log(self, module: str, event: str, success: bool = True, **metadata: Any):
        if not self.enabled:
            return
        safe_metadata = {}
        for key, value in metadata.items():
            lowered_key = key.lower()
            if lowered_key in SENSITIVE_KEYS or any(part in lowered_key for part in SENSITIVE_KEY_PARTS):
                safe_metadata[key] = "[redacted]"
            else:
                safe_metadata[key] = str(value)[:120]
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "module": module,
            "event": event,
            "success": bool(success),
            "metadata": safe_metadata,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def clear(self) -> int:
        count = 0
        for log_file in self.base_path.glob("*.log"):
            try:
                log_file.unlink()
                count += 1
            except OSError:
                continue
        return count
