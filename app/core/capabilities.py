"""Zentrale Registry der Faehigkeiten, die der neue Intent-Router (core/intent_router.py)
dem Sprachmodell zur Auswahl anbietet - Teil des Umbaus weg von der alten ~30-stufigen
Regex-/Fuzzy-Keyword-Kaskade in jarvis.py::answer_message() hin zu EINER strukturierten
LLM-Entscheidung pro Nachricht (siehe Plan "Jarvis-Intent-Router 2.0", 2026-09-02).

Wichtig: Diese Registry schreibt KEINE Fachlogik neu. Jede Capability verweist auf eine
bestehende, bereits produktiv genutzte handle_X_command()-Funktion aus jarvis.py (oder
core/*.py) - die eigentliche Text-/Datumsverarbeitung, Berechtigungspruefung (ensure_permission)
und ggf. ACTION_ENGINE-Bestaetigung bleibt dort unveraendert. Der Router entscheidet nur noch
EINMAL, WELCHE dieser Funktionen fuer eine Nachricht ueberhaupt in Frage kommt, statt dass jede
einzelne Funktion selbst per Regex pruefen muss, ob sie "zustaendig" ist.

Registrierung passiert NICHT hier (um einen Zirkelimport mit jarvis.py zu vermeiden, das diese
Handler definiert), sondern in jarvis.py selbst ueber register_capability() - analog zum
bestehenden Muster von ACTION_ENGINE.register() in core/action_engine.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Ein Capability-Handler bekommt IMMER denselben Kontext (nicht die stark unterschiedlichen
# Original-Signaturen der handle_X_command()-Funktionen) und gibt entweder eine fertige
# Antwort oder None zurueck (None bedeutet: die Faehigkeit war doch nicht zustaendig, z.B. weil
# eine noetige Berechtigung fehlt oder die Anfrage beim naeheren Hinsehen doch nicht passt -
# der Router-Aufrufer faellt dann auf eine ehrliche "das hat nicht geklappt"-Antwort zurueck,
# NICHT zurueck in die alte Kaskade, die es nicht mehr gibt).
CapabilityHandler = Callable[["CapabilityContext"], "str | None"]


@dataclass
class CapabilityContext:
    """Alles, was ein Capability-Handler potenziell braucht - bewusst ein einzelnes Objekt
    statt einer langen, je nach Handler unterschiedlichen Parameterliste, damit die Registry
    (und der Router-Dispatch) fuer jede Capability gleich aussieht."""

    text: str
    memory: Any
    llm: Any
    config: dict[str, Any]
    workers: Any = None  # AnswerWorkers-Instanz - Handler duerfen z.B.
                          # ctx.workers.photo_worker fuer verzoegerte Worker-
                          # Initialisierung setzen, genau wie die alte Kaskade es tat.
    model_manager: Any = None


@dataclass
class Capability:
    name: str
    description: str
    handler: CapabilityHandler
    # "action" = die Faehigkeit kann etwas VERAENDERN (loeschen, senden, anlegen) - fuer den
    # Router-Prompt relevant, damit er im Zweifel eher zu "chat"/Rueckfrage statt zu einem
    # riskanten Aufruf tendiert. Die eigentliche Sicherheits-Bestaetigung passiert weiterhin
    # INNERHALB des Handlers ueber ACTION_ENGINE, dieses Feld ist nur Beschreibung/Hinweis.
    mutates: bool = False


_REGISTRY: dict[str, Capability] = {}


def register_capability(name: str, description: str, handler: CapabilityHandler, *, mutates: bool = False) -> None:
    _REGISTRY[name] = Capability(name=name, description=description, handler=handler, mutates=mutates)


def get_capability(name: str) -> Capability | None:
    return _REGISTRY.get(name)


def all_capabilities() -> list[Capability]:
    return list(_REGISTRY.values())


def capability_catalog_text() -> str:
    """Fuer den Router-Prompt: Name + Beschreibung jeder registrierten Faehigkeit, als
    einfache Liste. Wird bei jedem Router-Aufruf frisch generiert, damit neu registrierte
    Faehigkeiten automatisch auftauchen."""
    lines = []
    for cap in _REGISTRY.values():
        marker = " (verändert etwas, braucht ggf. Bestätigung)" if cap.mutates else ""
        lines.append(f"- {cap.name}: {cap.description}{marker}")
    return "\n".join(lines)
