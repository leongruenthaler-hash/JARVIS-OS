"""Tests fuer den PermissionManager-Staleness-Fix (gleiches Bug-Muster wie
Memory/ModelManager, siehe docs/current-system-assessment.md Abschnitt 19/20):
PermissionManager() wird an fast jeder Aufrufstelle (ensure_permission(),
handle_privacy_command(), ...) frisch, funktions-lokal gebaut statt eine
gemeinsame Instanz wiederzuverwenden - waehrend local_server.py langlebige
Instanzen (self.permissions, self.dashboard.permission_manager) nur lesend
nutzt. Ohne Fix wuerde eine Aenderung ueber eine kurzlebige Instanz fuer die
langlebigen Instanzen unsichtbar bleiben, bis der Prozess neu startet.
"""

from permission_manager import PermissionManager


def test_grant_via_one_instance_is_visible_via_another(tmp_path):
    long_lived = PermissionManager(base_path=tmp_path)
    assert long_lived.is_allowed("mail") is False

    short_lived = PermissionManager(base_path=tmp_path)
    short_lived.grant("mail", source="test")

    assert long_lived.is_allowed("mail") is True


def test_revoke_via_one_instance_is_visible_via_another(tmp_path):
    first = PermissionManager(base_path=tmp_path)
    first.grant("calendar", source="test")

    second = PermissionManager(base_path=tmp_path)
    assert second.is_allowed("calendar") is True

    second.revoke("calendar", source="test")

    assert first.is_allowed("calendar") is True or first.is_allowed("calendar") is False
    # Die eigentliche Behauptung: `first` sieht die Aenderung von `second`,
    # nicht nur `second` sich selbst.
    assert first.is_allowed("calendar") is False


def test_alternating_grants_across_instances_do_not_clobber_each_other(tmp_path):
    """Reproduziert die urspruengliche Sorge direkt: mehrere kurzlebige
    Instanzen aendern nacheinander verschiedene Berechtigungen - keine geht
    verloren, unabhaengig davon, welche Instanz zuletzt geschrieben hat."""
    PermissionManager(base_path=tmp_path).grant("mail", source="a")
    PermissionManager(base_path=tmp_path).grant("calendar", source="b")
    PermissionManager(base_path=tmp_path).grant("notes", source="c")

    final = PermissionManager(base_path=tmp_path)
    assert final.is_allowed("mail") is True
    assert final.is_allowed("calendar") is True
    assert final.is_allowed("notes") is True


def test_export_reflects_fresh_state(tmp_path):
    long_lived = PermissionManager(base_path=tmp_path)
    assert long_lived.export()["photos"]["allowed"] is False

    PermissionManager(base_path=tmp_path).grant("photos", source="test")

    assert long_lived.export()["photos"]["allowed"] is True


def test_summary_reflects_fresh_state(tmp_path):
    long_lived = PermissionManager(base_path=tmp_path)
    assert "music" in long_lived.summary().split("Deaktiviert:")[1]

    PermissionManager(base_path=tmp_path).grant("music", source="test")

    assert "music" in long_lived.summary().split("Aktive Berechtigungen:")[1].split(".")[0]


def test_mark_explanation_shown_does_not_clobber_a_concurrent_grant(tmp_path):
    a = PermissionManager(base_path=tmp_path)
    b = PermissionManager(base_path=tmp_path)

    a.grant("files", source="test")
    b.mark_explanation_shown("screen")

    final = PermissionManager(base_path=tmp_path)
    assert final.is_allowed("files") is True
    assert final.data["screen"]["explanation_shown"] is True
