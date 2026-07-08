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


def main() -> int:
    try:
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
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": _safe_error(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
