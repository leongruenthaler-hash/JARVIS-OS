from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass
class FastIntentDecision:
    intent: str
    response: str = ""
    action: str = ""
    target: str = ""
    needs_confirmation: bool = False
    handled: bool = False
    payload: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class FastIntentRouter:
    OPEN_APP_MAP: dict[str, str] = {
        "mail": "Mail",
        "apple mail": "Mail",
        "kalender": "Calendar",
        "calendar": "Calendar",
        "erinnerungen": "Reminders",
        "reminders": "Reminders",
        "musik": "Music",
        "music": "Music",
        "spotify": "Spotify",
        "xcode": "Xcode",
        "safari": "Safari",
        "finder": "Finder",
        "notizen": "Notes",
        "notes": "Notes",
        "terminal": "Terminal",
    }

    def route(self, text: str) -> FastIntentDecision | None:
        normalized = self._normalize(text)
        if not normalized:
            return None

        if self._looks_like_time_query(normalized):
            now = datetime.now()
            return FastIntentDecision(
                intent="show_time",
                response=f"Es ist jetzt {now:%H:%M} Uhr.",
                handled=True,
            )

        if self._looks_like_date_query(normalized):
            today = datetime.now()
            return FastIntentDecision(
                intent="show_date",
                response=f"Heute ist {today:%A, %d. %B %Y}.",
                handled=True,
            )

        if self._looks_like_model_status(normalized):
            return FastIntentDecision(intent="model_status", handled=False, action="model_status")

        open_app = self._extract_open_app(normalized)
        if open_app:
            return FastIntentDecision(
                intent="open_app",
                action="open_app",
                target=open_app,
                handled=True,
                payload={"json_only": True, "app": open_app},
            )

        if self._looks_like_small_system_query(normalized):
            return FastIntentDecision(intent="status", action="show_status", handled=False)

        return None

    def _normalize(self, text: str) -> str:
        value = str(text or "").strip().lower()
        value = value.replace("-", " ")
        value = re.sub(r"\s+", " ", value)
        return value

    def _looks_like_time_query(self, text: str) -> bool:
        return any(term in text for term in ("wie spät", "wie spaet", "uhrzeit", "uhr"))

    def _looks_like_date_query(self, text: str) -> bool:
        return any(term in text for term in ("welcher tag", "welches datum", "datum", "heute für", "heutiger tag"))

    def _looks_like_model_status(self, text: str) -> bool:
        return any(term in text for term in ("welches modell", "modell nutzt", "welches modell nutzt du", "welcher modus"))

    def _extract_open_app(self, text: str) -> str | None:
        if not any(term in text for term in ("öffne", "oeffne", "starte", "öffnen", "oeffnen", "öffnest", "starte bitte", "öffne bitte")):
            return None
        for key, app_name in self.OPEN_APP_MAP.items():
            if key in text:
                return app_name
        return None

    def _looks_like_small_system_query(self, text: str) -> bool:
        return any(term in text for term in ("status", "überblick", "ueberblick", "was geht", "was steht", "was ist los", "zusammenfassung"))
