"""Duenner Wrapper um die lokal installierte 'claude'-CLI (Claude Code), damit Jarvis
Claude ueber das bestehende Abo (Pro/Max) nutzen kann statt ueber die separat
abgerechnete Anthropic-API. Nutzt --print/--output-format json fuer eine einzelne,
nicht-interaktive Antwort.

Zwei Betriebsarten:
- ask_claude_code(): --tools "" (alle Werkzeuge deaktiviert) - der normale Frage-
  Antwort-Pfad (Chat, Mail-Zusammenfassung etc.), darf nie Dateien/Bash anfassen.
- ask_claude_code_research(): Read/Grep/Glob/WebSearch aktiviert, aber NUR innerhalb
  eines macOS-Sandbox-Profils (sandbox-exec), das den Dateizugriff hart auf
  bestimmte Ordner beschraenkt. Wichtig: --add-dir allein ist KEINE Sicherheits-
  grenze (live getestet 2026-09-02 - der Prozess konnte damit trotzdem Dateien
  ausserhalb lesen, z.B. den eigenen Jarvis-Auth-Token), deshalb erzwingt diese
  Funktion zusaetzlich sandbox-exec. WebFetch ist bewusst NIE erlaubt (auch nicht
  im Sandbox-Modus) - kombiniert mit Read waere das ein Exfiltrationsweg fuer
  alles, was das Modell gelesen hat, an eine beliebige externe URL."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CLAUDE_BINARY_NAME = "claude"
SANDBOX_EXEC_BINARY = "sandbox-exec"

_AVAILABILITY_CACHE: tuple[float, bool] = (0.0, False)
_AVAILABILITY_CACHE_SECONDS = 30.0

RESEARCH_TOOLS = "Read,Grep,Glob,WebSearch"


class ClaudeCodeError(RuntimeError):
    """Claude Code CLI war nicht erreichbar, hat einen Fehler geliefert oder eine
    unbrauchbare/leere Antwort zurueckgegeben."""


_COMMON_CLAUDE_INSTALL_PATHS: tuple[str, ...] = (
    "~/.local/bin/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)


def find_claude_binary() -> str | None:
    """Sucht die claude-CLI. shutil.which() allein reicht nicht - JarvisApp wird ueber
    Finder/LaunchServices gestartet, dessen PATH enthaelt nicht die Shell-rc-Ergaenzungen
    (z.B. ~/.local/bin), unter denen npm/curl-Installer die CLI typischerweise ablegen.
    Live beobachtet 2026-09-02: 'claude' war interaktiv im Terminal sofort auffindbar,
    im laufenden Jarvis-Prozess (geerbtes PATH ohne ~/.local/bin) aber nicht - deshalb
    zusaetzlich die ueblichen Installationsorte direkt pruefen."""
    found = shutil.which(CLAUDE_BINARY_NAME)
    if found:
        return found
    for candidate in _COMMON_CLAUDE_INSTALL_PATHS:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


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


def _run_claude(args: list[str], timeout: float, cwd: str | None = None) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL)
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
        # Deaktiviert CLAUDE.md-Auto-Discovery, Plugins, Hooks, Skills etc. - fuer
        # diesen reinen Frage-Antwort-Pfad irrelevanter Overhead, der pro Aufruf
        # spuerbar Kontext-Token (und damit Kontingent) kostet, live gemessen
        # 2026-09-01: cache_creation_input_tokens fiel von 6635 auf 1858 durch
        # diese eine Option, Login/Abo-Auth bleibt davon unberuehrt (anders als
        # --bare, das zwingend einen API-Key statt OAuth verlangt).
        "--safe-mode",
    ]
    if system_prompt.strip():
        args += ["--system-prompt", system_prompt]
    if model:
        args += ["--model", model]

    return _run_claude(args, timeout=timeout)


def _build_sandbox_profile(allowed_dirs: list[str]) -> str:
    """Baut ein macOS-Seatbelt-Profil (sandbox-exec), das Lesezugriff auf das
    Home-Verzeichnis grundsaetzlich verweigert und nur explizit whitelisted
    Unterordner (plus die claude-CLI-eigenen Konfigurationsordner und den
    Schluesselbund fuers Login) wieder freigibt. Live getestet 2026-09-02: mit
    "(deny default)" als Basis startete der claude-Prozess selbst gar nicht mehr
    (offenbar inkompatibel mit dessen Code-Signing/JIT-Anforderungen) - deshalb
    "(allow default)" als Basis mit gezielten Deny/Allow-Regeln fuer den
    Home-Ordner statt umgekehrt."""
    home = str(Path.home())
    allow_lines = "\n".join(f'  (subpath "{d}")' for d in allowed_dirs)
    return f"""(version 1)
(allow default)

(deny file-read*
  (subpath "{home}")
)

(allow file-read* file-write*
  (subpath "{home}/.claude")
  (subpath "{home}/.local")
)

(allow file-read*
  (subpath "{home}/Library/Keychains")
{allow_lines}
)
"""


def ask_claude_code_research(
    prompt: str,
    allowed_dirs: list[str],
    system_prompt: str = "",
    model: str = "sonnet",
    timeout: float = 120.0,
) -> str:
    """Wie ask_claude_code(), aber mit Read/Grep/Glob/WebSearch aktiviert - IMMER
    innerhalb einer sandbox-exec-Sandbox, die den Dateizugriff hart auf
    allowed_dirs beschraenkt. Ohne installiertes sandbox-exec (sollte auf jedem
    Mac vorhanden sein) wird das aus Sicherheitsgruenden abgelehnt statt
    stillschweigend ungeschuetzt zu laufen."""
    binary = find_claude_binary()
    if not binary:
        raise ClaudeCodeError(
            "Claude Code CLI ('claude') wurde nicht gefunden. Ist sie installiert und im PATH?"
        )
    sandbox_binary = shutil.which(SANDBOX_EXEC_BINARY)
    if not sandbox_binary:
        raise ClaudeCodeError(
            "sandbox-exec wurde nicht gefunden - ohne echte Sandbox darf Claude Code keinen "
            "Datei-/Web-Werkzeugzugriff bekommen."
        )
    if not prompt.strip():
        raise ClaudeCodeError("Leerer Prompt fuer Claude Code.")
    resolved_dirs = [str(Path(d).expanduser()) for d in allowed_dirs if str(d).strip()]
    if not resolved_dirs:
        raise ClaudeCodeError("Keine erlaubten Ordner fuer den Recherche-Modus konfiguriert.")

    profile_text = _build_sandbox_profile(resolved_dirs)
    fd, profile_path = tempfile.mkstemp(prefix="jarvis_claude_sandbox_", suffix=".sb")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(profile_text)

        args = [
            sandbox_binary,
            "-f",
            profile_path,
            binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--tools",
            RESEARCH_TOOLS,
            "--allowedTools",
            RESEARCH_TOOLS,
            "--no-session-persistence",
            "--safe-mode",
        ]
        for directory in resolved_dirs:
            args += ["--add-dir", directory]
        if system_prompt.strip():
            args += ["--system-prompt", system_prompt]
        if model:
            args += ["--model", model]

        # cwd MUSS innerhalb eines erlaubten Ordners liegen - der Prozess braucht
        # Lesezugriff auf sein eigenes Arbeitsverzeichnis nur um zu starten, sonst
        # schlaegt schon "claude --version" fehl (live beobachtet 2026-09-02).
        return _run_claude(args, timeout=timeout, cwd=resolved_dirs[0])
    finally:
        try:
            os.unlink(profile_path)
        except OSError:
            pass
