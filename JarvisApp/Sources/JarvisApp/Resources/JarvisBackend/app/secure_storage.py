from __future__ import annotations

import getpass
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from data_dir import data_root


def _log_keyring_fallback(action: str, exc: Exception) -> None:
    # Never a hard failure (there's a "security" CLI fallback right after each of
    # these), but a real keychain error (locked keychain, revoked permission,
    # corrupted keychain) was previously invisible - silently falling through made
    # it indistinguishable from "keyring just isn't installed".
    print(f"Keychain-Zugriff über 'keyring' fehlgeschlagen ({action}): {type(exc).__name__}", file=sys.stderr)


SERVICE_NAME = "JarvisOS"
OPENAI_KEY_NAME = "OPENAI_API_KEY"
GEMINI_KEY_NAME = "GEMINI_API_KEY"
OPTIONAL_SECRET_NAMES = {
    "openai": OPENAI_KEY_NAME,
    "gemini": GEMINI_KEY_NAME,
}


class SecureStorageError(RuntimeError):
    pass


def _keyring_module():
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    return keyring


def set_secret(name: str, value: str) -> None:
    cleaned_name = _normalize_secret_name(name)
    cleaned_value = str(value or "").strip()
    if not cleaned_value:
        raise SecureStorageError("Der API-Key ist leer. Ich speichere nichts.")

    keyring = _keyring_module()
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, cleaned_name, cleaned_value)
            return
        except Exception as exc:
            _log_keyring_fallback("set_password", exc)

    _security_add_or_update(cleaned_name, cleaned_value)


def get_secret(name: str) -> str | None:
    cleaned_name = _normalize_secret_name(name)
    keyring = _keyring_module()
    if keyring is not None:
        try:
            value = keyring.get_password(SERVICE_NAME, cleaned_name)
            if value:
                return value
        except Exception as exc:
            _log_keyring_fallback("get_password", exc)

    return _security_find(cleaned_name)


def delete_secret(name: str) -> bool:
    cleaned_name = _normalize_secret_name(name)
    existed = get_secret(cleaned_name) is not None
    keyring = _keyring_module()
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, cleaned_name)
        except Exception as exc:
            _log_keyring_fallback("delete_password", exc)
    _security_delete(cleaned_name)
    return existed


_OPENAI_KEY_CACHE: tuple[float, str | None] = (0.0, None)
_OPENAI_KEY_CACHE_TTL_SECONDS = 5.0


def set_openai_api_key(value: str) -> None:
    global _OPENAI_KEY_CACHE
    set_secret(OPENAI_KEY_NAME, value)
    _OPENAI_KEY_CACHE = (0.0, None)


def get_openai_api_key() -> str | None:
    """Every chat turn ends up calling this at least twice (ModelManager._load() and
    the .provider property both read it, and both get reconstructed on most requests -
    see llm_client.py's _refresh_model_state), and each call is a real Keychain/`security`
    CLI round-trip. The key only ever changes via set/delete above (both invalidate this
    cache immediately), so a few seconds of staleness is safe and removes that latency
    from the hot chat path."""
    global _OPENAI_KEY_CACHE
    cached_at, cached_value = _OPENAI_KEY_CACHE
    if time.monotonic() - cached_at < _OPENAI_KEY_CACHE_TTL_SECONDS:
        return cached_value

    try:
        key = get_secret(OPENAI_KEY_NAME)
    except SecureStorageError:
        raise
    if not key:
        # Session-only fallback for advanced users. Do not store or log this value.
        key = os.getenv(OPENAI_KEY_NAME) or None
    _OPENAI_KEY_CACHE = (time.monotonic(), key)
    return key


def delete_openai_api_key() -> bool:
    global _OPENAI_KEY_CACHE
    _OPENAI_KEY_CACHE = (0.0, None)
    return delete_secret(OPENAI_KEY_NAME)


def prompt_and_store_openai_key() -> str:
    key = getpass.getpass("OpenAI API-Key eingeben (wird nicht angezeigt): ").strip()
    set_openai_api_key(key)
    return "OpenAI API-Key wurde sicher in der macOS Keychain gespeichert."


_GEMINI_KEY_CACHE: tuple[float, str | None] = (0.0, None)
_GEMINI_KEY_CACHE_TTL_SECONDS = 5.0


def set_gemini_api_key(value: str) -> None:
    global _GEMINI_KEY_CACHE
    set_secret(GEMINI_KEY_NAME, value)
    _GEMINI_KEY_CACHE = (0.0, None)


def get_gemini_api_key() -> str | None:
    """Analog zu get_openai_api_key() - siehe dessen Kommentar zum Cache-Grund."""
    global _GEMINI_KEY_CACHE
    cached_at, cached_value = _GEMINI_KEY_CACHE
    if time.monotonic() - cached_at < _GEMINI_KEY_CACHE_TTL_SECONDS:
        return cached_value

    try:
        key = get_secret(GEMINI_KEY_NAME)
    except SecureStorageError:
        raise
    if not key:
        key = os.getenv(GEMINI_KEY_NAME) or None
    _GEMINI_KEY_CACHE = (time.monotonic(), key)
    return key


def delete_gemini_api_key() -> bool:
    global _GEMINI_KEY_CACHE
    _GEMINI_KEY_CACHE = (0.0, None)
    return delete_secret(GEMINI_KEY_NAME)


def prompt_and_store_gemini_key() -> str:
    key = getpass.getpass("Gemini API-Key eingeben (wird nicht angezeigt): ").strip()
    set_gemini_api_key(key)
    return "Gemini API-Key wurde sicher in der macOS Keychain gespeichert."


def check_secure_storage() -> dict[str, Any]:
    result: dict[str, Any] = {
        "service": SERVICE_NAME,
        "keyring_available": False,
        "write_read_delete_ok": False,
        "openai_key_present": False,
        "plaintext_locations": [],
        "error": None,
    }
    test_name = "__JARVIS_PRIVACY_TEST__"
    test_value = "test-secret-value"
    try:
        result["keyring_available"] = _keyring_module() is not None
        set_secret(test_name, test_value)
        read_value = get_secret(test_name)
        delete_secret(test_name)
        result["write_read_delete_ok"] = read_value == test_value
        result["openai_key_present"] = bool(get_secret(OPENAI_KEY_NAME))
    except Exception as exc:
        result["error"] = type(exc).__name__

    result["plaintext_locations"] = find_plaintext_secret_locations()
    return result


def find_plaintext_secret_locations(project_root: Path | None = None) -> list[str]:
    root = project_root or data_root()
    suspicious: list[str] = []
    candidates = [root / "config.json", root / ".env"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lowered = text.lower()
        if "openai_api_key" in lowered or "gemini_api_key" in lowered or "api_key" in lowered or "sk-" in text:
            suspicious.append(str(path))
    return suspicious


def remove_openai_key_from_env_file(project_root: Path | None = None) -> bool:
    root = project_root or data_root()
    path = root / ".env"
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept = [line for line in lines if not line.strip().startswith(f"{OPENAI_KEY_NAME}=")]
    if kept == lines:
        return False
    if kept:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    return True



def _security_add_or_update(account: str, value: str) -> None:
    command = [
        "security",
        "add-generic-password",
        "-U",
        "-s",
        SERVICE_NAME,
        "-a",
        account,
        "-w",
        value,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise SecureStorageError("Der API-Key konnte nicht in der macOS Keychain gespeichert werden.")


def _security_find(account: str) -> str | None:
    command = ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", account, "-w"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _security_delete(account: str) -> None:
    command = ["security", "delete-generic-password", "-s", SERVICE_NAME, "-a", account]
    subprocess.run(command, capture_output=True, text=True, timeout=10)

def _normalize_secret_name(name: str) -> str:
    cleaned = str(name or "").strip().upper()
    if cleaned in OPTIONAL_SECRET_NAMES:
        return OPTIONAL_SECRET_NAMES[cleaned]
    if cleaned == "OPENAI":
        return OPENAI_KEY_NAME
    if not cleaned:
        raise SecureStorageError("Secret-Name fehlt.")
    return cleaned


def secret_file_path(name: str, base_path: Path | None = None) -> Path:
    # Kept only as a non-writing compatibility helper. Do not store secrets in this path.
    root = base_path or Path.home() / ".jarvis" / "secrets"
    return root / name
