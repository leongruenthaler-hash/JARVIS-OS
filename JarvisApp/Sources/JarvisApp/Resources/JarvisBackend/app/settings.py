from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_dir import data_root


SEED_CONFIG_FILE = Path(__file__).resolve().parent / "config.beta-template.json"


def _default_config_file() -> Path:
    return data_root() / "config.json"


def _ensure_config_seeded(path: Path) -> None:
    if path.exists():
        return
    if not SEED_CONFIG_FILE.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SEED_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or _default_config_file()
    _ensure_config_seeded(target)
    if not target.exists():
        raise FileNotFoundError(f"Konfigurationsdatei fehlt: {target}")

    return json.loads(target.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    target = path or _default_config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
