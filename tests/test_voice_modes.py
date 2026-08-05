"""Unit tests for conversation modes (app/core/voice_modes.py, Phase E)."""

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
CORE_DIR = APP_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from voice_modes import (  # noqa: E402
    VOICE_MODES,
    DEFAULT_VOICE_MODE,
    is_valid_mode,
    normalize_mode,
    mode_instruction,
    forces_compact,
    suppresses_voice_output,
    forces_local_only,
    disables_web_search,
    mode_label,
)


def test_all_five_modes_defined():
    assert set(VOICE_MODES) == {"kurz", "standard", "fokus", "diskret", "privat"}


def test_default_mode_is_standard():
    assert DEFAULT_VOICE_MODE == "standard"


def test_normalize_mode_passes_through_valid():
    for mode in VOICE_MODES:
        assert normalize_mode(mode) == mode


def test_normalize_mode_falls_back_for_invalid():
    assert normalize_mode("nicht-real") == "standard"
    assert normalize_mode(None) == "standard"
    assert normalize_mode("") == "standard"


def test_standard_mode_has_no_instruction():
    assert mode_instruction("standard") == ""


def test_kurz_and_fokus_have_distinct_instructions():
    kurz = mode_instruction("kurz")
    fokus = mode_instruction("fokus")
    assert kurz and fokus
    assert kurz != fokus
    assert "knapp" in kurz.lower()
    assert "ausführlich" in fokus.lower()


def test_forces_compact_only_for_kurz_and_diskret():
    assert forces_compact("kurz") is True
    assert forces_compact("diskret") is True
    assert forces_compact("standard") is False
    assert forces_compact("fokus") is False
    assert forces_compact("privat") is False


def test_suppresses_voice_output_only_for_diskret():
    assert suppresses_voice_output("diskret") is True
    for mode in ("kurz", "standard", "fokus", "privat"):
        assert suppresses_voice_output(mode) is False


def test_forces_local_only_only_for_privat():
    assert forces_local_only("privat") is True
    for mode in ("kurz", "standard", "fokus", "diskret"):
        assert forces_local_only(mode) is False


def test_disables_web_search_matches_forces_local_only():
    for mode in VOICE_MODES:
        assert disables_web_search(mode) == forces_local_only(mode)


def test_invalid_mode_behaves_like_standard():
    assert forces_compact("garbage") == forces_compact("standard")
    assert suppresses_voice_output("garbage") == suppresses_voice_output("standard")
    assert mode_instruction("garbage") == mode_instruction("standard")


def test_mode_label_returns_readable_text_for_every_mode():
    for mode in VOICE_MODES:
        label = mode_label(mode)
        assert label
        assert label != mode  # actual German label, not just the raw key
