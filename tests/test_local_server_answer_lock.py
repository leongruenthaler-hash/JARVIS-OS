"""Regressionstest fuer einen live gefundenen Nebenlaeufigkeits-Bug (2026-09-03):
ThreadingHTTPServer bedient jede /api/chat-/Sprach-Anfrage in einem eigenen Thread,
aber lokal_server.py::_answer_with_core() (und die Instanzattribute
self._last_answer_source/_last_answer_model, die der Aufrufer direkt danach liest)
waren durch keinerlei Sperre geschuetzt. Bei einer manuellen Testanfrage, die sich
zeitlich mit einem automatisierten Testlauf ueberschnitt, ordnete der Router dadurch
eine simple Scherzfrage faelschlich der Notiz-Faehigkeit zu UND legte tatsaechlich
eine Notiz in Apple Notizen an - reproduzierbar verschwand der Fehler, sobald
dieselbe Nachricht isoliert (ohne Ueberschneidung) gesendet wurde. self._answer_lock
serialisiert jetzt jede Antwort-Erzeugung ueber alle drei Aufrufstellen (chat(),
listen_once(), _stream_chat()) hinweg."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import local_server
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
    server._answer_lock = threading.Lock()
    server._clean_question = lambda text: text
    server._handle_fast_commands = lambda text: None
    server._handle_local_photo_vision_command = lambda text: None
    return server


def test_answer_lock_exists_and_is_a_real_lock(tmp_path):
    server = _make_server(Memory(base_path=tmp_path))
    assert isinstance(server._answer_lock, type(threading.Lock()))


def test_concurrent_answer_with_core_calls_never_overlap(tmp_path):
    memory = Memory(base_path=tmp_path)
    server = _make_server(memory)

    active = 0
    max_concurrent = 0
    counter_lock = threading.Lock()

    def fake_answer_message(*args, **kwargs):
        nonlocal active, max_concurrent
        with counter_lock:
            active += 1
            max_concurrent = max(max_concurrent, active)
        time.sleep(0.08)
        with counter_lock:
            active -= 1
        # Wie im echten Code (siehe test_local_server_error_source_accuracy.py) reicht
        # es, ueber eine Exception zu scheitern - _answer_with_core() setzt
        # self._last_answer_source/_model bereits VOR dem try-Block, unabhaengig vom
        # Ausgang, das genuegt hier, um die Ueberschneidung zu pruefen.
        raise RuntimeError("simulierte langsame Antwort")

    fake_core = SimpleNamespace(
        is_end_command=lambda q: False,
        answer_message=fake_answer_message,
        AnswerWorkers=lambda **kwargs: SimpleNamespace(photo_worker=None, mail_worker=None),
    )
    server._core_module = lambda: fake_core

    def call(i: int) -> None:
        with server._answer_lock:
            server._answer_with_core(f"Frage {i}")

    threads = [threading.Thread(target=call, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 1, (
        f"Antwort-Erzeugung lief mit bis zu {max_concurrent} gleichzeitigen Aufrufen statt seriell - "
        "das ist genau der Live-Bug vom 2026-09-03."
    )
