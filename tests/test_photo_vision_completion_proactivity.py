"""Tests fuer plans/2026-08-16-jarvis-proaktive-abschluss-meldung.md: Jarvis soll
sich von selbst melden, wenn ein Foto-Vision-Lauf fertig ist, statt dass der
Nutzer aktiv nachfragen muss. Deckt ab: PhotoIndex.local_vision_run_summary()
(sicheres Lesen der Fortschritts-Datei) und die neue Proactivity-Regel
rule_photo_vision_analysis_completed() (inkl. des zeitstempel-basierten
dedup_key, der verhindert, dass ein SPAETERER neuer Lauf faelschlich als
"schon gemeldet" gilt)."""

import json

from core.proactivity_rules import rule_photo_vision_analysis_completed
from photos_client import PhotoIndex


def _index(tmp_path) -> PhotoIndex:
    return PhotoIndex({}, base_path=tmp_path)


# --- PhotoIndex.local_vision_run_summary() ----------------------------------


def test_run_summary_missing_file_returns_empty_dict(tmp_path):
    assert _index(tmp_path).local_vision_run_summary() == {}


def test_run_summary_malformed_json_returns_empty_dict(tmp_path):
    index = _index(tmp_path)
    index.local_vision_progress_path.parent.mkdir(parents=True, exist_ok=True)
    index.local_vision_progress_path.write_text("{kaputt", encoding="utf-8")
    assert index.local_vision_run_summary() == {}


def test_run_summary_reads_completed_run(tmp_path):
    index = _index(tmp_path)
    index.local_vision_progress_path.parent.mkdir(parents=True, exist_ok=True)
    index.local_vision_progress_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "finishedAt": "2026-08-16T20:00:00",
                "stats": {"model": "gemma3:4b", "analyzed": 12, "errors": 1},
            }
        ),
        encoding="utf-8",
    )
    assert index.local_vision_run_summary() == {
        "status": "completed",
        "finished_at": "2026-08-16T20:00:00",
        "analyzed": 12,
        "errors": 1,
    }


# --- rule_photo_vision_analysis_completed() ----------------------------------


def _context(**photo_vision_run) -> dict:
    return {"config": {}, "photo_vision_run": photo_vision_run}


def test_rule_silent_when_status_not_completed():
    assert rule_photo_vision_analysis_completed(_context(status="indexing", analyzed=5, finished_at="x")) == []


def test_rule_silent_when_zero_analyzed():
    assert rule_photo_vision_analysis_completed(_context(status="completed", analyzed=0, finished_at="x")) == []


def test_rule_silent_without_finished_at():
    assert rule_photo_vision_analysis_completed(_context(status="completed", analyzed=5, finished_at="")) == []


def test_rule_fires_on_real_completion():
    events = rule_photo_vision_analysis_completed(
        _context(status="completed", analyzed=3, errors=0, finished_at="2026-08-16T20:00:00")
    )
    assert len(events) == 1
    event = events[0]
    assert "3 neue Fotos" in event["message"]
    assert event["dedup_key"] == "photo_vision_completed:2026-08-16T20:00:00"
    assert event["priority"] == "information"


def test_rule_singular_phrasing_for_one_photo():
    events = rule_photo_vision_analysis_completed(
        _context(status="completed", analyzed=1, errors=0, finished_at="2026-08-16T20:00:00")
    )
    assert "1 neues Foto" in events[0]["message"]


def test_rule_mentions_errors_when_present():
    events = rule_photo_vision_analysis_completed(
        _context(status="completed", analyzed=5, errors=2, finished_at="2026-08-16T20:00:00")
    )
    assert "2 davon nicht analysierbar" in events[0]["message"]


def test_rule_different_finish_times_get_different_dedup_keys():
    first = rule_photo_vision_analysis_completed(
        _context(status="completed", analyzed=3, errors=0, finished_at="2026-08-16T20:00:00")
    )
    second = rule_photo_vision_analysis_completed(
        _context(status="completed", analyzed=7, errors=0, finished_at="2026-08-17T03:15:00")
    )
    assert first[0]["dedup_key"] != second[0]["dedup_key"]


def test_rule_respects_config_toggle():
    context = _context(status="completed", analyzed=3, errors=0, finished_at="2026-08-16T20:00:00")
    context["config"] = {"proactivity_photo_vision_completion_enabled": False}
    assert rule_photo_vision_analysis_completed(context) == []
