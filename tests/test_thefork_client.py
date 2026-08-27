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
        '[{"time":"17:00","available":true},{"time":"17:30","available":false},'
        '{"time":"19:00","available":true}]'
    )
    with patch.object(thefork_client.subprocess, "run", return_value=_fake_result(stdout=stdout)):
        result = thefork_client.fetch_available_time_slots(
            "https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2
        )
    assert result == ["17:00", "19:00"]


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


def test_non_list_json_returns_none():
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
    assert 'starts with "https://www.thefork.de/restaurant/nobless-r598675?date=2026-08-28&partySize=2"' in cleanup_script
    assert "contains" not in cleanup_script


def test_unexpected_exception_returns_none_not_raised():
    # Regression: nur (TimeoutExpired, OSError) wurden gefangen - ein
    # unerwarteter Fehler (z.B. aus einer kuenftigen Markup-Aenderung bei
    # TheFork) haette den aufrufenden Chat-Turn crashen lassen (Codex-
    # Adversarial-Review 2026-08-27).
    with patch.object(thefork_client.subprocess, "run", side_effect=RuntimeError("unerwartet")):
        assert thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/x", "2026-08-28", 2) is None


def test_script_checks_each_click_result_and_cleans_up_on_error():
    # Regression: die Klick-Skripte gaben vorher unconditional 'true' zurueck,
    # auch wenn der Button/Kalendertag gar nicht gefunden wurde - eine leere
    # Uhrzeit-Liste war dann von echter Nichtverfuegbarkeit nicht zu
    # unterscheiden (Codex-Review 2026-08-27, P1).
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert 'if reserveClicked is not "true" then error' in script
    assert 'if dateClicked is not "true" then error' in script
    assert "on error errMsg" in script
    assert script.count("close theTab") >= 2  # Erfolgspfad UND Fehlerpfad


def test_script_retries_up_to_twice_on_empty_result_before_accepting_it():
    # Regression: zuerst gab es gar keinen Retry, dann nur einen einzelnen
    # festen - beides reichte bei einer langsam ladenden Seite u.U. nicht,
    # eine leere Liste wurde dann faelschlich als "definitiv ausgebucht"
    # statt als "noch am Laden" gewertet (Codex-Review 2026-08-27, zweite
    # und dritte Runde - die dritte Runde verlangte eine mehrfache statt nur
    # einmaliger Wiederholung).
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "repeat 2 times" in script
    assert 'if slotsJson is not "[]" then exit repeat' in script
    assert script.count("do JavaScript") >= 3  # reserve + date + mindestens ein Lese-Versuch, der Retry-Block ist ein weiterer


def test_url_and_selectors_are_correctly_embedded():
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["script"] = cmd[2]
        return _fake_result(stdout="[]")

    with patch.object(thefork_client.subprocess, "run", side_effect=_fake_run):
        thefork_client.fetch_available_time_slots("https://www.thefork.de/restaurant/nobless-r598675", "2026-08-28", 2)

    script = captured["script"]
    assert "nobless-r598675?date=2026-08-28&partySize=2" in script
    assert "calendar-day-2026-08-28" in script
