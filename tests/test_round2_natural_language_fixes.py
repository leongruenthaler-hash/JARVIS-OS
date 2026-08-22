"""Tests fuer die in der Runde-2-Faehigkeits-Simulation (2026-08-13, doppelt so
umfangreich und mit deutlich natuerlicherer Sprache als Runde 1) live
gefundenen Bugs. Zwei davon fuehrten waehrend des Tests zu echten
Seiteneffekten auf Leons echten Daten (ein "abbrechen" wurde vom
Fuzzy-Match-Bug abgefangen und lehnte 4 echte Kalender-Vorschlaege ab; eine
harmlose Frage wurde woertlich an die echte Einkaufszettel-Notiz angehaengt) -
beide wurden noch in derselben Sitzung wiederhergestellt. Siehe
docs/current-system-assessment.md, Abschnitt 42."""

import time
from unittest.mock import MagicMock, patch

import jarvis


# --- Fix 1+6: Fuzzy-Match-Bug in pending_action_matches_text() ---------------


def test_fuzzy_match_does_not_collide_on_substrings_inside_longer_words():
    # "wach" ist Teil von "wachsen" in einem echten Mail-Betreff - das darf
    # NICHT als Treffer zaehlen. Genau dieser Zufallstreffer sorgte live dafuer,
    # dass eine harmlose Begruessung ("bist du wach") als Reaktion auf eine
    # offene Kalender-Bestaetigung fehlinterpretiert wurde.
    settings = {
        "pending_mail_calendar_confirmation": {
            "action_keys": ["1|reminder|2026-01-01|Erinnerung: Warum unsere Kunden gerade so schnell wachsen"],
            "set_at": time.time(),
        }
    }
    assert jarvis.pending_action_matches_text(settings, jarvis.normalize_text("Hey Jarvis, bist du wach")) is False


def test_fuzzy_match_still_catches_genuine_whole_word_overlap():
    settings = {
        "pending_mail_calendar_confirmation": {
            "action_keys": ["1|reminder|2026-01-01|Erinnerung: Unterschriftenanforderung von Tom Weigl"],
            "set_at": time.time(),
        }
    }
    assert jarvis.pending_action_matches_text(settings, jarvis.normalize_text("was war das nochmal mit weigl")) is True


def test_whole_words_helper_ignores_punctuation_and_brackets():
    assert jarvis._whole_words("['abgeschlossen', \"Sparplan-Bearbeitung\"]") == {"abgeschlossen", "sparplan", "bearbeitung"}


# --- Fix 2+3: QUESTION_SHAPE_PREFIXES deckt jetzt auch Ja/Nein-Fragen ab -----


def test_pending_note_flow_guards_against_yes_no_question_not_just_w_questions():
    # Das ist der Vorfall aus der Runde-2-Simulation: diese Frage wurde
    # woertlich an Leons echte Einkaufszettel-Notiz angehaengt, weil der
    # bisherige Schutz nur W-Fragen (was/wie/wo/...) kannte. Seit dem
    # domaenen-basierten Bail-out (app/jarvis.py:3231-3235, 2026-08-20) greift
    # fuer "Posteingang" (mail-Domaene) bereits der breitere Schutz: die Notiz
    # wird verworfen, None zurueckgegeben, die echte mail-Domaene antwortet -
    # keine "eigenen Frage"-Ausweichantwort mehr noetig.
    memory = MagicMock()
    memory.get.return_value = {
        "pending_note": {"state": "awaiting_body", "title": "Einkaufszettel", "append": True}
    }
    answer = jarvis.handle_pending_note_flow(memory, "Hab ich heute irgendwas Wichtiges bekommen im Posteingang?")

    assert answer is None
    memory.set.assert_called_once()
    saved_settings = memory.set.call_args[0][1]
    assert "pending_note" not in saved_settings


def test_pending_action_flow_lets_yes_no_question_through_instead_of_swallowing():
    memory = MagicMock()
    memory.get.return_value = {
        "pending_cleanup_confirmation": {
            "items": [{"path": "/tmp/old.log", "size": 1}],
            "set_at": time.time(),
        }
    }
    answer = jarvis.handle_pending_action_flow(memory, "Ist das schon lange her?")

    assert answer is None


def test_question_shape_prefixes_shared_between_both_guards():
    # Beide Stellen nutzen jetzt dieselbe Liste - Regressionsschutz dagegen,
    # dass sie wieder auseinanderlaufen (genau das war die urspruengliche
    # Ursache des Vorfalls).
    assert "hab ich" in jarvis.QUESTION_SHAPE_PREFIXES
    assert "was " in jarvis.QUESTION_SHAPE_PREFIXES


# --- Fix 4: Fuellwort-Toleranz -----------------------------------------------


def test_notes_read_trigger_tolerates_inserted_filler_word():
    assert jarvis._looks_like_notes_read_request("Was steht eigentlich auf meinem Einkaufszettel?") is True


def test_strip_filler_words_removes_known_fillers_only():
    assert jarvis.strip_filler_words("wann ist eigentlich mein nächster termin") == "wann ist mein nächster termin"
    assert jarvis.strip_filler_words("das ist wichtig") == "das ist wichtig"


# --- Fix 5: Kalender-Erkennung fuer Alltagssprache ---------------------------


def test_next_termin_query_with_filler_word_answers_instead_of_asking_for_datetime():
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}):
        answer = jarvis.handle_calendar_command("Wann ist eigentlich mein nächster Termin?")

    assert answer is not None
    assert "Datum oder Uhrzeit" not in answer


def test_weekend_question_recognized_as_calendar_query():
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}) as fake_list:
        answer = jarvis.handle_calendar_command("Ist am Wochenende was bei mir eingetragen?")

    fake_list.assert_called_once()
    assert answer is not None
    assert "Datum oder Uhrzeit" not in answer


def test_colloquial_this_week_question_recognized_as_calendar_query():
    assert jarvis.looks_like_calendar_query("Hab ich diese Woche noch was Wichtiges vor mir?") is True


def test_explicit_create_request_still_goes_to_create_flow():
    # Regressionsschutz: die neue, grosszuegigere Frage-Erkennung darf einen
    # echten Erstell-Wunsch nicht kapern.
    with patch.object(jarvis, "_extract_datetime", return_value=None):
        answer = jarvis.handle_calendar_command("Erstelle mir einen Termin morgen um 15 Uhr")

    assert answer == "Für Kalender oder Erinnerung brauche ich noch Datum oder Uhrzeit."


# --- Fix 7: Speicherplatz-Erkennung fuer Alltagssprache ----------------------


def test_cleanup_intent_recognizes_colloquial_storage_request(monkeypatch):
    monkeypatch.setattr(jarvis, "suggest_cleanup_files", lambda config: ("Aufräum-Text A", []))
    answer = jarvis.handle_file_command(
        "Ich brauch dringend mehr Speicherplatz auf der Platte, hast du eine Idee was weg könnte?"
    )
    assert answer == "Aufräum-Text A"


def test_cleanup_intent_recognizes_festplatte_voll_variant(monkeypatch):
    monkeypatch.setattr(jarvis, "suggest_cleanup_files", lambda config: ("Aufräum-Text B", []))
    answer = jarvis.handle_file_command(
        "Meine Festplatte ist ziemlich voll, gibt's irgendwelche alten Sachen die nur rumliegen?"
    )
    assert answer == "Aufräum-Text B"


def test_cleanup_intent_checked_before_generic_file_gate():
    # Vorher gab die Funktion schon VOR der Aufraeum-Erkennung None zurueck,
    # weil weder "datei" noch "ordner" noch "desktop" im Satz vorkommen.
    normalized = jarvis.normalize_text(
        "Ich brauch dringend mehr Speicherplatz auf der Platte, hast du eine Idee was weg könnte?"
    )
    assert jarvis.has_domain(normalized, "files") is False


def test_unrelated_file_search_still_returns_none_without_cleanup_words():
    assert jarvis.handle_file_command("Wie ist das Wetter heute") is None


# --- Fix 8: Foto-Status-Erkennung fuer Alltagssprache ------------------------


def test_photo_status_question_with_durchsucht_routes_to_status_not_search():
    photo_worker = MagicMock()
    photo_worker.status.return_value = "Ich habe 508 Fotos im Index."
    with patch.object(jarvis, "has_domain", return_value=True):
        answer = jarvis.handle_photo_command("Wie viele Fotos hast du eigentlich mittlerweile durchsucht?", photo_worker)

    photo_worker.status.assert_called_once()
    assert answer == "Ich habe 508 Fotos im Index."


# --- Fix 9: "Bin wieder da" ohne Halluzination -------------------------------


def test_returning_phrase_gets_short_welcome_not_llm_speculation():
    answer = jarvis.handle_local_command("Bin wieder da")
    assert answer is not None
    assert "Amberg" not in answer
    assert "Willkommen zurück" in answer


# --- Fix 10: Stress-Aeusserung bekommt eine empathische Reaktion ------------


def test_stress_statement_gets_empathetic_reply_not_random_quote():
    answer = jarvis.handle_local_command("Puh, stressiger Tag heute muss ich sagen")
    assert answer is not None
    assert "Spruch des Tages" not in answer
    assert "anstrengend" in answer.lower()


# --- Fix 11: Freie Verabschiedung wird erkannt -------------------------------


def test_free_form_farewell_recognized():
    answer = jarvis.handle_local_command("Alles klar, das wär's von mir erstmal, bis später")
    assert answer is not None
    assert "Bis später" in answer


# --- Fix 12: Ehrliche Antwort statt halluzinierter "Erinnerung" -------------


def test_conversation_recall_question_gets_honest_answer_not_hallucination(tmp_path):
    # JarvisMemorySystem braucht eine echte Memory-Instanz (kein MagicMock) -
    # siehe deren Konstruktor-Kommentar zum Dual-Instance-Bug.
    memory = jarvis.Memory(base_path=tmp_path)
    answer = jarvis.handle_memory_command(memory, "Weißt du eigentlich noch, woran ich zuletzt mit dir gearbeitet hab?")

    assert answer is not None
    assert "Gesprächsverlauf" in answer
    # Darf keine erfundene, konkrete Behauptung ueber vergangene Anfragen machen.
    assert "Festplatte" not in answer


def test_genuine_fact_recall_still_works(tmp_path):
    # Regressionsschutz: die neue Meta-Frage-Erkennung darf normale
    # Fakt-Abfragen nicht kapern.
    memory = jarvis.Memory(base_path=tmp_path)
    answer = jarvis.handle_memory_command(memory, "Was weißt du über Amberg")
    assert "Gesprächsverlauf" not in (answer or "")
