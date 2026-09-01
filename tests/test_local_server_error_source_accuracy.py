"""Regressionstest fuer zwei zusammenhaengende Bugs, live in der App gefunden
(2026-09-02): eine Apple-Mail-AppleScript-Zeitueberschreitung wurde als "Ich
erreiche das lokale Modell gerade nicht sauber." angezeigt, obwohl Claude Code
(ein Cloud-Provider) aktiv war und mit dem eigentlichen Fehler nichts zu tun
hatte, und die Antwort war zusaetzlich mit "Antwort ueber lokal" beschriftet.

Ursache 1: local_server.py::_answer_with_core() fing jeden RuntimeError ab und
stellte pauschal "Ich erreiche das lokale Modell gerade nicht sauber." voran -
MailAccessError/CalendarAccessError/CameraAccessError/PhotosAccessError/
ClaudeCodeError sind aber alle RuntimeError-Unterklassen mit bereits
vollstaendigen, klaren eigenen Fehlertexten.

Ursache 2: self._last_answer_source wurde vor dem try-Block hartcodiert auf
"local" gesetzt und nur bei ERFOLG auf den echten Provider aktualisiert - bei
einer Exception blieb es auf "local" haengen, unabhaengig vom tatsaechlich
konfigurierten Provider."""

from __future__ import annotations

from types import SimpleNamespace

import local_server
from mail_client import MailAccessError
from memory import Memory


def _make_server(memory: Memory, provider: str = "claude_code") -> local_server.JarvisLocalServer:
    server = local_server.JarvisLocalServer.__new__(local_server.JarvisLocalServer)
    server.memory = memory
    server.models = SimpleNamespace(active_model="sonnet", provider=provider)
    server.photo_worker = None
    server.mail_worker = None
    server.pending_mail_followup = False
    server.llm = None
    server.config = {}
    server._clean_question = lambda text: text
    server._handle_fast_commands = lambda text: None
    server._handle_local_photo_vision_command = lambda text: None
    return server


def _fake_core_raising(exc: Exception) -> SimpleNamespace:
    def fake_answer_message(*args, **kwargs):
        raise exc

    return SimpleNamespace(
        is_end_command=lambda q: False,
        answer_message=fake_answer_message,
        AnswerWorkers=lambda **kwargs: SimpleNamespace(photo_worker=None, mail_worker=None),
    )


def test_mail_access_error_is_not_mislabeled_as_local_model_unreachable(tmp_path):
    memory = Memory(base_path=tmp_path)
    server = _make_server(memory, provider="claude_code")
    original_message = "Apple Mail hat zu lange nicht geantwortet. Oeffne Mail einmal normal, warte bis der Posteingang geladen ist, und versuch es dann nochmal."
    server._core_module = lambda: _fake_core_raising(MailAccessError(original_message))

    result = server._answer_with_core("Welche Mails habe ich vorkurzem bekommen?")

    assert result == original_message
    assert "lokale Modell" not in result
    assert "lokales Modell" not in result


def test_error_source_reflects_actual_configured_provider_not_hardcoded_local(tmp_path):
    memory = Memory(base_path=tmp_path)
    server = _make_server(memory, provider="claude_code")
    server._core_module = lambda: _fake_core_raising(RuntimeError("irgendein Fehler"))

    server._answer_with_core("Frage")

    assert server._last_answer_source == "claude_code"


def test_error_source_stays_ollama_when_that_is_the_configured_provider(tmp_path):
    memory = Memory(base_path=tmp_path)
    server = _make_server(memory, provider="ollama")
    server._core_module = lambda: _fake_core_raising(RuntimeError("Ollama läuft nicht."))

    server._answer_with_core("Frage")

    assert server._last_answer_source == "ollama"
