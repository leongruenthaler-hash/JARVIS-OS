from __future__ import annotations

"""Leerer Platzhalter: photos_client.py::PhotoIndex ruft LocalVisionService nur
in local_vision_status()/analyze_with_local_vision() auf - beides NICHT Teil
des scan()/search()-Pfads, den dieser Skill nutzt. Reicht als Stub, damit der
Import gelingt, ohne die echte Ollama-Vision-Anbindung mitschleppen zu muessen."""


class LocalVisionError(Exception):
    pass


class LocalVisionService:
    def __init__(self, config: dict) -> None:
        self.config = config

    def describe_image(self, path) -> dict:
        raise LocalVisionError("Lokale Vision-Analyse ist in diesem Skill nicht eingerichtet.")
