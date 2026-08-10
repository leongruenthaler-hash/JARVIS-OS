"""Tests fuer local_vision_service.py::_parse_response - insbesondere das
Entfernen von Markdown-Codezaeunen, mit denen gemma3:4b seine JSON-Antworten
bei manchen Fotos umschliesst (live getestet, 2026-08-10)."""

from local_vision_service import LocalVisionService


def _service() -> LocalVisionService:
    return LocalVisionService(config={})


def test_parse_response_plain_json():
    raw = '{"description": "Ein Sonnenuntergang am Strand.", "objects": ["Strand", "Meer"], "scene": "Natur", "colors": ["orange"], "text": "", "search_terms": ["sonnenuntergang"]}'
    result = _service()._parse_response(raw)
    assert result["description"] == "Ein Sonnenuntergang am Strand."
    assert result["objects"] == ["strand", "meer"]
    assert result["scene"] == "Natur"


def test_parse_response_strips_json_code_fence():
    raw = '```json\n{"description": "Ein Buerohund unter dem Schreibtisch.", "objects": ["Hund", "Schreibtisch"], "scene": "Buero", "colors": ["braun"], "text": "", "search_terms": ["hund"]}\n```'
    result = _service()._parse_response(raw)
    assert result["description"] == "Ein Buerohund unter dem Schreibtisch."
    assert result["objects"] == ["hund", "schreibtisch"]
    assert not result["description"].startswith("```")


def test_parse_response_strips_bare_code_fence():
    raw = '```\n{"description": "Ein Berg im Nebel.", "objects": ["Berg"], "scene": "Landschaft", "colors": ["grau"], "text": "", "search_terms": ["berg"]}\n```'
    result = _service()._parse_response(raw)
    assert result["description"] == "Ein Berg im Nebel."
    assert result["objects"] == ["berg"]


def test_parse_response_regression_dashboard_example():
    # Exaktes Beispiel aus dem Live-Test vom 2026-08-10 (photos_index.json): das
    # Modell hat die Antwort in ```json-Zaeune gepackt, der Parser ist vorher
    # sichtbar gescheitert und hat den rohen, unformatierten Text direkt in
    # local_vision_description/local_vision_objects abgelegt.
    raw = (
        '```json\n'
        '{\n'
        '  "description": "Ein digitales Dashboard mit mehreren Diagrammen und Kennzahlen.",\n'
        '  "objects": ["Dashboard", "Diagramm", "Bildschirm"],\n'
        '  "scene": "Buero",\n'
        '  "colors": ["blau", "weiss"],\n'
        '  "text": "Umsatz Q3",\n'
        '  "search_terms": ["dashboard", "analyse"]\n'
        '}\n'
        '```'
    )
    result = _service()._parse_response(raw)
    assert result["description"] == "Ein digitales Dashboard mit mehreren Diagrammen und Kennzahlen."
    assert not result["description"].startswith("```")
    assert result["objects"] == ["dashboard", "diagramm", "bildschirm"]
    assert not any(obj.startswith("```") for obj in result["objects"])
    assert result["scene"] == "Buero"


def test_parse_response_falls_back_to_raw_text_when_no_json_present():
    raw = "Das ist gar kein JSON, sondern nur ein Satz ueber ein Foto."
    result = _service()._parse_response(raw)
    assert result["description"] == raw
    assert result["scene"] == ""


def test_parse_response_falls_back_when_fenced_json_is_malformed():
    raw = '```json\n{"description": "kaputt", invalid}\n```'
    result = _service()._parse_response(raw)
    # Faellt sicher auf den Rohtext-Fallback zurueck statt eine Exception zu werfen.
    assert "kaputt" in result["description"] or result["description"].startswith("```")
    assert isinstance(result["objects"], list)
