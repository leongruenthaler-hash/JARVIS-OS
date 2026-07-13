from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from secure_storage import SecureStorageError, get_openai_api_key
from model_router import ModelRoute, ModelRouter
from model_manager import ModelManager, ollama_hint_for_model, ollama_base_url
from jarvis_personality import normalize_jarvis_messages


class LLMClient:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model_manager = ModelManager(config)
        self.provider = self.model_manager.provider
        self.model_router = ModelRouter(config, self.model_manager)
        self._openai_client = None
        self._last_state_refresh = 0.0

    def _refresh_model_state(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_state_refresh < 1.0:
            return
        self.model_manager = ModelManager(self.config)
        self.provider = self.model_manager.provider
        self.model_router = ModelRouter(self.config, self.model_manager)
        self._last_state_refresh = now

    def ask(
        self,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        user_text: str | None = None,
        route: ModelRoute | None = None,
    ) -> str:
        self._refresh_model_state()
        route = route or self.plan(messages, user_text=user_text)
        if self.provider == "openai":
            return self._ask_openai(messages, max_output_tokens=max_output_tokens, route=route)
        if self.provider == "ollama":
            return self._ask_ollama(messages, route=route)
        raise ValueError(f"Unbekannter KI-Anbieter: {self.provider}")

    def ask_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        user_text: str | None = None,
        route: ModelRoute | None = None,
        on_chunk: Any | None = None,
    ) -> str:
        self._refresh_model_state()
        route = route or self.plan(messages, user_text=user_text)
        if max_output_tokens is not None:
            route.max_output_tokens = int(max_output_tokens)
        if self.provider == "ollama":
            return self._ask_ollama(messages, route=route, stream=True, on_chunk=on_chunk)
        if self.provider == "openai":
            try:
                return self._ask_openai_stream(messages, max_output_tokens=max_output_tokens, route=route, on_chunk=on_chunk)
            except Exception:
                pass
        answer = self.ask(messages, max_output_tokens=max_output_tokens, user_text=user_text, route=route)
        if callable(on_chunk) and answer:
            words = answer.split()
            for index, word in enumerate(words):
                on_chunk(("" if index == 0 else " ") + word)
        return answer

    def plan(self, messages: list[dict[str, str]], user_text: str | None = None) -> ModelRoute:
        self._refresh_model_state()
        installed = self.model_manager.status().installed_models if self.provider == "ollama" else []
        inferred = user_text or self._last_user_text(messages)
        return self.model_router.route(inferred, provider=self.provider, installed_models=installed)

    def _ask_ollama(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
        stream: bool = False,
        on_chunk: Any | None = None,
    ) -> str:
        route = route or self.plan(messages)
        model = os.getenv("OLLAMA_MODEL", route.model or self.model_manager.active_model)
        payload = {
            "model": model,
            "messages": self._prepare_messages(messages, route=route),
            "stream": bool(stream or route.stream),
            "keep_alive": route.keep_alive,
            "think": False,
            "options": {
                "num_ctx": int(route.num_ctx),
                "num_predict": int(route.max_output_tokens),
                "temperature": float(route.temperature),
            },
        }

        request = urllib.request.Request(
            f"{ollama_base_url()}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=float(self.config.get("ollama_timeout", 60))) as response:
                if payload["stream"]:
                    return self._read_ollama_stream(response, on_chunk=on_chunk)
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(ollama_hint_for_model(model)) from exc

        return str(data.get("message", {}).get("content", "")).strip()

    def _prepare_messages(self, messages: list[dict[str, str]], route: ModelRoute | None = None) -> list[dict[str, str]]:
        recent_limit = route.recent_context_limit if route is not None else min(int(self.config.get("recent_context_messages", 4)), 4)
        prepared = normalize_jarvis_messages(messages, recent_limit=recent_limit)
        if route is not None and route.system_prompt_suffix and prepared and prepared[0]["role"] == "system":
            prepared[0]["content"] = f"{prepared[0]['content']}\n\n{route.system_prompt_suffix}"
        return prepared

    def _ask_openai_stream(
        self,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        route: ModelRoute | None = None,
        on_chunk: Any | None = None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Das Python-Paket 'openai' ist nicht installiert.") from exc

        if self._openai_client is None:
            timeout = float(self.config.get("openai_timeout", 30))
            try:
                api_key = get_openai_api_key()
            except SecureStorageError as exc:
                raise RuntimeError(str(exc)) from exc
            if not api_key:
                raise RuntimeError(
                    "OpenAI API-Key fehlt. Speichere ihn sicher mit: python3 app/jarvis.py --set-openai-key"
                )
            self._openai_client = OpenAI(api_key=api_key, timeout=timeout)

        route = route or self.plan(messages)
        model = os.getenv("OPENAI_MODEL", route.model or self.model_manager.active_model)
        prepared = self._prepare_messages(messages, route=route)
        complete: list[str] = []

        try:
            stream = self._openai_client.chat.completions.create(
                model=model,
                messages=prepared,
                max_tokens=int(max_output_tokens) if max_output_tokens is not None else int(route.max_output_tokens),
                temperature=float(self.config.get("openai_temperature", 0.3)),
                stream=True,
            )
            for part in stream:
                choices = getattr(part, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                chunk = str(getattr(delta, "content", "") or "")
                if not chunk:
                    continue
                complete.append(chunk)
                if callable(on_chunk):
                    on_chunk(chunk)
            text = "".join(complete).strip()
            if text:
                return text
        except Exception:
            pass

        return self._ask_openai(messages, max_output_tokens=max_output_tokens, route=route)

    def _ask_openai(
        self,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        route: ModelRoute | None = None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Das Python-Paket 'openai' ist nicht installiert.") from exc

        if self._openai_client is None:
            timeout = float(self.config.get("openai_timeout", 30))
            try:
                api_key = get_openai_api_key()
            except SecureStorageError as exc:
                raise RuntimeError(str(exc)) from exc
            if not api_key:
                raise RuntimeError(
                    "OpenAI API-Key fehlt. Speichere ihn sicher mit: python3 app/jarvis.py --set-openai-key"
                )
            self._openai_client = OpenAI(api_key=api_key, timeout=timeout)

        route = route or self.plan(messages)
        model = os.getenv("OPENAI_MODEL", route.model or self.model_manager.active_model)
        request = {
            "model": model,
            "input": self._prepare_messages(messages, route=route),
        }
        if max_output_tokens is not None:
            request["max_output_tokens"] = int(max_output_tokens)
        prepared = self._prepare_messages(messages, route=route)

        try:
            completion = self._openai_client.chat.completions.create(
                model=model,
                messages=prepared,
                max_tokens=int(max_output_tokens) if max_output_tokens is not None else None,
                temperature=float(self.config.get("openai_temperature", 0.3)),
            )
            text = str(completion.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception:
            pass

        response = self._openai_client.responses.create(**request)
        text = str(response.output_text).strip()
        if text:
            return text

        retry_request = {
            "model": model,
            "input": [
                *prepared,
                {
                    "role": "user",
                    "content": (
                        "Antworte jetzt als Jarvis auf Deutsch, ruhig, direkt, hilfreich und natürlich."
                    ),
                },
            ],
        }
        if max_output_tokens is not None:
            retry_request["max_output_tokens"] = int(max_output_tokens)

        retry_response = self._openai_client.responses.create(**retry_request)
        text = str(retry_response.output_text).strip()
        if text:
            return text

        return "Ich habe gerade keine gute Antwort bekommen. Versuch's bitte noch einmal."

    def _read_ollama_stream(self, response: Any, on_chunk: Any | None = None) -> str:
        complete = []
        for raw_line in response:
            try:
                line = raw_line.decode("utf-8").strip()
            except Exception:
                continue
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = str(
                payload.get("message", {}).get("content")
                or payload.get("response")
                or payload.get("content")
                or ""
            )
            if chunk:
                complete.append(chunk)
                if callable(on_chunk):
                    on_chunk(chunk)
            if payload.get("done"):
                break
        return "".join(complete).strip()

    def _last_user_text(self, messages: list[dict[str, str]]) -> str | None:
        for message in reversed(messages):
            if str(message.get("role") or "").strip().lower() == "user":
                content = str(message.get("content") or "").strip()
                if content:
                    return content
        return None
