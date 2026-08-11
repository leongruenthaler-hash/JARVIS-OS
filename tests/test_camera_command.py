"""Tests fuer jarvis.py::handle_camera_command() (siehe
plans/2026-08-11-jarvis-kamera-feedback.md). Deckt ab: enge Ausloese-Saetze
statt allgemeiner Kamera-Domaene, dass das aufgenommene Foto IMMER geloescht
wird (auch bei einem Analyse-Fehler), und dass ohne passenden Satz gar nichts
ausgeloest wird - CameraClient/LocalVisionService werden gemockt, damit Tests
weder eine echte Kamera noch Ollama brauchen."""

from unittest.mock import MagicMock, patch

import jarvis


def test_no_match_for_unrelated_text():
    assert jarvis.handle_camera_command("wie ist das Wetter heute") is None


def test_no_match_for_generic_foto_word():
    # Ein einzelnes Wort wie "Foto" darf NICHT als Kamera-Ausloeser zaehlen -
    # sonst kollidiert es mit der Fotos-Domaene (gleiches Risiko wie der
    # bereits behobene Bildschirm/Fotos-Bug dieser Sitzung).
    assert jarvis.handle_camera_command("zeig mir Fotos vom Urlaub") is None


def test_returns_status_message_when_vision_unavailable():
    with patch("local_vision_service.LocalVisionService") as fake_service_cls:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=False, message="Kein Vision-Modell installiert.")
        fake_service_cls.return_value = fake_service

        result = jarvis.handle_camera_command("wie sehe ich aus")

    assert result == "Kein Vision-Modell installiert."


def test_returns_camera_access_error_message():
    from camera_client import CameraAccessError

    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.side_effect = CameraAccessError("Kamera-Zugriff wurde nicht erlaubt.")
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie sehe ich aus")

    assert result == "Kamera-Zugriff wurde nicht erlaubt."


def test_photo_always_discarded_even_on_analysis_error():
    from local_vision_service import LocalVisionError

    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls, \
         patch("camera_client.discard_photo") as fake_discard:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service.describe_camera_photo.side_effect = LocalVisionError("kaputt")
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.return_value = "/tmp/fake_photo.jpg"
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie sehe ich aus")

    fake_discard.assert_called_once_with("/tmp/fake_photo.jpg")
    assert "nicht analysieren" in result


def test_successful_capture_returns_description():
    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls, \
         patch("camera_client.discard_photo") as fake_discard:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service.describe_camera_photo.return_value = {"description": "Dunkelblaues Hemd, wirkt ordentlich und stimmig."}
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.return_value = "/tmp/fake_photo.jpg"
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie ist mein outfit")

    assert result == "Dunkelblaues Hemd, wirkt ordentlich und stimmig."
    fake_discard.assert_called_once_with("/tmp/fake_photo.jpg")
