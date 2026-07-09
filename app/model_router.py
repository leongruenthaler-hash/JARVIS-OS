from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from model_manager import DEFAULT_LOCAL_MODEL, SUPPORTED_MODEL_ORDER, normalize_model_name


@dataclass
class ModelRoute:
    provider: str
    model: str
    max_output_tokens: int
    num_ctx: int
    temperature: float
    recent_context_limit: int
    compact_prompt: bool
    stream: bool
    mode: str
    keep_alive: str = "15m"
    system_prompt_suffix: str = ""


class ModelRouter:
    def __init__(self, config: dict[str, Any], model_manager: Any | None = None):
        self.config = config
        self.model_manager = model_manager

    def route(self, user_text: str | None, provider: str | None = None, installed_models: list[str] | None = None) -> ModelRoute:
        active_provider = str(provider or getattr(self.model_manager, "provider", self.config.get("ai_provider", "ollama"))).strip().lower()
        installed_models = installed_models or []
        text = self._normalize(user_text)
        mode = str(self.config.get("model_mode", "performance")).strip().lower()
        if mode not in {"performance", "balanced", "quality"}:
            mode = "performance"

        if active_provider == "openai":
            return ModelRoute(
                provider="openai",
                model=str(self.config.get("openai_model", "gpt-5.4-nano")),
                max_output_tokens=int(self.config.get("openai_max_output_tokens", 110)),
                num_ctx=int(self.config.get("ollama_num_ctx", 1024)),
                temperature=float(self.config.get("openai_temperature", 0.3)),
                recent_context_limit=2,
                compact_prompt=False,
                stream=True,
                mode="quality",
            )

        simple = self._is_simple(text)
        complex_task = self._is_complex(text)
        selected = self._pick_local_model(mode=mode, simple=simple, complex_task=complex_task, installed_models=installed_models)

        if selected == "phi4-mini":
            return ModelRoute(
                provider="ollama",
                model=selected,
                max_output_tokens=int(self.config.get("ollama_num_predict", 56)),
                num_ctx=int(self.config.get("ollama_num_ctx", 1024)),
                temperature=0.2,
                recent_context_limit=3,
                compact_prompt=True,
                stream=True,
                mode="performance",
            )

        if selected == "gemma3:4b":
            return ModelRoute(
                provider="ollama",
                model=selected,
                max_output_tokens=220,
                num_ctx=max(1536, int(self.config.get("ollama_num_ctx", 1024)) * 2),
                temperature=0.25,
                recent_context_limit=3,
                compact_prompt=False,
                stream=True,
                mode="quality",
            )

        return ModelRoute(
            provider="ollama",
            model=selected,
            max_output_tokens=max(72, int(self.config.get("ollama_num_predict", 56)) + 24),
            num_ctx=max(1280, int(self.config.get("ollama_num_ctx", 1024)) + 256),
            temperature=0.25,
            recent_context_limit=4,
            compact_prompt=simple,
            stream=True,
            mode="balanced",
        )

    def _pick_local_model(self, *, mode: str, simple: bool, complex_task: bool, installed_models: list[str]) -> str:
        installed = {normalize_model_name(model) for model in installed_models}
        selected_mode = mode
        if selected_mode == "performance":
            preferred = "phi4-mini" if simple or "phi4-mini" in installed or not installed else self._first_available(installed)
            if complex_task and "gemma3:4b" in installed:
                return "gemma3:4b"
            return preferred
        if selected_mode == "balanced":
            if complex_task and "gemma3:4b" in installed:
                return "gemma3:4b"
            if "gemma3:4b" in installed:
                return "gemma3:4b"
            if "phi4-mini" in installed:
                return "phi4-mini"
            return self._first_available(installed)
        if selected_mode == "quality":
            if "gemma3:4b" in installed:
                return "gemma3:4b"
            return self._first_available(installed)
        return DEFAULT_LOCAL_MODEL

    def _first_available(self, installed: set[str]) -> str:
        for candidate in SUPPORTED_MODEL_ORDER:
            if candidate in installed:
                return candidate
        return DEFAULT_LOCAL_MODEL

    def _normalize(self, text: str | None) -> str:
        value = str(text or "").strip().lower()
        value = value.replace("-", " ")
        value = re.sub(r"\s+", " ", value)
        return value

    def _is_simple(self, text: str) -> bool:
        keywords = (
            "wie spät",
            "uhrzeit",
            "öffne",
            "oeffne",
            "starte",
            "status",
            "welches modell",
            "modell nutzt",
            "was steht",
            "was gibt es neues",
            "kurz",
            "schnell",
        )
        return any(term in text for term in keywords)

    def _is_complex(self, text: str) -> bool:
        keywords = (
            "erkläre",
            "erklaere",
            "vergleiche",
            "analysiere",
            "debug",
            "problem",
            "warum",
            "wieso",
            "weshalb",
            "beschreibe",
            "zusammenfassen",
            "schreibe eine mail",
            "professionell",
            "entwerfe",
            "code",
            "python",
            "swift",
            "logik",
            "logisch",
            "bewerte",
            "entscheide",
            "strategie",
            "vor- und nachteile",
            "pro und contra",
            "rechnen",
            "berechne",
            "was wäre wenn",
            "welche option",
            "beste option",
        )
        return any(term in text for term in keywords)
