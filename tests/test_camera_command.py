"""Tests fuer jarvis.py::handle_camera_command() (siehe
plans/2026-08-11-jarvis-kamera-feedback.md). Deckt ab: enge Ausloese-Saetze
statt allgemeiner Kamera-Domaene, dass das aufgenommene Foto IMMER geloescht
wird (auch bei einem Analyse-Fehler), dass ohne passenden Satz gar nichts
ausgeloest wird, und dass die rohe Vision-Bildbeschreibung vor der Ausgabe
noch persoenlich umformuliert wird (Nachschaerfung: Leon bemaengelte live,
dass die rohe dritte-Person-Beschreibung ohne Anrede/Persoenlichkeit
unveraendert durchkam) - CameraClient/LocalVisionService werden gemockt,
damit Tests weder eine echte Kamera noch Ollama brauchen."""

from unittest.mock import MagicMock, patch

import jarvis


def _fake_llm(answer="Sir, Sie tragen ein dunkelblaues Hemd - ordentlich, fast verdächtig unauffällig."):
    llm = MagicMock()
    llm.ask.return_value = answer
    return llm


def test_no_match_for_unrelated_text():
    assert jarvis.handle_camera_command("wie ist das Wetter heute", _fake_llm()) is None


def test_no_match_for_generic_foto_word():
    # Ein einzelnes Wort wie "Foto" darf NICHT als Kamera-Ausloeser zaehlen -
    # sonst kollidiert es mit der Fotos-Domaene (gleiches Risiko wie der
    # bereits behobene Bildschirm/Fotos-Bug dieser Sitzung).
    assert jarvis.handle_camera_command("zeig mir Fotos vom Urlaub", _fake_llm()) is None


def test_returns_status_message_when_vision_unavailable():
    with patch("local_vision_service.LocalVisionService") as fake_service_cls:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=False, message="Kein Vision-Modell installiert.")
        fake_service_cls.return_value = fake_service

        result = jarvis.handle_camera_command("wie sehe ich aus", _fake_llm())

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

        result = jarvis.handle_camera_command("wie sehe ich aus", _fake_llm())

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

        result = jarvis.handle_camera_command("wie sehe ich aus", _fake_llm())

    fake_discard.assert_called_once_with("/tmp/fake_photo.jpg")
    assert "nicht analysieren" in result


def test_successful_capture_returns_humanized_feedback():
    llm = _fake_llm("Sir, Sie tragen ein dunkelblaues Hemd - ordentlich, fast verdächtig unauffällig.")
    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls, \
         patch("camera_client.discard_photo") as fake_discard:
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service.describe_camera_photo.return_value = {"description": "Die Person trägt ein dunkelblaues Hemd."}
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.return_value = "/tmp/fake_photo.jpg"
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie ist mein outfit", llm)

    # Nicht die rohe, unveraenderte Vision-Beschreibung - die wurde umformuliert.
    assert result == "Sir, Sie tragen ein dunkelblaues Hemd - ordentlich, fast verdächtig unauffällig."
    assert "Die Person" not in result
    fake_discard.assert_called_once_with("/tmp/fake_photo.jpg")
    llm.ask.assert_called_once()


def test_falls_back_to_raw_description_when_humanization_fails():
    llm = _fake_llm(answer="")
    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls, \
         patch("camera_client.discard_photo"):
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service.describe_camera_photo.return_value = {"description": "Rohe Beschreibung."}
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.return_value = "/tmp/fake_photo.jpg"
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie ist mein outfit", llm)

    assert result == "Rohe Beschreibung."
