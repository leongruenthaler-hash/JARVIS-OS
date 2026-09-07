from __future__ import annotations

"""Leerer Platzhalter: get_openai_api_key() wird nur erreicht, wenn
config['openai_photo_vision_enabled'] wahr ist - unser CLI-Wrapper setzt das
nie, dieser Pfad wird also nie betreten."""


class SecureStorageError(Exception):
    pass


def get_openai_api_key() -> str | None:
    return None
