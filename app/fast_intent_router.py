from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from core.intent_matching import has_domain_fuzzy, normalize_umlauts

_GERMAN_WEEKDAYS = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
)
_GERMAN_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
    "September", "Oktober", "November", "Dezember",
)


def _format_german_date(value: datetime) -> str:
    """Formatiert wie strftime('%A, %d. %B %Y'), aber unabhaengig von der
    Prozess-Locale (strftime() liefert je nach System-Locale englische statt
    deutsche Wochentags-/Monatsnamen, obwohl Jarvis konfigurationsseitig immer
    Deutsch spricht - siehe config.json: language). Live beobachtet 2026-08-18:
    "Heute ist Tuesday, 18. August 2026." auf einem Mac mit en_US-Locale."""
    weekday = _GERMAN_WEEKDAYS[value.weekday()]
    month = _GERMAN_MONTHS[value.month - 1]
    return f"{weekday}, {value.day:02d}. {month} {value.year}"


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
                response=f"Heute ist {_format_german_date(today)}.",
                handled=True,
            )

        if self._looks_like_model_status(normalized):
            return FastIntentDecision(intent="model_status", handled=False, action="model_status")

        if self._looks_like_identity_query(normalized):
            return FastIntentDecision(intent="user_identity", handled=False)

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

    _OPEN_VERBS = ("oeffne", "starte", "oeffnen", "starten", "oeffnest", "starte bitte", "oeffne bitte")

    def _normalize(self, text: str) -> str:
        value = str(text or "").strip().lower()
        value = value.replace("-", " ")
        value = re.sub(r"\s+", " ", value)
        # ae/oe/ue/ss-Normalisierung, damit z.B. "Kalenda"/"Öffne" auch bei leicht
        # falscher Spracherkennung/Tippfehlern noch erkannt werden (siehe
        # core/intent_matching.py, has_domain_fuzzy).
        return normalize_umlauts(value)

    # Woerter, die anzeigen, dass "Uhr"/"Datum" nur als Nebenangabe in einer
    # anderen Anfrage vorkommen (z.B. "Termin heute um 19:00 Uhr eintragen") -
    # dann ist es keine reine Zeit-/Datumsfrage, sondern z.B. ein Kalender- oder
    # Erinnerungs-Auftrag, der die eigentliche Antwort-Kette (core.answer_message)
    # erreichen muss statt vom Fast-Intent abgefangen zu werden.
    _ACTION_CONTEXT_WORDS = (
        "termin", "termine", "termineintrag", "kalender", "kalendereintrag",
        "erinnerung", "erinnere", "erinnern",
        "notiz", "notizen", "aufgabe", "aufgaben", "eintragen", "trage ein",
        "trag ein", "plane", "planen", "verschiebe", "verschieben", "lösche",
        "loesche",
    )

    def _looks_like_time_query(self, text: str) -> bool:
        if has_domain_fuzzy(text, self._ACTION_CONTEXT_WORDS):
            return False
        # "trag ein" oben deckt nur die exakte Zweiwort-Phrase ab - "trag DAS
        # BITTE ein" (dazwischenliegende Fuellwoerter, ganz normale deutsche
        # Wortstellung) fiel durch und ein Kalender-Erstell-Satz mit Uhrzeit
        # landete dann faelschlich hier. Live beobachtet 2026-08-19: "Ich hab
        # heute um 9 Uhr Zahnarzt, trag das bitte ein." -> "Es ist jetzt ... Uhr."
        if re.search(r"\btrag\w*\b(?:\s+\w+){1,4}\s+ein\b", text):
            return False
        return has_domain_fuzzy(text, ("wie spaet", "uhrzeit", "uhr"))

    def _looks_like_date_query(self, text: str) -> bool:
        if has_domain_fuzzy(text, self._ACTION_CONTEXT_WORDS):
            return False
        return has_domain_fuzzy(text, ("welcher tag", "welches datum", "datum", "heute fuer", "heutiger tag"))

    def _looks_like_model_status(self, text: str) -> bool:
        return has_domain_fuzzy(text, ("welches modell", "modell nutzt", "welches modell nutzt du", "welcher modus"))

    def _looks_like_identity_query(self, text: str) -> bool:
        # Deterministischer Rueckhalt dagegen, dass das kleine lokale Modell
        # (phi4-mini) diese Frage trotz korrekt injiziertem Namen im System-Prompt
        # unzuverlaessig beantwortet (z.B. generische Begruessung statt des
        # tatsaechlichen Namens) - live beobachtet 2026-08-18, siehe
        # jarvis.py::route_fast_intent() fuer die eigentliche, garantiert korrekte
        # Antwort aus configured_user_name()/configured_user_address().
        return has_domain_fuzzy(
            text,
            ("wie heisse ich", "wer bin ich", "was ist mein name", "wie ist mein name", "kennst du meinen namen"),
        )

    def _extract_open_app(self, text: str) -> str | None:
        if not has_domain_fuzzy(text, self._OPEN_VERBS):
            return None
        for key, app_name in self.OPEN_APP_MAP.items():
            if has_domain_fuzzy(text, (normalize_umlauts(key),)):
                return app_name
        return None

    # Woerter fuer andere, spezifische Domaenen ("Status meiner Mails", "Status
    # meiner Fotos") - ohne diesen Schutz griff dasselbe Kollisionsmuster wie
    # beim Kalender-Fix weiter oben: "status" allein reichte, um JEDE
    # domaenenspezifische Statusfrage mit dem hartkodierten "Alles läuft,
    # {Anrede}." abzufangen, bevor die echte Domaenen-Logik (z.B. Mail-Postfach-
    # Pruefung) je zum Zug kam. Live beobachtet 2026-08-19: "Wie ist der Status
    # meiner Mails?" ergab trotz ungelesener Mails "Alles läuft, Sir.".
    _OTHER_DOMAIN_WORDS = (
        "mail", "mails", "email", "emails", "e mail", "posteingang", "postfach",
        "kalender", "termin", "termine", "erinnerung", "erinnerungen",
        "notiz", "notizen", "zettel", "foto", "fotos", "bild", "bilder",
        "vision", "fotoindex", "dateiindex",
        "datei", "dateien", "ordner", "musik", "song", "lied",
        "aufgabe", "aufgaben", "kontakt", "kontakte",
    )

    def _looks_like_small_system_query(self, text: str) -> bool:
        # "was steht" und "was ist los" bewusst NICHT hier - beide sind in
        # jarvis.py::CALENDAR_QUERY_PHRASES bereits als Kalenderabfrage-Muster
        # hinterlegt ("was steht heute an", "was ist heute los"). Da dieser
        # Fast-Intent-Pfad VOR der eigentlichen Kalenderlogik laeuft und bei
        # Treffer sofort mit dem hartkodierten "Alles läuft, {Anrede}."
        # antwortet, ueberschattete er bisher jede so formulierte Kalenderfrage
        # komplett - die echte Terminliste wurde nie erreicht. Live beobachtet
        # 2026-08-18: "was steht heute bei mir an" (ein echter Termin um 19 Uhr
        # war eingetragen) ergab trotzdem "Alles läuft, Sir.".
        if has_domain_fuzzy(text, self._OTHER_DOMAIN_WORDS):
            return False
        return has_domain_fuzzy(text, ("status", "ueberblick", "was geht", "zusammenfassung"))
