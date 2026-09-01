"""Regressionstest fuer einen beim Live-Testen von MailBackgroundWorker gefundenen Bug
(siehe plans/2026-08-09-jarvis-mail-hintergrund-aktivieren.md): list_inbox_messages()
rief _run_applescript() immer mit dessen 8-Sekunden-Default auf, unabhaengig davon, ob
include_preview=True den vollen Mail-Inhalt fuer bis zu 20 (morgens) bzw. 80 (nachts)
Nachrichten abruft - das ist deutlich langsamer als reine Metadaten und lief beim echten
Test auch mit bereits geoeffnetem Mail.app in den Timeout (8s + 12s Retry)."""

from unittest.mock import patch

from mail_client import list_inbox_messages


def test_list_inbox_messages_uses_default_timeout_without_preview():
    # War lange 8s, auf 20s angehoben (2026-09-02) - unter spuerbarer Systemlast
    # (fileproviderd/iCloud-Nachhol-Sync) reichte selbst 8s+12s-Retry nicht,
    # obwohl Mail.app bereits offen und in Benutzung war.
    with patch("mail_client._run_applescript", return_value="") as fake_run:
        list_inbox_messages(max_messages=20, include_preview=False)

    _, kwargs = fake_run.call_args
    assert kwargs["timeout"] == 20


def test_list_inbox_messages_scales_timeout_with_preview_and_message_count():
    with patch("mail_client._run_applescript", return_value="") as fake_run:
        list_inbox_messages(max_messages=20, include_preview=True)

    _, kwargs = fake_run.call_args
    assert kwargs["timeout"] > 20


def test_list_inbox_messages_preview_timeout_capped_at_sixty():
    with patch("mail_client._run_applescript", return_value="") as fake_run:
        list_inbox_messages(max_messages=80, include_preview=True)

    _, kwargs = fake_run.call_args
    assert kwargs["timeout"] == 60
