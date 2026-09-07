from __future__ import annotations

"""Leerer Platzhalter: remote_worker_client wird nur von PhotoBackgroundWorker
(nicht von PhotoIndex, das dieser Skill nutzt) angefragt, und is_configured()
gibt hier immer False zurueck, damit dieser Zweig nie betreten wird."""


def is_configured(config: dict) -> bool:
    return False


def search_photos(config: dict, query: str):
    raise RuntimeError("remote_worker_client ist in diesem Skill nicht verfuegbar.")
