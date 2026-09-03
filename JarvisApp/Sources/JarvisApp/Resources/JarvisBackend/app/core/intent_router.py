"""Der neue Intent-Router: ersetzt die alte ~30-stufige Regex-/Fuzzy-Keyword-Kaskade in
jarvis.py::answer_message() durch EINE strukturierte LLM-Entscheidung pro Nachricht (Plan
"Jarvis-Intent-Router 2.0", 2026-09-02). Enthaelt nur die ENTSCHEIDUNG (Prompt-Aufbau,
Schema, Aufruf, Parsing) - die eigentliche AUSFUEHRUNG (welche bestehende Funktion aufgerufen
wird) bleibt bewusst in jarvis.py, das die Capability-Handler und handle_pending_action_flow()
bereits kennt (vermeidet einen Zirkelimport core <-> jarvis)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.capabilities import capability_catalog_text

ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "response_type": {
            "type": "string",
            "enum": ["chat", "capability_call", "confirm_pending", "cancel_pending"],
        },
        "chat_reply": {
            "type": "string",
            "description": "Nur bei response_type=chat: die fertige, direkte Antwort auf Deutsch.",
        },
        "capability": {
            "type": "string",
            "description": (
                "PFLICHT bei response_type=capability_call: EXAKT der Name einer Faehigkeit "
                "aus der Liste oben (z.B. 'calendar', 'notes', 'mail') - nie ein Befehlstext, "
                "nie ein Satz, nur der eine kurze Name selbst."
            ),
        },
        "clean_command": {
            "type": "string",
            "description": (
                "Nur bei response_type=capability_call, ZUSAETZLICH zu 'capability' (nicht "
                "statt dessen): der Befehl in einer klaren, vollstaendigen, eindeutigen "
                "Formulierung fuer die Ausfuehrung. IMMER AUF DEUTSCH, in derselben Sprache "
                "wie die Nutzer-Nachricht selbst - NIE ins Englische uebersetzen, auch wenn "
                "Englisch als Zwischenschritt natuerlicher wirkt (die Ausfuehrung erkennt nur "
                "deutsche Stichwoerter wie 'Termine', 'Notiz', 'heute'). Behalte zentrale "
                "Woerter aus der Originalnachricht moeglichst woertlich bei (z.B. 'Termine'/"
                "'Notiz'/Fragewoerter wie 'welche'/'wann') statt frei umzuformulieren - nur "
                "echtes Rauschen entfernen (Fuellwoerter, Selbstkorrekturen, Tippfehler), "
                "keinen neuen Satzbau erfinden. Eine Frage bleibt eine Frage (z.B. mit "
                "Fragewort/Fragezeichen), wird NICHT in eine Aussage oder Aufforderung "
                "umformuliert. Relative Zeitangaben (heute/morgen/naechsten Montag) "
                "unveraendert lassen (die Ausfuehrung loest die datumsmaessig selbst auf). "
                "Ergaenze alles fuer die Aufgabe Relevante aus dem bisherigen Gespraech, "
                "falls die letzte Nachricht allein nicht vollstaendig waere (z.B. eine kurze "
                "Zustimmung nach einer Rueckfrage)."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "Ein knapper Satz, warum diese Entscheidung getroffen wurde (nicht fuer den Nutzer sichtbar).",
        },
    },
    "required": ["response_type"],
}

ROUTER_SYSTEM_PROMPT_TEMPLATE = """Du bist der interne Entscheidungs-Teil von {assistant_name}, {creator_name}s \
persoenlichem Assistenten. Deine einzige Aufgabe hier: fuer die letzte Nachricht des Nutzers \
entscheiden, WIE geantwortet werden soll - nicht die eigentliche Persoenlichkeits-Antwort \
formulieren (das passiert in einem separaten Schritt).

Verfuegbare Faehigkeiten (nutze eine davon nur, wenn die Nachricht wirklich danach verlangt,\
 nicht bei beilaeufiger Erwaehnung im Gespraech). Vertraue der Beschreibung: wenn eine \
Nachricht zu einer Faehigkeit passt, waehle "capability_call" dafuer, auch wenn du selbst \
unsicher waerst, ob DU das koenntest - die Beschreibung sagt verbindlich, was die \
Ausfuehrung (nicht du) tatsaechlich kann. Behaupte im chat-Zweig NIE, etwas nicht zu \
koennen, das laut einer der Beschreibungen unten moeglich ist:
{capabilities}

{pending_context}

Entscheide response_type:
- "chat": eine normale Gespraechsantwort reicht, keine der Faehigkeiten oben ist wirklich \
gemeint. Fuelle chat_reply mit einer kurzen, natuerlichen Antwort im ueblichen Jarvis-Ton.
- "capability_call": die Nachricht ist eine klare Anfrage/Aufgabe, die zu einer der \
Faehigkeiten oben passt. Setze IMMER BEIDE Felder: "capability" auf deren exakten, kurzen \
Namen (nur den Namen, z.B. "calendar" - niemals einen Satz oder Befehlstext in dieses \
Feld!) UND zusaetzlich "clean_command" auf eine klare, vollstaendige Formulierung des \
Befehls (siehe Schema-Beschreibung) - die Ausfuehrung bekommt NUR diesen Text, nicht den \
gesamten Gespraechsverlauf, muss ihn also allein verstehen koennen. Formuliere KEINE \
eigene Antwort - die Ausfuehrung passiert danach separat.
- "confirm_pending": es gibt oben einen offenen Vorschlag, und der Nutzer stimmt dem gerade zu \
(auch indirekt/knapp wie "ja", "mach das", "passt").
- "cancel_pending": es gibt oben einen offenen Vorschlag, und der Nutzer lehnt ab oder wechselt \
erkennbar das Thema, ohne sich auf den Vorschlag zu beziehen.

Wichtig: wenn ein Vorschlag offen ist, aber die Nachricht klar etwas VOELLIG anderes ist (kein \
Bezug erkennbar), waehle "chat" oder "capability_call" fuer das neue Thema, NICHT \
"cancel_pending" erzwingen - der offene Vorschlag bleibt dann einfach unbeantwortet stehen und \
verfaellt spaeter von selbst."""


@dataclass
class RouterDecision:
    response_type: str
    chat_reply: str = ""
    capability: str = ""
    clean_command: str = ""
    reasoning: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_chat(self) -> bool:
        return self.response_type == "chat"

    @property
    def is_capability_call(self) -> bool:
        return self.response_type == "capability_call"

    @property
    def is_confirm(self) -> bool:
        return self.response_type == "confirm_pending"

    @property
    def is_cancel(self) -> bool:
        return self.response_type == "cancel_pending"


def describe_pending_action(memory: Any) -> str:
    """Baut eine kurze, dem Modell verstaendliche Beschreibung eines offenen
    Bestaetigungs-Vorschlags (memory.settings.pending_*) - schliesst die in der
    Architektur-Analyse gefundene Luecke: bisher war dieser Zustand ein reiner
    Seitenkanal, den das Modell nie sah. Absichtlich knapp/generisch statt jedes der
    ~16 pending_*-Felder einzeln zu benennen, da sich deren genaue Form aendern kann -
    der Router muss nur wissen "es gibt gerade etwas Offenes, hier ist der Text dazu",
    nicht die interne Datenstruktur."""
    settings = memory.get("settings") or {} if memory is not None else {}
    pending_keys = [
        "pending_mail_delete",
        "pending_call_contact",
        "pending_call_choice",
        "pending_permission",
        "pending_note",
        "pending_desktop_move",
        "pending_desktop_move_many",
        "pending_calendar_create",
        "pending_calendar_delete",
        "pending_mail_document_export",
        "pending_file_action",
        "pending_domain_clarification",
        "pending_mail_calendar_confirmation",
        "pending_cleanup_confirmation",
        "pending_lieferando_open",
        "pending_reservation_open",
    ]
    for key in pending_keys:
        value = settings.get(key)
        if isinstance(value, dict) and value:
            prompt = value.get("confirm_prompt") or value.get("action") or ""
            return (
                f"Es gibt gerade einen offenen, noch unbeantworteten Vorschlag ({key}): "
                f"{prompt or 'siehe letzte Jarvis-Antwort im Verlauf'}. "
            )
    return "Es gibt gerade keinen offenen Vorschlag."


def build_router_prompt(*, assistant_name: str, creator_name: str, memory: Any) -> str:
    return ROUTER_SYSTEM_PROMPT_TEMPLATE.format(
        assistant_name=assistant_name,
        creator_name=creator_name,
        capabilities=capability_catalog_text(),
        pending_context=describe_pending_action(memory),
    )


def parse_router_decision(data: dict[str, Any]) -> RouterDecision:
    response_type = str(data.get("response_type") or "chat").strip()
    if response_type not in {"chat", "capability_call", "confirm_pending", "cancel_pending"}:
        response_type = "chat"
    return RouterDecision(
        response_type=response_type,
        chat_reply=str(data.get("chat_reply") or "").strip(),
        capability=str(data.get("capability") or "").strip(),
        clean_command=str(data.get("clean_command") or "").strip(),
        reasoning=str(data.get("reasoning") or "").strip(),
        raw=data,
    )


def decide(
    llm: Any,
    *,
    memory: Any,
    question: str,
    messages: list[dict[str, str]],
    assistant_name: str = "Jarvis",
    creator_name: str = "Leon",
) -> RouterDecision:
    """Fuehrt den eigentlichen Router-Aufruf aus: baut den Entscheidungs-System-Prompt,
    haengt ihn VOR den vom Aufrufer schon vorbereiteten Verlauf (messages, wie ihn
    build_input() liefert) und laesst das Modell strukturiert antworten. Bei jedem Fehler
    (Timeout, kaputtes JSON, ...) wird defensiv auf "chat" mit leerer chat_reply
    zurueckgefallen, statt die ganze Anfrage scheitern zu lassen - der Aufrufer (jarvis.py)
    erkennt eine leere chat_reply und laesst in dem Fall die normale Chat-Antwort ohnehin
    vom folgenden regulaeren llm.ask() kommen."""
    router_system = build_router_prompt(assistant_name=assistant_name, creator_name=creator_name, memory=memory)
    history = [m for m in messages if m.get("role") != "system"]
    # `messages` ist reine VORGESCHICHTE (siehe _routing_history() in jarvis.py) - die
    # aktuelle Frage steht da NICHT zwangslaeufig schon drin. Bugreport 2026-09-02: ohne
    # dieses explizite Anhaengen bekam das Modell die aktuelle Frage nie zu sehen, sondern
    # antwortete auf die letzte Historie-Nachricht - "Welche Termine habe ich heute?" wurde
    # so ignoriert und stattdessen "wie geht es dir" (Verlaufsrest) beantwortet.
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != question:
        history = [*history, {"role": "user", "content": question}]
    router_messages = [{"role": "system", "content": router_system}, *history]
    try:
        # force_provider="gemini": die Klassifikationsentscheidung selbst soll immer
        # ueber den schnellsten verfuegbaren Anbieter laufen (Nutzerwunsch 2026-09-03:
        # "Gemini fuer die schnelleren Antworten"), unabhaengig davon, welcher Anbieter
        # gerade als Haupt-Provider aktiv ist. Faellt in llm.ask_structured() still auf
        # den aktiven Anbieter zurueck, wenn (noch) kein Gemini-Key hinterlegt ist.
        data = llm.ask_structured(router_messages, json_schema=ROUTER_SCHEMA, force_provider="gemini")
    except Exception:
        return RouterDecision(response_type="chat", chat_reply="")
    return parse_router_decision(data)
