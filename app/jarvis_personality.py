from __future__ import annotations

from core.personality_manager import (
    DEFAULT_JARVIS_SYSTEM_PROMPT as JARVIS_SYSTEM_PROMPT,
    JarvisPersonalityManager,
    build_compact_jarvis_system_prompt,
    build_jarvis_system_prompt,
    normalize_jarvis_messages,
)


def message_shape(messages):
    parts = []
    for message in messages:
        role = str(message.get("role") or "?")
        content = str(message.get("content") or message.get("text") or "")
        parts.append(f"{role}:{len(content)}")
    return ",".join(parts)


def text_summary(text: str) -> str:
    content = str(text or "").strip()
    words = len(content.split()) if content else 0
    return f"chars={len(content)} words={words}"
