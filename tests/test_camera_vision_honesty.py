"""Tests fuer den am 2026-08-13 live entdeckten Kamera-Feedback-Bug: Leon trug
nur Unterwaesche, Jarvis beschrieb einen frei erfundenen dunklen Pullover samt
silbernem Guertel. Root cause (siehe local_vision_service.py::
VISION_MODEL_CANDIDATES-Kommentar): das lokale Vision-Modell llava lag bei
einem eindeutigen, einfarbigen Testbild ("reines Rot") auf Leons Mac falsch
("Grau"), gemma3:4b (bereits installiert, kein Download noetig) traf beide
Testfarben korrekt und schneller. Zwei Massnahmen, beide hier getestet:
1) gemma3:4b hat in VISION_MODEL_CANDIDATES jetzt Vorrang vor llava.
2) Die Prompts (Vision-Beschreibung + Umformulierung) verlangen jetzt explizit
   Ehrlichkeit statt erfundener Details, auch bei kaum/keiner Kleidung."""

from unittest.mock import MagicMock, patch

import jarvis
from local_vision_service import LocalVisionService, VISION_MODEL_CANDIDATES


def _service() -> LocalVisionService:
    return LocalVisionService(config={})


def test_gemma3_precedes_llava_in_candidate_order():
    assert VISION_MODEL_CANDIDATES.index("gemma3:4b") < VISION_MODEL_CANDIDATES.index("llava")
    assert VISION_MODEL_CANDIDATES.index("gemma3:4b") < VISION_MODEL_CANDIDATES.index("llava:7b")


def test_select_model_prefers_gemma3_over_llava_when_both_installed():
    # Exakt Leons installierte Modelle (ollama list, 2026-08-13): qwen3:4b (kein
    # Vision-Modell), gemma3:4b, phi4-mini, llava:latest.
    installed = ["qwen3:4b", "gemma3:4b", "phi4-mini:latest", "llava:latest"]
    assert _service()._select_model(installed) == "gemma3:4b"


def test_select_model_falls_back_to_llava_when_gemma3_not_installed():
    installed = ["phi4-mini:latest", "llava:latest"]
    assert _service()._select_model(installed) == "llava:latest"


def _capture_camera_prompt(monkeypatch, response_json='{"description": "Test."}'):
    captured = {}

    def fake_generate(self, model, prompt, image_path):
        captured["prompt"] = prompt
        return response_json

    monkeypatch.setattr(LocalVisionService, "_ollama_generate", fake_generate)
    monkeypatch.setattr(LocalVisionService, "status", lambda self: MagicMock(available=True, model="gemma3:4b"))
    return captured


def test_camera_photo_prompt_does_not_presuppose_clothing(monkeypatch, tmp_path):
    captured = _capture_camera_prompt(monkeypatch)
    image_path = tmp_path / "fake.jpg"
    image_path.write_bytes(b"fake-image-bytes")

    _service().describe_camera_photo(image_path)

    prompt = captured["prompt"]
    assert "kaum oder keine Kleidung" in prompt
    assert "erfinde nichts dazu" in prompt


def test_camera_photo_prompt_requests_honesty_when_unclear(monkeypatch, tmp_path):
    captured = _capture_camera_prompt(monkeypatch)
    image_path = tmp_path / "fake.jpg"
    image_path.write_bytes(b"fake-image-bytes")

    _service().describe_camera_photo(image_path)

    prompt = captured["prompt"]
    assert "zu dunkel" in prompt
    assert "statt zu raten" in prompt


def test_humanize_camera_feedback_prompt_requires_fidelity_to_source():
    llm = MagicMock()
    llm.ask.return_value = "Sir, kurze Antwort."

    jarvis.humanize_camera_feedback_via_llm(llm, "Rohe Beschreibung.")

    system_message = llm.ask.call_args[0][0][0]["content"]
    assert "erfinde keine" in system_message
    assert "kaum oder keine Kleidung" in system_message


def test_humanize_camera_feedback_still_falls_back_on_empty_answer():
    llm = MagicMock()
    llm.ask.return_value = ""

    assert jarvis.humanize_camera_feedback_via_llm(llm, "Rohe Beschreibung.") is None


def test_full_pipeline_reports_missing_clothing_honestly_instead_of_inventing_outfit():
    # End-to-End (mit gemocktem Vision-Modell + LLM): wenn die rohe
    # Bildbeschreibung ehrlich "kaum Kleidung" sagt, darf die Umformulierung
    # kein Outfit erfinden - hier simuliert durch ein LLM, das die Vorgabe
    # tatsaechlich befolgt (Trefflichkeit des eigentlichen Modells kann ein Test
    # nicht erzwingen, wohl aber dass der Prompt es korrekt anweist - siehe
    # test_humanize_camera_feedback_prompt_requires_fidelity_to_source).
    llm = MagicMock()
    llm.ask.return_value = "Sir, Sie tragen gerade kaum etwas - kein Kommentar zum Stil heute nötig."

    with patch("local_vision_service.LocalVisionService") as fake_service_cls, \
         patch("camera_client.CameraClient") as fake_camera_cls, \
         patch("camera_client.discard_photo"):
        fake_service = MagicMock()
        fake_service.status.return_value = MagicMock(available=True)
        fake_service.describe_camera_photo.return_value = {
            "description": "Die Person traegt kaum Kleidung, hauptsaechlich Unterwaesche."
        }
        fake_service_cls.return_value = fake_service

        fake_camera = MagicMock()
        fake_camera.capture_photo.return_value = "/tmp/fake_photo.jpg"
        fake_camera_cls.return_value = fake_camera

        result = jarvis.handle_camera_command("wie sehe ich aus", llm)

    assert "Pullover" not in result
    assert "Hemd" not in result
    assert "Gürtel" not in result
