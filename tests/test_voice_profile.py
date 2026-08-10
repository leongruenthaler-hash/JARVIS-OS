"""Tests fuer app/voice_profile.py::VoiceProfileStore - lokale Sprecher-
Verifikation beim Weckwort, siehe
plans/2026-08-10-jarvis-sprecher-verifikation-weckwort.md. _embed() wird
gemockt (liefert feste Vektoren statt das echte Resemblyzer-Modell
aufzurufen) - schnell, deterministisch, testet die Vergleichs-/
Speicher-Logik statt der externen Bibliothek."""

import wave
from unittest.mock import patch

import numpy as np
import pytest

from voice_profile import VoiceProfileError, VoiceProfileStore


def _write_silent_wav(path, seconds=1.0, sample_rate=16000):
    frames = np.zeros(int(seconds * sample_rate), dtype=np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames.tobytes())


@pytest.fixture
def store(tmp_path):
    return VoiceProfileStore(base_path=tmp_path)


def test_verify_without_profile_always_matches(store, tmp_path):
    clip = tmp_path / "clip.wav"
    _write_silent_wav(clip)

    result = store.verify(str(clip))

    assert result == {"match": True, "score": None, "reason": "no_profile"}


def test_has_profile_false_before_enrollment(store):
    assert store.has_profile() is False


def test_enroll_raises_for_missing_file(store):
    with pytest.raises(VoiceProfileError):
        store.enroll(["/does/not/exist.wav"])


def test_enroll_raises_when_no_paths_given(store):
    with pytest.raises(VoiceProfileError):
        store.enroll([])


def test_enroll_averages_and_normalizes_embeddings(store, tmp_path):
    clip_a = tmp_path / "a.wav"
    clip_b = tmp_path / "b.wav"
    _write_silent_wav(clip_a)
    _write_silent_wav(clip_b)

    with patch.object(
        store,
        "_embed",
        side_effect=[np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)],
    ):
        result = store.enroll([str(clip_a), str(clip_b)])

    assert result["ok"] is True
    assert result["sample_count"] == 2
    assert store.has_profile() is True


def test_verify_matches_when_embedding_close_to_profile(store, tmp_path):
    clip = tmp_path / "enroll.wav"
    _write_silent_wav(clip)
    with patch.object(store, "_embed", return_value=np.array([1.0, 0.0], dtype=np.float32)):
        store.enroll([str(clip)])

    probe = tmp_path / "probe.wav"
    _write_silent_wav(probe)
    with patch.object(store, "_embed", return_value=np.array([0.99, 0.01], dtype=np.float32)):
        result = store.verify(str(probe))

    assert result["match"] is True
    assert result["score"] > 0.9


def test_verify_rejects_when_embedding_far_from_profile(store, tmp_path):
    clip = tmp_path / "enroll.wav"
    _write_silent_wav(clip)
    with patch.object(store, "_embed", return_value=np.array([1.0, 0.0], dtype=np.float32)):
        store.enroll([str(clip)])

    probe = tmp_path / "probe.wav"
    _write_silent_wav(probe)
    with patch.object(store, "_embed", return_value=np.array([0.0, 1.0], dtype=np.float32)):
        result = store.verify(str(probe), threshold=0.6)

    assert result["match"] is False
    assert result["score"] < 0.6


def test_reset_removes_profile(store, tmp_path):
    clip = tmp_path / "enroll.wav"
    _write_silent_wav(clip)
    with patch.object(store, "_embed", return_value=np.array([1.0, 0.0], dtype=np.float32)):
        store.enroll([str(clip)])

    assert store.reset() is True
    assert store.has_profile() is False
    assert store.reset() is False
