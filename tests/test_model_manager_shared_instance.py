"""Tests fuer den ModelManager-Dual-Instance-Bug (gleiches Muster wie der bereits
behobene Gedaechtnis-Bug, siehe app/core/memory_system.py): ModelManager cacht
model_settings.json bei Konstruktion in self.data und schreibt bei jeder Aenderung
den GANZEN gecachten Stand zurueck - eine zweite, kurzlebige Instanz neben einer
langlebigen (local_server.py::self.models) kann so eine Aenderung unsichtbar machen
und spaeter stillschweigend wieder ueberschreiben. Siehe
plans/... (Bug-Muster-Audit, 2026-08-09).
"""

import jarvis
from model_manager import ModelManager


def test_dual_instance_clobbers_write_documents_the_bug_shape(tmp_path):
    """Reproduziert die Bug-Ursache in Isolation (kein handle_model_command
    beteiligt) - dokumentiert, warum eine zweite Instanz gefaehrlich ist."""
    config = {}
    long_lived = ModelManager(config, base_path=tmp_path)
    long_lived.use_local_model("qwen3:4b")

    # Kurzlebige zweite Instanz sieht den aktuellen Stand nicht (laedt beim
    # Konstruieren den Stand von der Platte, der zu diesem Zeitpunkt schon
    # "qwen3:4b" enthaelt - aendert aber etwas anderes und speichert ihren
    # eigenen, ab jetzt schon wieder veralteten Cache).
    fresh = ModelManager(config, base_path=tmp_path)
    fresh.data["local_model"] = "phi4-mini"
    fresh._save()

    # Die langlebige Instanz weiss von der Aenderung nichts und ueberschreibt
    # jetzt mit ihrem eigenen, ebenfalls veralteten Cache-Stand.
    long_lived.use_openai()

    on_disk = ModelManager(config, base_path=tmp_path)
    # Die Aenderung der kurzlebigen Instanz ("phi4-mini") ist stillschweigend
    # verloren - genau der Bug.
    assert on_disk.data["local_model"] == "qwen3:4b"


def test_handle_model_command_mutates_passed_manager_in_place(tmp_path):
    """Regressionstest fuer den Fix: handle_model_command() baut KEINE eigene
    ModelManager-Instanz mehr, wenn eine bereits vorhandene uebergeben wird -
    die Aenderung landet direkt im Cache der uebergebenen Instanz."""
    manager = ModelManager({}, base_path=tmp_path)
    assert manager.data["local_model"] != "gemma3:4b"

    result = jarvis.handle_model_command("nutze gemma", model_manager=manager)

    assert result is not None
    assert manager.data["local_model"] == "gemma3:4b"


def test_handle_model_command_no_clobber_across_two_calls_with_shared_manager(tmp_path):
    """End-to-End-Variante der lokalen Server-Situation: dieselbe Instanz wird
    fuer mehrere Anfragen wiederverwendet (wie self.models in local_server.py) -
    keine Aenderung geht mehr verloren."""
    shared_manager = ModelManager({}, base_path=tmp_path)

    shared_manager.use_local_model("qwen3:4b")
    jarvis.handle_model_command("arbeite lokal", model_manager=shared_manager)
    shared_manager.use_local_model("gemma3:4b")

    on_disk = ModelManager({}, base_path=tmp_path)
    assert on_disk.data["local_model"] == "gemma3:4b"
    assert on_disk.data["provider"] == "ollama"
    assert on_disk.data["openai_enabled"] is False


def test_handle_model_command_builds_fresh_manager_when_none_given(monkeypatch):
    """Bestehendes Verhalten (CLI-Pfad jarvis.py::main(), kein langlebiger
    ModelManager im Prozess vorhanden) bleibt unveraendert - ohne uebergebene
    Instanz wird weiterhin eine neue gebaut."""
    built = {}

    class _FakeManager:
        def __init__(self, config):
            built["called"] = True
            self.data = {}

        def use_local_model(self, name):
            return f"ok {name}"

    monkeypatch.setattr(jarvis, "ModelManager", _FakeManager)

    result = jarvis.handle_model_command("nutze gemma")

    assert built.get("called") is True
    assert result == "ok gemma3:4b"
