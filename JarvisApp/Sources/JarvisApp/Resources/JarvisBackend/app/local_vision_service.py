from __future__ import annotations

import base64
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from model_manager import is_ollama_installed, is_ollama_running, list_installed_ollama_models, ollama_base_url


VISION_MODEL_CANDIDATES = (
    "qwen2.5vl",
    "qwen2.5vl:7b",
    "llava",
    "llava:7b",
    "llama3.2-vision",
    "llama3.2-vision:11b",
    "gemma3:4b",
)


class LocalVisionError(RuntimeError):
    pass


@dataclass
class LocalVisionStatus:
    available: bool
    model: str
    installed_models: list[str]
    message: str


class LocalVisionService:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        configured = self.config.get("local_vision_model")
        self.candidates = [str(configured)] if configured else []
        self.candidates.extend(VISION_MODEL_CANDIDATES)

    def status(self) -> LocalVisionStatus:
        if not is_ollama_installed():
            return LocalVisionStatus(
                available=False,
                model="",
                installed_models=[],
                message="Ollama ist nicht installiert. Installiere Ollama und danach ein lokales Vision-Modell.",
            )
        if not is_ollama_running():
            return LocalVisionStatus(
                available=False,
                model="",
                installed_models=[],
                message="Ollama läuft nicht. Starte Ollama oder führe aus: ollama serve",
            )

        installed = list_installed_ollama_models()
        model = self._select_model(installed)
        if not model:
            return LocalVisionStatus(
                available=False,
                model="",
                installed_models=installed,
                message=(
                    "Es ist noch kein lokales Vision-Modell installiert. "
                    "Empfohlen: ollama pull llava oder ollama pull llama3.2-vision"
                ),
            )

        return LocalVisionStatus(
            available=True,
            model=model,
            installed_models=installed,
            message=f"Lokales Vision-Modell bereit: {model}",
        )

    def describe_image(self, image_url: str | Path) -> dict[str, Any]:
        image_path = Path(image_url)
        status = self.status()
        if not status.available:
            raise LocalVisionError(status.message)
        if not image_path.exists() or image_path.stat().st_size <= 0:
            raise LocalVisionError(f"Bildvorschau fehlt lokal: {image_path}")

        prompt = (
            "Analysiere dieses private Foto lokal fuer Jarvis. Keine Personennamen raten, keine Gesichter identifizieren. "
            "Antworte auf Deutsch als kompaktes JSON mit diesen Schluesseln: "
            "description, objects, scene, colors, text, search_terms. "
            "description: ein kurzer natuerlicher Satz. objects/colors/search_terms: kurze Arrays. "
            "Wenn Text sichtbar ist, schreibe ihn knapp in text."
        )
        response_text = self._ollama_generate(status.model, prompt, image_path)
        parsed = self._parse_response(response_text)
        parsed["model"] = status.model
        return parsed

    def describe_images(self, image_urls: list[str | Path]) -> list[dict[str, Any]]:
        return [self.describe_image(path) for path in image_urls]

    def describe_screen(self, image_url: str | Path) -> dict[str, Any]:
        """Wie describe_image(), aber mit einem auf Bildschirminhalte statt Fotos
        zugeschnittenen Prompt (App/Fenster/sichtbarer Text statt Motiv/Farben)."""
        image_path = Path(image_url)
        status = self.status()
        if not status.available:
            raise LocalVisionError(status.message)
        if not image_path.exists() or image_path.stat().st_size <= 0:
            raise LocalVisionError(f"Screenshot fehlt lokal: {image_path}")

        prompt = (
            "Analysiere diesen Bildschirm-Screenshot lokal fuer Jarvis. Keine Personennamen raten, "
            "keine Gesichter identifizieren. Antworte auf Deutsch als kompaktes JSON mit diesen "
            "Schluesseln: description, app, objects, text, search_terms. "
            "description: ein kurzer natuerlicher Satz, was auf dem Bildschirm zu sehen ist. "
            "app: die vermutlich aktive App oder Website, falls erkennbar, sonst leerer String. "
            "objects/search_terms: kurze Arrays sichtbarer UI-Elemente/Themen. "
            "text: sichtbaren Text (Titel, Ueberschriften) knapp zusammengefasst, nicht wortwoertlich abtippen."
        )
        response_text = self._ollama_generate(status.model, prompt, image_path)
        parsed = self._parse_response(response_text)
        parsed["app"] = clean_text(self._parse_screen_app(response_text))
        parsed["model"] = status.model
        return parsed

    @staticmethod
    def _parse_screen_app(text: str) -> str:
        match = re.search(r'"app"\s*:\s*"([^"]*)"', text)
        return match.group(1) if match else ""

    def extract_search_tags(self, image_url: str | Path) -> list[str]:
        result = self.describe_image(image_url)
        tags: set[str] = set()
        for key in ("objects", "colors", "search_terms"):
            values = result.get(key, [])
            if isinstance(values, list):
                tags.update(str(value).strip().lower() for value in values if str(value).strip())
        scene = str(result.get("scene") or "").strip().lower()
        if scene:
            tags.add(scene)
        return sorted(tags)

    def search_images(self, query: str, entries: list[dict[str, Any]], max_results: int = 25) -> list[dict[str, Any]]:
        terms = {term for term in re.split(r"\W+", query.lower()) if len(term) >= 3}
        matches: list[tuple[int, dict[str, Any]]] = []
        for entry in entries:
            haystack_parts = [
                str(entry.get("filename", "")),
                str(entry.get("local_vision_description", "")),
                str(entry.get("local_vision_scene", "")),
                " ".join(str(v) for v in entry.get("local_vision_objects", []) or []),
                " ".join(str(v) for v in entry.get("local_vision_colors", []) or []),
                " ".join(str(v) for v in entry.get("local_vision_search_terms", []) or []),
                " ".join(str(v) for v in entry.get("labels", []) or []),
                " ".join(str(v) for v in entry.get("texts", []) or []),
            ]
            haystack = " ".join(haystack_parts).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                matches.append((score, entry))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [entry for _score, entry in matches[:max_results]]

    def _select_model(self, installed: list[str]) -> str:
        installed_set = set(installed)
        for candidate in self.candidates:
            if not candidate:
                continue
            normalized = candidate.replace(":latest", "")
            if candidate in installed_set:
                return candidate
            if normalized in installed_set:
                return normalized
        for model in installed:
            lowered = model.lower()
            if "vision" in lowered or "llava" in lowered or "qwen2.5vl" in lowered:
                return model
        return ""

    def _ollama_generate(self, model: str, prompt: str, image_path: Path) -> str:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {
                # War 2048 - live getestet: ein Bildschirm-Screenshot in voller Aufloesung
                # tokenisiert bei qwen2.5vl auf ueber 4000 Tokens (llava kommt mit 2048 aus,
                # qwen2.5vl's Bild-Tokenizer ist feiner) - Ollama antwortet sonst mit HTTP 400
                # "exceeds the available context size" statt einer Beschreibung.
                "num_ctx": int(self.config.get("local_vision_num_ctx", 8192)),
                # War 180 - live getestet: das reicht nicht, um das volle JSON-Schema
                # (description/objects/scene/colors/text/search_terms bzw. .../app) zu Ende
                # zu generieren, das Modell wird mitten im JSON abgeschnitten, json.loads()
                # schlägt fehl und _parse_response() faellt auf den unstrukturierten
                # Rohtext-Fallback zurueck (sichtbar an raw "```json {...", nicht zu Ende
                # geschriebenem JSON in describe_screen()-Antworten).
                "num_predict": int(self.config.get("local_vision_num_predict", 400)),
                "temperature": float(self.config.get("local_vision_temperature", 0.1)),
            },
        }
        request = urllib.request.Request(
            f"{ollama_base_url()}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=float(self.config.get("local_vision_timeout", 90))) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data.get("response") or "").strip()

    def _parse_response(self, text: str) -> dict[str, Any]:
        json_text = text.strip()
        match = re.search(r"\{.*\}", json_text, flags=re.DOTALL)
        if match:
            json_text = match.group(0)
        try:
            data = json.loads(json_text)
            if isinstance(data, dict):
                return {
                    "description": clean_text(data.get("description", "")),
                    "objects": clean_list(data.get("objects", [])),
                    "scene": clean_text(data.get("scene", "")),
                    "colors": clean_list(data.get("colors", [])),
                    "text": clean_text(data.get("text", "")),
                    "search_terms": clean_list(data.get("search_terms", [])),
                    "raw": text[:1000],
                }
        except json.JSONDecodeError:
            pass

        tags = clean_list(re.split(r"[,;\n]", text))
        return {
            "description": clean_text(text[:300]),
            "objects": tags[:12],
            "scene": "",
            "colors": [],
            "text": "",
            "search_terms": tags[:20],
            "raw": text[:1000],
        }


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,;\n]", value)
    elif isinstance(value, list):
        parts = value
    else:
        parts = []
    result = []
    seen = set()
    for item in parts:
        text = clean_text(item).strip(" .,:;").lower()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
