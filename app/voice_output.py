from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd


class VoiceOutput:
    """Sprachausgabe fuer Jarvis: Edge-TTS zuerst, macOS als Fallback."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.current_process: subprocess.Popen | None = None
        self.playing_with_sounddevice = False
        self.is_speaking = False
        self.warned_about_fallback = False

    def speak(self, text: str, voice: str | None = None):
        text = str(text).strip()
        if not text:
            return

        self.stop()

        provider = str(self.config.get("tts_provider", "edge")).strip().lower()
        if provider == "edge":
            try:
                self._speak_edge(text, voice)
                return
            except Exception as exc:
                self._warn_fallback(exc)

        self._speak_macos(text, voice)

    def stop(self):
        if self.playing_with_sounddevice:
            sd.stop()
            self.playing_with_sounddevice = False
            self.is_speaking = False

        if self.current_process is not None:
            if self.current_process.poll() is None:
                self.current_process.terminate()

            self.current_process = None
            self.is_speaking = False

    def wait(self):
        if self.playing_with_sounddevice:
            sd.wait()
            self.playing_with_sounddevice = False
            self.is_speaking = False

        if self.current_process is not None:
            if self.current_process.poll() is None:
                self.current_process.wait()

            self.current_process = None
            self.is_speaking = False

    def _speak_edge(self, text: str, voice: str | None = None):
        edge_voice = str(
            voice
            or self.config.get("edge_voice")
            or self.config.get("voice")
            or "de-DE-ConradNeural"
        ).strip()

        chunks = self._split_for_tts(text)
        if len(chunks) <= 1:
            audio_file = Path(tempfile.gettempdir()) / "jarvis_edge_tts.mp3"
            asyncio.run(self._save_edge_audio(text, edge_voice, audio_file))
            self._play_audio_file(audio_file)
            return

        self.is_speaking = True
        for index, chunk in enumerate(chunks):
            if not chunk:
                continue

            audio_file = Path(tempfile.gettempdir()) / f"jarvis_edge_tts_{index}.mp3"
            asyncio.run(self._save_edge_audio(chunk, edge_voice, audio_file))
            self._play_audio_file(audio_file, wait=True)

    def synthesize_edge_to_file(self, text: str, voice: str | None = None) -> Path:
        """Synthesizes `text` via edge-TTS into a uniquely-named temp file and returns its
        path, WITHOUT playing it - lets a caller prefetch the next segment's audio while
        the current one is still playing. Raises if tts_provider isn't edge or synthesis
        fails; callers should fall back to the combined speak() path in that case."""
        text = str(text).strip()
        if not text:
            raise ValueError("Kein Text zum Synthetisieren angegeben.")

        provider = str(self.config.get("tts_provider", "edge")).strip().lower()
        if provider != "edge":
            raise RuntimeError("synthesize_edge_to_file erfordert tts_provider=edge.")

        edge_voice = str(
            voice
            or self.config.get("edge_voice")
            or self.config.get("voice")
            or "de-DE-ConradNeural"
        ).strip()
        audio_file = Path(tempfile.gettempdir()) / f"jarvis_edge_tts_{uuid.uuid4().hex}.mp3"
        asyncio.run(self._save_edge_audio(text, edge_voice, audio_file))
        return audio_file

    def play_file(self, audio_file: Path | str) -> None:
        """Plays a pre-synthesized audio file (e.g. from synthesize_edge_to_file) and
        blocks until playback finishes."""
        self._play_audio_file(Path(audio_file), wait=True)

    async def _save_edge_audio(self, text: str, voice: str, audio_file: Path):
        import edge_tts

        rate = str(self.config.get("edge_rate", "+0%"))
        volume = str(self.config.get("edge_volume", "+0%"))
        pitch = str(self.config.get("edge_pitch", "+0Hz"))

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )
        await communicate.save(str(audio_file))

    def _play_audio_file(self, audio_file: Path, wait: bool = False):
        import miniaudio

        decoded = miniaudio.decode_file(str(audio_file))
        samples = np.array(decoded.samples, dtype=np.int16)
        audio = samples.reshape(-1, decoded.nchannels)
        audio = audio.astype(np.float32) / 32768.0

        sd.play(audio, decoded.sample_rate, device=self._output_device())
        self.playing_with_sounddevice = True
        self.is_speaking = True
        if wait:
            sd.wait()
            self.playing_with_sounddevice = False
            self.is_speaking = False

    def _output_device(self) -> int | None:
        configured_device = os.getenv("JARVIS_OUTPUT_DEVICE")
        if configured_device is None:
            configured_device = self.config.get("output_device")

        if configured_device in (None, ""):
            return None

        try:
            return int(configured_device)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("output_device muss eine Geraetenummer sein, zum Beispiel 0 oder 1.") from exc

    def _split_for_tts(self, text: str) -> list[str]:
        max_chars = int(self.config.get("edge_tts_chunk_chars", 1200))
        if max_chars <= 0 or len(text) <= max_chars:
            return [text]

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if current and len(current) + 1 + len(sentence) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()

        if current:
            chunks.append(current)

        return chunks or [text]

    def _split_long_tts_part(self, text: str, max_chars: int) -> list[str]:
        text = text.strip()
        if len(text) <= max_chars:
            return [text]

        soft_parts = re.split(r"(?<=[,;:])\s+", text)
        if len(soft_parts) > 1:
            chunks: list[str] = []
            current = ""
            for part in soft_parts:
                part = part.strip()
                if not part:
                    continue

                if current and len(current) + 1 + len(part) > max_chars:
                    chunks.extend(self._split_long_tts_part(current, max_chars))
                    current = part
                else:
                    current = f"{current} {part}".strip()

            if current:
                chunks.extend(self._split_long_tts_part(current, max_chars))
            return chunks

        words = text.split()
        chunks = []
        current = ""
        for word in words:
            if current and len(current) + 1 + len(word) > max_chars:
                chunks.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()

        if current:
            chunks.append(current)

        return chunks or [text]

    def _speak_macos(self, text: str, voice: str | None = None):
        macos_voice = str(
            self.config.get("macos_fallback_voice", "Reed (Deutsch (Deutschland))")
        ).strip()
        command = ["say", "-v", macos_voice, text]

        try:
            self.current_process = subprocess.Popen(command)
            self.is_speaking = True
        except FileNotFoundError as exc:
            raise RuntimeError("macOS-Sprachausgabe 'say' wurde nicht gefunden.") from exc
        except OSError as exc:
            raise RuntimeError(
                f"macOS-Sprachausgabe konnte nicht gestartet werden: {exc}"
            ) from exc

    def _warn_fallback(self, exc: Exception):
        if self.warned_about_fallback:
            return

        print(f"Edge-TTS nicht bereit: {type(exc).__name__}")
        print("Nutze voruebergehend macOS-Sprachausgabe.")
        self.warned_about_fallback = True
