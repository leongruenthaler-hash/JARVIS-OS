"""Baustein E (siehe plans/2026-08-09-jarvis-mehrstufige-auftraege.md): plant aus
einer einzigen Anfrage eine geordnete Liste von Teilauftraegen ueber mehrere der
bestehenden Faehigkeiten, OHNE neue Faehigkeiten oder Parameter-Formate einzufuehren -
jeder geplante Schritt wird 1:1 an den schon vorhandenen Domaenen-Handler
weitergereicht (siehe jarvis.py::_dispatch_confirmed_domain). Bewusst "Plan einmal
aufstellen, dann streng sequenziell abarbeiten" statt eines iterativen Tool-Loops -
einfacher nachvollziehbar, kein Risiko einer Endlosschleife.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLANNER_DOMAINS = {
    "notes": "Notizen (Apple Notes, Einkaufslisten)",
    "calendar": "Kalender und Erinnerungen",
    "mail": "Mail (Apple Mail lesen/bearbeiten)",
    "photos": "Fotos-App und Fotoindex",
    "screen": "Bildschirm-Screenshot",
    "files": "Dateien und Schreibtisch",
    "music": "Apple Music",
    "contacts": "Kontakte und Anrufe",
}

_JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def _build_prompt(question: str) -> list[dict[str, str]]:
    domains_text = "\n".join(f"- {key}: {desc}" for key, desc in _PLANNER_DOMAINS.items())
    system = (
        "Du zerlegst einen Nutzerauftrag in eine geordnete Liste einzelner Schritte, "
        "wenn er mehrere unterschiedliche Faehigkeiten braucht. Verfuegbare Faehigkeiten "
        f"(Domaenen):\n{domains_text}\n\n"
        "Antworte AUSSCHLIESSLICH mit einem JSON-Array, keine Erklaerung, kein Fliesstext. "
        'Jedes Element ist ein Objekt mit genau zwei Feldern: "domain" (einer der obigen '
        'Domaenen-Schluessel, klein geschrieben) und "teilauftrag" (der auf diesen Schritt '
        "heruntergebrochene Anfrage-Text, auf Deutsch, so wie ihn ein Nutzer direkt sagen "
        "wuerde). Maximal 4 Schritte. Nutze nur Domaenen aus der Liste oben. Wenn der Auftrag "
        "erkennbar nur EINEN Schritt braucht, gib trotzdem ein Array mit genau einem Element "
        "zurueck."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


def _extract_json_array(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    match = _JSON_ARRAY_PATTERN.search(raw)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def parse_plan_response(raw: str, *, max_steps: int) -> list[dict[str, str]] | None:
    """Validiert die rohe Modellantwort streng - bei jedem Zweifel None statt zu
    raten (nie stillschweigend ausfuehren, was nicht sicher als gueltiger Plan
    erkennbar war)."""
    parsed = _extract_json_array(raw)
    if not isinstance(parsed, list) or not parsed:
        return None
    if len(parsed) > max_steps:
        return None

    steps: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            return None
        domain = str(item.get("domain") or "").strip().lower()
        teilauftrag = str(item.get("teilauftrag") or "").strip()
        if domain not in _PLANNER_DOMAINS or not teilauftrag:
            return None
        steps.append({"domain": domain, "teilauftrag": teilauftrag})
    return steps


def plan_multistep(
    llm: Any,
    question: str,
    *,
    max_steps: int = 4,
    max_output_tokens: int = 300,
) -> list[dict[str, str]] | None:
    """Stufe 3 der Absichtserkennung. Gibt eine geordnete Schrittliste zurueck oder
    None, wenn die Modellantwort nicht sauber als gueltiger Plan validiert werden
    konnte - der Aufrufer faellt dann auf den bestehenden Weg zurueck (Stufe 1/2),
    raet also nie selbst weiter."""
    messages = _build_prompt(question)
    try:
        raw = llm.ask(messages, max_output_tokens=max_output_tokens, user_text=question)
    except Exception:
        return None
    return parse_plan_response(raw, max_steps=max_steps)
