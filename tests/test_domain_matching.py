"""Tests for the robuster Absichtserkennung
(plans/2026-08-08-jarvis-intelligenz-verbessern.md): Tippfehler-/Verhaspel-
Toleranz bei der Faehigkeits-Erkennung (Stufe 1, app/core/intent_matching.py +
app/jarvis.py::has_domain) und der LLM-Klassifikations-Rueckfrage als
Sicherheitsnetz (Stufe 2, app/jarvis.py).
"""

from unittest.mock import patch

import pytest

from core.intent_matching import (
    fuzzy_word_match,
    has_domain_fuzzy,
    levenshtein_distance,
    normalize_umlauts,
)
from memory import Memory
import jarvis


# --- Stufe 1: core/intent_matching.py Bausteine ----------------------------


def test_normalize_umlauts_all_four_pairs():
    assert normalize_umlauts("grösse") == "groesse"
    assert normalize_umlauts("spät") == "spaet"
    assert normalize_umlauts("müde") == "muede"
    assert normalize_umlauts("schließen") == "schliessen"


def test_fuzzy_word_match_accepts_typo_but_rejects_unrelated_word():
    assert fuzzy_word_match("meil", ("mail",), max_distance=2) is True
    assert fuzzy_word_match("musik", ("mail",), max_distance=2) is False


def test_fuzzy_word_match_ignores_common_stopwords():
    # "mal" hat Editierdistanz 1 zu "mail" - darf trotzdem NIE als Mail-Anfrage
    # durchgehen, weil "mal" ein extrem haeufiges deutsches Fuellwort ist
    # (z.B. "spiel mal Musik").
    assert fuzzy_word_match("mal", ("mail",), max_distance=2) is False


def test_has_domain_fuzzy_multiword_terms_do_not_leak_stopword_fragments():
    # "bilder von" ist ein Mehrwort-Begriff - "von" darf daraus NICHT als
    # eigenstaendiger Fuzzy-Kandidat entstehen (siehe intent_matching.py-
    # Kommentar zu has_domain_fuzzy).
    assert has_domain_fuzzy("von", ("bilder von",)) is False
    assert has_domain_fuzzy("zeig mir bilder von rom", ("bilder von",)) is True


def test_has_domain_fuzzy_single_word_term_requires_word_boundary():
    assert has_domain_fuzzy("was siehst du auf meinem bildschirm", ("bild",)) is False
    assert has_domain_fuzzy("zeig mir das bild", ("bild",)) is True


def test_has_domain_fuzzy_multiword_term_still_uses_plain_substring():
    assert has_domain_fuzzy("kannst du das e mail machen", ("e mail",)) is True


def test_levenshtein_distance_basic():
    assert levenshtein_distance("mail", "mail") == 0
    assert levenshtein_distance("mail", "meil") == 1
    assert levenshtein_distance("", "mail") == 4


# --- Stufe 1: app/jarvis.py::has_domain Integration -------------------------


def test_has_domain_exact_match_still_works():
    assert jarvis.has_domain("öffne mail", "mail") is True
    assert jarvis.has_domain("ruf peter an", "contacts") is True


def test_has_domain_tolerates_typo():
    assert jarvis.has_domain("oeffne meil", "mail") is True


def test_has_domain_tolerates_missing_letter():
    assert jarvis.has_domain("zeig mir den klender", "calendar") is True


def test_has_domain_rejects_unrelated_text():
    assert jarvis.has_domain("wie ist das wetter heute", "mail") is False


def test_has_domain_does_not_false_positive_on_common_filler_word():
    # Regressionsfall aus diesem Gespraech: "mal" ist Distanz 1 zu "mail".
    assert jarvis.has_domain("spiel mal musik", "mail") is False
    assert jarvis.has_domain("spiel mal musik", "music") is True


def test_has_domain_does_not_false_positive_on_dabei_vs_datei():
    # Live-Bug 2026-09-02: "dabei" (sehr haeufiges Fuellwort) hat Editierdistanz 1
    # zu "datei" und loeste faelschlich die files-Domaene aus - der komplette
    # Rohsatz landete dann als "nichts Passendes zu ..." in der Desktop-Dateisuche.
    text = (
        "nein dabei brauche ich so derzeit keine hilfe ich muss halt nur die "
        "arbeitsvertraege und noch die kundenvertraege und so weiter alles "
        "ziemlich passend machen"
    )
    assert jarvis.has_domain(text, "files") is False


def test_has_domain_existing_multiword_phrases_still_work():
    assert jarvis.has_domain("erinnere mich an den zahnarzt", "calendar") is True
    assert jarvis.has_domain("zeig mir bilder von rom", "photos") is True


def test_has_domain_single_word_term_no_longer_matches_as_substring_of_longer_word():
    # Regressionsfall aus dem Testlauf auf dem echten Mac: "bild" ist ein
    # Domaenen-Stichwort fuer "photos" und war zugleich ein Teilstring von
    # "bildschirm" - jede Bildschirm-Anfrage wurde dadurch faelschlich als
    # Fotos-Anfrage erkannt (hat sogar echte Fotos in einen Ordner kopiert statt
    # einen Screenshot zu machen). Einzelwort-Begriffe zaehlen jetzt nur noch als
    # eigenstaendiges Wort.
    assert jarvis.has_domain("was siehst du auf meinem bildschirm", "photos") is False
    assert jarvis.has_domain("was siehst du auf meinem bildschirm", "screen") is True
    assert jarvis.has_domain("mach einen screenshot von meinem bildschirm", "photos") is False


def test_has_domain_single_word_term_still_matches_as_standalone_word():
    assert jarvis.has_domain("zeig mir das bild", "photos") is True
    assert jarvis.has_domain("zeig mir meine bilder", "photos") is True


def test_has_reservation_domain_tolerates_typo_and_natural_phrasing():
    # Live beobachtet 2026-08-27: DOMAIN_TERMS["reservation"] enthielt nur enge
    # Mehrwort-Phrasen (z.B. "reserviere einen tisch") und ein einzelnes
    # Fuzzy-Wort ("reservierung") - eine ganz natuerliche Formulierung wie
    # "reserviere doch bitte einen tisch fuer 2 Personen" (passt zu KEINER der
    # hartcodierten Phrasen wortwoertlich) UND ihr Tippfehler "resarviere"
    # matchten dadurch ueberhaupt nicht; Jarvis wich auf eine generische
    # "Meinten Sie Kalender/Erinnerung?"-Rueckfrage aus statt die Reservierung
    # zu starten.
    #
    # Ein bare Einzelwort-Fuzzy-Muster fuer "reservieren" in DOMAIN_TERMS
    # selbst haette aber auch "ein Hotel reservieren" (falsche Domaene) und
    # "das Essen SERVIEREN" (Distanz 2, unabhaengiges Wort) ausgeloest -
    # deshalb stattdessen has_reservation_domain(): has_domain(text,
    # "reservation") ERWEITERT um eine UND-Bedingung (Reservierungs-Verb UND
    # Tisch-/Restaurant-Signal im selben Satz), siehe
    # _looks_like_table_reservation(). Ein Denylist einzelner Verben
    # ("servieren" ausschliessen) skalierte dabei nicht - "referieren" haette
    # denselben Ueberlapp gehabt und war nicht ausgeschlossen. Die finale
    # Loesung vergleicht stattdessen nur den distinktiven Wortstamm "reservi"
    # als PRAEFIX statt das ganze Wort (siehe _looks_like_reservation_verb(),
    # Codex-Review 2026-08-27, mehrere Folgerunden).
    assert jarvis.has_reservation_domain("Jarvis resarviere doch bitte einen tisch für 2 Personen für mich") is True
    assert jarvis.has_reservation_domain("reserviere doch bitte einen tisch für 2 Personen") is True
    assert jarvis.has_reservation_domain("reserviere doch bitte im Restaurant für 2 Personen") is True
    # Pluralformen ("Tische"/"Restaurants") muessen genauso zaehlen wie der
    # Singular - eine reine Exakt-Singular-Liste haette diese ganz normale
    # Formulierung verpasst (Codex-Review 2026-08-27, Folgerunde).
    assert jarvis.has_reservation_domain("reserviere bitte zwei Tische für morgen") is True
    assert jarvis.has_reservation_domain("reserviere bitte in einem der Restaurants für morgen") is True
    # Reservierungs-Verb OHNE Tisch-/Restaurant-Signal darf ueber den NEUEN
    # UND-Pfad (_looks_like_table_reservation()) nicht matchen.
    assert jarvis.has_reservation_domain("ich habe schon reserviert") is False
    # "ich moechte ein Hotel reservieren" matcht trotzdem noch (True) - aber
    # ueber einen VORBESTEHENDEN, unabhaengigen Pfad: has_domain_fuzzy()
    # vergleicht "reservieren" (Verb) mit dem bereits laenger existierenden
    # Einzelwort-Term "reservierung" (Distanz 2, exakt dieselbe Toleranz).
    # Dieser Ueberlapp bestand schon VOR dieser Aenderung (nicht Teil des
    # heute neu ergaenzten Wortstamm-Pfads, den dieser Test prueft) und wird
    # hier bewusst nicht mitgeloest - siehe
    # test_has_domain_pre_existing_reservierung_overlap_with_hotel_booking.
    assert jarvis.has_reservation_domain("ich möchte ein Hotel reservieren") is True
    # "servieren" hat Editierdistanz 2 zu "reservieren" auf Wortebene, aber
    # sein Wortstamm ("servier") liegt weit vom distinktiven "reservi"-Praefix
    # entfernt - darf trotz Tisch-Erwaehnung in der Naehe nicht als
    # Reservierungs-Verb durchgehen.
    assert jarvis.has_reservation_domain("bitte das Essen am Tisch servieren") is False
    # "referieren" ist genauso weit von "reservieren" entfernt wie
    # "servieren" (Editierdistanz 2 auf Wortebene) - ein reiner
    # Ganzwort-Denylist haette das nicht abgedeckt, der Wortstamm-Vergleich
    # schon (Codex-Review 2026-08-27, Folgerunde).
    assert jarvis.has_reservation_domain("ich soll über das Restaurant referieren") is False
    # "Reservat"/"Reservoir" (voellig unabhaengige Substantive) haben mit dem
    # urspruenglich 7 Zeichen kurzen Praefix-Fenster ("reservi") ebenfalls nur
    # Distanz 1 gehabt - erst das laengere, 9 Zeichen umfassende Fenster
    # ("reservier") unterscheidet sie zuverlaessig vom Reservierungs-Verb
    # (Codex-Review 2026-08-27, Folgerunde).
    assert jarvis.has_reservation_domain("Restaurant im Reservat") is False
    assert jarvis.has_reservation_domain("Reservoir beim Restaurant") is False
    # Darf keine voellig unabhaengigen Anfragen faelschlich als Reservierung
    # erkennen.
    assert jarvis.has_reservation_domain("was soll ich heute essen") is False
    assert jarvis.has_reservation_domain("trag das bitte in meinen kalender ein") is False


def test_looks_like_table_reservation_allows_detailed_date_time_phrasing():
    # Ein frueherer Versuch begrenzte den Wortabstand zwischen Verb und
    # Tisch-/Restaurant-Signal (max. 6 Woerter), um ein konstruiertes
    # Beispiel auszuschliessen, in dem das Tisch-/Restaurant-Wort semantisch
    # nicht das Objekt des Verbs ist ("Im Restaurant besprechen wir, wie wir
    # ein Hotel reservieren", Wortabstand 7). Das brach aber ganz normale,
    # detailreiche Anfragen wie diese hier (Wortabstand 9) - es gibt keinen
    # Schwellwert, der beide Faelle sauber trennt. Die haeufige, echte
    # Formulierung wiegt schwerer als der seltene Konstrukt-Fall, deshalb
    # bewusst KEIN Wortabstands-Limit mehr (Codex-Review 2026-08-27, mehrere
    # Folgerunden) - siehe Docstring von _looks_like_table_reservation() fuer
    # die vollstaendige Abwaegung.
    assert jarvis._looks_like_table_reservation(
        "Reserviere bitte für morgen Abend um 19 Uhr einen Tisch"
    ) is True


def test_looks_like_table_reservation_does_not_distinguish_past_from_command():
    # Dokumentiert eine bewusst NICHT geloeste Einschraenkung (siehe
    # Docstring von _looks_like_table_reservation()): eine bereits
    # abgeschlossene Aussage in Vergangenheitsform matcht genauso wie eine
    # Aufforderung, weil die Funktion nur Stichwoerter/Wortabstand prueft,
    # keine Tempus-/Modus-Analyse. Folgenlos: fuehrt hoechstens zu einer
    # unnoetigen, leicht ablehnbaren Rueckfrage - reserviert nie etwas
    # endgueltig (Codex-Review 2026-08-27, Folgerunde - nach mehreren
    # Runden auf genau diesem Pfad bewusst als Grenze akzeptiert statt
    # weiter verfeinert).
    assert jarvis._looks_like_table_reservation("Ich habe den Tisch schon reserviert") is True


def test_has_reservation_domain_strips_punctuation_from_mid_sentence_words():
    # Regression: normalize_text() entfernt Satzzeichen nur an den Raendern
    # des GESAMTEN Texts, nicht pro Wort - ein Tisch-/Restaurant-Signal MITTEN
    # im Satz vor einem Punkt (z.B. "Resarviere bitte einen Tisch. Fuer
    # morgen.") blieb dadurch als "tisch." stehen und matchte den exakten
    # Woertervergleich in _looks_like_table_reservation() nicht mehr - genau
    # der freie-Wortstellung-/Tippfehler-Fall, fuer den dieser Pfad ueberhaupt
    # gebaut wurde (Codex-Review 2026-08-27, Folgerunde).
    assert jarvis.has_reservation_domain("Resarviere bitte einen Tisch. Für morgen.") is True


def test_looks_like_table_reservation_does_not_cross_sentence_boundaries():
    # Regression: der vorherige Fix (Satzzeichen pro Wort entfernen, siehe
    # test_has_reservation_domain_strips_punctuation_from_mid_sentence_words)
    # entfernte dabei versehentlich auch die SatzENDE-Zeichen selbst, bevor
    # der Wortabstand gemessen wurde - "Wir sitzen im Restaurant. Morgen
    # reserviere ich ein Hotel" (zwei voellig unabhaengige Saetze) landete
    # dadurch bei Wortabstand 2 und matchte faelschlich (Codex-Review
    # 2026-08-27, Folgerunde). Fix: Satzgrenzen bleiben erhalten, die
    # Wortabstands-Pruefung laeuft separat PRO SATZ.
    assert jarvis._looks_like_table_reservation(
        "Wir sitzen im Restaurant. Morgen reserviere ich ein Hotel"
    ) is False


def test_looks_like_table_reservation_preserves_german_time_period():
    # Regression: der Satzgrenzen-Split (siehe
    # test_looks_like_table_reservation_does_not_cross_sentence_boundaries)
    # behandelte JEDEN Punkt als Satzende - deutsche Uhrzeit-Notation
    # ("19.30") nutzt den Punkt aber ganz alltaeglich, nicht nur seltene
    # Abkuerzungen. "Reserviere um 19.30 einen Tisch" trennte das Verb
    # dadurch faelschlich vom Tisch-Wort in zwei "Saetze" (Codex-Review
    # 2026-08-27, Folgerunde). Der INNERE Punkt zwischen zwei kurzen
    # Zifferngruppen wird deshalb vor dem Satz-Split maskiert.
    assert jarvis._looks_like_table_reservation("Reserviere um 19.30 einen Tisch") is True


def test_looks_like_table_reservation_trailing_date_period_stays_a_sentence_boundary():
    # Bewusst akzeptierte Einschraenkung (siehe Docstring von
    # _looks_like_table_reservation()): ein AEUSSERER Punkt nach einer
    # Datumsangabe ("28.08.", deutsches Tagesdatum-Format) bleibt ein
    # potenzielles Satzende, auch wenn er tatsaechlich Teil der
    # Datumsnotation war und der Satz eigentlich weitergeht - er ist ohne
    # echtes Satzverstaendnis nicht zuverlaessig von einem GENUINEN
    # Satzende zu unterscheiden. Ein frueherer Versuch maskierte diesen
    # aeusseren Punkt ebenfalls und fuehrte dadurch die Restaurant-/
    # Hotel-Verwechslung von test_looks_like_table_reservation_does_not_
    # cross_sentence_boundaries wieder ein ("Wir essen im Restaurant am
    # 28.08. Morgen reserviere ich ein Hotel" waere sonst wieder ein
    # einziger Satz gewesen) (Codex-Review 2026-08-27, Folgerunde).
    assert jarvis._looks_like_table_reservation("Reserviere am 28.08. einen Tisch") is False
    assert jarvis._looks_like_table_reservation(
        "Wir essen im Restaurant am 28.08. Morgen reserviere ich ein Hotel"
    ) is False


def test_has_domain_pre_existing_reservierung_overlap_with_hotel_booking():
    # Dokumentiert einen bereits VOR dem heutigen Fuzzy-Fix bestehenden
    # Nebeneffekt, nicht dessen Ursache: DOMAIN_TERMS["reservation"] enthielt
    # "reservierung" schon vorher als einzelnes Fuzzy-Wort - "reservieren"
    # (Verb) hat Editierdistanz 2 dazu, exakt dieselbe Toleranz wie beim
    # Tippfehler "resarviere". Eine Hotel-/Flugbuchung wird dadurch weiterhin
    # (schon immer) faelschlich als Tischreservierungs-Domaene erkannt - bewusst
    # NICHT im Rahmen dieser Aenderung geloest (Aufwand/Nutzen, siehe
    # Session-Notizen 2026-08-27), da es unabhaengig vom heute neu ergaenzten
    # UND-basierten Pfad besteht.
    assert jarvis.has_domain("ich möchte ein Hotel reservieren", "reservation") is True


# --- Stufe 2: LLM-Klassifikation als Sicherheitsnetz ------------------------


class _FakeLLM:
    """Minimaler Ersatz fuer LLMClient.ask() - kein echter Modellaufruf."""

    def __init__(self, response: str):
        self._response = response
        self.last_messages = None

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, raw_system_prompt=False, **kwargs):
        self.last_messages = messages
        return self._response


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def test_classify_domain_via_llm_parses_single_label():
    llm = _FakeLLM("mail")
    assert jarvis.classify_domain_via_llm(llm, "irgendwas unklares") == ["mail"]


def test_classify_domain_via_llm_parses_two_labels():
    llm = _FakeLLM("mail, calendar")
    assert jarvis.classify_domain_via_llm(llm, "irgendwas unklares") == ["mail", "calendar"]


def test_classify_domain_via_llm_none_label_returns_empty():
    llm = _FakeLLM("keine")
    assert jarvis.classify_domain_via_llm(llm, "wie geht es dir") == []


def test_classify_domain_via_llm_prompt_contains_self_statement_example():
    # Regressionstest fuer den Live-Bug: eine reine Selbstauskunft ("Ich lebe seit
    # 18 Jahren in Amberg") wurde faelschlich als mail/calendar klassifiziert. Der
    # Prompt muss ein explizites Gegenbeispiel enthalten (gleiche Haertungs-Technik
    # wie beim News-Baustein).
    llm = _FakeLLM("keine")
    jarvis.classify_domain_via_llm(llm, "Ich lebe schon seit 18 Jahren in Amberg in Deutschland")
    system_content = llm.last_messages[0]["content"]
    assert "Amberg" in system_content
    assert "keine" in system_content


def test_classify_domain_via_llm_swallows_exceptions():
    class _BrokenLLM:
        def ask(self, *args, **kwargs):
            raise RuntimeError("Ollama nicht erreichbar")

    assert jarvis.classify_domain_via_llm(_BrokenLLM(), "irgendwas") == []


def test_maybe_ask_domain_clarification_stores_pending_state_and_asks(memory):
    # Seit plans/2026-08-16-jarvis-stufe2-klassifikation-direkt-beantworten.md
    # versucht eine eindeutige Ein-Domaenen-Klassifikation zuerst eine direkte
    # Antwort (siehe test_stage2_direct_dispatch.py) - dieser Test isoliert
    # bewusst weiterhin nur das reine Rueckfrage-Verhalten selbst, indem er das
    # neue Verhalten explizit abschaltet.
    llm = _FakeLLM("mail")
    question = "kannst du das für mich checken"

    answer = jarvis.maybe_ask_domain_clarification(
        llm, memory, question, config={"stage2_direct_dispatch_enabled": False}
    )

    assert answer is not None
    assert "Mail" in answer or "mail" in answer.lower()

    settings = memory.get("settings") or {}
    pending = settings.get("pending_domain_clarification")
    assert isinstance(pending, dict)
    assert pending["domains"] == ["mail"]
    assert pending["question"] == question


def test_maybe_ask_domain_clarification_returns_none_when_llm_finds_nothing(memory):
    llm = _FakeLLM("keine")
    assert jarvis.maybe_ask_domain_clarification(llm, memory, "wie geht's dir") is None
    settings = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings


def test_pending_domain_clarification_flow_cancel(memory):
    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": ["mail"], "question": "check das mal"}
    memory.set("settings", settings)

    answer = jarvis.handle_pending_domain_clarification_flow(memory, "nein danke")

    assert answer is not None
    settings_after = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings_after


def test_pending_domain_clarification_flow_unrelated_reply_falls_through(memory):
    settings = memory.get("settings") or {}
    settings["pending_domain_clarification"] = {"domains": ["mail", "calendar"], "question": "check das mal"}
    memory.set("settings", settings)

    # Weder Bestaetigung noch erkennbare Domaene in der Antwort - Flow gibt None
    # zurueck (normal weiterverarbeiten), raet aber nicht auf gut Glueck.
    answer = jarvis.handle_pending_domain_clarification_flow(memory, "wie ist das wetter heute")

    assert answer is None
    settings_after = memory.get("settings") or {}
    assert "pending_domain_clarification" not in settings_after


def test_pending_domain_clarification_flow_has_no_pending_state_returns_none(memory):
    assert jarvis.handle_pending_domain_clarification_flow(memory, "ja") is None


def test_record_pattern_event_if_matched_counts_reservation_via_the_wider_matcher():
    # Regression: record_pattern_event_if_matched() prueft jede Domaene ueber
    # has_domain() - fuer "reservation" gibt es aber einen zusaetzlichen,
    # breiteren Erkennungspfad (has_reservation_domain(), siehe
    # _looks_like_table_reservation()). Eine nur darueber erkannte Anfrage wie
    # "reserviere doch bitte einen tisch fuer 2 Personen" haette die
    # Nutzungsmuster-Zaehlung deshalb verpasst, obwohl handle_reservation_command()
    # dafuer tatsaechlich anlief - die Funktion verspricht aber, JEDE erkannte
    # Faehigkeit zu zaehlen (Codex-Review 2026-08-27, Folgerunde).
    with patch.object(jarvis, "record_pattern_event") as record:
        jarvis.record_pattern_event_if_matched("reserviere doch bitte einen tisch für 2 Personen")
    assert any(call.args == ("reservation",) for call in record.call_args_list)
