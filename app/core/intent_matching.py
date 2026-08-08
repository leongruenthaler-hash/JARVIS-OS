from __future__ import annotations

"""Gemeinsame Fuzzy-Matching-Bausteine fuer die Absichtserkennung (Domain-Erkennung
in jarvis.py, fast_intent_router.py) und fuer die bereits bestehende Kontaktsuche
(contacts_client.py). Zentralisiert an einer Stelle, weil dieselbe
Edit-Distanz-Logik sonst ein drittes Mal kopiert wuerde.

Siehe plans/2026-08-08-jarvis-intelligenz-verbessern.md fuer den vollen Kontext:
DOMAIN_TERMS/has_domain() in jarvis.py haben bisher nur exakte Teilstring-Treffer
akzeptiert - ein einziger Tippfehler oder ein Spracherkennungs-Fehler hat gereicht,
um eine ganze Faehigkeit (Mail/Kalender/...) unerreichbar zu machen.
"""

_UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
}


def levenshtein_distance(left: str, right: str) -> int:
    """Editierdistanz zwischen zwei Strings (Einfuegen/Loeschen/Ersetzen je 1).
    1:1 aus contacts_client.py verschoben, wo diese Technik fuer die
    Tippfehler-tolerante Kontaktnamen-Suche bereits bewaehrt ist."""
    if left == right:
        return 0

    if not left:
        return len(right)

    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current

    return previous[-1]


def normalize_umlauts(text: str) -> str:
    """Normalisiert deutsche Umlaute/scharfes-S auf ihre ae/oe/ue/ss-Schreibweise,
    damit Wortlisten (DOMAIN_TERMS etc.) nur noch eine Schreibweise pflegen
    muessen, statt jede Umlaut-Variante einzeln aufzufuehren. Wird NACH dem
    Kleinschreiben angewendet, arbeitet also nur mit Kleinbuchstaben-Umlauten."""
    result = text
    for umlaut, replacement in _UMLAUT_MAP.items():
        result = result.replace(umlaut, replacement)
    return result


# Sehr haeufige, kurze deutsche Fuell-/Funktionswoerter, die NIE per Fuzzy-Vergleich
# gegen ein Domaenen-Stichwort matchen duerfen, egal wie klein die Editierdistanz
# ist - sonst gibt es Falsch-Positive wie "spiel MAL musik" -> "mal" hat Distanz 1
# zu "mail" und wuerde sonst faelschlich als Mail-Anfrage erkannt. Exakte Treffer
# (Wort ist selbst ein Domaenen-Stichwort) sind davon nicht betroffen - die laufen
# weiterhin ueber has_domain_fuzzy()s exakten Teilstring-Pfad.
_FUZZY_STOPWORDS = frozenset(
    {
        "mal", "man", "was", "wie", "wer", "wen", "wem", "wo", "der", "die", "das",
        "den", "dem", "des", "ein", "und", "oder", "aber", "doch", "noch", "nur",
        "auch", "sehr", "gut", "neu", "alt", "hat", "bin", "bist", "ist", "sind",
        "war", "wir", "ihr", "sie", "für", "fuer", "von", "vor", "bei", "aus",
        "auf", "mit", "zum", "zur", "ans", "ins", "am", "im", "um", "an", "in",
        "zu", "so", "ja", "nein", "ich", "du", "es", "mir", "dir", "mich", "dich",
    }
)


def _fuzzy_max_distance(word: str, max_distance: int) -> int:
    # Kurze/mittellange Woerter duerfen nicht dieselbe absolute Toleranz wie lange
    # Woerter bekommen, sonst werden z.B. "mail" und "mall" (Distanz 1) faelschlich
    # gleichgesetzt, oder "wetter"/"kinder"/"bruder" faelschlich zu "zettel"/"bilder"
    # (alle Distanz 2 bei 6 Buchstaben) - beim Testen dieser Aenderung konkret so
    # aufgefallen. Distanz 2 nur noch bei wirklich langen Woertern erlauben.
    if len(word) <= 7:
        return min(max_distance, 1)
    return max_distance


def fuzzy_word_match(word: str, candidates: tuple[str, ...], *, max_distance: int = 2) -> bool:
    """Vergleicht ein einzelnes, bereits normalisiertes Wort gegen eine Liste von
    Kandidatenwoertern per Editierdistanz. Die tatsaechlich verwendete Schwelle
    haengt von der Wortlaenge ab (siehe _fuzzy_max_distance) - kurze Woerter
    bekommen absichtlich weniger Toleranz, um Falsch-Positive zu vermeiden.
    Haeufige kurze Fuellwoerter (siehe _FUZZY_STOPWORDS) werden nie fuzzy
    gematcht, nur noch exakt."""
    if not word:
        return False
    if word in _FUZZY_STOPWORDS:
        return word in candidates
    threshold = _fuzzy_max_distance(word, max_distance)
    for candidate in candidates:
        if not candidate:
            continue
        if word == candidate:
            return True
        if candidate in _FUZZY_STOPWORDS:
            continue
        if levenshtein_distance(word, candidate) <= threshold:
            return True
    return False


def has_domain_fuzzy(text: str, terms: tuple[str, ...], *, max_distance: int = 2) -> bool:
    """Prueft, ob eine (bereits normalisierte) Anfrage zu einer Domaene passt -
    kombiniert einen schnellen exakten Teilstring-Check (deckt Mehrwort-Begriffe
    wie "e mail" zuverlaessig ab) mit einem Wort-fuer-Wort-Fuzzy-Vergleich (faengt
    Tippfehler/Verhaspler/Spracherkennungs-Fehler bei Einzelwoertern ab)."""
    if not text:
        return False

    # Schneller Pfad: exakter Teilstring-Treffer, wie bisher - deckt Mehrwort-
    # Begriffe ab, bei denen ein Wort-fuer-Wort-Vergleich nichts finden wuerde.
    if any(term in text for term in terms):
        return True

    words = text.split()
    if not words:
        return False

    # NUR Terme, die selbst schon ein einzelnes Wort sind, werden fuzzy verglichen.
    # Mehrwort-Begriffe (z.B. "bilder von", "erinnere mich", "was siehst du gerade")
    # NICHT in ihre Einzelwoerter zerlegen und die zum Fuzzy-Vergleich zulassen -
    # das wuerde generische Fuellwoerter aus der Phrase (z.B. "von", "mich", "du")
    # zu eigenstaendigen Fuzzy-Kandidaten machen und Falsch-Positive erzeugen
    # (z.B. "von" -> Distanz 0 zu sich selbst, weil "bilder von" gesplittet wurde).
    # Mehrwort-Begriffe werden ausschliesslich ueber den exakten Teilstring-Pfad
    # oben abgedeckt.
    single_word_terms = tuple(term for term in terms if term and " " not in term)

    return any(fuzzy_word_match(word, single_word_terms, max_distance=max_distance) for word in words)
