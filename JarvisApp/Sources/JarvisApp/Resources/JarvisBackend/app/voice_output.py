from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd


class _EdgeTTSPartialFailure(Exception):
    """Raised internally when an Edge-TTS synth/playback failure happens partway
    through a multi-chunk sequence, after one or more earlier chunks already played.
    Carries only the text that was NOT yet spoken, so the macOS fallback repeats just
    the remainder instead of the whole response from the beginning."""

    def __init__(self, remaining_text: str, cause: Exception):
        super().__init__(str(cause))
        self.remaining_text = remaining_text


class VoiceOutput:
    """Sprachausgabe fuer Jarvis: Edge-TTS zuerst, macOS als Fallback."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.current_process: subprocess.Popen | None = None
        self.playing_with_sounddevice = False
        self.is_speaking = False
        self.warned_about_fallback = False
        # Bumped by stop() and by every speak() call. A multi-chunk Edge-TTS sequence
        # checks this between chunks so a stop() (or a newer speak()) fired from
        # another thread while chunk N is mid-flight actually halts chunks N+1.. -
        # without this, stop() only silenced the currently-playing chunk and the loop
        # carried on synthesizing/playing the rest regardless.
        self._generation_lock = threading.Lock()
        self._generation = 0

    def _bump_generation(self) -> int:
        with self._generation_lock:
            self._generation += 1
            return self._generation

    def _is_current(self, generation: int) -> bool:
        with self._generation_lock:
            return generation == self._generation

    def speak(self, text: str, voice: str | None = None):
        text = str(text).strip()
        if not text:
            return

        self.stop()
        generation = self._bump_generation()

        provider = str(self.config.get("tts_provider", "edge")).strip().lower()
        if provider == "edge":
            try:
                self._speak_edge(text, voice, generation)
                return
            except _EdgeTTSPartialFailure as exc:
                self._warn_fallback(exc.__cause__ or exc)
                if self._is_current(generation):
                    self._speak_macos(exc.remaining_text, voice)
                return
            except Exception as exc:
                self._warn_fallback(exc)

        if self._is_current(generation):
            self._speak_macos(text, voice)

    def stop(self):
        self._bump_generation()

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

    def _speak_edge(self, text: str, voice: str | None = None, generation: int | None = None):
        edge_voice = str(
            voice
            or self.config.get("edge_voice")
            or self.config.get("voice")
            or "de-DE-ConradNeural"
        ).strip()

        chunks = self._split_for_tts(text)
        if len(chunks) <= 1:
            # Unique per-call filename (not a fixed "jarvis_edge_tts.mp3") so two
            # overlapping speak() calls - or another local user/process - can't read or
            # collide with each other's half-written audio in the shared system temp dir.
            audio_file = Path(tempfile.gettempdir()) / f"jarvis_edge_tts_{uuid.uuid4().hex}.mp3"
            try:
                asyncio.run(self._save_edge_audio(text, edge_voice, audio_file))
                self._play_audio_file(audio_file)
            finally:
                audio_file.unlink(missing_ok=True)
            return

        self.is_speaking = True
        for index, chunk in enumerate(chunks):
            if not chunk:
                continue

            if generation is not None and not self._is_current(generation):
                # Superseded mid-sequence by stop() or a newer speak() call - don't
                # synthesize/play the remaining chunks.
                return

            audio_file = Path(tempfile.gettempdir()) / f"jarvis_edge_tts_{uuid.uuid4().hex}.mp3"
            try:
                asyncio.run(self._save_edge_audio(chunk, edge_voice, audio_file))
                self._play_audio_file(audio_file, wait=True)
            except Exception as exc:
                # A mid-sequence failure used to propagate straight out of
                # _speak_edge, which speak() would catch and then re-speak the WHOLE
                # original text via the macOS fallback - including the chunk(s) that
                # already played fine via Edge-TTS. Only replay what's left instead.
                remaining = " ".join(c for c in chunks[index:] if c)
                raise _EdgeTTSPartialFailure(remaining, exc) from exc
            finally:
                audio_file.unlink(missing_ok=True)

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
        blocks until playback finishes, then deletes the temp file - this is the only
        consumer of files produced by synthesize_edge_to_file, so it owns cleanup the
        same way _speak_edge cleans up its own per-chunk temp files."""
        path = Path(audio_file)
        try:
            self._play_audio_file(path, wait=True)
        finally:
            path.unlink(missing_ok=True)

    async def _save_edge_audio(self, text: str, voice: str, audio_file: Path):
        import edge_tts

        rate = str(self.config.get("edge_rate", "+0%"))
        volume = str(self.config.get("edge_volume", "+0%"))
        pitch = str(self.config.get("edge_pitch", "+0Hz"))
        timeout_seconds = float(self.config.get("edge_tts_timeout_seconds", 12))

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )
        try:
            await asyncio.wait_for(communicate.save(str(audio_file)), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Edge-TTS-Synthese hat das Zeitlimit von {timeout_seconds:.0f}s ueberschritten "
                "(vermutlich langsames/blockiertes Netzwerk)."
            ) from exc

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

            if len(sentence) > max_chars:
                # A single sentence (no '.', '!' or '?' inside it) can itself exceed
                # max_chars - e.g. a long comma-separated list or run-on clause. Left
                # alone this became its own oversized, unbounded chunk (the whole
                # point of edge_tts_chunk_chars was silently defeated). Split it
                # further via _split_long_tts_part instead of emitting it whole.
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_long_tts_part(sentence, max_chars))
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
