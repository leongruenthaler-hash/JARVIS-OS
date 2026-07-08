from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "config.json"


def load_config(path: Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei fehlt: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any], path: Path = DEFAULT_CONFIG_FILE) -> None:
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
