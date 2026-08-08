from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path


class ScreenAccessError(RuntimeError):
    pass


_FRONTMOST_WINDOW_SCRIPT = """
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set frontAppName to name of frontApp
    try
        set frontWindow to first window of frontApp whose value of attribute "AXMain" is true
    on error
        set frontWindow to front window of frontApp
    end try
    set winID to id of frontWindow
end tell
return frontAppName & "|" & winID
"""


def _new_target_path() -> Path:
    return Path(tempfile.gettempdir()) / f"jarvis_screen_{os.getpid()}_{int(time.time() * 1000)}.png"


def _run_screencapture(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["screencapture", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ScreenAccessError("screencapture ist auf diesem System nicht verfügbar.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScreenAccessError("Bildschirmaufnahme hat zu lange gedauert.") from exc


def _check_capture_result(result: subprocess.CompletedProcess, target: Path) -> None:
    if result.returncode != 0 or not target.exists() or target.stat().st_size <= 0:
        detail = (result.stderr or "").strip()
        raise ScreenAccessError(
            "Bildschirmaufnahme fehlgeschlagen - vermutlich fehlt die "
            "Bildschirmaufnahme-Berechtigung in Systemeinstellungen > "
            "Datenschutz & Sicherheit > Bildschirmaufnahme."
            + (f" ({detail})" if detail else "")
        )


def capture_screenshot(timeout: float = 10.0) -> Path:
    """Captures the whole screen (all displays) via macOS' built-in `screencapture`
    CLI (no extra permission library needed - screencapture itself triggers the
    system Screen-Recording TCC prompt on first use, same as any other macOS app).

    Writes to a per-process temp file rather than anywhere under data_root(), so a
    stale screenshot never lingers in the app's own memory/cache directories -
    callers are expected to delete the returned path once they're done with it
    (see describe_screen())."""
    target = _new_target_path()
    try:
        result = _run_screencapture(["-x", "-t", "png", str(target)], timeout)
        _check_capture_result(result, target)
    except Exception:
        # Don't leave a failed/partial capture (garbage bytes, zero-length file,
        # or whatever screencapture wrote before a timeout killed it) sitting on
        # disk - a screenshot of the user's screen must not linger past a failure.
        target.unlink(missing_ok=True)
        raise
    try:
        # screencapture creates the file with the process umask (typically 0644,
        # world-readable) - narrow it to the owner only, since this is a raw
        # screenshot of the user's screen and the temp dir isn't guaranteed private.
        target.chmod(0o600)
    except OSError:
        pass
    return target


def frontmost_window() -> tuple[str, int] | None:
    """Best-effort lookup of the active app name + its main window's CGWindowID via
    System Events (AppleScript) - needs macOS Accessibility permission for the
    Jarvis process, separate from the Screen-Recording permission `screencapture`
    itself needs. Returns None (never raises) if System Events can't answer -
    callers should fall back to a whole-screen capture in that case, since not
    finding the exact window is not a reason to fail the whole request."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _FRONTMOST_WINDOW_SCRIPT],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if "|" not in output:
        return None
    app_name, _, window_id_text = output.rpartition("|")
    try:
        return app_name.strip(), int(window_id_text.strip())
    except ValueError:
        return None


def capture_window_screenshot(window_id: int, timeout: float = 10.0) -> Path:
    """Captures a single window by CGWindowID (`-l`), with a transparent
    background outside the window bounds (`-o` drops the drop-shadow but keeps
    only that window's pixels) - deliberately narrower than a full-screen capture
    so other apps/windows the user has open never end up in the image at all."""
    target = _new_target_path()
    try:
        result = _run_screencapture(["-x", "-o", "-t", "png", "-l", str(window_id), str(target)], timeout)
        _check_capture_result(result, target)
    except Exception:
        # Same reasoning as capture_screenshot(): never leave a failed/partial
        # window capture behind on disk.
        target.unlink(missing_ok=True)
        raise
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def capture_active_window_screenshot(timeout: float = 10.0) -> tuple[Path, str]:
    """Preferred entry point: captures just the frontmost app's window instead of
    the whole screen. Falls back to a full-screen capture if the active window
    can't be identified (e.g. Accessibility permission not granted) - still
    better than failing the request outright, and no more data than the previous
    whole-screen-only behavior."""
    located = frontmost_window()
    if located is None:
        return capture_screenshot(timeout=timeout), ""
    app_name, window_id = located
    try:
        return capture_window_screenshot(window_id, timeout=timeout), app_name
    except ScreenAccessError:
        return capture_screenshot(timeout=timeout), app_name


def discard_screenshot(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
