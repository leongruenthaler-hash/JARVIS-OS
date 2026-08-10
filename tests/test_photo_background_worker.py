"""Tests fuer app/photos_client.py::PhotoBackgroundWorker (bisher komplett
ungetestet) - siehe plans/2026-08-10-jarvis-foto-vision-lokal-aktivieren.md.
Deckt ab: dass der naechtliche Zyklus Scan UND lokale Vision-Analyse ausloest
(vorher lief nur der Scan, Vision-Beschreibungen entstanden nie automatisch),
dass beides jeweils nur einmal pro Tag laeuft, und dass ein fehlendes/
unerreichbares lokales Vision-Modell den Zyklus nicht zum Absturz bringt."""

from datetime import datetime
from unittest.mock import patch

import pytest

from photos_client import PhotoBackgroundWorker


@pytest.fixture
def worker(tmp_path):
    config = {
        "photos_background_enabled": True,
        "photos_background_scan_time": "07:00",
        "local_photo_vision_background_enabled": True,
    }
    w = PhotoBackgroundWorker(config, base_path=tmp_path)
    return w


def _at(hour, minute):
    return datetime(2027, 1, 1, hour, minute)


# --- _tick: Scan + Vision im selben nächtlichen Zyklus -----------------------


def test_tick_runs_scan_and_vision_when_time_reached(worker):
    with patch.object(worker.index, "permission_status", return_value="authorized"), \
         patch.object(worker.index, "scan", return_value=3) as fake_scan, \
         patch.object(worker.index, "local_vision_status", return_value={"available": True, "model": "llava"}), \
         patch.object(worker.index, "analyze_with_local_vision", return_value=(3, 0)) as fake_vision:
        worker._tick(_at(7, 0))

    fake_scan.assert_called_once()
    fake_vision.assert_called_once()

    cache = worker.index._load_cache()
    assert cache["last_background_scan_date"] == "2027-01-01"
    assert cache["last_background_vision_date"] == "2027-01-01"


def test_tick_does_nothing_before_scan_time(worker):
    with patch.object(worker.index, "scan") as fake_scan, \
         patch.object(worker.index, "analyze_with_local_vision") as fake_vision:
        worker._tick(_at(6, 59))

    fake_scan.assert_not_called()
    fake_vision.assert_not_called()


def test_tick_runs_scan_only_once_per_day(worker):
    with patch.object(worker.index, "permission_status", return_value="authorized"), \
         patch.object(worker.index, "scan", return_value=0) as fake_scan, \
         patch.object(worker.index, "local_vision_status", return_value={"available": True}), \
         patch.object(worker.index, "analyze_with_local_vision", return_value=(0, 0)) as fake_vision:
        worker._tick(_at(7, 0))
        worker._tick(_at(8, 0))

    fake_scan.assert_called_once()
    fake_vision.assert_called_once()


def test_tick_skips_vision_when_background_vision_disabled(tmp_path):
    config = {
        "photos_background_enabled": True,
        "photos_background_scan_time": "07:00",
        "local_photo_vision_background_enabled": False,
    }
    w = PhotoBackgroundWorker(config, base_path=tmp_path)
    with patch.object(w.index, "permission_status", return_value="authorized"), \
         patch.object(w.index, "scan", return_value=0), \
         patch.object(w.index, "analyze_with_local_vision") as fake_vision:
        w._tick(_at(7, 0))

    fake_vision.assert_not_called()
    cache = w.index._load_cache()
    assert "last_background_vision_date" not in cache


# --- _vision_safely: robust gegen fehlendes/unerreichbares Modell ------------


def test_vision_safely_skips_when_model_unavailable(worker):
    with patch.object(worker.index, "local_vision_status", return_value={"available": False, "message": "kein Modell installiert"}), \
         patch.object(worker.index, "analyze_with_local_vision") as fake_vision:
        worker._vision_safely()

    fake_vision.assert_not_called()


def test_vision_safely_swallows_exceptions(worker):
    with patch.object(worker.index, "local_vision_status", side_effect=RuntimeError("kaputt")):
        worker._vision_safely()  # darf nicht werfen