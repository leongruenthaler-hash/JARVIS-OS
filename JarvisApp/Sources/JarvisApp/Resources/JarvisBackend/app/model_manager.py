from __future__ import annotations

import atexit
import json
import os
import tempfile
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_dir import data_root
from secure_storage import get_openai_api_key, SecureStorageError
from settings import load_config


DEFAULT_LOCAL_MODEL = "phi4-mini"
SUPPORTED_LOCAL_MODELS = {
    "phi4-mini": "phi4-mini",
    "gemma": "gemma3:4b",
    "gemma3": "gemma3:4b",
    "gemma3:4b": "gemma3:4b",
    "qwen": "qwen3:4b",
    "qwen3": "qwen3:4b",
    "qwen3:4b": "qwen3:4b",
}
SUPPORTED_MODEL_ORDER = ["phi4-mini", "gemma3:4b", "qwen3:4b"]

_OLLAMA_PROCESS: subprocess.Popen[str] | None = None
_OLLAMA_LAST_START_ATTEMPT: float = 0.0
_OLLAMA_RUNNING_CACHE: tuple[float, bool] = (0.0, False)
_OLLAMA_MODELS_CACHE: tuple[float, list[str]] = (0.0, [])
_OLLAMA_CLEANUP_REGISTERED = False


def _cleanup_ollama_process() -> None:
    """Terminates the Ollama process this module spawned as a self-heal, if it's
    still alive when this Python process exits. Covers cases where jarvis.py exits
    without going through the Swift wrapper's own port-based Ollama cleanup (e.g.
    when running app/jarvis.py standalone)."""
    process = _OLLAMA_PROCESS
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _register_ollama_cleanup() -> None:
    global _OLLAMA_CLEANUP_REGISTERED
    if _OLLAMA_CLEANUP_REGISTERED:
        return
    atexit.register(_cleanup_ollama_process)
    _OLLAMA_CLEANUP_REGISTERED = True


@dataclass
class ModelStatus:
    provider: str
    active_model: str
    openai_enabled: bool
    ollama_installed: bool
    ollama_running: bool
    installed_models: list[str]
    missing_models: list[str]
    openai_key_present: bool


class ModelManager:
    def __init__(self, config: dict[str, Any], base_path: Path | None = None):
        self.config = config
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.path = self.base_path / "model_settings.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        defaults = {
            "provider": "ollama",
            "local_model": DEFAULT_LOCAL_MODEL,
            "openai_enabled": False,
        }
        if not self.path.exists():
            self._save(defaults)
            return defaults
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken = self.path.with_suffix(".json.broken")
            self.path.rename(broken)
            self._save(defaults)
            return defaults
        changed = False
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
                changed = True
        if data.get("provider") not in {"ollama", "openai"}:
            data["provider"] = "ollama"
            changed = True
        normalized_model = normalize_model_name(str(data.get("local_model") or DEFAULT_LOCAL_MODEL))
        if data.get("local_model") != normalized_model:
            data["local_model"] = normalized_model
            changed = True
        try:
            has_key = bool(get_openai_api_key())
        except SecureStorageError:
            has_key = False
        if not bool(data.get("openai_enabled")) or not has_key:
            if data.get("provider") != "ollama":
                data["provider"] = "ollama"
                changed = True
            if data.get("openai_enabled") is not False:
                data["openai_enabled"] = False
                changed = True
        if changed:
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

    @property
    def provider(self) -> str:
        try:
            has_key = bool(get_openai_api_key())
        except SecureStorageError:
            has_key = False
        if self.data.get("provider") == "openai" and self.data.get("openai_enabled") and has_key:
            return "openai"
        return "ollama"

    @property
    def active_model(self) -> str:
        if self.provider == "openai":
            return str(self.config.get("openai_model", "gpt-5.4-nano"))
        return normalize_model_name(str(self.data.get("local_model") or DEFAULT_LOCAL_MODEL))

    def use_standard_model(self) -> str:
        return self.use_local_model(DEFAULT_LOCAL_MODEL)

    def use_local_model(self, model_name: str) -> str:
        model = normalize_model_name(model_name)
        self.data["provider"] = "ollama"
        self.data["openai_enabled"] = False
        self.data["local_model"] = model
        self._save()
        return f"Lokaler Modus aktiv. Ich nutze jetzt {model}."

    def use_openai(self) -> str:
        try:
            has_key = bool(get_openai_api_key())
        except SecureStorageError:
            has_key = False
        if not has_key:
            self.data["provider"] = "ollama"
            self.data["openai_enabled"] = False
            self._save()
            return "OpenAI ist nicht aktiviert. Speichere zuerst deinen API-Key mit: python3 app/jarvis.py --set-openai-key"
        self.data["openai_enabled"] = True
        self.data["provider"] = "openai"
        self._save()
        return "OpenAI ist aktiviert. Ich nutze Cloud-KI nur nach deiner Zustimmung fuer Cloud-KI und externe APIs."

    def work_locally(self) -> str:
        self.data["provider"] = "ollama"
        self.data["openai_enabled"] = False
        self._save()
        return f"Lokaler Modus aktiv. OpenAI ist deaktiviert. Ich nutze {self.data.get('local_model', DEFAULT_LOCAL_MODEL)}."

    def status(self) -> ModelStatus:
        running = is_ollama_running()
        installed = list_installed_ollama_models() if running else []
        missing = [model for model in SUPPORTED_MODEL_ORDER if model not in installed]
        try:
            has_key = bool(get_openai_api_key())
        except SecureStorageError:
            has_key = False
        if self.data.get("provider") == "openai" and self.data.get("openai_enabled") and has_key:
            provider = "openai"
        else:
            provider = "ollama"
        if provider == "openai":
            active_model = str(self.config.get("openai_model", "gpt-5.4-nano"))
        else:
            active_model = normalize_model_name(str(self.data.get("local_model") or DEFAULT_LOCAL_MODEL))
        return ModelStatus(
            provider=provider,
            active_model=active_model,
            openai_enabled=bool(self.data.get("openai_enabled", False) and has_key),
            ollama_installed=is_ollama_installed(),
            ollama_running=running,
            installed_models=installed,
            missing_models=missing,
            openai_key_present=has_key,
        )

    def status_text(self) -> str:
        status = self.status()
        mode = str(self.config.get("model_mode", "performance")).strip().lower()
        if status.provider == "openai":
            return f"Ich nutze aktuell OpenAI mit {status.active_model}. Modus: {mode}. Lokaler Standard bleibt {self.data.get('local_model', DEFAULT_LOCAL_MODEL)}."
        hints = []
        if not status.ollama_installed:
            hints.append("Ollama fehlt. Installiere Ollama von ollama.com.")
        elif not status.ollama_running:
            hints.append("Ollama läuft nicht. Starte es mit: ollama serve")
        elif status.active_model not in status.installed_models:
            hints.append(f"Das aktive Modell fehlt. Bitte ausführen: ollama pull {status.active_model}")
        installed_text = ", ".join(status.installed_models) if status.installed_models else "keine erkannt"
        hint_text = " " + " ".join(hints) if hints else ""
        return f"Ich arbeite lokal im {mode}-Modus mit {status.active_model}. Installierte lokale Modelle: {installed_text}.{hint_text}"



def normalize_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    return SUPPORTED_LOCAL_MODELS.get(normalized, DEFAULT_LOCAL_MODEL)


def ollama_base_url() -> str:
    host = os.environ.get("OLLAMA_HOST")
    if not host:
        try:
            host = load_config().get("ollama_host")
        except Exception:
            host = None
    return f"http://{host or '127.0.0.1:11434'}"


def is_ollama_installed() -> bool:
    bundled = os.environ.get("JARVIS_BUNDLED_OLLAMA")
    if bundled and Path(bundled).exists():
        return True
    return shutil.which("ollama") is not None


def is_ollama_running(timeout: float = 1.5, *, use_cache: bool = True) -> bool:
    global _OLLAMA_RUNNING_CACHE
    now = time.time()
    if use_cache and now - _OLLAMA_RUNNING_CACHE[0] < 1.5:
        return _OLLAMA_RUNNING_CACHE[1]

    base = ollama_base_url()
    urls = [f"{base}/api/tags"]
    if "127.0.0.1" in base:
        urls.append(base.replace("127.0.0.1", "localhost") + "/api/tags")
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status == 200:
                    _OLLAMA_RUNNING_CACHE = (now, True)
                    return True
        except Exception:
            continue
    _OLLAMA_RUNNING_CACHE = (now, False)
    return False


def ensure_ollama_running(wait_seconds: float = 15.0) -> bool:
    if is_ollama_running(use_cache=False):
        return True
    executable = find_ollama_executable()
    started = False

    global _OLLAMA_PROCESS
    global _OLLAMA_LAST_START_ATTEMPT
    now = time.time()
    if now - _OLLAMA_LAST_START_ATTEMPT < 8.0:
        deadline = now + max(0.0, wait_seconds)
        while time.time() < deadline:
            if is_ollama_running(timeout=0.4, use_cache=False):
                return True
            time.sleep(0.2)
        return is_ollama_running(timeout=0.6, use_cache=False)
    _OLLAMA_LAST_START_ATTEMPT = now

    if executable is not None and (_OLLAMA_PROCESS is None or _OLLAMA_PROCESS.poll() is not None):
        try:
            _OLLAMA_PROCESS = subprocess.Popen(
                [executable, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            started = True
            _register_ollama_cleanup()
        except Exception:
            _OLLAMA_PROCESS = None

    if not started:
        app_bundle_candidates = [
            Path("/Applications/Ollama.app"),
            Path.home() / "Applications" / "Ollama.app",
        ]
        for app_bundle in app_bundle_candidates:
            executable_path = app_bundle / "Contents" / "MacOS" / "Ollama"
            if executable_path.exists():
                try:
                    _OLLAMA_PROCESS = subprocess.Popen(
                        [str(executable_path), "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    started = True
                    _register_ollama_cleanup()
                    break
                except Exception:
                    _OLLAMA_PROCESS = None
        if not started and any(bundle.exists() for bundle in app_bundle_candidates):
            try:
                subprocess.Popen(
                    ["open", "-a", "Ollama"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                started = True
            except Exception:
                started = False

    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline:
        if is_ollama_running(timeout=0.7, use_cache=False):
            return True
        time.sleep(0.2)
    return is_ollama_running(timeout=0.8, use_cache=False)


def find_ollama_executable() -> str | None:
    candidates = [
        os.environ.get("JARVIS_BUNDLED_OLLAMA"),
        shutil.which("ollama"),
        "/opt/homebrew/bin/ollama",
        "/usr/local/bin/ollama",
        str(Path.home() / "Applications" / "Ollama.app" / "Contents" / "MacOS" / "Ollama"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def list_installed_ollama_models(timeout: float = 2.0, *, use_cache: bool = True) -> list[str]:
    global _OLLAMA_MODELS_CACHE
    now = time.time()
    if use_cache and now - _OLLAMA_MODELS_CACHE[0] < 8.0:
        return list(_OLLAMA_MODELS_CACHE[1])

    try:
        with urllib.request.urlopen(f"{ollama_base_url()}/api/tags", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    models = []
    for item in data.get("models", []):
        name = str(item.get("name") or "").split(":latest")[0]
        if name:
            models.append(name)
    result = sorted(set(models))
    _OLLAMA_MODELS_CACHE = (now, result)
    return result


def ollama_hint_for_model(model: str = DEFAULT_LOCAL_MODEL) -> str:
    if not is_ollama_installed():
        return "Ollama ist nicht installiert. Installiere Ollama und führe danach aus: ollama pull phi4-mini"
    if not ensure_ollama_running():
        return "Ollama läuft nicht. Bitte starte Ollama oder führe aus: ollama serve"
    installed = list_installed_ollama_models()
    if model not in installed:
        return f"Das Modell {model} fehlt. Bitte führe aus: ollama pull {model}"
    return "Ollama ist bereit."
