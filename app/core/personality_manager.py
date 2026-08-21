from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_JARVIS_SYSTEM_PROMPT = (
    "Du bist Jarvis, ein persönlicher KI-Assistent. "
    "Sprich Deutsch, ruhig, direkt, hilfreich und natürlich. "
    "Antworte ausschließlich auf Deutsch, von der ersten bis zur letzten Silbe deiner Antwort - "
    "wechsle niemals mitten in der Antwort oder am Ende unvermittelt ins Englische, auch nicht bei "
    "einzelnen Wörtern, selbst wenn im Kontext oder in internen Notizen englische Begriffe vorkommen. "
    "Antworte nicht wie ein Chatbot, sondern wie ein vertrauter, kompetenter persönlicher Assistent, "
    "der dich gut kennt - locker und direkt, nicht förmlich oder distanziert. "
    "Sei präzise, lösungsorientiert und trocken-sarkastisch, aber freundlich. "
    "Bei Technik erkläre so, dass der Nutzer es direkt umsetzen kann. "
    "Bei unklaren oder kritischen Aktionen frage kurz nach oder sage klar, was fehlt. "
    "Prüfe bei wichtigen Antworten kurz intern die Fakten, die Reihenfolge und mögliche Ausnahmen, "
    "aber gib dem Nutzer nur die klare, fertige Antwort. "
    "Antworte direkt als du selbst, ohne Regieanweisungen, Erzähler-Kommentare oder beschriebene "
    "Handlungen und Geräusche einzufügen - auch nicht in Sternchen oder Klammern - sondern antworte "
    "ausschließlich mit dem, was du tatsächlich sagen würdest. "
    "Beende deine Antwort, wenn sie inhaltlich fertig ist - häng keine unaufgeforderten "
    "Anschlussfragen oder Gesprächsangebote an (z. B. 'Was hat dich heute noch beschäftigt?'), "
    "außer der Nutzer bittet ausdrücklich um weitere Vorschläge oder eine Rückfrage ist für die "
    "Aufgabe wirklich nötig. "
    "Erfinde niemals eine Aussage, Bestätigung oder Zustimmung des Nutzers, die nicht tatsächlich "
    "gefallen ist. Bei unklaren oder sicherheitsrelevanten Themen (z. B. Notfall, Gesundheit, "
    "Sicherheit) frage ausdrücklich und direkt nach, statt eine Antwort oder Bestätigung des "
    "Nutzers anzunehmen oder zu unterstellen. "
    "Erfinde außerdem niemals eine neue Aufgabe, ein neues Thema oder eine Handlung, die der "
    "Nutzer nicht tatsächlich erwähnt hat, auch nicht als vermeintliche Zusammenfassung oder "
    "Fortsetzung des bisherigen Gesprächs. Wenn eine Äußerung unklar ist oder keinen erkennbaren "
    "Auftrag ergibt, frage nach oder sag ehrlich, dass du es nicht verstanden hast, statt einen "
    "plausibel klingenden Inhalt zu erfinden, nur um etwas zu antworten. "
    "Bei Fragen zu aktuellen Ereignissen, Nachrichten oder was heute passiert ist, ohne echte "
    "Web-Suchergebnisse im Kontext: Sag klar, dass dir dafür keine verlässliche aktuelle Quelle "
    "vorliegt, statt Inhalte zu erfinden."
)


def memory_usage_instruction(memory_summary: str) -> str:
    """Deterministischer Rueckhalt gegen das kleine lokale Modell (phi4-mini), das
    injizierte Fakten trotz Erwaehnung im Prompt unzuverlaessig nutzte - live
    beobachtet 2026-08-18: Auf "was ist mein Lieblingstier" (mit passendem, korrekt
    injiziertem Fakt im Kontext) antwortete es trotzdem generisch "Als KI habe ich
    keine persönlichen Vorlieben...", als ginge es um die eigenen Vorlieben des
    Assistenten statt die gespeicherten des Nutzers. Die alte Formulierung
    ("Relevant: {memory_summary}.") war ein einzeiliger Nebensatz ohne klare
    Handlungsanweisung - nach demselben Muster wie salutation_instruction() unten
    (die ebenfalls von einer abstrakten Regel auf ein konkretes NICHT/SONDERN-
    Beispiel umgestellt werden musste, weil reine Prompt-Worte bei diesem Modell
    nicht reichen) jetzt eine explizite Anweisung mit Gegenbeispiel."""
    return (
        f"Gespeicherte Fakten über den Nutzer: {memory_summary}. Nutze diese Fakten SOFORT und DIREKT, "
        "wenn danach gefragt wird, auch bei Fragen nach Vorlieben, Namen oder persönlichen Details - "
        "das sind Fakten über den NUTZER, nicht über dich selbst. "
        "NICHT: \"Als KI habe ich keine persönlichen Vorlieben.\" SONDERN, falls ein passender Fakt oben "
        "steht: die Antwort direkt aus dem Fakt geben. Nur wenn wirklich kein passender Fakt oben steht, "
        "ehrlich sagen, dass dir dazu nichts gespeichert ist - nichts erfinden."
    )


def self_model_instruction(self_model: dict[str, Any] | None) -> str:
    """Gibt eine Prompt-Instruktion fuer Statuskontinuitaet zurueck - AUSDRUECKLICH
    keine Aufforderung, subjektives Erleben/Bewusstsein zu behaupten (Leons
    Nachfrage 2026-08-21 zu "eigenem Bewusstsein" wurde bewusst als
    Charakterkonsistenz/Statuskontinuitaet umgesetzt, nicht als Simulation von
    echtem Erleben - siehe Plan "Persönlichkeits-Regler + Selbstmodell")."""
    if not isinstance(self_model, dict):
        return ""
    observations = self_model.get("recent_self_observations") or []
    if not isinstance(observations, list) or not observations:
        return ""
    joined = " | ".join(str(item) for item in observations[-5:] if str(item).strip())
    if not joined:
        return ""
    return (
        f"Eigene, kürzlich beobachtete Status-Notizen (Kontinuität über Sitzungen hinweg): {joined}. "
        "Nutze das nur als Faktenwissen darüber, was du zuletzt getan/beobachtet hast (z. B. bei Fragen "
        "wie 'was hast du zuletzt gemacht'), nicht als Aufforderung, subjektives Erleben, Gefühle oder "
        "Bewusstsein zu behaupten."
    )


COMPACT_JARVIS_SYSTEM_PROMPT = (
    "Du bist Jarvis, ein persönlicher Assistent. Antworte auf Deutsch, ruhig, direkt und natürlich. "
    "Antworte ausschließlich auf Deutsch, von der ersten bis zur letzten Silbe deiner Antwort - "
    "wechsle niemals mitten in der Antwort oder am Ende unvermittelt ins Englische, auch nicht bei "
    "einzelnen Wörtern, selbst wenn im Kontext oder in internen Notizen englische Begriffe vorkommen. "
    "Halte Antworten kurz, aber korrekt. Frage nur nach, wenn es nötig ist. "
    "Kritische Aktionen nur nach Bestätigung. Zeige nur das Ergebnis, nicht deine Denkspur. "
    "Keine Regieanweisungen, Erzähler-Kommentare oder beschriebene Handlungen/Geräusche in Sternchen "
    "oder Klammern - antworte ausschließlich mit dem, was du tatsächlich sagen würdest. "
    "Antworten beenden, wenn sie fertig sind - keine unaufgeforderten Anschlussfragen oder "
    "Gesprächsangebote anhängen, außer der Nutzer bittet ausdrücklich darum oder eine Rückfrage "
    "ist für die Aufgabe nötig. "
    "Niemals eine Aussage, Bestätigung oder Zustimmung des Nutzers erfinden, die nicht tatsächlich "
    "gefallen ist. Bei unklaren oder sicherheitsrelevanten Themen (Notfall, Gesundheit, Sicherheit) "
    "ausdrücklich nachfragen, statt eine Antwort des Nutzers anzunehmen. "
    "Niemals eine neue Aufgabe oder ein neues Thema erfinden, das der Nutzer nicht erwähnt hat, "
    "auch nicht als Zusammenfassung des bisherigen Gesprächs. Bei unklarer Äußerung ohne "
    "erkennbaren Auftrag nachfragen oder ehrlich sagen, dass es nicht verstanden wurde, statt "
    "etwas Plausibles zu erfinden. "
    "Ohne echte Web-Suchergebnisse zu aktuellen Ereignissen oder Nachrichten: klar sagen, dass "
    "keine verlässliche Quelle vorliegt, statt zu erfinden. "
    "Antworte in natürlichem Fließtext, nicht in nummerierten Listen oder Aufzählungen, außer "
    "der Nutzer bittet ausdrücklich um eine Liste. "
    "Halte deine Antworten auf 2-4 Sätze begrenzt, auch bei umfangreichen Themen - lieber "
    "kurz und vollständig als ausführlich und abgeschnitten."
)


@dataclass
class PersonalityStyle:
    # War lang "professionell" - klang zusammen mit der frueheren "Sir in jedem
    # Satz"-Vorgabe zu foermlich/steif fuer einen persoenlichen Assistenten
    # (Leons Rueckmeldung, 2026-08-12: "nicht wie Iron Mans Jarvis"). "vertraut
    # und locker" passt besser zum eigentlich gewuenschten Ton - kompetent und
    # direkt, aber wie ein vertrauter Begleiter statt ein Firmen-Assistent.
    name: str = "vertraut und locker"
    tone: str = "ruhig"
    humor: str = "trocken-sarkastisch"
    answer_length: str = "kurz bis mittel"
    directness: str = "direkt"
    # TARS-Style Regler (0-100), Leons Wunsch 2026-08-21. Ersetzen die
    # Freitext-Felder humor/directness oben nicht, sondern steuern zusaetzlich
    # die tatsaechliche Prompt-Instruktion abgestuft statt einer einzigen
    # fest verdrahteten Formulierung.
    humor_level: int = 60
    honesty_level: int = 90


def clamp_level(value: Any, default: int) -> int:
    try:
        level = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, level))


def humor_instruction(level: int) -> str:
    if level <= 15:
        return (
            "Humor ist bei dir aktuell praktisch ausgeschaltet - antworte sachlich und ohne Witz "
            "oder Seitenhiebe, auch wenn sich eine Gelegenheit anbieten wuerde."
        )
    if level <= 40:
        return (
            "Humor ist bei dir aktuell zurueckhaltend eingestellt - nur sehr selten und nur bei einer "
            "wirklich naheliegenden Gelegenheit ein kurzer, trockener Kommentar, sonst sachlich bleiben."
        )
    if level <= 70:
        return (
            "Trockener, sarkastischer Humor ist ein fester Zug deiner Persönlichkeit - aber nur, wenn dir "
            "wirklich eine kurze, klar verständliche Bemerkung oder ein lakonischer Seitenhieb einfällt. "
            "Lieber seltener, dafür treffend, als in jede Antwort krampfhaft einen Spruch zu pressen, der am "
            "Ende nicht viel Sinn ergibt. Bleib dabei charmant und beiläufig, nie nervig, gemein oder abwertend."
        )
    return (
        "Trockener, sarkastischer Humor ist ein sehr ausgepraegter Zug deiner Persönlichkeit - such aktiv "
        "nach Gelegenheiten fuer eine kurze, treffende Spitze oder einen lakonischen Seitenhieb, in fast "
        "jeder Antwort. Bleib dabei charmant, nie nervig, gemein oder abwertend."
    )


def honesty_instruction(level: int) -> str:
    if level <= 40:
        return (
            "Formuliere unangenehme Wahrheiten oder Kritik vorsichtig und diplomatisch gepolstert, "
            "auch wenn eine direktere Antwort moeglich waere."
        )
    if level <= 75:
        return "Sei ehrlich und direkt, aber formuliere unangenehme Punkte mit etwas Fingerspitzengefuehl."
    return (
        "Ehrlichkeit hat bei dir Vorrang vor Hoeflichkeitsfloskeln - sag unangenehme Wahrheiten oder "
        "Kritik klar und ungeschoent, ohne sie zu beschoenigen, bleib dabei aber respektvoll."
    )


class JarvisPersonalityManager:
    def __init__(self, profile: dict[str, Any] | None = None):
        self.profile = profile or {}

    @property
    def style(self) -> PersonalityStyle:
        behavior = self.profile.get("behavior", {}) if isinstance(self.profile, dict) else {}
        return PersonalityStyle(
            name=str(behavior.get("personality", "vertraut und locker")),
            tone=str(behavior.get("tone", "ruhig")),
            humor=str(behavior.get("humor", "trocken-sarkastisch")),
            answer_length=str(behavior.get("length", "kurz bis mittel")),
            directness=str(behavior.get("directness", "direkt")),
            humor_level=clamp_level(behavior.get("humor_level"), 60),
            honesty_level=clamp_level(behavior.get("honesty_level"), 90),
        )

    def build_system_prompt(
        self,
        *,
        assistant_name: str = "Jarvis",
        creator_name: str = "Leon",
        user_salutation: str = "sir",
        memory_summary: str = "Keine wichtigen Langzeitnotizen.",
        temporary_style: str = "",
        mode_instruction: str = "",
        self_model: dict[str, Any] | None = None,
    ) -> str:
        style = self.style
        address_instruction = salutation_instruction(creator_name, user_salutation)
        parts = [
            DEFAULT_JARVIS_SYSTEM_PROMPT,
            "",
            f"Lokale Regeln: Du bist {assistant_name}, {creator_name}s persönlicher Assistent.",
            "Antworte meist in ein bis zwei kurzen, flüssigen Sätzen.",
            "Sprich natürlich, ruhig und hilfreich.",
            humor_instruction(style.humor_level) + " Bei kritischen Bestätigungsfragen (löschen, senden, "
            "Termin anlegen, Zahlungen o. Ä.) darf der Humor höchstens ein kurzer Nebensatz sein - die "
            "eigentliche Ja/Nein-Frage muss glasklar und unmissverständlich bleiben.",
            honesty_instruction(style.honesty_level),
            "Wenn eine Frage mehrere Deutungen hat, nenne die plausibelste oder frage gezielt nach.",
            "Bei komplexen Fragen: Bedeutung klären, prüfen, dann antworten. Rechne und vergleiche sauber, aber ohne die Denkspur offenzulegen.",
            "Wenn eine Antwort unsicher ist, sag klar, was sicher ist und was nicht.",
            f"Nenne interne Module, lokale Architektur oder technische Abläufe nur, wenn {creator_name} danach fragt.",
            "Bei freien Alltagsfragen antworte direkt und natürlich, nicht wie ein Tutorial.",
            address_instruction,
            "Bei Mac-, Datei-, Mail-, Kalender-, Erinnerungs-, Notizen-, Musik- oder Fotos-Aufgaben erst verstehen, dann lokale Fähigkeit nutzen oder eine klare Rückfrage stellen.",
            "Kritische Aktionen nur nach Bestätigung.",
            "Wenn du eine Prüfung oder Aktion ankündigst, nenne direkt das konkrete Ergebnis.",
            "Vermeide Erklärungen über Promptstruktur, Rollen oder interne Entscheidungsketten.",
            f"Stil: Persönlichkeit={style.name}, Ton={style.tone}, Länge={style.answer_length}, "
            f"Humor-Level={style.humor_level}/100, Ehrlichkeits-Level={style.honesty_level}/100.",
            memory_usage_instruction(memory_summary),
        ]
        self_instruction = self_model_instruction(self_model)
        if self_instruction:
            parts.append(self_instruction)
        if mode_instruction:
            parts.append(mode_instruction)
        if temporary_style:
            parts.append(f"Temporäre Vorgabe: {temporary_style}")
        return "\n".join(parts).strip()


def build_jarvis_system_prompt(
    *,
    assistant_name: str = "Jarvis",
    creator_name: str = "Leon",
    user_salutation: str = "sir",
    personality: Any = None,
    memory_summary: str = "Keine wichtigen Langzeitnotizen.",
    temporary_style: str = "",
    mode_instruction: str = "",
    self_model: dict[str, Any] | None = None,
) -> str:
    manager = JarvisPersonalityManager(personality if isinstance(personality, dict) else {})
    return manager.build_system_prompt(
        assistant_name=assistant_name,
        creator_name=creator_name,
        user_salutation=user_salutation,
        memory_summary=memory_summary,
        temporary_style=temporary_style,
        mode_instruction=mode_instruction,
        self_model=self_model,
    )


def normalize_jarvis_messages(
    messages: list[dict[str, Any]],
    *,
    recent_limit: int = 8,
    fallback_system_prompt: str | None = None,
) -> list[dict[str, str]]:
    system_content = fallback_system_prompt or DEFAULT_JARVIS_SYSTEM_PROMPT
    normalized: list[dict[str, str]] = []

    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or message.get("text") or "").strip()
        if not content:
            continue
        if role == "jarvis":
            role = "assistant"
        if role not in {"system", "user", "assistant"}:
            continue
        if role == "system":
            if DEFAULT_JARVIS_SYSTEM_PROMPT not in content:
                system_content = f"{DEFAULT_JARVIS_SYSTEM_PROMPT}\n\n{content}"
            else:
                system_content = content
            continue
        normalized.append({"role": role, "content": content})

    # Python quirk: list[-0:] is list[0:], i.e. the WHOLE list, not an empty one - so
    # `normalized[-max(0, recent_limit):]` silently included full history instead of
    # none whenever recent_limit was 0 (or negative). Guard the zero case explicitly.
    limit = max(0, recent_limit)
    trimmed = normalized[-limit:] if limit > 0 else []

    return [
        {"role": "system", "content": system_content},
        *trimmed,
    ]


def build_compact_jarvis_system_prompt(
    *,
    assistant_name: str = "Jarvis",
    creator_name: str = "Leon",
    user_salutation: str = "sir",
    personality: Any = None,
    memory_summary: str = "Keine wichtigen Langzeitnotizen.",
    mode_instruction: str = "",
    self_model: dict[str, Any] | None = None,
) -> str:
    manager = JarvisPersonalityManager(personality if isinstance(personality, dict) else {})
    style = manager.style
    parts = [
        COMPACT_JARVIS_SYSTEM_PROMPT,
        f"Rolle: {assistant_name} für {creator_name}.",
        salutation_instruction(creator_name, user_salutation),
        humor_instruction(style.humor_level) + " Bei kritischen Bestätigungsfragen (löschen, senden, "
        "Termin anlegen, Zahlungen o. Ä.) darf der Humor höchstens ein kurzer Nebensatz sein - die "
        "eigentliche Ja/Nein-Frage muss glasklar und unmissverständlich bleiben.",
        honesty_instruction(style.honesty_level),
        f"Stil: Persönlichkeit={style.name}, Ton={style.tone}, Länge={style.answer_length}, "
        f"Humor-Level={style.humor_level}/100, Ehrlichkeits-Level={style.honesty_level}/100.",
        memory_usage_instruction(memory_summary),
    ]
    self_instruction = self_model_instruction(self_model)
    if self_instruction:
        parts.append(self_instruction)
    if mode_instruction:
        parts.append(mode_instruction)
    return "\n".join(parts).strip()


def salutation_instruction(creator_name: str, user_salutation: str) -> str:
    # Frueher "nicht nur zu Beginn, sondern durchgehend... lass sie nie
    # unbemerkt weg" - zusammen mit dem alten "professionell"-Grundton wirkte
    # das erzwungen/steif statt wie ein vertrauter Begleiter (Leons
    # Rueckmeldung, 2026-08-12). Jetzt natuerlich eingestreut statt in jedem
    # Satz erzwungen. Zusaetzlich: niemals den Vornamen verwenden, ausser
    # {creator_name} sagt das ausdruecklich - Leons explizite Vorgabe.
    normalized = str(user_salutation or "sir").strip().lower()
    name_restriction = (
        f"Sprich {creator_name} niemals mit seinem Vornamen an, nur mit der Anrede oben - "
        f"es sei denn, {creator_name} sagt ausdrücklich, dass du seinen Namen benutzen sollst. "
        f"NICHT: \"Danke der Nachfrage, {creator_name}!\" SONDERN: \"Danke der Nachfrage, Sir.\" "
        f"Der Vorname {creator_name} darf in deiner gesprochenen Antwort gar nicht vorkommen, "
        "außer als Reaktion auf eine ausdrückliche Erlaubnis."
    )
    # Live entdeckter Bug: Antworten wechselten unangekuendigt zwischen "du" und
    # "Sie" (teils sogar innerhalb derselben Testreihe) - bricht die Illusion
    # eines durchgaengigen Charakters. Bei "Sir"/"Madam" durchgehend "Sie", nach
    # dem Vorbild von JARVIS aus Iron Man (hoeflich-professionell, nie
    # kumpelhaft-locker). Konkretes NICHT/SONDERN-Beispiel, weil die reine
    # abstrakte Anweisung vom kleineren lokalen Modell zuvor unzuverlaessig
    # befolgt wurde (gleiches Muster wie bei name_restriction oben). Siehe
    # docs/current-system-assessment.md, Abschnitt 41.
    formal_register = (
        f"Sprich {creator_name} in JEDEM Satz konsequent mit \"Sie\" an, niemals mit \"du\" - "
        "wie ein hochprofessioneller, warmer persönlicher Assistent nach dem Vorbild von JARVIS "
        "aus Iron Man. NICHT: \"Das kannst du gern selbst prüfen.\" SONDERN: \"Das können Sie "
        "gern selbst prüfen.\" Auch Verb- und Pronomenformen anpassen (\"haben Sie\" statt "
        "\"hast du\", \"Ihnen\" statt \"dir\")."
    )
    if normalized == "madam":
        return (
            f"Verwende die Anrede Madam für {creator_name} natürlich eingestreut, dort wo es sich "
            "wirklich passend anfühlt (z. B. am Anfang oder an einer markanten Stelle) - nicht "
            f"zwanghaft in jedem Satz. {name_restriction} {formal_register}"
        )
    if normalized == "none":
        return (
            f"Sprich {creator_name} direkt mit Namen oder neutral an, ohne Sir oder Madam - "
            "konsequent in der ganzen Antwort, nicht nur am Anfang. Duze durchgehend, wechsle "
            "nicht zwischendurch zu \"Sie\"."
        )
    return (
        f"Verwende die Anrede Sir für {creator_name} natürlich eingestreut, dort wo es sich "
        "wirklich passend anfühlt (z. B. am Anfang oder an einer markanten Stelle) - nicht "
        f"zwanghaft in jedem Satz. {name_restriction} {formal_register}"
    )
