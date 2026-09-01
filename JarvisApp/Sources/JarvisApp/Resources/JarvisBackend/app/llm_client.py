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
from claude_code_client import ask_claude_code, ClaudeCodeError

# Modelle, die Ollamas "thinking"-Feature unterstuetzen (per "ollama show <model>"
# verifiziert, 2026-08-19). "think": True bei einem nicht-faehigen Modell
# (phi4-mini, gemma3:4b) schlaegt mit einem harten API-Fehler fehl ("does not
# support thinking"), "think": False bei einem faehigen Modell unterdrueckt das
# Nachdenken nicht wirklich, sondern vermischt es unmarkiert mit der
# eigentlichen Antwort - siehe Kommentar in _ask_ollama().
_THINKING_CAPABLE_MODELS = {"qwen3:4b"}


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
        force_local: bool = False,
        raw_system_prompt: bool = False,
    ) -> str:
        self._refresh_model_state()
        route = route or self.plan(messages, user_text=user_text, force_local=force_local)
        # Ein explizit uebergebenes max_output_tokens muss die vom Router
        # berechnete Standard-Budgetierung ueberschreiben - ask_stream() macht
        # das bereits korrekt (siehe dort), ask() ignorierte es bisher fuer den
        # Ollama-Pfad komplett und nutzte immer route.max_output_tokens. Live
        # beobachtet 2026-08-19: classify_domain_via_llm() bat explizit um nur
        # 20 Token fuer eine knappe Ein-Wort-Klassifikation, bekam aber
        # tatsaechlich das volle Standardbudget des aktiven Modells (z.B. 160
        # bei qwen3:4b) - das gab dem Modell genug Raum, um ueber die geforderte
        # knappe Antwort hinauszugehen und dabei zufaellig Domaenen-Woerter in
        # eine laengere, nicht als Ein-Wort-Antwort gedachte Ausgabe einzustreuen,
        # die dann faelschlich als Kategorie geparst wurde - z.B. stufte das
        # reine "Wie geht es dir, Jarvis?" faelschlich als Kalender/Erinnerung
        # ein, obwohl derselbe Prompt bei tatsaechlich 20 Token sauber "keine"
        # antwortete.
        if max_output_tokens is not None:
            route.max_output_tokens = int(max_output_tokens)
        # "Privater Modus": dispatch on the effective provider, not the user's
        # configured default - route.provider already reflects force_local via plan(),
        # but the actual network call below must too, or a stale/explicitly-passed
        # `route` with provider="ollama" could still be sent to OpenAI here.
        effective_provider = "ollama" if force_local else self.provider
        if effective_provider == "openai":
            return self._ask_openai(messages, max_output_tokens=max_output_tokens, route=route)
        if effective_provider == "claude_code":
            return self._ask_claude_code(messages, route=route)
        if effective_provider == "ollama":
            return self._ask_ollama(messages, route=route, raw_system_prompt=raw_system_prompt)
        raise ValueError(f"Unbekannter KI-Anbieter: {effective_provider}")

    def ask_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        user_text: str | None = None,
        route: ModelRoute | None = None,
        on_chunk: Any | None = None,
        force_local: bool = False,
    ) -> str:
        self._refresh_model_state()
        route = route or self.plan(messages, user_text=user_text, force_local=force_local)
        if max_output_tokens is not None:
            route.max_output_tokens = int(max_output_tokens)
        effective_provider = "ollama" if force_local else self.provider
        if effective_provider == "ollama":
            # Live beobachtet (2026-08-12): Ollamas Streaming-Endpunkt liefert fuer
            # phi4-mini gelegentlich HTTP 200 mit komplett leerem Body (0 Bytes,
            # keine NDJSON-Zeilen ueberhaupt) - reproduzierbar sowohl direkt gegen
            # /api/chat als auch ueber diesen Client, obwohl derselbe Prompt ueber
            # den nicht-gestreamten Weg (ask()) einwandfrei funktioniert. Ein reiner
            # Ollama-/Modell-Bug, kein Fehler in unserem Parsing - aber Leon darf nie
            # eine stille Leerantwort bekommen, nur weil Streaming diesmal ausfiel.
            answer = self._ask_ollama(messages, route=route, stream=True, on_chunk=on_chunk)
            if answer.strip():
                return answer
        elif effective_provider == "openai":
            try:
                return self._ask_openai_stream(messages, max_output_tokens=max_output_tokens, route=route, on_chunk=on_chunk)
            except Exception:
                pass
        answer = self.ask(messages, max_output_tokens=max_output_tokens, user_text=user_text, route=route, force_local=force_local)
        if callable(on_chunk) and answer:
            words = answer.split()
            for index, word in enumerate(words):
                on_chunk(("" if index == 0 else " ") + word)
        return answer

    def plan(self, messages: list[dict[str, str]], user_text: str | None = None, force_local: bool = False) -> ModelRoute:
        self._refresh_model_state()
        installed = self.model_manager.status().installed_models if (self.provider == "ollama" or force_local) else []
        inferred = user_text or self._last_user_text(messages)
        return self.model_router.route(inferred, provider=self.provider, installed_models=installed, force_local=force_local)

    def _ask_ollama(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
        stream: bool = False,
        on_chunk: Any | None = None,
        raw_system_prompt: bool = False,
    ) -> str:
        route = route or self.plan(messages)
        model = os.getenv("OLLAMA_MODEL", route.model or self.model_manager.active_model)
        # "think": False schaltet bei reasoning-faehigen Modellen (aktuell nur
        # qwen3:4b unter den installierten) das Nachdenken NICHT wirklich ab -
        # es unterdrueckt nur die saubere Kennzeichnung als eigenes "thinking"-
        # Feld, der Denkprozess landet dann unmarkiert direkt im "content"-Feld,
        # das an den Nutzer geht. Live beobachtet 2026-08-19: "Wie geht es dir,
        # Jarvis?" ergab damit die rohe Gedankenkette ("Okay, let's see. The
        # user asked...") als sichtbare Antwort statt einer echten. Bei
        # Modellen OHNE thinking-Fähigkeit (phi4-mini, gemma3:4b) wuerde
        # "think": True dagegen einen harten API-Fehler ausloesen ("does not
        # support thinking") - deshalb pro Modell entscheiden statt pauschal.
        payload = {
            "model": model,
            "messages": self._prepare_messages(messages, route=route, raw_system_prompt=raw_system_prompt),
            "stream": bool(stream or route.stream),
            "keep_alive": route.keep_alive,
            "think": model in _THINKING_CAPABLE_MODELS,
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

    def _prepare_messages(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
        raw_system_prompt: bool = False,
    ) -> list[dict[str, str]]:
        recent_limit = route.recent_context_limit if route is not None else min(int(self.config.get("recent_context_messages", 4)), 4)
        if raw_system_prompt:
            # normalize_jarvis_messages() haengt jedem System-Prompt, der nicht
            # bereits woertlich DEFAULT_JARVIS_SYSTEM_PROMPT enthaelt, dieses
            # komplette Persoenlichkeits-Prompt VORAN - sinnvoll fuer normale
            # Chat-Antworten, aber falsch fuer schmale Werkzeug-Aufrufe wie
            # classify_domain_via_llm(), deren strikte "du bist NUR ein
            # Klassifikator"-Anweisung dadurch faktisch von der viel laengeren,
            # widersprechenden Jarvis-Rollenbeschreibung ueberschrieben wurde.
            # Live beobachtet 2026-08-19: das Modell bekam zwei kollidierende
            # Rollen ("hilfsbereiter Assistent mit Tool-Zugriff" UND "reiner
            # Klassifikator") und folgte eher der ersten, laengeren - dadurch
            # stufte es reinen Smalltalk ("Wie geht es dir, Jarvis?")
            # faelschlich als Kalender/Erinnerung ein. raw_system_prompt=True
            # gibt den vom Aufrufer gebauten System-Prompt unveraendert weiter.
            trimmed = [message for message in messages if str(message.get("role") or "") != "system"]
            trimmed = trimmed[-max(0, recent_limit):] if recent_limit > 0 else []
            system_messages = [message for message in messages if str(message.get("role") or "") == "system"]
            system_content = str(system_messages[0].get("content") or "") if system_messages else ""
            return [{"role": "system", "content": system_content}, *trimmed]

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
        prepared = self._prepare_messages(messages, route=route)
        request = {
            "model": model,
            "input": prepared,
            "max_output_tokens": int(max_output_tokens) if max_output_tokens is not None else int(route.max_output_tokens),
        }

        try:
            completion = self._openai_client.chat.completions.create(
                model=model,
                messages=prepared,
                max_tokens=int(max_output_tokens) if max_output_tokens is not None else int(route.max_output_tokens),
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
            "max_output_tokens": int(max_output_tokens) if max_output_tokens is not None else int(route.max_output_tokens),
        }

        retry_response = self._openai_client.responses.create(**retry_request)
        text = str(retry_response.output_text).strip()
        if text:
            return text

        return "Ich habe gerade keine gute Antwort bekommen. Versuch's bitte noch einmal."

    def _ask_claude_code(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
    ) -> str:
        """Nutzt die lokal installierte 'claude'-CLI (Claude Code) als Provider, damit
        Antworten ueber das bestehende Claude-Abo laufen statt ueber die separat
        abgerechnete API. Die CLI nimmt nur einen einzelnen Prompt-String entgegen,
        deshalb werden die vorbereiteten Nachrichten hier zu System-Prompt +
        Verlauf-Text zusammengefasst statt als Rollen-Liste uebergeben."""
        route = route or self.plan(messages)
        prepared = self._prepare_messages(messages, route=route)

        system_content = ""
        turns: list[str] = []
        for message in prepared:
            role = str(message.get("role") or "")
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_content = content
            elif role == "assistant":
                turns.append(f"Jarvis: {content}")
            else:
                turns.append(f"Nutzer: {content}")

        prompt = "\n\n".join(turns) if turns else "Antworte kurz und hilfreich."
        model = os.getenv("CLAUDE_CODE_MODEL", route.model or self.model_manager.active_model)
        timeout = float(self.config.get("claude_code_timeout", 90))

        try:
            return ask_claude_code(prompt, system_prompt=system_content, model=model, timeout=timeout)
        except ClaudeCodeError as exc:
            raise RuntimeError(str(exc)) from exc

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
