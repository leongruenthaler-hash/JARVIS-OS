from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib.util
import os
import subprocess
import tempfile
import time
import uuid
import wave

import numpy as np

from data_dir import data_root


class STTEngineError(RuntimeError):
    pass


class BaseSTTEngine:
    name = "base"

    def transcribe(self, audio: np.ndarray) -> str:
        raise NotImplementedError


class AppleSpeechEngine(BaseSTTEngine):
    name = "apple_speech"

    def __init__(self, locale: str = "de-DE"):
        self.locale = locale
        self.app_dir = Path(__file__).resolve().parent
        self.source_file = self.app_dir / "apple_speech.swift"
        self.binary_file = data_root() / "apple_speech"
        print(f"STT Engine: {self.name} ({self.locale})")
        self._ensure_helper()

    def transcribe(self, audio: np.ndarray) -> str:
        # Unique, owner-only filename: a fixed name in the shared system temp dir would
        # let another local account read (or race-overwrite) the user's most recent
        # voice recording, and it was never cleaned up afterwards either.
        audio_file = Path(tempfile.gettempdir()) / f"jarvis_apple_speech_{uuid.uuid4().hex}.wav"
        flat_audio = _flatten_audio(audio)
        _write_wav(audio_file, flat_audio, sample_rate=16000)
        try:
            os.chmod(audio_file, 0o600)
        except OSError:
            pass

        try:
            result = subprocess.run(
                [str(self.binary_file), str(audio_file), self.locale],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if result.returncode != 0:
                error_text = (result.stderr or result.stdout).strip()
                if not error_text:
                    return ""
                raise STTEngineError(f"Apple Speech konnte nicht transkribieren: {error_text}")

            transcript = result.stdout.strip()
            if not transcript:
                duration = len(flat_audio) / 16000
                print(
                    "Apple Speech hat keinen Text geliefert "
                    f"(Audio {duration:.2f}s, Datei {audio_file.stat().st_size} Bytes)."
                )

            return transcript
        finally:
            audio_file.unlink(missing_ok=True)

    def listen_and_transcribe(self) -> tuple[str, dict[str, float]]:
        print("Jarvis hört zu...")
        result = subprocess.run(
            [str(self.binary_file), "--live", self.locale],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout).strip()
            if not error_text:
                return "", {"duration": 0.0, "mean_volume": 0.0, "peak_volume": 0.0}
            raise STTEngineError(f"Apple Speech Live konnte nicht transkribieren: {error_text}")

        debug_text = result.stderr.strip()
        if debug_text:
            print(debug_text)

        transcript = result.stdout.strip()
        if not transcript:
            print("Apple Speech lieferte leer zurück; warte kurz statt Endlosschleife.")
            time.sleep(1.0)

        return transcript, {
            "duration": 0.0,
            "mean_volume": 0.0,
            "peak_volume": 0.0,
            "speech_time": 0.0,
            "threshold": 0.0,
        }

    # KEEP IN SYNC: LocalServerController.ensureAppleSpeechHelperCompiled() in
    # JarvisApp/Sources/JarvisApp/Core/LocalServerController.swift is a byte-for-byte
    # port of this method's logic (same mtime comparison, same swiftc invocation) - it
    # exists because the live-transcription path launches this binary directly from
    # Swift, bypassing this Python engine (and therefore this lazy-compile check)
    # entirely. If you change the compile logic here, change it there too.
    def _ensure_helper(self):
        if not self.source_file.exists():
            raise STTEngineError(f"Apple-Speech-Helper fehlt: {self.source_file}")

        needs_compile = not self.binary_file.exists()
        if not needs_compile:
            needs_compile = self.source_file.stat().st_mtime > self.binary_file.stat().st_mtime
        if not needs_compile:
            return

        print("Kompiliere Apple-Speech-Helper...")
        module_cache = Path(tempfile.gettempdir()) / "jarvis_swift_module_cache"
        module_cache.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "swiftc",
                    "-module-cache-path",
                    str(module_cache),
                    str(self.source_file),
                    "-o",
                    str(self.binary_file),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise STTEngineError("Apple-Speech-Helper Kompilierung hat zu lange gedauert.") from exc
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout).strip()
            raise STTEngineError(f"Apple-Speech-Helper konnte nicht kompiliert werden: {error_text}")


class FasterWhisperTurboEngine(BaseSTTEngine):
    name = "faster_whisper_turbo"

    def __init__(
        self,
        model_name: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        cache_dir: Path | None = None,
    ):
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise STTEngineError(f"faster-whisper ist nicht bereit: {exc}") from exc

        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        print(f"STT Engine: {self.name} ({self.model_name}, {self.device}, {self.compute_type})")
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=str(cache_dir) if cache_dir else None,
        )

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _info = self.model.transcribe(
            _flatten_audio(audio),
            language="de",
            vad_filter=False,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
            initial_prompt=(
                "Dies ist ein kurzer deutscher Sprachbefehl an Jarvis. "
                "Häufige Wörter sind: Jarvis, ruf, rufe, anrufen, Baby, Bby, Schatz, "
                "Laura Kurz, Ja, Nein, Fotos, Foto-Freigabe, Mail, Mails, Kalender, "
                "Notiz, Musik, Schreibtisch, Desktop, Datei, Ordner, Rechnung, Versicherung, "
                "Abonnement, Abo, Dokumente, Downloads, Codeordner, Projektordner, "
                "suche, kopiere, verschiebe und erstelle."
            ),
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


class Whisper4BitEngine(BaseSTTEngine):
    name = "whisper_4bit"

    def __init__(
        self,
        model_name: str = "mlx-community/whisper-large-v3-turbo-4bit",
        language: str = "de",
        cache_dir: Path | None = None,
    ):
        self.model_name = model_name
        self.language = language
        self.cache_dir = cache_dir
        self._mlx_whisper = None
        print(f"STT Engine: {self.name} ({self.model_name}, {self.language})")
        self._load_backend()

    def _load_backend(self) -> None:
        if importlib.util.find_spec("mlx_whisper") is None:
            raise STTEngineError(
                "mlx-whisper ist nicht installiert. Installiere optional 'mlx-whisper' "
                "oder nutze den automatischen Faster-Whisper-Fallback."
            )

        try:
            import mlx_whisper
        except Exception as exc:
            raise STTEngineError(f"mlx-whisper konnte nicht geladen werden: {exc}") from exc

        if not hasattr(mlx_whisper, "transcribe"):
            raise STTEngineError("mlx-whisper ist installiert, aber transcribe(...) fehlt.")

        self._mlx_whisper = mlx_whisper

    def transcribe(self, audio: np.ndarray) -> str:
        if self._mlx_whisper is None:
            raise STTEngineError("Whisper-4Bit-Backend ist nicht initialisiert.")

        flat_audio = _flatten_audio(audio)
        result = self._transcribe_array(flat_audio)
        if result is None:
            result = self._transcribe_temp_wav(flat_audio)
        return _extract_transcript_text(result)

    def _transcribe_array(self, audio: np.ndarray):
        try:
            return self._mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self.model_name,
                language=self.language,
                verbose=False,
                word_timestamps=False,
            )
        except TypeError:
            return None
        except Exception as exc:
            message = str(exc).lower()
            if "path" in message or "file" in message or "format" in message:
                return None
            raise STTEngineError(f"Whisper-4Bit konnte Audio nicht transkribieren: {exc}") from exc

    def _transcribe_temp_wav(self, audio: np.ndarray):
        audio_file = Path(tempfile.gettempdir()) / f"jarvis_whisper_4bit_{time.time_ns()}.wav"
        try:
            _write_wav(audio_file, audio, sample_rate=16000)
            return self._mlx_whisper.transcribe(
                str(audio_file),
                path_or_hf_repo=self.model_name,
                language=self.language,
                verbose=False,
                word_timestamps=False,
            )
        except Exception as exc:
            raise STTEngineError(f"Whisper-4Bit konnte WAV nicht transkribieren: {exc}") from exc
        finally:
            try:
                audio_file.unlink(missing_ok=True)
            except Exception:
                pass


class MoonshineStreamingEngine(BaseSTTEngine):
    name = "moonshine_streaming"

    def __init__(
        self,
        preferred_model: str = "UsefulSensors/moonshine-streaming-small",
        fallback_model: str = "UsefulSensors/moonshine-streaming-tiny",
    ):
        self.preferred_model = preferred_model
        self.fallback_model = fallback_model
        print(f"STT Engine: {self.name} ({self.preferred_model})")
        self.backend = self._load_backend()

    def _load_backend(self):
        if importlib.util.find_spec("moonshine_onnx") is not None:
            return self._load_moonshine_onnx_backend()

        if importlib.util.find_spec("moonshine") is not None:
            return self._load_moonshine_backend()

        raise STTEngineError(
            "Kein Moonshine-Python-Paket gefunden. Installiere spaeter moonshine-onnx "
            "oder nutze den automatischen Faster-Whisper-Fallback."
        )

    def _load_moonshine_onnx_backend(self):
        import moonshine_onnx

        if hasattr(moonshine_onnx, "MoonshineOnnxModel"):
            return moonshine_onnx.MoonshineOnnxModel(model_name=self.preferred_model)

        if hasattr(moonshine_onnx, "load_model"):
            return moonshine_onnx.load_model(self.preferred_model)

        raise STTEngineError("moonshine_onnx ist installiert, aber die Modell-API ist unbekannt.")

    def _load_moonshine_backend(self):
        import moonshine

        if hasattr(moonshine, "load_model"):
            return moonshine.load_model(self.preferred_model)

        if hasattr(moonshine, "MoonshineModel"):
            return moonshine.MoonshineModel(self.preferred_model)

        raise STTEngineError("moonshine ist installiert, aber die Modell-API ist unbekannt.")

    def transcribe(self, audio: np.ndarray) -> str:
        audio = _flatten_audio(audio)

        if hasattr(self.backend, "transcribe"):
            result = self.backend.transcribe(audio)
        elif callable(self.backend):
            result = self.backend(audio)
        else:
            raise STTEngineError("Moonshine-Backend kann nicht transkribieren.")

        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return str(result).strip()


def create_stt_engine(config: dict[str, Any]) -> BaseSTTEngine:
    engine_name = str(config.get("stt_engine", "moonshine_streaming")).strip().lower()
    cache_dir = data_root() / ".cache" / "whisper"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if engine_name == "apple_speech":
        return AppleSpeechEngine(locale=str(config.get("apple_speech_locale", "de-DE")))

    if engine_name == "moonshine_streaming":
        try:
            return MoonshineStreamingEngine(
                preferred_model=str(
                    config.get("moonshine_model", "UsefulSensors/moonshine-streaming-small")
                ),
                fallback_model=str(
                    config.get("moonshine_fallback_model", "UsefulSensors/moonshine-streaming-tiny")
                )
            )
        except STTEngineError as exc:
            # moonshine_streaming is the DEFAULT engine, and its own error message
            # ("...oder nutze den automatischen Faster-Whisper-Fallback") promises this
            # fallback - but nothing actually engaged it, so a fresh install without the
            # optional moonshine/moonshine_onnx package installed raised uncaught here
            # instead of falling back, same as the whisper_4bit branch below already does.
            print(f"Moonshine Streaming nicht bereit: {exc}")
            print("Fallback auf faster-whisper")
            return _create_faster_whisper(config, cache_dir)

    if engine_name in {"whisper_4bit", "mlx_whisper_4bit", "quantized_whisper_4bit"}:
        try:
            return Whisper4BitEngine(
                model_name=str(
                    config.get("whisper_4bit_model", "mlx-community/whisper-large-v3-turbo-4bit")
                ),
                language=str(config.get("whisper_4bit_language", "de")),
                cache_dir=cache_dir,
            )
        except STTEngineError as exc:
            print(f"Whisper-4Bit nicht bereit: {exc}")
            print("Fallback auf faster-whisper")
            return _create_faster_whisper(config, cache_dir)

    if engine_name == "faster_whisper_turbo":
        return _create_faster_whisper(config, cache_dir)

    raise STTEngineError(
        f"Unbekannte STT Engine '{engine_name}'. Nutze 'apple_speech', 'moonshine_streaming', 'whisper_4bit' oder 'faster_whisper_turbo'."
    )


def _create_faster_whisper(config: dict[str, Any], cache_dir: Path) -> BaseSTTEngine:
    return FasterWhisperTurboEngine(
        model_name=str(config.get("faster_whisper_model", "base")),
        device=str(config.get("faster_whisper_device", "cpu")),
        compute_type=str(config.get("faster_whisper_compute_type", "int8")),
        cache_dir=cache_dir,
    )


def _flatten_audio(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.reshape(-1)
    return np.clip(audio, -1.0, 1.0)


def _extract_transcript_text(result: Any) -> str:
    if isinstance(result, dict):
        text = result.get("text", "")
        if text:
            return str(text).strip()
        segments = result.get("segments", [])
        if isinstance(segments, list):
            return " ".join(str(segment.get("text", "")).strip() for segment in segments).strip()
        return ""

    if isinstance(result, (list, tuple)):
        return " ".join(str(item).strip() for item in result).strip()

    return str(result or "").strip()


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int = 16000):
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
