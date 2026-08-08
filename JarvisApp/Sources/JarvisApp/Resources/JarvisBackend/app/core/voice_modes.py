from __future__ import annotations

# Master-Plan Abschnitt 6.4: Kurzmodus, Standardmodus, Fokusmodus, Diskreter Modus,
# Privater Modus. Pure, dependency-free logic - the actual behavior (system prompt,
# TTS suppression, web-search gating) is applied by the callers in jarvis.py and
# local_server.py. See docs/voice-system.md.

VOICE_MODES = ("kurz", "standard", "fokus", "diskret", "privat")
DEFAULT_VOICE_MODE = "standard"

_MODE_INSTRUCTIONS: dict[str, str] = {
    "kurz": (
        "Kurzmodus ist aktiv: Antworte extrem knapp, nach Möglichkeit in einem Satz, "
        "nur das Wichtigste. Keine Einleitung, keine Zusammenfassung am Ende."
    ),
    "standard": "",
    "fokus": (
        "Fokusmodus ist aktiv: Antworte ausführlich und präzise, mit technischen Details "
        "wo hilfreich - passend für Programmierung, Planung und detaillierte Analysen."
    ),
    "diskret": (
        "Diskreter Modus ist aktiv: Diese Antwort wird nur als Text angezeigt, nicht "
        "vorgelesen. Fasse dich trotzdem klar."
    ),
    "privat": (
        "Privater Modus ist aktiv: Antworte ausschließlich mit lokal verfügbarem Wissen. "
        "Erwähne oder unterstelle keine Cloud-Dienste oder externen Datenquellen."
    ),
}


def is_valid_mode(mode: str | None) -> bool:
    return mode in VOICE_MODES


def normalize_mode(mode: str | None) -> str:
    return mode if is_valid_mode(mode) else DEFAULT_VOICE_MODE


def mode_instruction(mode: str | None) -> str:
    return _MODE_INSTRUCTIONS.get(normalize_mode(mode), "")


def forces_compact(mode: str | None) -> bool:
    return normalize_mode(mode) in ("kurz", "diskret")


def suppresses_voice_output(mode: str | None) -> bool:
    return normalize_mode(mode) == "diskret"


def forces_local_only(mode: str | None) -> bool:
    """"Privater Modus" darf für diesen Zug weder externe Datenquellen (Websuche)
    noch den Cloud-LLM-Anbieter verwenden. Der Aufrufer muss dieses Flag als
    `force_local=True` an LLMClient.plan()/ask()/ask_stream() durchreichen -
    das erzwingt dort tatsächlich Ollama statt OpenAI, unabhängig vom sonst
    konfigurierten Standard-Anbieter. Siehe docs/voice-system.md."""
    return normalize_mode(mode) == "privat"


def disables_web_search(mode: str | None) -> bool:
    return forces_local_only(mode)


def mode_label(mode: str | None) -> str:
    labels = {
        "kurz": "Kurzmodus",
        "standard": "Standardmodus",
        "fokus": "Fokusmodus",
        "diskret": "Diskreter Modus",
        "privat": "Privater Modus",
    }
    return labels.get(normalize_mode(mode), "Standardmodus")
