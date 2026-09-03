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
from claude_code_client import ask_claude_code, ask_claude_code_structured, ClaudeCodeError, is_claude_code_available
from gemini_client import ask_gemini, ask_gemini_structured, GeminiError, is_gemini_available

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

    def _provider_is_available(self, name: str) -> bool:
        """Prueft, ob ein per force_provider gewuenschter Anbieter gerade wirklich
        nutzbar ist (API-Key/CLI-Login vorhanden) - force_provider soll NIE zu einem
        harten Fehler fuehren, nur zu einem stillen Rueckfall auf self.provider, wenn
        der bevorzugte Anbieter (noch) nicht konfiguriert ist."""
        if name == "gemini":
            return is_gemini_available()
        if name == "claude_code":
            return is_claude_code_available()
        if name == "openai":
            try:
                return bool(get_openai_api_key())
            except SecureStorageError:
                return False
        if name == "ollama":
            return True
        return False

    def _resolve_effective_provider(self, force_local: bool, force_provider: str | None) -> str:
        if force_local:
            return "ollama"
        if force_provider and self._provider_is_available(force_provider):
            return force_provider
        return self.provider

    def _plan_for_provider(
        self,
        messages: list[dict[str, str]],
        user_text: str | None = None,
        force_local: bool = False,
        provider_override: str | None = None,
    ) -> ModelRoute:
        provider = provider_override or self.provider
        installed = self.model_manager.status().installed_models if (provider == "ollama" or force_local) else []
        inferred = user_text or self._last_user_text(messages)
        return self.model_router.route(inferred, provider=provider, installed_models=installed, force_local=force_local)

    def ask(
        self,
        messages: list[dict[str, str]],
        max_output_tokens: int | None = None,
        user_text: str | None = None,
        route: ModelRoute | None = None,
        force_local: bool = False,
        raw_system_prompt: bool = False,
        force_provider: str | None = None,
    ) -> str:
        self._refresh_model_state()
        # force_provider erlaubt einem Aufrufer, unabhaengig vom global aktiven Provider
        # (self.provider) gezielt einen anderen Anbieter fuer diesen einen Aufruf zu
        # verlangen - Grundlage der Rollenaufteilung Gemini (schnelle Router-Entscheidung
        # + normale Chat-Antworten) / Claude Code (Hintergrund-Aktionen, eigentliche
        # Aufgaben), siehe core/intent_router.py und jarvis.py::answer_message().
        # Faellt still auf self.provider zurueck, wenn der gewuenschte Anbieter (noch)
        # nicht verfuegbar ist (z.B. kein Gemini-Key hinterlegt).
        effective_provider = self._resolve_effective_provider(force_local, force_provider)
        route = route or self._plan_for_provider(messages, user_text=user_text, force_local=force_local, provider_override=effective_provider)
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
        try:
            return self._dispatch(effective_provider, messages, route, max_output_tokens=max_output_tokens, raw_system_prompt=raw_system_prompt)
        except Exception:
            # Nicht nur RuntimeError: ein Provider-Client kann auch eine rohe, nicht
            # eigens verpackte Exception durchlassen (z.B. ein Netzwerk-Timeout, das nicht
            # in die vom jeweiligen Client erwarteten except-Klauseln passt - live Bug
            # 2026-09-03, siehe gemini_client.py::_call_gemini()-Kommentar zu
            # socket.timeout vs. TimeoutError auf Python 3.9). force_provider soll auch
            # dann noch auf den natuerlichen Provider zurueckfallen koennen, nicht nur bei
            # sauber gemeldeten RuntimeErrors.
            # force_provider ist ein Vorzugswunsch, kein hartes Muss (siehe Kommentar oben) -
            # das gilt nicht nur fuer Nichtverfuegbarkeit (oben schon abgefangen), sondern auch
            # fuer einen tatsaechlichen Fehlschlag beim Aufruf selbst (live beobachtet
            # 2026-09-03: Gemini antwortete zeitweise mit HTTP 503 "high demand"). Ohne diesen
            # Rueckfall haette der Nutzer die rohe Fehlermeldung als Jarvis-Antwort gesehen,
            # obwohl der eigentlich aktive Provider (z.B. Claude Code) die Frage problemlos
            # haette beantworten koennen. Nur EIN Rueckfallversuch, nur wenn wir wegen
            # force_provider ueberhaupt vom natuerlichen self.provider abgewichen sind - ein
            # Fehler vom natuerlichen Provider selbst wird weiterhin normal nach oben gereicht.
            if force_provider and effective_provider == force_provider and effective_provider != self.provider and not force_local:
                fallback_provider = self.provider
                fallback_route = self._plan_for_provider(messages, user_text=user_text, force_local=force_local, provider_override=fallback_provider)
                if max_output_tokens is not None:
                    fallback_route.max_output_tokens = int(max_output_tokens)
                return self._dispatch(fallback_provider, messages, fallback_route, max_output_tokens=max_output_tokens, raw_system_prompt=raw_system_prompt)
            raise

    def _dispatch(
        self,
        provider: str,
        messages: list[dict[str, str]],
        route: ModelRoute,
        max_output_tokens: int | None = None,
        raw_system_prompt: bool = False,
    ) -> str:
        if provider == "openai":
            return self._ask_openai(messages, max_output_tokens=max_output_tokens, route=route)
        if provider == "claude_code":
            return self._ask_claude_code(messages, route=route)
        if provider == "gemini":
            return self._ask_gemini(messages, route=route)
        if provider == "ollama":
            return self._ask_ollama(messages, route=route, raw_system_prompt=raw_system_prompt)
        raise ValueError(f"Unbekannter KI-Anbieter: {provider}")

    def ask_structured(
        self,
        messages: list[dict[str, str]],
        json_schema: dict,
        route: ModelRoute | None = None,
        force_local: bool = False,
        force_provider: str | None = None,
    ) -> dict:
        """Wie ask(), aber erzwingt schema-validierte JSON-Ausgabe statt freien Text -
        Grundlage des Intent-Routers (core/intent_router.py). Claude Code nutzt dafuer
        --json-schema (claude_code_client.py::ask_claude_code_structured), Gemini das
        native responseSchema-Feld (gemini_client.py::ask_gemini_structured), Ollama das
        native "format"-Feld von /api/chat. Der Nachrichtenverlauf wird wie bei ask()
        ueber _prepare_messages()/normalize_jarvis_messages() vorbereitet, damit
        System-Prompt/Persona identisch aufgebaut werden. Siehe force_provider-Kommentar
        in ask()."""
        self._refresh_model_state()
        effective_provider = self._resolve_effective_provider(force_local, force_provider)
        route = route or self._plan_for_provider(messages, force_local=force_local, provider_override=effective_provider)
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

        try:
            return self._dispatch_structured(effective_provider, prompt, json_schema, system_content, messages, route)
        except Exception:
            # Nicht nur RuntimeError: ein Provider-Client kann auch eine rohe, nicht
            # eigens verpackte Exception durchlassen (z.B. ein Netzwerk-Timeout, das nicht
            # in die vom jeweiligen Client erwarteten except-Klauseln passt - live Bug
            # 2026-09-03, siehe gemini_client.py::_call_gemini()-Kommentar zu
            # socket.timeout vs. TimeoutError auf Python 3.9). force_provider soll auch
            # dann noch auf den natuerlichen Provider zurueckfallen koennen, nicht nur bei
            # sauber gemeldeten RuntimeErrors.
            # Gleicher Rueckfall-Gedanke wie in ask() - siehe dortigen Kommentar. Ein
            # transienter Fehler (z.B. Gemini HTTP 503) beim erzwungenen Provider soll die
            # Router-Entscheidung nicht platzen lassen, wenn der natuerliche Provider
            # (self.provider) die Anfrage stattdessen beantworten kann.
            if force_provider and effective_provider == force_provider and effective_provider != self.provider and not force_local:
                fallback_provider = self.provider
                fallback_route = self._plan_for_provider(messages, force_local=force_local, provider_override=fallback_provider)
                fallback_prepared = self._prepare_messages(messages, route=fallback_route)
                fallback_system = ""
                fallback_turns: list[str] = []
                for message in fallback_prepared:
                    role = str(message.get("role") or "")
                    content = str(message.get("content") or "").strip()
                    if not content:
                        continue
                    if role == "system":
                        fallback_system = content
                    elif role == "assistant":
                        fallback_turns.append(f"Jarvis: {content}")
                    else:
                        fallback_turns.append(f"Nutzer: {content}")
                fallback_prompt = "\n\n".join(fallback_turns) if fallback_turns else "Antworte kurz und hilfreich."
                return self._dispatch_structured(fallback_provider, fallback_prompt, json_schema, fallback_system, messages, fallback_route)
            raise

    def _dispatch_structured(
        self,
        provider: str,
        prompt: str,
        json_schema: dict,
        system_content: str,
        messages: list[dict[str, str]],
        route: ModelRoute,
    ) -> dict:
        if provider == "claude_code":
            model = os.getenv("CLAUDE_CODE_MODEL", route.model or self.model_manager.active_model)
            timeout = float(self.config.get("claude_code_timeout", 90))
            try:
                return ask_claude_code_structured(prompt, json_schema=json_schema, system_prompt=system_content, model=model, timeout=timeout)
            except ClaudeCodeError as exc:
                raise RuntimeError(str(exc)) from exc

        if provider == "gemini":
            model = os.getenv("GEMINI_MODEL", route.model or str(self.config.get("gemini_model", "gemini-3.6-flash")))
            timeout = float(self.config.get("gemini_timeout", 20))
            try:
                return ask_gemini_structured(prompt, json_schema=json_schema, system_prompt=system_content, model=model, timeout=timeout)
            except GeminiError as exc:
                raise RuntimeError(str(exc)) from exc

        # Ollama (auch fuer force_local/"privater Modus") und Fallback fuer alles
        # andere (OpenAI hat noch keinen strukturierten Pfad - low priority laut Plan,
        # faellt hier auf Ollama-Aufruf mit demselben Schema zurueck, statt zu scheitern).
        raw = self._ask_ollama(messages, route=route, response_schema=json_schema)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama lieferte keine valide JSON-Antwort fuer den Router: {raw[:200]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Ollama lieferte kein JSON-Objekt fuer den Router.")
        return parsed

    def ask_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        user_text: str | None = None,
        route: ModelRoute | None = None,
        on_chunk: Any | None = None,
        force_local: bool = False,
        force_provider: str | None = None,
    ) -> str:
        self._refresh_model_state()
        effective_provider = self._resolve_effective_provider(force_local, force_provider)
        route = route or self._plan_for_provider(messages, user_text=user_text, force_local=force_local, provider_override=effective_provider)
        if max_output_tokens is not None:
            route.max_output_tokens = int(max_output_tokens)
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
        answer = self.ask(messages, max_output_tokens=max_output_tokens, user_text=user_text, route=route, force_local=force_local, force_provider=force_provider)
        if callable(on_chunk) and answer:
            words = answer.split()
            for index, word in enumerate(words):
                on_chunk(("" if index == 0 else " ") + word)
        return answer

    def plan(self, messages: list[dict[str, str]], user_text: str | None = None, force_local: bool = False) -> ModelRoute:
        self._refresh_model_state()
        return self._plan_for_provider(messages, user_text=user_text, force_local=force_local)

    def _ask_ollama(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
        stream: bool = False,
        on_chunk: Any | None = None,
        raw_system_prompt: bool = False,
        response_schema: dict | None = None,
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
        if response_schema is not None:
            # Ollamas /api/chat akzeptiert ein JSON-Schema im "format"-Feld und
            # erzwingt damit schema-konforme Ausgabe - Grundlage des Intent-Routers
            # (core/intent_router.py) fuer den lokalen Provider, live verifiziert
            # 2026-09-02 gegen phi4-mini (Mechanismus funktioniert, inhaltliche
            # Verlaesslichkeit haengt vom Modell ab).
            payload["format"] = response_schema

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

    def _ask_gemini(
        self,
        messages: list[dict[str, str]],
        route: ModelRoute | None = None,
    ) -> str:
        """Nutzt die Google Gemini API als Provider - im Gegensatz zu Claude Code (Abo
        ueber die lokale CLI) laeuft das ueber einen API-Key und einen einzelnen HTTP-
        Aufruf (gemini_client.py). Gleiches Prompt-Zusammenbau-Muster wie
        _ask_claude_code(), da Geminis generateContent ebenfalls kein Rollen-Array mit
        beliebig vielen System-Nachrichten erwartet."""
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
        model = os.getenv("GEMINI_MODEL", route.model or str(self.config.get("gemini_model", "gemini-3.6-flash")))
        timeout = float(self.config.get("gemini_timeout", 20))

        try:
            return ask_gemini(prompt, system_prompt=system_content, model=model, timeout=timeout)
        except GeminiError as exc:
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
