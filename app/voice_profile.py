from __future__ import annotations

import json
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from data_dir import data_root

VOICE_PROFILE_FILENAME = "voice_profile.json"

# Urspruenglich grosszuegig auf 0.6 gesetzt (Leons Entscheidung, siehe
# plans/2026-08-10-jarvis-sprecher-verifikation-weckwort.md), nach Leons Live-Test
# auf 0.75 angehoben: der Weckwort-Clip enthaelt oft nur das eine Wort "Jarvis"
# (unter 1s Sprache) - bei so kurzen Clips streut die Aehnlichkeit staerker, eine
# bewusst verstellte (deutlich hoehere) Stimme wurde bei 0.6 nicht zuverlaessig
# abgelehnt. 0.75 als straffere Marge, auf Kosten eines etwas hoeheren Risikos,
# Leons eigene Stimme gelegentlich faelschlich abzulehnen.
DEFAULT_SPEAKER_THRESHOLD = 0.75


class VoiceProfileError(RuntimeError):
    pass


def _load_wav_as_float32(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise VoiceProfileError(f"Nicht unterstützte Sample-Breite: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    return audio


class VoiceProfileStore:
    """Lokales Sprecher-Profil für die Sprecher-Verifikation beim Weckwort (Immer-
    Zuhör-Modus der App) - siehe
    plans/2026-08-10-jarvis-sprecher-verifikation-weckwort.md. Nutzt Resemblyzer
    (ein kompaktes, rein lokales Sprecher-Embedding-Modell, ~256-dim) statt eines
    Cloud-Diensts, passend zu privacy_local_first - Audio verlässt nie das Gerät.
    Ohne eingelerntes Profil blockiert verify() nie: das Feature darf niemanden
    versehentlich aussperren, der es nicht aktiv eingerichtet hat."""

    def __init__(self, base_path: Path | None = None):
        self.profile_path = (base_path or data_root() / "memory") / VOICE_PROFILE_FILENAME
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            from resemblyzer import VoiceEncoder

            self._encoder = VoiceEncoder()
        return self._encoder

    def _embed(self, audio: np.ndarray) -> np.ndarray:
        from resemblyzer import preprocess_wav

        wav = preprocess_wav(audio, source_sr=16000)
        if wav.size == 0:
            raise VoiceProfileError("Die Aufnahme enthält keine erkennbare Sprache.")
        return self._get_encoder().embed_utterance(wav)

    def has_profile(self) -> bool:
        return self.profile_path.exists()

    def enroll(self, audio_paths: list[str]) -> dict[str, Any]:
        if not audio_paths:
            raise VoiceProfileError("Keine Aufnahmen zum Einlernen erhalten.")

        embeddings: list[np.ndarray] = []
        for audio_path in audio_paths:
            path = Path(str(audio_path)).expanduser()
            if not path.exists():
                raise VoiceProfileError(f"Aufnahme nicht gefunden: {audio_path}")
            embeddings.append(self._embed(_load_wav_as_float32(path)))

        mean_embedding = np.mean(np.stack(embeddings), axis=0)
        norm = float(np.linalg.norm(mean_embedding))
        if norm > 0:
            mean_embedding = mean_embedding / norm

        payload = {
            "embedding": mean_embedding.tolist(),
            "sample_count": len(embeddings),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.profile_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"ok": True, "sample_count": len(embeddings)}

    def verify(self, audio_path: str, threshold: float = DEFAULT_SPEAKER_THRESHOLD) -> dict[str, Any]:
        if not self.has_profile():
            return {"match": True, "score": None, "reason": "no_profile"}

        path = Path(str(audio_path)).expanduser()
        if not path.exists():
            raise VoiceProfileError(f"Aufnahme nicht gefunden: {audio_path}")

        embedding = self._embed(_load_wav_as_float32(path))

        stored = json.loads(self.profile_path.read_text(encoding="utf-8"))
        stored_embedding = np.array(stored["embedding"], dtype=np.float32)

        denom = float(np.linalg.norm(embedding) * np.linalg.norm(stored_embedding))
        score = float(np.dot(embedding, stored_embedding) / denom) if denom > 0 else 0.0
        return {"match": score >= threshold, "score": score, "reason": None}

    def reset(self) -> bool:
        if self.profile_path.exists():
            self.profile_path.unlink()
            return True
        return False
