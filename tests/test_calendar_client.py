"""Tests fuer die numerischen Datumsfelder in app/calendar_client.py und den
darauf aufbauenden "nur heute"-Bugfix in app/jarvis.py::answer_calendar_query().
Siehe plans/2026-08-08-jarvis-termin-nudges.md.

Reine Funktionslogik - kein echter AppleScript-/Calendar.app-Aufruf noetig,
die AppleScript-Ausgabe wird als Text simuliert (dasselbe Format, das das
echte Skript liefert: ASCII-31-getrennte Felder, ASCII-30-getrennte Records).
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from calendar_client import _parse_calendar_items
import jarvis

FS = chr(31)
RS = chr(30)


def _fake_record(calendar, title, start_year, start_month, start_day, start_hour, start_minute, all_day="false"):
    # end date irrelevant fuer die meisten Tests hier - identisch zum Start gesetzt.
    fields = [
        calendar, title, "irrelevant-text", "irrelevant-text",
        str(start_year), str(start_month), str(start_day), str(start_hour), str(start_minute),
        str(start_year), str(start_month), str(start_day), str(start_hour), str(start_minute),
        all_day,
    ]
    return FS.join(fields)


def test_parse_calendar_items_builds_start_dt():
    raw = _fake_record("Kalender", "Meeting", 2026, 8, 10, 14, 5) + RS
    items = _parse_calendar_items(raw)
    assert len(items) == 1
    assert items[0]["title"] == "Meeting"
    assert items[0]["start_dt"] == datetime(2026, 8, 10, 14, 5)
    assert items[0]["all_day"] is False


def test_parse_calendar_items_all_day_flag():
    raw = _fake_record("Kalender", "Urlaub", 2026, 8, 10, 0, 0, all_day="true") + RS
    items = _parse_calendar_items(raw)
    assert items[0]["all_day"] is True


def test_parse_calendar_items_handles_malformed_record_without_crashing():
    # Zu wenige Felder (z.B. durch einen unerwarteten AppleScript-Fehlerfall) -
    # start_dt/end_dt muessen None werden, nicht crashen.
    raw = FS.join(["Kalender", "Kaputt"]) + RS
    items = _parse_calendar_items(raw)
    assert len(items) == 1
    assert items[0]["start_dt"] is None
    assert items[0]["end_dt"] is None


def test_parse_calendar_items_existing_text_fields_still_present():
    raw = _fake_record("Kalender", "Meeting", 2026, 8, 10, 14, 5) + RS
    items = _parse_calendar_items(raw)
    # Bestehende Aufrufstellen lesen weiterhin "start"/"end" als Text - muessen
    # unveraendert vorhanden bleiben (additive Erweiterung, siehe Plan).
    assert items[0]["start"] == "irrelevant-text"
    assert items[0]["end"] == "irrelevant-text"


def test_answer_calendar_query_today_excludes_far_future_events():
    """Regressionstest fuer den gemeldeten Bug: 'was steht heute an' zeigte
    Termine aus dem ganzen Jahr statt nur von heute."""
    now = datetime.now()
    # Feste Uhrzeit relativ zum Tagesanfang statt "now + 1h" - andernfalls rollt der
    # Termin kurz vor Mitternacht auf den naechsten Kalendertag und der Test wird
    # abhaengig von der Uhrzeit, zu der er laeuft, faelschlich rot.
    today_start = datetime(now.year, now.month, now.day)
    fake_items = [
        {
            "title": "Heute-Termin", "start": "heute", "end": "heute",
            "start_dt": today_start + timedelta(hours=9), "end_dt": today_start + timedelta(hours=10), "all_day": False,
        },
        {
            "title": "Weit-weg-Termin", "start": "weit weg", "end": "weit weg",
            "start_dt": now + timedelta(days=90), "end_dt": now + timedelta(days=90, hours=1), "all_day": False,
        },
    ]

    with patch("jarvis.list_upcoming_calendar_items", return_value={"items": fake_items}):
        answer = jarvis.answer_calendar_query("was steht heute noch an", "was steht heute noch an")

    assert "Heute-Termin" in answer
    assert "Weit-weg-Termin" not in answer


def test_answer_calendar_query_today_keeps_events_with_unparseable_start_dt():
    """Ein Termin ohne start_dt (Parsing fehlgeschlagen) darf nicht faelschlich
    herausgefiltert werden - sonst behauptet Jarvis "keine Termine heute",
    obwohl welche existieren."""
    fake_items = [
        {"title": "Unklar", "start": "unklar", "end": "unklar", "start_dt": None, "end_dt": None, "all_day": False},
    ]

    with patch("jarvis.list_upcoming_calendar_items", return_value={"items": fake_items}):
        answer = jarvis.answer_calendar_query("was steht heute noch an", "was steht heute noch an")

    assert "Unklar" in answer


def test_answer_calendar_query_not_today_is_unaffected():
    now = datetime.now()
    fake_items = [
        {
            "title": "Naechste-Woche", "start": "naechste woche", "end": "naechste woche",
            "start_dt": now + timedelta(days=5), "end_dt": now + timedelta(days=5, hours=1), "all_day": False,
        },
    ]

    with patch("jarvis.list_upcoming_calendar_items", return_value={"items": fake_items}):
        answer = jarvis.answer_calendar_query("welche termine habe ich", "welche termine habe ich")

    assert "Naechste-Woche" in answer
