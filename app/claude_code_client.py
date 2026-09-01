"""Duenner Wrapper um die lokal installierte 'claude'-CLI (Claude Code), damit Jarvis
Claude ueber das bestehende Abo (Pro/Max) nutzen kann statt ueber die separat
abgerechnete Anthropic-API. Nutzt --print/--output-format json fuer eine einzelne,
nicht-interaktive Antwort und --tools "" (alle Werkzeuge deaktiviert), damit dieser
reine Frage-Antwort-Pfad nie Dateien/Bash anfasst oder auf einen nie erscheinenden
Berechtigungsdialog wartet."""

from __future__ import annotations

import json
import shutil
import subprocess
import time

CLAUDE_BINARY_NAME = "claude"

_AVAILABILITY_CACHE: tuple[float, bool] = (0.0, False)
_AVAILABILITY_CACHE_SECONDS = 30.0


class ClaudeCodeError(RuntimeError):
    """Claude Code CLI war nicht erreichbar, hat einen Fehler geliefert oder eine
    unbrauchbare/leere Antwort zurueckgegeben."""


def find_claude_binary() -> str | None:
    return shutil.which(CLAUDE_BINARY_NAME)


def is_claude_code_available(*, force: bool = False) -> bool:
    """Prueft nur, ob die CLI installiert/im PATH ist - keine echte Netzwerk-/Auth-
    Pruefung, um jede Statusabfrage (z.B. fuer die Einstellungen-UI) nicht selbst
    einen Claude-Aufruf auszuloesen. Kurzzeitig gecacht, da das u.a. bei jeder
    Chat-Anfrage in ModelManager.provider gelesen wird."""
    global _AVAILABILITY_CACHE
    now = time.time()
    last_check, cached = _AVAILABILITY_CACHE
    if not force and now - last_check < _AVAILABILITY_CACHE_SECONDS:
        return cached
    available = find_claude_binary() is not None
    _AVAILABILITY_CACHE = (now, available)
    return available


def ask_claude_code(
    prompt: str,
    system_prompt: str = "",
    model: str = "sonnet",
    timeout: float = 90.0,
) -> str:
    binary = find_claude_binary()
    if not binary:
        raise ClaudeCodeError(
            "Claude Code CLI ('claude') wurde nicht gefunden. Ist sie installiert und im PATH?"
        )
    if not prompt.strip():
        raise ClaudeCodeError("Leerer Prompt fuer Claude Code.")

    args = [
        binary,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--tools",
        "",
        "--no-session-persistence",
    ]
    if system_prompt.strip():
        args += ["--system-prompt", system_prompt]
    if model:
        args += ["--model", model]

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeError(f"Claude Code hat nach {timeout:.0f} Sekunden nicht geantwortet.") from exc
    except OSError as exc:
        raise ClaudeCodeError(f"Claude Code konnte nicht gestartet werden: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ClaudeCodeError(f"Claude Code Fehler (Code {result.returncode}): {stderr[:300] or 'unbekannt'}")

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise ClaudeCodeError("Claude Code lieferte eine leere Antwort.")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # --output-format json sollte immer JSON liefern - falls doch nicht (z.B.
        # veraenderte CLI-Version), lieber den rohen Text als Antwort nehmen als
        # hart zu scheitern.
        return stdout

    if data.get("is_error"):
        raise ClaudeCodeError(f"Claude Code meldete einen Fehler: {str(data.get('result') or '')[:300]}")

    text = data.get("result")
    if isinstance(text, str) and text.strip():
        return text.strip()

    raise ClaudeCodeError("Claude Code Antwort enthielt kein 'result'-Feld.")
