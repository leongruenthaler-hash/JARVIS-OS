#!/usr/bin/env python3
"""Schlanker HTTP-Endpunkt, der eine per Base64 geschickte WAV-Aufnahme mit
der auf diesem Mac Mini konfigurierten STT-Engine transkribiert.

Grund: JarvisApp (die Mac-App) hatte Sprachnachrichten-Transkription bisher
ueber das alte Backend laufen (`serverController.transcribeVoice`), das
einen lokalen Dateipfad an den Server schickte - funktioniert nur, solange
Client und Server auf derselben Maschine laufen. Seit der OpenClaw-Migration
laeuft JarvisApp aber nur noch remote gegen den Mac Mini, der lokale
Dateipfad des Clients existiert dort gar nicht. Dieser Proxy nimmt die
Audio-BYTES entgegen (nicht nur einen Pfad) und transkribiert sie direkt
hier, mit derselben Engine-Auswahl (inkl. automatischem Fallback), die auch
das alte Backend schon nutzte (siehe app/stt_engines.py::create_stt_engine).

Bewusst NUR dieser eine Baustein, kein kompletter Backend-Neustart - gleiches
Muster wie scripts/tts_proxy_server.py (schmaler Bearer-Token-Proxy statt
`app/jarvis.py --local-server`).

Installation auf dem Mac Mini: siehe scripts/voice_transcribe_proxy_launch.sh
und scripts/com.leon.jarvis.voicetranscribeproxy.plist im selben Ordner.
"""
from __future__ import annotations

import base64
import json
import secrets
import sys
import tempfile
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from data_dir import data_root  # noqa: E402
from stt_engines import create_stt_engine  # noqa: E402

PORT = 18803
TOKEN_FILE = Path.home() / ".jarvis_voice_transcribe_proxy_token"
CONFIG_FILE = REPO_ROOT / "config.json"


def _load_or_create_token() -> str:
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token


TOKEN = _load_or_create_token()


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


# Die Engine ist teuer zu laden (Modellgewichte) - einmal beim Start
# aufbauen und fuer alle Requests wiederverwenden, statt pro Anfrage neu zu
# initialisieren. Nutzt dieselbe Konfig-gesteuerte Auswahl (inkl. Fallback
# auf faster-whisper, falls die bevorzugte Engine z.B. mangels mlx-whisper/
# moonshine nicht installiert ist) wie das alte Backend.
_config = _load_config()
_cache_dir = data_root() / ".cache" / "whisper"
_cache_dir.mkdir(parents=True, exist_ok=True)
print(f"Lade STT-Engine (stt_engine={_config.get('stt_engine', 'moonshine_streaming')}) ...")
ENGINE = create_stt_engine(_config)
print(f"STT-Engine bereit: {ENGINE.name}")


def _load_wav_audio(path: Path, target_sample_rate: float | None = None) -> np.ndarray:
    # Byte-fuer-Byte dieselbe Lade-/Resampling-Logik wie
    # app/local_server.py::transcribe_voice's _load_audio - reine
    # Uebernahme, keine Verhaltensaenderung.
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        frame_rate = float(wav_file.getframerate())
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Nicht unterstuetzte Sample-Breite: {sample_width}")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if target_sample_rate and frame_rate and abs(frame_rate - float(target_sample_rate)) > 1.0 and audio.size > 16:
        duration = audio.size / frame_rate
        target_size = max(1, int(round(duration * target_sample_rate)))
        source_positions = np.linspace(0.0, duration, num=audio.size, endpoint=False)
        target_positions = np.linspace(0.0, duration, num=target_size, endpoint=False)
        audio = np.interp(target_positions, source_positions, audio).astype(np.float32)

    return np.clip(audio.astype(np.float32), -1.0, 1.0)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/api/voice/transcribe":
            self._send_json(404, {"error": "Unbekannter Pfad."})
            return

        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Ungueltiges JSON."})
            return

        audio_base64 = str(body.get("audio_base64") or "")
        if not audio_base64:
            self._send_json(400, {"error": "Kein 'audio_base64' im Request-Body."})
            return

        sample_rate = body.get("sample_rate")

        try:
            wav_bytes = base64.b64decode(audio_base64)
        except Exception:  # noqa: BLE001 - ungueltiges Base64 wird als 400 durchgereicht
            self._send_json(400, {"error": "audio_base64 konnte nicht dekodiert werden."})
            return

        tmp_path = Path(tempfile.gettempdir()) / f"jarvis_voice_transcribe_proxy_{uuid.uuid4().hex}.wav"
        try:
            tmp_path.write_bytes(wav_bytes)
            audio = _load_wav_audio(tmp_path, target_sample_rate=sample_rate)
            text = ENGINE.transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - Transkriptionsfehler als 502 durchreichen
            self._send_json(502, {"error": f"Transkription fehlgeschlagen: {exc}"})
            return
        finally:
            tmp_path.unlink(missing_ok=True)

        self._send_json(200, {"text": text, "engine": ENGINE.name})

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[voice-transcribe-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Voice-Transcribe-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
