"""Tests fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Kalender-Bug: "morgen" und "diese Woche" lieferten wortgleich dieselbe,
ungefilterte Terminliste wie eine Anfrage ganz ohne Zeitangabe - nur "heute"
filterte tatsaechlich. Siehe docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import patch

import jarvis


def _item(title, start_dt):
    return {"title": title, "start": start_dt.strftime("%d.%m.%Y um %H:%M"), "start_dt": start_dt}


def test_tomorrow_query_passes_until_and_filters_to_tomorrow():
    from datetime import datetime, timedelta

    tomorrow = datetime.now() + timedelta(days=1)
    items = [_item("Zahnarzt", tomorrow)]

    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": items}) as fake_list, \
         patch.object(jarvis, "events_on_date", wraps=jarvis.events_on_date) as fake_filter:
        answer = jarvis.answer_calendar_query("was hab ich morgen vor", jarvis.normalize_text("was hab ich morgen vor"))

    fake_list.assert_called_once()
    assert fake_list.call_args.kwargs.get("until") is not None
    fake_filter.assert_called_once()
    assert "Morgen steht an" in answer
    assert "Zahnarzt" in answer


def test_this_week_query_passes_until_bound():
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}) as fake_list:
        answer = jarvis.answer_calendar_query(
            "was steht diese woche in meinem kalender", jarvis.normalize_text("was steht diese woche in meinem kalender")
        )

    fake_list.assert_called_once()
    assert fake_list.call_args.kwargs.get("until") is not None
    assert "diese Woche" in answer


def test_bare_query_without_time_word_uses_no_until_bound():
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}) as fake_list:
        jarvis.answer_calendar_query("was steht in meinem kalender", jarvis.normalize_text("was steht in meinem kalender"))

    fake_list.assert_called_once()
    assert fake_list.call_args.kwargs.get("until") is None


def test_today_query_still_works_as_before():
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}) as fake_list:
        answer = jarvis.answer_calendar_query("was hab ich heute vor", jarvis.normalize_text("was hab ich heute vor"))

    fake_list.assert_called_once()
    assert fake_list.call_args.kwargs.get("until") is not None
    assert "Für heute sehe ich keine Termine." == answer
