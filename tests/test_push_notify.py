from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import push_notify


def test_not_configured_returns_false_without_network_call():
    with patch.object(push_notify.urllib.request, "urlopen") as urlopen:
        assert push_notify.send_push({}, "Titel", "Text") is False
        urlopen.assert_not_called()


def test_configured_success_returns_true_and_sets_click_header():
    config = {"ntfy_host": "100.64.0.1", "ntfy_port": 8080, "ntfy_topic": "geheimes-topic"}
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    with patch.object(push_notify.urllib.request, "urlopen", return_value=response) as urlopen:
        result = push_notify.send_push(config, "Tisch bei Hans im Glück?", "19 Uhr, 2 Personen", url="https://example.com/reservieren")

    assert result is True
    sent_request = urlopen.call_args.args[0]
    assert sent_request.full_url == "http://100.64.0.1:8080/geheimes-topic"
    assert sent_request.headers["Click"] == "https://example.com/reservieren"


def test_network_error_returns_false_not_exception():
    config = {"ntfy_host": "100.64.0.1", "ntfy_port": 8080, "ntfy_topic": "geheimes-topic"}
    with patch.object(push_notify.urllib.request, "urlopen", side_effect=urllib.error.URLError("unreachable")):
        assert push_notify.send_push(config, "Titel", "Text") is False


def test_malformed_port_returns_false_not_exception():
    # Regression: int(ntfy_port) lag urspruenglich VOR dem try-Block - ein von
    # Hand falsch eingetragener config.json-Wert wie ein Text-Port haette den
    # gesamten Chat-/Proaktivitaets-Aufrufer zum Absturz gebracht (Codex-Review
    # 2026-08-23).
    config = {"ntfy_host": "100.64.0.1", "ntfy_port": "nicht-numerisch", "ntfy_topic": "x"}
    assert push_notify.send_push(config, "Titel", "Text") is False


def test_is_configured_requires_host_and_topic():
    assert push_notify.is_configured({}) is False
    assert push_notify.is_configured({"ntfy_host": "100.64.0.1"}) is False
    assert push_notify.is_configured({"ntfy_host": "100.64.0.1", "ntfy_topic": "x"}) is True
