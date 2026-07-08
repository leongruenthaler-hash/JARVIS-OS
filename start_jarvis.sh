#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="$PWD/.venv/bin/python"

if ! "$PYTHON" -c "import numpy, sounddevice, dotenv, openai, edge_tts, miniaudio, faster_whisper, torch" >/dev/null 2>&1; then
    echo "Python-Pakete fehlen oder laden nicht sauber in .venv."
    echo "Installiere requirements.txt ..."
    "$PYTHON" -m pip install -r requirements.txt
fi

"$PYTHON" - <<'PY' || true
import sys
from pathlib import Path

sys.path.insert(0, str(Path("app").resolve()))

try:
    from photos_client import PhotoIndex

    helper = PhotoIndex({})
    helper_path = helper._ensure_helper()
    print(f"Fotos-Helper vorbereitet: {helper_path}")
except Exception as exc:
    print(f"Fotos-Helper konnte beim Start nicht vorbereitet werden: {exc}")
PY

echo "Starte Jarvis mit: $PYTHON"
exec "$PYTHON" app/jarvis.py
