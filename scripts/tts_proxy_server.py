#!/usr/bin/env python3
"""Minimaler HTTP-Endpunkt, der Text via Microsofts kostenloser edge-tts-
Bibliothek in Audio (MP3) umwandelt und die Bytes zurueckgibt.

Grund: JarvisMobile (die iPhone-App) spricht seit der OpenClaw-Migration
sonst nur noch mit OpenClaws Gateway - kein eigenes Backend mehr. Ein
direkter Versuch, Microsofts Edge-TTS-WebSocket-Protokoll direkt aus der App
heraus nachzubauen, wurde am 2026-09-08 durch eine neue Bot-Erkennung
(HTTP 403 + Client-Hints-Anfrage) blockiert - dieser Server nutzt stattdessen
dieselbe, aktiv gepflegte Python-Bibliothek, die schon der alte
JARVIS-OS-Server benutzte (siehe app/voice_output.py::_save_edge_audio).
Bewusst auf GENAU diese eine Aufgabe beschraenkt (kein Chat, keine Skills,
keine Persona-Logik) - kein Wiederaufleben des alten Custom-Backends, nur ein
schmaler Sprachausgabe-Proxy.

Installation auf dem Mac Mini: siehe scripts/tts_proxy_launch.sh und
scripts/com.leon.jarvis.ttsproxy.plist im selben Ordner.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import edge_tts

PORT = 18790
TOKEN_FILE = Path.home() / ".jarvis_tts_proxy_token"


def _load_or_create_token() -> str:
    # Einmalig erzeugen, danach dauerhaft wiederverwenden - gleiches Muster
    # wie remote_worker_server.py::_load_or_create_pairing_token(), damit ein
    # Neustart dieses Prozesses nicht die App aussperrt (siehe
    # docs/... Begruendung fuer ein stabiles statt bei jedem Start neu
    # gewuerfeltes Token).
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token


TOKEN = _load_or_create_token()


async def _synthesize(text: str, voice: str, rate: str, pitch: str, volume: str) -> bytes:
    # Ueber eine temporaere Datei statt communicate.stream() - spiegelt exakt
    # den bereits erprobten Pfad in app/voice_output.py::_save_edge_audio.
    audio_file = Path(tempfile.gettempdir()) / f"jarvis_tts_proxy_{uuid.uuid4().hex}.mp3"
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch, volume=volume)
        await communicate.save(str(audio_file))
        return audio_file.read_bytes()
    finally:
        audio_file.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/tts":
            self._send_plain(404, "Unbekannter Pfad.")
            return

        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send_plain(401, "Ungueltiges oder fehlendes Token.")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw_body or b"{}")
        except json.JSONDecodeError:
            self._send_plain(400, "Ungueltiges JSON.")
            return

        text = str(body.get("text", "")).strip()
        if not text:
            self._send_plain(400, "Kein 'text' im Request-Body.")
            return

        voice = str(body.get("voice") or "de-DE-KillianNeural")
        rate = str(body.get("rate") or "+0%")
        pitch = str(body.get("pitch") or "+0Hz")
        volume = str(body.get("volume") or "+0%")

        try:
            audio = asyncio.run(_synthesize(text, voice, rate, pitch, volume))
        except Exception as exc:  # noqa: BLE001 - Synthese-Fehler sollen als 502 durchgereicht werden
            self._send_plain(502, f"Edge-TTS-Synthese fehlgeschlagen: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

    def _send_plain(self, status: int, message: str) -> None:
        payload = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - BaseHTTPRequestHandler-Signatur
        print(f"[tts-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis TTS-Proxy laeuft auf 127.0.0.1:{PORT}")
    print(f"Token (einmalig in JarvisMobile -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
