"""Tests fuer jarvis.py::handle_privacy_command()'s Erlauben/Verbieten-Erkennung.

Regressionstest fuer einen live gefundenen Bug: "aktiviere" ist ein Teilstring
von "deaktiviere" ("de" + "aktiviere") - ohne Wortgrenze (\\b) im grant_match-
Regex loeste "deaktiviere dateien" faelschlich das Erlauben aus (grant_match
wird vor revoke_match geprueft), obwohl der Nutzer die Berechtigung entziehen
wollte.

handle_privacy_command() baut intern ein eigenes `PermissionManager()` ohne
base_path (landet sonst in den echten Produktivdaten) - hier per monkeypatch
auf eine Test-Instanz mit tmp_path umgeleitet, analog zum bestehenden Muster
in tests/test_multistep_planner.py.
"""

import pytest

import jarvis
from memory import Memory
from permission_manager import PermissionManager


@pytest.fixture
def manager_factory(tmp_path, monkeypatch):
    def factory(*args, **kwargs):
        return PermissionManager(base_path=tmp_path)

    monkeypatch.setattr(jarvis, "PermissionManager", factory)
    return lambda: PermissionManager(base_path=tmp_path)


def test_deaktiviere_revokes_not_grants(tmp_path, manager_factory):
    memory = Memory(base_path=tmp_path)
    manager_factory().grant("files", source="test")

    answer = jarvis.handle_privacy_command(memory, "berechtigung deaktiviere dateien")

    assert answer is not None
    assert "Deaktiviert" in answer
    assert manager_factory().is_allowed("files") is False


def test_aktiviere_still_grants(tmp_path, manager_factory):
    memory = Memory(base_path=tmp_path)

    answer = jarvis.handle_privacy_command(memory, "berechtigung aktiviere dateien")

    assert answer is not None
    assert "Erlaubt" in answer
    assert manager_factory().is_allowed("files") is True


def test_erlaube_still_grants(tmp_path, manager_factory):
    memory = Memory(base_path=tmp_path)

    answer = jarvis.handle_privacy_command(memory, "berechtigung erlaube kalender")

    assert answer is not None
    assert "Erlaubt" in answer
    assert manager_factory().is_allowed("calendar") is True


def test_verbiete_still_revokes(tmp_path, manager_factory):
    memory = Memory(base_path=tmp_path)
    manager_factory().grant("mail", source="test")

    answer = jarvis.handle_privacy_command(memory, "berechtigung verbiete mail")

    assert answer is not None
    assert "Deaktiviert" in answer
    assert manager_factory().is_allowed("mail") is False
