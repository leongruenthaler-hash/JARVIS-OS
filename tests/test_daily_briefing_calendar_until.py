"""Test fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Tagesbriefing-Bug: list_upcoming_calendar_items() wurde ohne "until"-Grenze
aufgerufen und iteriert Kalender-fuer-Kalender in beliebiger (nicht nach
Datum sortierter) Reihenfolge - bei limit=10 konnte ein heutiger Termin aus
einem spaeter durchsuchten Kalender komplett unter den Tisch fallen, bevor
events_on_date() ueberhaupt zum Filtern kam. local_server.py::daily_briefing()
hatte das "until"-Limit bereits, jarvis.py::handle_daily_briefing_command()
nicht - beide sollten laut Kommentar konsistent sein. Siehe
docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import patch

import jarvis
from memory import Memory


def test_calendar_fetch_passes_until_bound(tmp_path):
    memory = Memory(base_path=tmp_path)
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": []}) as fake_list, \
         patch.object(jarvis, "list_open_reminders", return_value={"items": []}), \
         patch.object(jarvis, "TaskManager") as fake_task_manager, \
         patch.object(jarvis, "has_permission", return_value=False):
        fake_task_manager.return_value.list_tasks.return_value = []
        jarvis.handle_daily_briefing_command(memory, "Gib mir mein Tagesbriefing")

    fake_list.assert_called_once()
    assert fake_list.call_args.kwargs.get("until") is not None
    assert fake_list.call_args.kwargs.get("limit") == 20


def test_todays_calendar_event_appears_in_briefing(tmp_path):
    from datetime import datetime

    memory = Memory(base_path=tmp_path)
    today_event = {"title": "Zahnarzt", "start": "13.08.2026 um 15:00", "start_dt": datetime.now()}
    with patch.object(jarvis, "list_upcoming_calendar_items", return_value={"items": [today_event]}), \
         patch.object(jarvis, "list_open_reminders", return_value={"items": []}), \
         patch.object(jarvis, "TaskManager") as fake_task_manager, \
         patch.object(jarvis, "has_permission", return_value=False):
        fake_task_manager.return_value.list_tasks.return_value = []
        briefing = jarvis.handle_daily_briefing_command(memory, "Gib mir mein Tagesbriefing")

    assert "Zahnarzt" in briefing
