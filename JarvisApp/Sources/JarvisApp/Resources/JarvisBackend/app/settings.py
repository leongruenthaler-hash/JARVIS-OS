from __future__ import annotations

import json
import os
import tempfile
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
    data = SEED_CONFIG_FILE.read_text(encoding="utf-8")
    # Same atomic write as save_config(): a crash mid-write here would otherwise
    # leave a truncated config.json that exists() (so this seed step never runs
    # again) but fails json.loads() on every future load_config() call, permanently
    # breaking startup until the file is deleted by hand.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or _default_config_file()
    _ensure_config_seeded(target)
    if not target.exists():
        raise FileNotFoundError(f"Konfigurationsdatei fehlt: {target}")

    return json.loads(target.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    target = path or _default_config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(config, ensure_ascii=False, indent=4) + "\n"
    # Write to a temp file and rename atomically so a crash or power loss
    # mid-write can't leave config.json (which holds the privacy switches)
    # truncated or corrupted.
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
