from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import jarvis
from memory import Memory
from model_router import ModelRoute
from permission_manager import PermissionManager


@pytest.fixture(autouse=True)
def _run_push_thread_synchronously(monkeypatch):
    # handle_reservation_command() feuert send_push() in einem Hintergrund-Thread
    # (siehe Kommentar dort) statt den Live-Chat-Pfad auf ntfy warten zu lassen -
    # in Tests soll der Seiteneffekt trotzdem deterministisch VOR der Assertion
    # passiert sein, deshalb hier synchron statt in einem echten Thread ausfuehren.
    class _SynchronousThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(jarvis.threading, "Thread", _SynchronousThread)


@pytest.fixture
def memory(tmp_path):
    return Memory(base_path=tmp_path)


def _remember_restaurant(memory: Memory) -> None:
    memory.remember_fact(
        "Restaurant Hans im Glück: https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551",
        category="facts",
    )


def _past_time_today() -> str:
    # Dynamisch berechnet statt fest "8 Uhr" - ein fester Wert waere je nach
    # Tageszeit des Testlaufs noch in der Zukunft gewesen (live so
    # aufgefallen). Einfaches "jetzt minus 1 Minute" kann in der ersten Minute
    # nach Mitternacht auf den VORTAG zurueckrollen (z.B. 23:59) - "heute um
    # 23:59" waere dann noch in der Zukunft und die "schon vorbei"-Assertion
    # schluege fehl (Codex-Review 2026-08-27, Folgerunde). Faellt in diesem
    # engen Fenster stattdessen auf "00:00" zurueck, das fuer "heute"
    # garantiert im selben Kalendertag bleibt.
    now = datetime.now()
    candidate = now - timedelta(minutes=1)
    if candidate.date() != now.date():
        candidate = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return candidate.strftime("%H:%M")


def _correction_time_distinct_from(past_time: str) -> str:
    # +12 Stunden (mod 24) auf die MINUTE genau statt eines fest verdrahteten
    # "19 Uhr" - ein fester Wert kann zufaellig exakt mit past_time
    # zusammenfallen (z.B. beide "19:00", wenn der Testlauf um 19:01 startet)
    # und wuerde dann sowohl die "ist jetzt frei"- als auch die "alte Zeit
    # nicht mehr enthalten"-Assertion widerspruechlich machen (Codex-Review
    # 2026-08-27, Folgerunde). +12h mod 24 auf denselben Wert kann nie mit ihm
    # uebereinstimmen.
    hour, minute = (int(part) for part in past_time.split(":"))
    return f"{(hour + 12) % 24:02d}:{minute:02d}"


class _FakeLLM:
    """Minimaler LLM-Stub fuer answer_message() - wird in diesem Testfall nie
    tatsaechlich befragt, weil handle_reservation_command() vorher greift oder
    der Berechtigungs-Check die Kette abbricht."""

    def plan(self, messages, user_text=None, force_local=False):
        return ModelRoute(
            provider="ollama", model="phi4-mini", max_output_tokens=160, num_ctx=1024,
            temperature=0.3, recent_context_limit=6, compact_prompt=False, stream=False, mode="performance",
        )

    def ask(self, messages, max_output_tokens=None, user_text=None, route=None, force_local=False):
        return "Chat-Antwort"


def test_revoked_permission_blocks_pending_reservation_followup(memory, tmp_path, monkeypatch):
    # Regression: has_domain(question, "reservation") matcht eine kurze
    # Folgeantwort wie "19 Uhr" nicht - der Berechtigungs-Check am Dispatch-
    # Aufrufer war urspruenglich daran gekoppelt und wurde deshalb fuer
    # Folgeantworten komplett uebersprungen. Ein zwischenzeitlicher
    # Berechtigungsentzug waehrend eines laufenden Reservierungs-Dialogs haette
    # so unbemerkt durchgehen koennen (Codex-Review 2026-08-23).
    monkeypatch.setattr(jarvis, "PermissionManager", lambda base_path=None: PermissionManager(base_path=tmp_path))
    PermissionManager(base_path=tmp_path).grant("reservation", source="test_setup")

    _remember_restaurant(memory)
    workers = jarvis.AnswerWorkers()
    llm = _FakeLLM()

    first = jarvis.answer_message("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory, llm, {}, workers=workers)
    assert "personen" in first.text.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    PermissionManager(base_path=tmp_path).revoke("reservation", source="test_setup")

    second = jarvis.answer_message("2", memory, llm, {}, workers=workers)

    assert "reservation" in second.text.lower() or "zustimmung" in second.text.lower()
    assert memory.get("settings").get("pending_reservation_open") is None


def test_revoked_permission_blocks_pending_confirmation_at_execute_time(memory, tmp_path, monkeypatch):
    # Regression: handle_pending_action_flow() (bearbeitet "ja"/"nein") laeuft
    # in der Dispatch-Kette VOR dem regulaeren Berechtigungs-Check - ein
    # Entzug NACH dem Vorschlag, aber VOR der "ja"-Bestaetigung, wurde bisher
    # beim Ausfuehren gar nicht mehr geprueft und haette TheFork trotzdem
    # geoeffnet (Codex-Review 2026-08-23).
    monkeypatch.setattr(jarvis, "PermissionManager", lambda base_path=None: PermissionManager(base_path=tmp_path))
    PermissionManager(base_path=tmp_path).grant("reservation", source="test_setup")

    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True):
        jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen um 19 Uhr für 2 Personen", memory=memory
        )
    assert memory.get("settings").get("pending_reservation_open") is not None

    PermissionManager(base_path=tmp_path).revoke("reservation", source="test_setup")

    with patch("subprocess.run") as run:
        result = jarvis.handle_pending_action_flow(memory, "ja")

    run.assert_not_called()  # darf TheFork nicht mehr oeffnen, sobald die Berechtigung weg ist
    assert "entzogen" in result.lower()
    assert memory.get("settings").get("pending_reservation_open") is None


def test_pasted_thefork_link_gets_remembered_instead_of_looping(memory):
    # Regression: die Rueckfrage versprach "schick mir den TheFork-Link, dann
    # merke ich ihn mir", aber nichts hat den Link je gespeichert - eine
    # Antwort mit dem Link haette die Frage endlos wiederholt (Codex-Review
    # 2026-08-23).
    first = jarvis.handle_reservation_command("ich möchte einen tisch reservieren", memory=memory)
    assert "restaurant" in first.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    second = jarvis.handle_reservation_command(
        "https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551", memory=memory
    )
    # Restaurant jetzt bekannt, aber Personenzahl/Datum/Uhrzeit fehlen noch -
    # keine Endlosschleife bei derselben Frage mehr (Personenzahl kommt zuerst
    # dran, siehe fetch_available_time_slots()-Integration).
    assert "personen" in second.lower()
    facts = memory.search_facts("Restaurant")
    assert any("hans-im-gluck-burgergrill-bar-amberg-spitalkirche" in f.get("content", "") for f in facts)


def test_hint_selects_correct_restaurant_among_several(memory):
    # Regression: der Vergleich war urspruenglich verkehrt herum und wurde von
    # einem einzigen hinterlegten Restaurant maskiert (fiel trotzdem auf
    # candidates[0] zurueck) - erst mit einem zweiten Restaurant zeigt sich der
    # echte Bug (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    memory.remember_fact(
        "Restaurant Pizza Blitz: https://www.thefork.de/restaurant/pizza-blitz-amberg-r999999",
        category="facts",
    )
    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Pizza Blitz", memory=memory
        )
    settings = memory.get("settings") or {}
    pending = settings.get("pending_reservation_open")
    assert pending is not None
    assert "pizza-blitz-amberg-r999999" in pending["url"]


def test_bare_restaurant_name_answers_disambiguation_question(memory):
    # Regression: _RESERVATION_CONTINUATION_RE erkennt Zeit-/Personenzahl-
    # Antworten, aber keinen blossen Restaurantnamen ("Pizza Blitz" auf
    # "Welches Restaurant meinst du?") - ohne Zusatz-Check waere die
    # Rueckfrage bei mehreren hinterlegten Restaurants nie beantwortbar
    # gewesen (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    memory.remember_fact(
        "Restaurant Pizza Blitz: https://www.thefork.de/restaurant/pizza-blitz-amberg-r999999",
        category="facts",
    )
    first = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr für 2 Personen", memory=memory)
    assert "restaurant" in first.lower()
    assert memory.get("settings").get("pending_reservation_details") is not None

    with patch.object(jarvis, "send_push", return_value=True):
        second = jarvis.handle_reservation_command("Pizza Blitz", memory=memory)

    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "pizza-blitz-amberg-r999999" in pending["url"]


def test_none_for_unrelated_text(memory):
    assert jarvis.handle_reservation_command("wie geht es dir", memory=memory) is None


def test_asks_for_restaurant_when_none_known(memory):
    result = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr für 2 Personen", memory=memory)
    assert result is not None
    assert "thefork-link" in result.lower() or "restaurant" in result.lower()


def test_asks_for_date_and_time_when_missing(memory):
    _remember_restaurant(memory)
    result = jarvis.handle_reservation_command("ich möchte eine reservierung für 2 personen", memory=memory)
    assert "wann" in result.lower() or "tag" in result.lower() or "uhrzeit" in result.lower()


def test_asks_for_party_size_when_missing(memory):
    _remember_restaurant(memory)
    result = jarvis.handle_reservation_command("reserviere einen tisch morgen um 19 Uhr", memory=memory)
    assert "personen" in result.lower()


def test_happy_path_proposes_and_sends_push_with_prefilled_url(memory):
    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True) as send_push:
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Hans im Glück", memory=memory
        )

    assert "hans im glück" in result.lower()
    assert "bestätig" in result.lower() or "sag ja" in result.lower()

    settings = memory.get("settings") or {}
    pending = settings.get("pending_reservation_open")
    assert isinstance(pending, dict)
    assert "hour=19%3A00" in pending["url"]
    assert "partySize=2" in pending["url"]
    assert pending["url"].startswith("https://www.thefork.de/restaurant/hans-im-gluck-burgergrill-bar-amberg-spitalkirche-r615551#booking=")
    assert "set_at" in pending

    send_push.assert_called_once()
    push_kwargs = send_push.call_args.kwargs
    assert push_kwargs["url"] == pending["url"]


def test_followup_answers_complete_the_reservation_across_turns(memory):
    # Regression: eine kurze Folgeantwort wie "2 Personen" oder "19 Uhr" matcht
    # has_domain(text, "reservation") nicht - ohne den pending_reservation_details-
    # Mechanismus wuerde die Anfrage tot enden und der Nutzer muesste alles
    # nochmal von vorn sagen (Codex-Review 2026-08-23). fetch_available_time_slots()
    # wird gemockt (gibt None zurueck, wie ein nicht erreichbares Safari) - das
    # AppleScript/Safari-Verhalten selbst wird in test_thefork_client.py getestet,
    # nicht hier.
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=None):
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen", memory=memory)
        assert "personen" in first.lower()
        assert memory.get("settings").get("pending_reservation_details") is not None

        second = jarvis.handle_reservation_command("2 Personen", memory=memory)
        assert "uhr" in second.lower()
        assert memory.get("settings").get("pending_reservation_details") is not None

        with patch.object(jarvis, "send_push", return_value=True):
            third = jarvis.handle_reservation_command("19 Uhr", memory=memory)

    assert "hans im glück" in third.lower()
    assert memory.get("settings").get("pending_reservation_details") is None


def test_available_times_are_offered_and_validated(memory):
    # Kernanforderung: Jarvis soll echte verfuegbare Uhrzeiten nennen, der
    # Nutzer waehlt eine, und nur eine tatsaechlich genannte Zeit wird
    # akzeptiert (Plan "Echte TheFork-Verfuegbarkeit per Safari-
    # Fernsteuerung", 2026-08-27).
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=["18:00", "19:00", "20:00"]) as fetch:
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory)
        assert "18:00" in first and "19:00" in first and "20:00" in first
        fetch.assert_called_once()
        assert fetch.call_args.args[2] == 2  # party_size wurde vor der Abfrage schon aufgeloest

        # Eine nicht genannte Uhrzeit wird abgelehnt, nicht stillschweigend uebernommen.
        second = jarvis.handle_reservation_command("21 Uhr", memory=memory)
        assert "nicht mehr frei" in second.lower()
        assert "18:00" in second

        with patch.object(jarvis, "send_push", return_value=True):
            third = jarvis.handle_reservation_command("19 Uhr", memory=memory)

    assert "hans im glück" in third.lower()
    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "hour=19%3A00" in pending["url"]
    assert "partySize=2" in pending["url"]


def test_empty_availability_is_not_treated_as_a_failed_lookup(memory):
    # Regression: "if slots:" behandelte eine erfolgreiche, aber leere
    # Verfuegbarkeits-Liste (Tag komplett ausgebucht) genauso wie eine
    # fehlgeschlagene Abfrage - Jarvis haette danach blind jede genannte
    # Uhrzeit akzeptiert, obwohl echt abgefragt bekannt war, dass keine frei
    # ist (Codex-Review 2026-08-27, P2).
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=[]):
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory)
        assert "nichts mehr frei" in first.lower()

        # Egal welche Uhrzeit jetzt genannt wird - keine ist gueltig, eine
        # Reservierung darf nicht vorbereitet werden.
        second = jarvis.handle_reservation_command("19 Uhr", memory=memory)

    assert "nichts mehr frei" in second.lower()


def test_rejected_day_suggests_alternative_dates_found_by_the_scan(memory):
    # Nutzer-Wunsch 2026-08-30: statt blind "fuer welchen anderen Tag soll
    # ich schauen?" zu fragen, soll Jarvis gleich die naechsten Tage pruefen
    # und die freien direkt mitnennen.
    _remember_restaurant(memory)

    def fake_fetch(url, date, party_size, timeout=None):
        return {"2026-09-03": ["19:00", "20:00"]}.get(date, [])

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", side_effect=fake_fetch):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory
        )

    assert "nichts mehr frei" in result.lower()
    assert "03.09." in result
    assert "19:00" in result and "20:00" in result


def test_rejected_day_falls_back_to_plain_question_when_scan_finds_nothing(memory):
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=[]):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory
        )

    assert "nichts mehr frei" in result.lower()
    assert "für welchen anderen tag soll ich schauen" in result.lower()


def test_rejected_day_falls_back_to_plain_question_when_scan_itself_fails(memory):
    _remember_restaurant(memory)

    def fake_fetch(url, date, party_size, timeout=None):
        # Der abgelehnte Tag selbst liefert eine leere Liste (echt
        # ausgebucht), der anschliessende Scan schlaegt fuer JEDEN
        # weiteren Tag komplett fehl (None) - find_available_dates() gibt
        # dann selbst None zurueck, die Rueckfrage bleibt die reine Frage.
        return [] if date == "2026-08-31" else None

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", side_effect=fake_fetch):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory
        )

    assert "nichts mehr frei" in result.lower()
    assert "für welchen anderen tag soll ich schauen" in result.lower()


def test_rejected_date_does_not_repeat_query_but_a_new_date_does(memory):
    # Regression: das abgelehnte Datum blieb im aufaddierten Text stehen -
    # eine Korrektur-Antwort mit einem neuen Tag haette _extract_datetime()
    # trotzdem wieder auf das alte, bereits als ausgebucht bekannte Datum
    # treffen lassen (Codex-Review 2026-08-27, dritte Runde). rejected_dates
    # muss den bekannten Tag kurzschliessen (keine erneute Safari-Abfrage),
    # ein WIRKLICH neuer Tag muss aber normal weiterlaufen.
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=[]) as fetch:
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory)
        assert "nichts mehr frei" in first.lower()
        # 1 Aufruf fuer den abgelehnten Tag selbst + 7 fuer den anschliessenden
        # Alternativtage-Scan (_reject_day_with_alternative_suggestions(), mit
        # return_value=[] fuer JEDEN Tag findet der Scan nichts und die
        # Rueckfrage bleibt die reine "fuer welchen anderen Tag"-Frage).
        assert fetch.call_count == 8

        # Derselbe (bereits abgelehnte) Tag nochmal genannt - keine neue Abfrage.
        second = jarvis.handle_reservation_command("morgen", memory=memory)
        assert "nichts mehr frei" in second.lower()
        assert fetch.call_count == 8  # weiterhin nur die Aufrufe von oben

        # Ein WIRKLICH anderer Tag - muss eine neue, echte Abfrage ausloesen.
        fetch.return_value = ["18:00"]
        third = jarvis.handle_reservation_command("übermorgen", memory=memory)
        assert "18:00" in third
        assert fetch.call_count == 9  # sofort Zeiten gefunden, kein Scan noetig
    assert memory.get("settings").get("pending_reservation_open") is None


def test_rejected_absolute_date_does_not_block_a_new_absolute_date(memory):
    # Regression: _strip_resolved_relative_date_phrase() entfernte urspruenglich
    # nur relative Formulierungen (heute/morgen/uebermorgen/Wochentage) - ein
    # abgelehntes ABSOLUTES Datum (ISO-Format) blieb im aufaddierten Text stehen
    # und _extract_datetime() fand es weiterhin zuerst, selbst wenn der Nutzer
    # danach ein echt anderes absolutes Datum nannte (Codex-Review 2026-08-27,
    # Folgerunde nach dem relativen Datums-Fix).
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=[]) as fetch:
        first = jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück am 2026-09-01 für 2 Personen", memory=memory
        )
        assert "nichts mehr frei" in first.lower()
        # 1 Aufruf fuer den abgelehnten Tag + 7 fuer den Alternativtage-Scan
        # (siehe test_rejected_date_does_not_repeat_query_but_a_new_date_does).
        assert fetch.call_count == 8

        fetch.return_value = ["18:00"]
        second = jarvis.handle_reservation_command("am 2026-09-15", memory=memory)
        assert "18:00" in second
        assert fetch.call_count == 9  # sofort Zeiten gefunden, kein Scan noetig


def test_user_can_change_the_date_before_it_was_ever_rejected(memory):
    # Regression: der Bug trat nicht nur NACH einer Ablehnung wegen
    # Ausbuchung auf, sondern schon VORHER - sobald zwei unterschiedliche
    # Datums-Woerter im aufaddierten Text stehen, gewann das eine mit
    # hoeherer Prioritaet in _extract_relative_date() (z.B. "morgen") immer
    # gegen ein spaeter genanntes anderes ("uebermorgen"), obwohl der Nutzer
    # den Tag noch vor jeder Antwort auf verfuegbare Zeiten aendert (Codex-
    # Review 2026-08-27, dritte Folgerunde).
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots") as fetch:
        fetch.return_value = ["18:00", "19:00"]
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory)
        assert "18:00" in first
        fetch.assert_called_once()

        fetch.return_value = ["20:00"]
        second = jarvis.handle_reservation_command("doch lieber übermorgen", memory=memory)
        assert "20:00" in second
        assert fetch.call_count == 2


def test_time_paired_with_a_superseded_date_is_not_reused_for_the_new_date(memory):
    # Regression: _resolve_latest_date() entfernte beim Ueberholen eines
    # aelteren Datums nur das Datums-Wort selbst, nicht die daneben stehende
    # Uhrzeit - "heute um 8 Uhr" (schon vorbei) gefolgt von einer Korrektur
    # "morgen um 19 Uhr" loeste dann zwar korrekt auf MORGEN auf, aber
    # _extract_time() fand ueber re.search() weiterhin zuerst die alte,
    # eigentlich verworfene "8 Uhr" - die Reservierung waere fuer die
    # falsche Uhrzeit vorbereitet worden (Codex-Review 2026-08-27, fuenfte
    # Folgerunde).
    _remember_restaurant(memory)

    # Siehe _past_time_today() fuer den Grund, warum das nicht einfach "8 Uhr"
    # oder ein naives "jetzt minus 1 Minute" ist. Ein ISO-Datum von "gestern"
    # waere ebenfalls robust, deckt aber einen unabhaengigen, bereits
    # bestehenden Fehler in _safe_datetime() auf (rollt ein EXPLIZIT
    # genanntes, bereits vergangenes Jahr faelschlich auf naechstes Jahr vor)
    # - nicht Teil dieser Aenderung, deshalb hier bewusst umgangen.
    past_time = _past_time_today()
    first = jarvis.handle_reservation_command(
        f"reserviere einen tisch bei Hans im Glück heute um {past_time} für 2 Personen", memory=memory
    )
    assert "schon vorbei" in first.lower()

    correction_time = _correction_time_distinct_from(past_time)
    second = jarvis.handle_reservation_command(f"morgen um {correction_time}", memory=memory)
    assert correction_time in second
    assert past_time not in second


def test_time_removal_window_does_not_swallow_an_intervening_valid_date(memory):
    # Regression: das Suchfenster um ein zu entfernendes altes Datum durfte
    # eine naheliegende Uhrzeit mitreissen - stand dazwischen aber ein
    # DRITTES, gueltiges Datum sehr nah beieinander (z.B. "morgen uebermorgen
    # um 19 Uhr"), wurde das Fenster von "morgen" bis zur "19 Uhr" faelschlich
    # ausgedehnt und riss das dazwischenliegende "uebermorgen" mit heraus -
    # die eigentlich gueltige Korrektur ging dadurch komplett verloren
    # (Codex-Review 2026-08-27, sechste Folgerunde).
    _remember_restaurant(memory)

    # Siehe _past_time_today() fuer den Grund, warum das nicht einfach "8 Uhr"
    # oder ein naives "jetzt minus 1 Minute" ist. Ein ISO-Datum von "gestern"
    # waere ebenfalls robust, deckt aber einen unabhaengigen, bereits
    # bestehenden Fehler in _safe_datetime() auf (rollt ein EXPLIZIT
    # genanntes, bereits vergangenes Jahr faelschlich auf naechstes Jahr vor)
    # - nicht Teil dieser Aenderung, deshalb hier bewusst umgangen.
    past_time = _past_time_today()
    first = jarvis.handle_reservation_command(
        f"reserviere einen tisch bei Hans im Glück heute um {past_time} für 2 Personen", memory=memory
    )
    assert "schon vorbei" in first.lower()

    correction_time = _correction_time_distinct_from(past_time)
    second = jarvis.handle_reservation_command(f"morgen übermorgen um {correction_time}", memory=memory)
    assert correction_time in second
    assert past_time not in second


def test_stale_availability_cache_is_not_used_for_a_different_corrected_date(memory):
    # Regression: available_times wurde nicht danach gescoped, FUER WELCHES
    # Datum es echt abgefragt wurde - nennt der Nutzer Datum UND Uhrzeit in
    # einer Korrektur zusammen (z.B. "doch übermorgen um 19 Uhr" nach zuvor
    # fuer "morgen" abgefragten Zeiten), ueberspringt has_time die neue
    # Abfrage und die alte (fuer ein anderes Datum gueltige) Liste haette die
    # neue Uhrzeit faelschlich validiert (Codex-Review 2026-08-27, vierte
    # Folgerunde).
    _remember_restaurant(memory)

    with patch.object(jarvis.thefork_client, "fetch_available_time_slots", return_value=["19:00"]) as fetch:
        first = jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen für 2 Personen", memory=memory)
        assert "19:00" in first
        fetch.assert_called_once()

        # "19 Uhr" ist bei den fuer MORGEN abgefragten Zeiten gueltig, aber der
        # Nutzer wechselt hier gleichzeitig auf UEBERMORGEN - fuer diesen Tag
        # wurde nie echt geprueft, ob 19 Uhr wirklich frei ist. Die alte Liste
        # darf das nicht mehr validieren (weder blind bestaetigen noch
        # faelschlich als "nicht mehr frei" ablehnen) - das Verhalten faellt
        # stattdessen auf den bestehenden, unvalidierten Bestaetigungs-Fluss
        # zurueck (identisch zu einer allerersten Nachricht mit Datum+Uhrzeit
        # zusammen, die ebenfalls nie live geprueft wird).
        second = jarvis.handle_reservation_command("doch übermorgen um 19 Uhr", memory=memory)
        assert "nicht mehr frei" not in second.lower()
        assert "vorbereiten" in second.lower()


def test_invalid_party_size_can_be_corrected(memory):
    # Regression: "fuer 0 Personen" wird abgelehnt und nachgefragt, aber "0
    # Personen" blieb im aufaddierten Text stehen - re.search() fand bei der
    # naechsten Extraktion weiterhin die alte "0", eine Korrektur-Antwort ("2")
    # kam nie an (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr für 0 Personen", memory=memory)
    assert memory.get("settings").get("pending_reservation_details") is not None

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command("2", memory=memory)

    assert "hans im glück" in result.lower()
    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None
    assert "partySize=2" in pending["url"]


def test_bare_number_answers_party_size_question(memory):
    # Regression: die natuerlichste Antwort auf "Fuer wie viele Personen...?"
    # ist eine blanke Zahl ("2"), nicht "fuer 2 Personen" - ohne Fallback haette
    # das die Frage endlos wiederholt (Codex-Review 2026-08-23).
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command("2", memory=memory)

    assert "hans im glück" in result.lower()
    assert memory.get("settings").get("pending_reservation_details") is None
    pending = memory.get("settings").get("pending_reservation_open")
    assert "partySize=2" in pending["url"]


def test_spelled_out_party_size_is_recognized_in_initial_message_and_followup(memory):
    # Live beobachtet 2026-08-28: sowohl _PARTY_SIZE_RE als auch der blanke-
    # Zahl-Fallback verstanden nur Ziffern ("2 Personen"), keine ausge-
    # schriebenen deutschen Zahlwoerter ("zwei Personen"). "Reserviere mir
    # doch bitte einen Tisch fuer zwei Personen" fragte deshalb trotzdem
    # wieder nach der Personenzahl, und die Folgeantwort "Zwei Personen
    # bitte" loeste dieselbe Frage ein zweites Mal aus statt sie zu
    # beantworten - Jarvis haengte sich in einer Endlosschleife auf.
    _remember_restaurant(memory)

    first = jarvis.handle_reservation_command(
        "Reserviere mir doch bitte einen Tisch für zwei Personen", memory=memory
    )
    # Personenzahl war jetzt schon bekannt - die naechste fehlende Angabe
    # (Datum/Uhrzeit) wird erfragt, nicht nochmal die Personenzahl.
    assert "personen" not in first.lower()

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command(
            "reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory
        )
    pending = memory.get("settings").get("pending_reservation_open")
    assert pending is not None and "partySize=2" in pending["url"]


def test_bare_spelled_out_number_answers_party_size_question(memory):
    # Wie test_bare_number_answers_party_size_question(), aber mit einer
    # ausgeschriebenen Zahl statt einer Ziffer als blanke Folgeantwort -
    # live beobachtet 2026-08-28 als "Zwei Personen bitte" (mit "Personen"
    # dran, matcht bereits ueber _PARTY_SIZE_RE) UND als reine Zahl allein.
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)

    with patch.object(jarvis, "send_push", return_value=True):
        result = jarvis.handle_reservation_command("zwei", memory=memory)

    assert "hans im glück" in result.lower()
    pending = memory.get("settings").get("pending_reservation_open")
    assert "partySize=2" in pending["url"]


def test_bare_party_size_answer_with_polite_suffix_or_punctuation(memory):
    # Regression: die urspruengliche strikte Fassung von
    # _BARE_PARTY_SIZE_ANSWER_RE erlaubte nur Leerraum um die Zahl - eine
    # ganz natuerliche Antwort wie "zwei bitte" oder "zwei." matchte weder
    # die Fortsetzungs-Erkennung noch die eigentliche Extraktion, wodurch
    # die GESAMTE offene Reservierung faelschlich verworfen wurde statt
    # fortgesetzt zu werden (Codex-Review 2026-08-28, Folgerunde).
    _remember_restaurant(memory)

    for reply, expected_party_size in [("zwei bitte", 2), ("zwei.", 2), ("2 bitte", 2)]:
        memory.set("settings", {})
        jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)
        assert memory.get("settings").get("pending_reservation_details") is not None

        with patch.object(jarvis, "send_push", return_value=True):
            result = jarvis.handle_reservation_command(reply, memory=memory)

        assert result is not None and "hans im glück" in result.lower(), reply
        pending = memory.get("settings").get("pending_reservation_open")
        assert pending is not None and f"partySize={expected_party_size}" in pending["url"], reply


def test_party_size_number_words_require_whole_word_match(memory):
    # Regression: die urspruengliche Fassung matchte Zahlwoerter als reinen
    # Teilstring - "eine" matchte auch als Teilstring in "keine" (eine
    # Ablehnung "keine Personen" waere faelschlich als 1 Person gebucht
    # worden) und "zwanzig" als Suffix von "einundzwanzig" (faelschlich 20
    # statt 21 Personen) (Codex-Review 2026-08-28).
    assert jarvis._PARTY_SIZE_RE.search("keine Personen") is None
    match = jarvis._PARTY_SIZE_RE.search("einundzwanzig Personen")
    assert match is None or jarvis._parse_party_size_token(match.group(1)) != 20


def test_reservation_continuation_regex_does_not_match_number_word_substring(memory):
    # Regression: "ein" (Zahlwort) matchte als Teilstring auch in "nein" -
    # eine Ablehnung wie "nein, abbrechen" auf eine offene Reservierungs-
    # Rueckfrage waere faelschlich als Fortsetzung behandelt worden statt die
    # Anfrage zu verwerfen (Codex-Review 2026-08-28).
    assert jarvis._RESERVATION_CONTINUATION_RE.search("nein, abbrechen") is None
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)
    result = jarvis.handle_reservation_command("nein, abbrechen", memory=memory)
    assert result is None
    assert memory.get("settings").get("pending_reservation_details") is None


def test_reservation_continuation_regex_does_not_match_generic_number_word_mentions(memory):
    # Regression (Codex Stop-Hook 2026-08-28): ein frueherer Fix nahm die
    # ausgeschriebenen Zahlwoerter (siehe _GERMAN_PARTY_SIZE_WORDS) per
    # .search() irgendwo im Text in _RESERVATION_CONTINUATION_RE auf, damit
    # eine blanke Antwort wie "zwei" als Fortsetzung erkannt wird. Anders als
    # "personen"/"uhr" sind kleine Zahlwoerter im Alltagsdeutsch aber extrem
    # haeufig und voellig unspezifisch (Alter, Mengen, ...) - jede voellig
    # unabhaengige Folgenachricht, die zufaellig eines davon enthielt, waere
    # faelschlich in die laengst veraltete Reservierungs-Rueckfrage gezogen
    # worden statt als neue, unabhaengige Anfrage zu gelten. Die blanke
    # Personenzahl-Antwort wird stattdessen ueber das gezielte
    # _BARE_PARTY_SIZE_ANSWER_RE (fullmatch) erkannt.
    assert jarvis._RESERVATION_CONTINUATION_RE.search("ich habe acht Katzen") is None

    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück morgen um 19 Uhr", memory=memory)
    # Eine voellig unabhaengige Nachricht, die zufaellig ein Zahlwort enthaelt
    # und kein Reservierungs-Restaurant aufloest, muss verworfen werden
    # (None), nicht in die offene Personenzahl-Rueckfrage gezogen werden.
    result = jarvis.handle_reservation_command("ich habe acht Katzen", memory=memory)
    assert result is None
    assert memory.get("settings").get("pending_reservation_details") is None


def test_unrelated_followup_discards_pending_details(memory):
    _remember_restaurant(memory)
    jarvis.handle_reservation_command("reserviere einen tisch bei Hans im Glück heute", memory=memory)
    assert memory.get("settings").get("pending_reservation_details") is not None

    result = jarvis.handle_reservation_command("wie ist eigentlich das Wetter", memory=memory)

    assert result is None
    assert memory.get("settings").get("pending_reservation_details") is None


def test_stale_confirmation_expires_instead_of_firing(memory):
    _remember_restaurant(memory)
    with patch.object(jarvis, "send_push", return_value=True):
        jarvis.handle_reservation_command(
            "reserviere einen tisch morgen um 19 Uhr für 2 Personen bei Hans im Glück", memory=memory
        )

    settings = memory.get("settings") or {}
    settings["pending_reservation_open"]["set_at"] -= jarvis.PENDING_RESERVATION_OPEN_TTL_SECONDS + 1
    memory.set("settings", settings)

    with patch("subprocess.run") as run:
        result = jarvis.handle_pending_action_flow(memory, "ja")

    run.assert_not_called()  # eine abgelaufene Anfrage darf niemals noch den Browser oeffnen
    assert "abgelaufen" in result.lower()
    assert memory.get("settings").get("pending_reservation_open") is None
