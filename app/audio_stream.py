from __future__ import annotations

import queue
import sys
import time
from collections import deque
from dataclasses import dataclass
from threading import Event, Lock
from typing import Callable

import numpy as np
import sounddevice as sd


AUDIO_PIPELINE_LOCK = Lock()


@dataclass
class AudioUtterance:
    audio: np.ndarray
    stats: dict[str, float]


class StreamingAudioListener:
    def __init__(
        self,
        samplerate: int = 16000,
        channels: int = 1,
        input_device: int | None = None,
        chunk_seconds: float = 0.3,
        silence_limit: float = 0.55,
        volume_threshold: float = 0.008,
        min_speech_seconds: float = 0.5,
        min_audio_peak: float = 0.006,
        max_recording_seconds: float = 20.0,
        partial_transcript_interval_seconds: float = 1.15,
        partial_transcript_min_audio_seconds: float = 1.0,
        partial_transcript_max_audio_seconds: float = 6.0,
        is_speaking: Callable[[], bool] | None = None,
    ):
        self.samplerate = samplerate
        self.channels = channels
        self.input_device = input_device
        self.chunk_seconds = chunk_seconds
        self.silence_limit = silence_limit
        self.volume_threshold = volume_threshold
        self.min_speech_seconds = min_speech_seconds
        self.min_audio_peak = min_audio_peak
        self.max_recording_seconds = max_recording_seconds
        self.partial_transcript_interval_seconds = max(0.6, partial_transcript_interval_seconds)
        self.partial_transcript_min_audio_seconds = max(0.6, partial_transcript_min_audio_seconds)
        self.partial_transcript_max_audio_seconds = max(1.5, partial_transcript_max_audio_seconds)
        self.is_speaking = is_speaking or (lambda: False)
        self.blocksize = max(1, int(self.samplerate * self.chunk_seconds))
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._stream_started = False
        self._cancel_event = Event()
        self.keep_stream_open = False

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            if not self._stream.active:
                self._stream.start()
            return

        def callback(indata, frames, time, status):
            if status:
                print("Audio-Hinweis:", status)
            self._audio_queue.put(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            device=self.input_device,
            blocksize=self.blocksize,
            callback=callback,
        )
        self._stream.start()
        self._stream_started = True
        print("VoicePerformanceEvent: microphoneReady", file=sys.stderr)
        print("VoicePerformanceEvent: recordingStarted", file=sys.stderr)
        print("Jarvis hört zu...")

    def _flush_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def stop_stream(self) -> None:
        if self._stream is None:
            return
        try:
            if self._stream.active:
                self._stream.stop()
        except Exception as exc:
            print(f"AudioStopHinweis: {type(exc).__name__}: {exc}", file=sys.stderr)
        self._flush_queue()

    def cancel_current_listen(self) -> None:
        self._cancel_event.set()
        self.stop_stream()
        self._flush_queue()

    def warm(self) -> dict[str, float]:
        start = time.perf_counter()
        try:
            sd.query_devices(device=self.input_device, kind="input")
            self._flush_queue()
            return {"ok": 1.0, "duration": time.perf_counter() - start}
        except Exception as exc:
            print(f"AudioWarmupError: {type(exc).__name__}: {exc}", file=sys.stderr)
            return {"ok": 0.0, "duration": time.perf_counter() - start}

    def listen_for_utterance(
        self,
        on_audio_update: Callable[[np.ndarray, dict[str, float]], None] | None = None,
    ) -> AudioUtterance | None:
        pre_roll: deque[np.ndarray] = deque(maxlen=5)
        speech_chunks: list[np.ndarray] = []
        has_speech = False
        speech_seconds = 0.0
        silence_seconds = 0.0
        elapsed_seconds = 0.0
        last_voice_index = -1
        voice_chunk_count = 0
        noise_samples: list[float] = []
        dynamic_threshold = self.volume_threshold
        last_level_log = 0.0
        last_partial_update = 0.0
        recording_started = time.perf_counter()
        recording_stopped_logged = False

        with AUDIO_PIPELINE_LOCK:
            self._cancel_event.clear()
            self._ensure_stream()
            self._flush_queue()
            while elapsed_seconds < self.max_recording_seconds:
                if self._cancel_event.is_set():
                    print("VoicePerformanceEvent: recordingStopped", file=sys.stderr)
                    if not self.keep_stream_open:
                        self.stop_stream()
                    return None
                try:
                    chunk = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if self.is_speaking():
                    pre_roll.clear()
                    speech_chunks.clear()
                    has_speech = False
                    speech_seconds = 0.0
                    silence_seconds = 0.0
                    voice_chunk_count = 0
                    noise_samples.clear()
                    continue

                chunk = self._ensure_mono(chunk)
                volume = float(np.abs(chunk).mean())
                peak = float(np.abs(chunk).max())

                if not has_speech and len(noise_samples) < 4:
                    noise_samples.append(volume)
                    noise_floor = float(np.median(noise_samples))
                    dynamic_threshold = max(self.volume_threshold, noise_floor * 1.6)

                is_voice = volume >= dynamic_threshold or (
                    has_speech and peak >= self.min_audio_peak * 1.35
                )

                if not has_speech and peak >= max(self.min_audio_peak * 1.1, dynamic_threshold * 0.9):
                    is_voice = True

                if not has_speech and elapsed_seconds - last_level_log >= 2.0:
                    print(
                        "Mikrofonpegel: "
                        f"Mean={volume:.4f} | Peak={peak:.4f} | Schwelle={dynamic_threshold:.4f}"
                    )
                    last_level_log = elapsed_seconds

                if is_voice:
                    if not has_speech:
                        print(
                            "Sprache erkannt... "
                            f"Mean={volume:.4f} | Peak={peak:.4f} | Schwelle={dynamic_threshold:.4f}"
                        )
                        speech_chunks.extend(pre_roll)
                        has_speech = True
                    voice_chunk_count += 1
                    speech_chunks.append(chunk)
                    last_voice_index = len(speech_chunks)
                    speech_seconds += self.chunk_seconds
                    silence_seconds = 0.0
                elif has_speech:
                    speech_chunks.append(chunk)
                    silence_seconds += self.chunk_seconds
                else:
                    pre_roll.append(chunk)

                elapsed_seconds += self.chunk_seconds

                if has_speech and on_audio_update is not None and speech_seconds >= self.partial_transcript_min_audio_seconds:
                    now = time.perf_counter()
                    if now - last_partial_update >= self.partial_transcript_interval_seconds:
                        max_chunks = max(1, int(round(self.partial_transcript_max_audio_seconds / self.chunk_seconds)))
                        preview_chunks = speech_chunks[-max_chunks:]
                        try:
                            preview_audio = np.concatenate(preview_chunks, axis=0).astype(np.float32)
                            on_audio_update(
                                preview_audio,
                                {
                                    "duration": len(preview_audio) / self.samplerate,
                                    "speech_time": speech_seconds,
                                    "mean_volume": float(np.abs(preview_audio).mean()),
                                    "peak_volume": float(np.abs(preview_audio).max()),
                                },
                            )
                        except Exception as exc:
                            print(f"AudioPartialUpdateError: {type(exc).__name__}: {exc}", file=sys.stderr)
                        last_partial_update = now

                enough_speech = speech_seconds >= self.min_speech_seconds and voice_chunk_count >= 4
                required_silence = max(self.silence_limit, 0.85)
                sentence_done = has_speech and enough_speech and silence_seconds >= required_silence
                if sentence_done:
                    print("Satz abgeschlossen, transkribiere...")
                    print("VoicePerformanceEvent: recordingStopped", file=sys.stderr)
                    recording_stopped_logged = True
                    break

        if has_speech and not recording_stopped_logged:
            print("VoicePerformanceEvent: recordingStopped", file=sys.stderr)

        if not has_speech or speech_seconds < self.min_speech_seconds or voice_chunk_count < 2:
            if not self.keep_stream_open:
                self.stop_stream()
            return None

        if last_voice_index > 0:
            trailing_chunks = max(1, int(round(self.silence_limit / self.chunk_seconds)))
            speech_chunks = speech_chunks[: last_voice_index + trailing_chunks]

        audio = np.concatenate(speech_chunks, axis=0).astype(np.float32)
        stats = {
            "duration": len(audio) / self.samplerate,
            "mean_volume": float(np.abs(audio).mean()),
            "peak_volume": float(np.abs(audio).max()),
            "speech_time": speech_seconds,
            "threshold": dynamic_threshold,
            "capture_time": time.perf_counter() - recording_started,
        }

        print(
            "Audio: "
            f"Dauer={stats['duration']:.2f}s | "
            f"Mean={stats['mean_volume']:.4f} | "
            f"Peak={stats['peak_volume']:.4f} | "
            f"Sprache={stats['speech_time']:.2f}s"
        )

        if stats["peak_volume"] < self.min_audio_peak:
            if not self.keep_stream_open:
                self.stop_stream()
            return None

        if not self.keep_stream_open:
            self.stop_stream()

        return AudioUtterance(audio=audio, stats=stats)

    def _ensure_mono(self, chunk: np.ndarray) -> np.ndarray:
        if chunk.ndim == 1:
            return chunk.reshape(-1, 1)

        if chunk.shape[1] == 1:
            return chunk

        return np.mean(chunk, axis=1, keepdims=True).astype(np.float32)


def detect_wake_word(audio_chunk: np.ndarray) -> bool:
    return True


def warm_audio_pipeline(
    samplerate: int = 16000,
    channels: int = 1,
    input_device: int | None = None,
) -> dict[str, float]:
    start = time.perf_counter()
    try:
        sd.query_devices(device=input_device, kind="input")
        return {"ok": 1.0, "duration": time.perf_counter() - start}
    except Exception as exc:
        print(f"AudioWarmupError: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {"ok": 0.0, "duration": time.perf_counter() - start}
