"""Tests fuer die lokale-Server-Haertung vom Mac-Mini-Umbau (Plan
"Jarvis proaktiv machen", 2026-09-03, Phase 1): das Auth-Token wird jetzt
einmalig erzeugt und dauerhaft geladen statt bei jedem Prozessstart neu erzeugt
(sonst wuerde ein Reboot des Mac Mini alle gepaarten Clients aussperren, ohne
dass jemand den neuen Wert abholen koennte), plus eine simple IP-basierte
Rate-Limitierung fehlgeschlagener Token-Versuche (portiert aus
remote_worker_server.py, das dieselbe Notwendigkeit schon frueher hatte)."""

from unittest.mock import patch

import local_server as ls


def test_load_or_create_auth_token_generates_once_and_persists(tmp_path):
    with patch.object(ls, "data_root", return_value=tmp_path):
        first = ls._load_or_create_auth_token()
        token_path = tmp_path / ls.AUTH_TOKEN_FILENAME
        assert token_path.exists()
        assert token_path.read_text(encoding="utf-8").strip() == first


def test_load_or_create_auth_token_reuses_existing_value_across_calls(tmp_path):
    with patch.object(ls, "data_root", return_value=tmp_path):
        first = ls._load_or_create_auth_token()
        # Simuliert einen zweiten Prozessstart (z.B. nach einem Reboot): der Token darf
        # sich NICHT aendern, sonst waeren gepaarte Clients ausgesperrt.
        ls.AUTH_TOKEN = None
        second = ls._load_or_create_auth_token()
        assert first == second


def test_rotate_auth_token_produces_a_new_persisted_value(tmp_path):
    with patch.object(ls, "data_root", return_value=tmp_path):
        first = ls._load_or_create_auth_token()
        rotated = ls._rotate_auth_token()
        assert rotated != first
        token_path = tmp_path / ls.AUTH_TOKEN_FILENAME
        assert token_path.read_text(encoding="utf-8").strip() == rotated


def test_rate_limit_blocks_after_max_failures_from_same_ip():
    ip = "10.0.0.42"
    ls._failure_log.pop(ip, None)
    try:
        for _ in range(ls._RATE_LIMIT_MAX_FAILURES):
            assert not ls._is_rate_limited(ip)
            ls._record_failure(ip)
        assert ls._is_rate_limited(ip)
    finally:
        ls._failure_log.pop(ip, None)


def test_rate_limit_is_per_ip_not_global():
    ip_a, ip_b = "10.0.0.1", "10.0.0.2"
    ls._failure_log.pop(ip_a, None)
    ls._failure_log.pop(ip_b, None)
    try:
        for _ in range(ls._RATE_LIMIT_MAX_FAILURES):
            ls._record_failure(ip_a)
        assert ls._is_rate_limited(ip_a)
        assert not ls._is_rate_limited(ip_b)
    finally:
        ls._failure_log.pop(ip_a, None)
        ls._failure_log.pop(ip_b, None)


def test_run_defaults_stay_loopback_when_config_has_no_override():
    assert ls.CONFIG.get("local_server_bind_host", "127.0.0.1") == "127.0.0.1"
    assert int(ls.CONFIG.get("local_server_port", 8765)) == 8765
