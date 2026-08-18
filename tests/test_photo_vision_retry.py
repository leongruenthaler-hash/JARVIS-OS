"""Tests fuer den am 2026-08-16 live entdeckten Foto-Vision-Lastproblem: ein
Foto, das isoliert anstandslos exportierte, scheiterte im 200er-Batch
reihenweise (bis zu 82% Fehlerquote trotz freiem Speicherplatz, kein
Format-Unterschied zwischen JPG/DNG) - Symptom-Muster "klappt einzeln,
scheitert unter Last". Fix: PhotoIndex.analyze_with_local_vision() versucht
ein gescheitertes Foto nach kurzer Pause einmal erneut, bevor es als
endgueltiger Fehler zaehlt.

Der Retry allein loeste das Problem am Ende nicht (siehe
plans/2026-08-17-jarvis-foto-export-phimagemanager-fix.md): die eigentliche
Ursache war eine PhotoKit-Falle (isSynchronous + isNetworkAccessAllowed) in
photos_helper.swift, die inzwischen behoben ist - aber selbst mit dem
korrekten asynchronen Warten brauchen manche Fotos laenger als der neue
45-Sekunden-Timeout, um aus iCloud geladen zu werden (echte, nicht
kurzzeitige Zeitueberschreitung). Statt solche Fotos jede Nacht erneut zu
versuchen, markiert analyze_with_local_vision() sie ab jetzt als "aktuell
nicht abrufbar" mit Zeitstempel + konkreter Fehlermeldung und laesst sie erst
nach local_photo_vision_unavailable_retry_days wieder in den naechsten Lauf."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from photos_client import PhotoIndex


def _index_with_one_pending_photo(tmp_path) -> PhotoIndex:
    index = PhotoIndex({}, base_path=tmp_path)
    index._save_cache(
        {
            "entries": [
                {"id": "PHOTO-1", "filename": "IMG_0001.JPG", "mediaType": "image"},
            ]
        }
    )
    return index


def _fake_status():
    status = MagicMock()
    status.available = True
    status.model = "gemma3:4b"
    return status


def test_transient_failure_then_success_counts_as_analyzed(tmp_path):
    index = _index_with_one_pending_photo(tmp_path)
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()
    fake_service.describe_image.return_value = {"description": "Ein Foto.", "model": "gemma3:4b"}

    export_calls = {"count": 0}

    def flaky_export(self, photo_id, destination, max_size):
        export_calls["count"] += 1
        if export_calls["count"] == 1:
            raise RuntimeError("voruebergehend ueberlastet")
        destination.write_bytes(b"fake-jpeg-bytes")

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", side_effect=flaky_export, autospec=True), \
         patch("photos_client.time.sleep") as fake_sleep:
        analyzed, failed = index.analyze_with_local_vision()

    assert (analyzed, failed) == (1, 0)
    assert export_calls["count"] == 2
    fake_sleep.assert_called_once_with(2)


def test_persistent_failure_counts_as_failed_after_two_attempts(tmp_path):
    index = _index_with_one_pending_photo(tmp_path)
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()

    export_calls = {"count": 0}

    def always_fails(self, photo_id, destination, max_size):
        export_calls["count"] += 1
        raise RuntimeError("weiterhin ueberlastet")

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", side_effect=always_fails, autospec=True), \
         patch("photos_client.time.sleep") as fake_sleep:
        analyzed, failed = index.analyze_with_local_vision()

    assert (analyzed, failed) == (0, 1)
    assert export_calls["count"] == 2
    fake_sleep.assert_called_once_with(2)
    fake_service.describe_image.assert_not_called()


def test_success_on_first_attempt_never_sleeps(tmp_path):
    index = _index_with_one_pending_photo(tmp_path)
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()
    fake_service.describe_image.return_value = {"description": "Ein Foto.", "model": "gemma3:4b"}

    def clean_export(self, photo_id, destination, max_size):
        destination.write_bytes(b"fake-jpeg-bytes")

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", side_effect=clean_export, autospec=True), \
         patch("photos_client.time.sleep") as fake_sleep:
        analyzed, failed = index.analyze_with_local_vision()

    assert (analyzed, failed) == (1, 0)
    fake_sleep.assert_not_called()


def test_persistent_failure_marks_entry_unavailable_with_error(tmp_path):
    index = _index_with_one_pending_photo(tmp_path)
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()

    def always_times_out(self, photo_id, destination, max_size):
        raise RuntimeError("Zeitüberschreitung beim Laden aus iCloud.")

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", side_effect=always_times_out, autospec=True), \
         patch("photos_client.time.sleep"):
        index.analyze_with_local_vision()

    entry = index._load_cache()["entries"][0]
    assert entry.get("local_vision_unavailable_since")
    assert entry.get("local_vision_last_error") == "Zeitüberschreitung beim Laden aus iCloud."
    assert "local_vision_analyzed_at" not in entry


def test_unavailable_entry_excluded_from_pending_within_retry_window(tmp_path):
    index = PhotoIndex({"local_photo_vision_unavailable_retry_days": 14}, base_path=tmp_path)
    recent = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    index._save_cache(
        {
            "entries": [
                {
                    "id": "PHOTO-1",
                    "filename": "IMG_0001.JPG",
                    "mediaType": "image",
                    "local_vision_unavailable_since": recent,
                    "local_vision_last_error": "Zeitüberschreitung beim Laden aus iCloud.",
                },
            ]
        }
    )
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", autospec=True) as fake_export:
        analyzed, failed = index.analyze_with_local_vision()

    assert (analyzed, failed) == (0, 0)
    fake_export.assert_not_called()


def test_unavailable_entry_retried_after_cooldown_expires(tmp_path):
    index = PhotoIndex({"local_photo_vision_unavailable_retry_days": 14}, base_path=tmp_path)
    long_ago = (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds")
    index._save_cache(
        {
            "entries": [
                {
                    "id": "PHOTO-1",
                    "filename": "IMG_0001.JPG",
                    "mediaType": "image",
                    "local_vision_unavailable_since": long_ago,
                    "local_vision_last_error": "Zeitüberschreitung beim Laden aus iCloud.",
                },
            ]
        }
    )
    fake_service = MagicMock()
    fake_service.status.return_value = _fake_status()
    fake_service.describe_image.return_value = {"description": "Ein Foto.", "model": "gemma3:4b"}

    def clean_export(self, photo_id, destination, max_size):
        destination.write_bytes(b"fake-jpeg-bytes")

    with patch("photos_client.LocalVisionService", return_value=fake_service), \
         patch.object(PhotoIndex, "_export_preview", side_effect=clean_export, autospec=True):
        analyzed, failed = index.analyze_with_local_vision()

    assert (analyzed, failed) == (1, 0)
    entry = index._load_cache()["entries"][0]
    assert "local_vision_unavailable_since" not in entry
    assert "local_vision_last_error" not in entry
