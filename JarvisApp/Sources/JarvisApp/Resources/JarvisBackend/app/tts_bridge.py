from __future__ import annotations

import json
import sys
from typing import Any

from settings import load_config
from voice_output import VoiceOutput
from jarvis_personality import text_summary


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__


def _main_combined() -> int:
    """Synthesizes AND plays in one blocking call - the original, always-available mode."""
    raw = sys.stdin.read().strip()
    payload: dict[str, Any] = json.loads(raw) if raw else {}
    text = str(payload.get("text") or "").strip()
    voice = payload.get("voice")
    if not text:
        print(json.dumps({"ok": True, "spoken": False}, ensure_ascii=False))
        return 0

    print(f"Pipeline: ttsText {text_summary(text)}", file=sys.stderr)
    print("VoicePerformanceEvent: ttsStarted", file=sys.stderr)
    output = VoiceOutput(load_config())
    output.speak(text, voice=str(voice).strip() if voice else None)
    print("VoicePerformanceEvent: audioPlaybackStarted", file=sys.stderr)
    output.wait()
    print("VoicePerformanceEvent: ttsFinished", file=sys.stderr)
    print(json.dumps({"ok": True, "spoken": True}, ensure_ascii=False))
    return 0


def _main_synthesize() -> int:
    """Synthesizes only, no playback - lets a caller prefetch the next segment's audio
    while a previous segment is still playing. Prints the resulting file path."""
    raw = sys.stdin.read().strip()
    payload: dict[str, Any] = json.loads(raw) if raw else {}
    text = str(payload.get("text") or "").strip()
    voice = payload.get("voice")
    if not text:
        print(json.dumps({"ok": True, "audio_file": None}, ensure_ascii=False))
        return 0

    print(f"Pipeline: ttsSynthesize {text_summary(text)}", file=sys.stderr)
    print("VoicePerformanceEvent: ttsSynthesizeStarted", file=sys.stderr)
    output = VoiceOutput(load_config())
    audio_file = output.synthesize_edge_to_file(text, voice=str(voice).strip() if voice else None)
    print("VoicePerformanceEvent: ttsSynthesizeFinished", file=sys.stderr)
    print(json.dumps({"ok": True, "audio_file": str(audio_file)}, ensure_ascii=False))
    return 0


def _main_play() -> int:
    """Plays a previously synthesized audio file and blocks until playback finishes."""
    raw = sys.stdin.read().strip()
    payload: dict[str, Any] = json.loads(raw) if raw else {}
    audio_file = str(payload.get("audio_file") or "").strip()
    if not audio_file:
        raise ValueError("Kein audio_file zum Abspielen angegeben.")

    print(f"Pipeline: ttsPlay {audio_file}", file=sys.stderr)
    print("VoicePerformanceEvent: audioPlaybackStarted", file=sys.stderr)
    output = VoiceOutput(load_config())
    output.play_file(audio_file)
    print("VoicePerformanceEvent: ttsFinished", file=sys.stderr)
    print(json.dumps({"ok": True, "played": True}, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        if mode == "--synthesize":
            return _main_synthesize()
        if mode == "--play":
            return _main_play()
        return _main_combined()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": _safe_error(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
