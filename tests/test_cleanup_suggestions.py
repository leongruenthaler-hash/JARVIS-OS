"""Tests fuer die Speicherplatz-Aufraeum-Vorschlaege per Chat, siehe
plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md.

Live-Bug (Leons genaue Frage): "welche Dateien koennen wir loeschen, die mir
mehr Speicherplatz bringen und nicht fuer Coding-Arbeiten benoetigt werden"
wurde faelschlich vom generischen Datei-Such-Fallback abgefangen und lieferte
eine kaputte "nichts gefunden"-Vorlage mit der eingesetzten Rohanfrage.

Leons ausdrueckliche Vorgaben (aus der Klaerung der offenen Fragen):
1. Alles innerhalb selbst angelegter/Projekt-Ordner ist von Vorschlaegen
   komplett ausgeschlossen - kein Gewichten, ein harter Filter.
2. Loeschen bedeutet immer "in den Papierkorb legen", nie endgueltig.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import files_client
import jarvis


# --- list_cleanup_candidates() / suggest_cleanup_files(): Ausschluesse -----


@pytest.fixture
def fake_index(tmp_path, monkeypatch):
    """Baut einen minimalen, echten Dateibaum + passenden file_index.json auf,
    damit list_cleanup_candidates() gegen echte Path.exists()/is_file()-Aufrufe
    laufen kann, statt alles zu mocken."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    old_time = time.time() - 200 * 86400  # 200 Tage alt, klar ueber der Schwelle

    def _make_old_file(path: Path, size: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        import os

        os.utime(path, (old_time, old_time))

    # Ein echter Kandidat: grosse, alte Datei in Downloads, ausserhalb jedes Projekts.
    downloads_file = home / "Downloads" / "altes-installer.dmg"
    _make_old_file(downloads_file, 80 * 1024 * 1024)

    # Ein Kandidat, der NICHT vorgeschlagen werden darf: liegt in einem
    # Projekt-Ordner mit eigenem .git-Repo, obwohl er selbst gross+alt ist.
    project_file = home / "Desktop" / "Projekte" / "MeinProjekt" / "big_binary.bin"
    _make_old_file(project_file, 90 * 1024 * 1024)
    (home / "Desktop" / "Projekte" / "MeinProjekt" / ".git").mkdir(parents=True)

    # Ein Kandidat unterhalb eines Ordnernamens aus CLEANUP_ALWAYS_EXCLUDED_NAME_HINTS.
    node_modules_file = home / "Desktop" / "node_modules" / "riesig.bin"
    _make_old_file(node_modules_file, 70 * 1024 * 1024)

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    index_path = index_dir / "file_index.json"
    entries = [
        {
            "root": "downloads",
            "name": downloads_file.name,
            "kind": "file",
            "relative_path": downloads_file.name,
            "path": str(downloads_file),
            "size": 80 * 1024 * 1024,
            "modified": __import__("datetime").datetime.fromtimestamp(old_time).isoformat(timespec="seconds"),
            "extension": "dmg",
        },
        {
            "root": "desktop",
            "name": project_file.name,
            "kind": "file",
            "relative_path": str(project_file.relative_to(home / "Desktop")),
            "path": str(project_file),
            "size": 90 * 1024 * 1024,
            "modified": __import__("datetime").datetime.fromtimestamp(old_time).isoformat(timespec="seconds"),
            "extension": "bin",
        },
        {
            "root": "desktop",
            "name": node_modules_file.name,
            "kind": "file",
            "relative_path": str(node_modules_file.relative_to(home / "Desktop")),
            "path": str(node_modules_file),
            "size": 70 * 1024 * 1024,
            "modified": __import__("datetime").datetime.fromtimestamp(old_time).isoformat(timespec="seconds"),
            "extension": "bin",
        },
    ]
    index_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    monkeypatch.setattr(files_client, "FILE_INDEX_PATH", index_path)
    return {"downloads_file": downloads_file, "project_file": project_file, "node_modules_file": node_modules_file}


def test_excludes_files_inside_git_repos(fake_index):
    candidates = files_client.list_cleanup_candidates(config={})
    paths = {c["path"] for c in candidates}
    assert str(fake_index["project_file"]) not in paths


def test_excludes_files_inside_excluded_name_hints(fake_index):
    candidates = files_client.list_cleanup_candidates(config={})
    paths = {c["path"] for c in candidates}
    assert str(fake_index["node_modules_file"]) not in paths


def test_includes_safe_downloads_candidate(fake_index):
    candidates = files_client.list_cleanup_candidates(config={})
    paths = {c["path"] for c in candidates}
    assert str(fake_index["downloads_file"]) in paths


def test_suggest_cleanup_files_returns_text_and_candidates(fake_index):
    text, candidates = files_client.suggest_cleanup_files(config={})
    assert "altes-installer.dmg" in text
    assert "Papierkorb" in text
    assert len(candidates) == 1


def test_suggest_cleanup_files_no_index_returns_empty():
    with patch.object(files_client, "FILE_INDEX_PATH", Path("/nonexistent/file_index.json")):
        text, candidates = files_client.suggest_cleanup_files(config={})
    assert candidates == []
    assert "Dateiindex" in text


def test_respects_configured_min_size(fake_index):
    # Schwelle so hoch setzen, dass selbst die 80MB-Downloads-Datei nicht mehr passt.
    candidates = files_client.list_cleanup_candidates(config={"cleanup_suggestion_min_size_mb": 500})
    assert candidates == []


# --- Intent-Erkennung: Cleanup-Frage vs. normale Datei-Suche ---------------


def test_cleanup_intent_matches_leons_example_question():
    text = "welche Dateien können wir löschen, die mir mehr Speicherplatz bringen und nicht für Coding-Arbeiten benötigt werden"
    normalized = jarvis.normalize_text(text)
    assert "speicherplatz" in normalized
    assert "löschen" in normalized or "loeschen" in normalized


def test_normal_file_search_does_not_trigger_cleanup(monkeypatch):
    monkeypatch.setattr(jarvis, "suggest_cleanup_files", MagicMock(side_effect=AssertionError("sollte nicht aufgerufen werden")))
    with patch("jarvis.search_files", return_value="Ich habe eine Datei gefunden.") as fake_search:
        answer = jarvis.handle_file_command("suche die Datei Rechnung.pdf", memory=None)
    assert answer == "Ich habe eine Datei gefunden."
    fake_search.assert_called_once()


def test_cleanup_question_calls_suggest_cleanup_files(monkeypatch):
    fake_memory = MagicMock()
    fake_memory.get.return_value = {}
    monkeypatch.setattr(
        jarvis,
        "suggest_cleanup_files",
        MagicMock(return_value=("Ich habe 1 Datei gefunden.", [{"path": "/x", "name": "x", "size": 1}])),
    )
    answer = jarvis.handle_file_command(
        "welche Dateien können wir löschen, die mir mehr Speicherplatz bringen", memory=fake_memory
    )
    assert answer == "Ich habe 1 Datei gefunden."
    fake_memory.set.assert_called_once()
    saved_settings = fake_memory.set.call_args[0][1]
    assert saved_settings["pending_cleanup_confirmation"]["items"][0]["path"] == "/x"


# --- Bestaetigungsfluss: nichts wird ohne "ja" geloescht -------------------


def _pending_marker(items, set_at=None):
    return {"items": items, "set_at": set_at if set_at is not None else time.time()}


def test_confirmation_moves_to_trash(monkeypatch):
    settings = {"pending_cleanup_confirmation": _pending_marker([{"path": "/tmp/x.dmg", "name": "x.dmg", "size": 1}])}
    memory = MagicMock()
    memory.get.return_value = settings

    with patch("jarvis.move_to_trash", return_value=(["x.dmg"], [])) as fake_trash:
        answer = jarvis.handle_pending_action_flow(memory, "ja bitte", router_decision="confirm")

    fake_trash.assert_called_once()
    assert "Papierkorb" in answer
    saved_settings = memory.set.call_args[0][1]
    assert "pending_cleanup_confirmation" not in saved_settings


def test_cancellation_does_not_touch_files(monkeypatch):
    settings = {"pending_cleanup_confirmation": _pending_marker([{"path": "/tmp/x.dmg", "name": "x.dmg", "size": 1}])}
    memory = MagicMock()
    memory.get.return_value = settings

    with patch("jarvis.move_to_trash") as fake_trash:
        answer = jarvis.handle_pending_action_flow(memory, "nein", router_decision="cancel")

    fake_trash.assert_not_called()
    assert "nicht" in answer


def test_expired_cleanup_marker_discarded():
    settings = {"pending_cleanup_confirmation": _pending_marker([{"path": "/tmp/x.dmg", "name": "x.dmg", "size": 1}], set_at=0.0)}
    memory = MagicMock()
    memory.get.return_value = settings

    with patch("jarvis.move_to_trash") as fake_trash:
        answer = jarvis.handle_pending_action_flow(memory, "ja", router_decision="confirm")

    fake_trash.assert_not_called()
    assert "nicht mehr aktuell" in answer


# --- move_to_trash(): nie endgueltig loeschen -------------------------------


def test_move_to_trash_uses_finder_delete_not_rm(tmp_path):
    target = tmp_path / "loeschbar.txt"
    target.write_text("x")
    with patch("files_client.subprocess.run") as fake_run:
        fake_run.return_value = MagicMock(returncode=0)
        moved, skipped = files_client.move_to_trash([target])
    assert moved == ["loeschbar.txt"]
    assert skipped == []
    call_args = fake_run.call_args[0][0]
    assert call_args[0] == "osascript"
    assert "delete" in call_args[2]
    assert target.exists()  # move_to_trash selbst loescht nichts direkt - das AppleScript uebernimmt das


def test_move_to_trash_skips_missing_files(tmp_path):
    missing = tmp_path / "existiert-nicht.txt"
    moved, skipped = files_client.move_to_trash([missing])
    assert moved == []
    assert skipped == ["existiert-nicht.txt"]
