from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import thefork_client


def _fake_result(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_success_returns_only_available_time_strings():
    stdout = (
        '{"ready":true,"slots":['
        '{"time":"17:00","available":true},{"time":"17:30","available":false},'
        '{"time":"19:00","available":true}]}'
    )
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout=stdout)):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result == ["17:00", "19:00"]


def test_ready_but_all_slots_unavailable_returns_empty_list_not_none():
    # "ready:true" heisst: mindestens ein echter Uhrzeit-Button ist erschienen
    # (siehe read_slots_js) - sind ALLE davon "available:false", ist der Tag
    # echt ausgebucht. Ein ANDERER Fall als eine fehlgeschlagene Abfrage
    # (None), siehe handle_reservation_command()'s "is not None"-Unterscheidung.
    stdout = '{"ready":true,"slots":[{"time":"18:00","available":false},{"time":"19:00","available":false}]}'
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout=stdout)):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result == []


def test_widget_never_ready_returns_none_not_empty_list():
    # Regression (Codex-Review 2026-08-30, zwei Runden): eine erste Fassung
    # kollabierte "Widget nie gemountet" auf dasselbe leere "[]" wie ein echt
    # ausgebuchter Tag (P2); eine zweite Fassung wertete bereits die beiden
    # SOFORT beim Mounten erscheinenden Abschnittsueberschriften als "ready",
    # obwohl die eigentlichen Uhrzeit-Buttons noch asynchron nachgeladen
    # wurden (P1) - in beiden Faellen kam eine fehlgeschlagene/noch nicht
    # fertige Abfrage faelschlich als "nichts frei" beim Nutzer an.
    # "ready:false" (kein einziger echter Uhrzeit-Button) muss None liefern
    # (loest die alte, datenlose Rueckfrage aus), auch wenn schon
    # Abschnittsueberschriften da sind.
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout='{"ready":false,"slots":[]}')):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result is None


def test_explicit_no_availability_message_returns_none_not_empty_list():
    # Live entdeckt 2026-08-30 gegen ein echtes Restaurant ("Nobless",
    # Maxhuette-Haidhof) ohne Online-Verfuegbarkeit: TheFork rendert dafuer
    # NIE echte Uhrzeit-Buttons (strukturell, nicht "noch am Laden"), zeigt
    # aber ein explizites Element
    # `[data-testid="booking-widget-no-availability-message"]`.
    #
    # Regression (Codex-Review 2026-08-30, dritte Runde, P2): eine erste
    # Fassung bildete dieses Signal auf eine leere Zeiten-Liste ab ([]) -
    # dieselbe Antwort wie bei einem echt ausgebuchten Tag. "Keine
    # Online-Verfuegbarkeitspruefung moeglich" ist aber NICHT dasselbe wie
    # "definitiv nichts frei" (eine telefonische Reservierung koennte trotzdem
    # gehen) - live beim Nutzer beobachtet, dass diese Formulierung
    # verwirrend war. None behandelt diesen Fall deshalb wie einen
    # Abfrage-Fehlschlag (bisherige, datenlose Rueckfrage), nicht wie ein
    # bestaetigtes "ausgebucht".
    stdout = '{"ready":true,"noAvailability":true,"slots":[]}'
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout=stdout)):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result is None


def test_ready_signal_also_checks_no_availability_message_selector():
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout='{"ready":false,"slots":[]}')

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert 'booking-widget-no-availability-message' in script
    assert "noAvailability:noAvail" in script
    assert "ready:real.length>0||noAvail" in script


def test_list_shaped_json_returns_none():
    # Das erwartete Format ist jetzt ein Objekt ({"ready":..., "slots":...}),
    # kein bares Array mehr - ein Array (z.B. Rueckstand des alten Formats)
    # muss sauber als ungueltig behandelt werden, nicht crashen.
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout="[]")):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result is None


def test_timeout_returns_none_not_exception():
    with patch.object(thefork_client.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=15)):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_missing_permission_returns_none():
    # Fehlende Safari-JavaScript-/Automation-Berechtigung liefert returncode != 0 -
    # muss still auf None zurueckfallen, nicht crashen (siehe Moduldoc).
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(returncode=1, stderr="not allowed")):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_malformed_json_returns_none():
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout="not-json")):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_dict_without_ready_key_returns_none():
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout='{"error": "oops"}')):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_empty_stdout_returns_none():
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout="")):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_timeout_triggers_stray_tab_cleanup():
    # Regression: das Haupt-AppleScript schliesst seinen Tab erst ganz am
    # Ende - bricht osascript vorher per Timeout ab, blieb der Tab bisher
    # offen stehen. Ein zweiter (Aufraeum-)Aufruf muss trotzdem erfolgen
    # (Codex-Adversarial-Review 2026-08-27).
    with patch.object(
        thefork_client.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=15)
    ) as run:
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None
    assert run.call_count == 2  # Hauptversuch + Aufraeum-Versuch


def test_missing_permission_does_not_trigger_external_cleanup():
    # Ein returncode != 0 bedeutet entweder "Safari/Automation liess sich gar
    # nicht ansprechen" (nie ein Tab erstellt) oder "das Skript hat mit der
    # ECHTEN Tab-Referenz schon selbst aufgeraeumt" (siehe try/on error im
    # AppleScript) - in beiden Faellen KEIN zusaetzlicher, URL-basierter
    # externer Aufraeum-Versuch mehr noetig, der einen unabhaengigen Tab von
    # Leon treffen koennte (zweite Fassung nach Codex-Review 2026-08-27, P1).
    with patch.object(
        thefork_client.subprocess, "run", return_value=_fake_result(returncode=1, stderr="not allowed")
    ) as run:
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None
    assert run.call_count == 1


def test_cleanup_matches_full_request_url_not_just_restaurant_or_domain():
    # Regression: eine erste Fassung matchte pauschal "enthaelt thefork.de"
    # (jeder TheFork-Tab in jedem Fenster), eine zweite nur die Restaurant-
    # Basis-URL (haette einen eigenen, unabhaengigen Tab fuer GENAU dieses
    # Restaurant treffen koennen) - jetzt matcht es die VOLLE Anfrage-URL
    # inklusive Datum+Personenzahl, die pro Anfrage praktisch eindeutig ist
    # (Codex-Review 2026-08-27, dritte Runde). Der externe Aufraeum-Pfad wird
    # nur noch beim echten externen Timeout ausgeloest, deshalb TimeoutExpired
    # statt returncode=1.
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd[2])
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=15)

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    cleanup_script = calls[1]
    assert 'starts with "https://www.thefork.de/restaurant/nobless-r598675#booking=&date=2026-08-28&partySize=2"' in cleanup_script
    assert "contains" not in cleanup_script


def test_unexpected_exception_returns_none_not_raised():
    # Regression: nur (TimeoutExpired, OSError) wurden gefangen - ein
    # unerwarteter Fehler (z.B. aus einer kuenftigen Markup-Aenderung bei
    # TheFork) haette den aufrufenden Chat-Turn crashen lassen (Codex-
    # Adversarial-Review 2026-08-27).
    with patch.object(thefork_client.subprocess, "run", side_effect=RuntimeError("unerwartet")):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_script_cleans_up_tab_on_success_and_on_error():
    # Der Tab muss sowohl im Erfolgspfad als auch im Fehlerpfad
    # (try/on error) geschlossen werden - kein liegen gebliebener Tab bei
    # z.B. einem "do JavaScript"-Fehler.
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "on error errMsg" in script
    assert script.count("close theTab") >= 2  # Erfolgspfad UND Fehlerpfad


def test_script_retries_up_to_twice_while_widget_not_ready():
    # Regression: zuerst gab es gar keinen Retry, dann nur einen einzelnen
    # festen - beides reichte bei einer langsam ladenden Seite u.U. nicht
    # (Codex-Review 2026-08-27, zweite und dritte Runde). Der Retry haengt
    # seit 2026-08-30 (P2) an "ready:true" statt an einer nicht-leeren
    # Zeiten-Liste - ein echt ausgebuchter, aber erfolgreich geladener Tag
    # ("ready:true", leere/komplett belegte Liste) darf nicht laenger als
    # "noch am Laden" missverstanden werden.
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout='{"ready":true,"slots":[]}')

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "repeat 2 times" in script
    assert 'if slotsJson contains "\\"ready\\":true" then exit repeat' in script
    assert script.count("do JavaScript") >= 2  # mindestens ein Lese-Versuch, der Retry-Block ist ein weiterer


def test_ready_signal_requires_real_time_slots_not_just_section_headers():
    # Regression (Codex-Review 2026-08-30, zweite Runde, P1): eine erste
    # Fassung setzte "ready" auf Basis ALLER "timeslot-*"-Elemente, auch der
    # beiden Abschnittsueberschriften ("timeslot-service-lunch"/"-diner"),
    # die live verifiziert SOFORT beim Mounten erscheinen - noch bevor die
    # eigentlichen Uhrzeit-Buttons asynchron nachgeladen sind. "ready" muss
    # stattdessen an der gefilterten "real"-Liste (echte HH:MM-Buttons)
    # haengen, nicht an der ungefilterten "btns"-Liste.
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout='{"ready":true,"slots":[]}')

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "ready:real.length>0" in script
    assert "ready:btns.length>0" not in script
    assert "ready:all.length>0" not in script


def test_url_and_selectors_are_correctly_embedded():
    # Regression 2026-08-30: eine fruehere Fassung baute die URL mit
    # Query-Parametern (?date=...) und klickte einen
    # "calendar-day-{date}"-Testid, der auf der echten Seite nicht (mehr)
    # existiert - live verifiziert, dass TheFork stattdessen ein
    # Hash-Fragment ("#booking=&date=...&partySize=...") beim initialen
    # Laden liest, ganz ohne Klick-Simulation.
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "nobless-r598675#booking=&date=2026-08-28&partySize=2" in script
    assert "calendar-day-2026-08-28" not in script
    assert "Reservieren" not in script
    assert 'timeslot-' in script


def test_only_slots_matching_time_pattern_are_kept_service_headers_excluded():
    # TheForks Widget rendert neben den echten Uhrzeit-Buttons
    # ("timeslot-17:00") auch zwei Abschnittsueberschriften
    # ("timeslot-service-lunch"/"timeslot-service-diner") mit demselben
    # data-testid-Praefix - die duerfen nicht als Uhrzeiten durchrutschen.
    # Der Filter passiert im Browser-JS; hier wird nur sichergestellt, dass
    # das ausgelieferte Regex-Muster im Skript tatsaechlich HH:MM verlangt.
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "^timeslot-\\\\d{1,2}:\\\\d{2}$" in script
