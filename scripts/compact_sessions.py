#!/usr/bin/env python3
"""Komprimiert automatisch alle OpenClaw-Sessions, die ueber einer
Token-Schwelle liegen (2026-09-13, Nutzerwunsch: "Jarvis soll in einem
gewissen Zyklus selbst das Kontingent wieder kompakter machen").

Hintergrund: JarvisMobile und die WhatsApp-Bridge behalten aus Gruenden der
Gespraechs-Kontinuitaet dieselbe Session dauerhaft bei (stabile Session-IDs
pro Geraet/Kontakt) - ohne aktives Eingreifen waechst der Verlauf
unbegrenzt, bis jede noch so kurze Nachricht den kompletten alten Kontext
mitverarbeitet (live beobachtet 2026-09-13: 314.369 Tokens fuer ein paar
Saetze). `agents.defaults.compaction.maxActiveTranscriptBytes` (300kb, siehe
Config) faengt neues Wachstum jetzt proaktiv ab, dieses Skript raeumt
zusaetzlich turnusmaessig ALLE Sessions auf, die trotzdem ueber die
Schwelle gewachsen sind - z.B. weil der eingebaute Schwellenwert erst beim
naechsten Turn greift, nicht rueckwirkend.

Laeuft als "command"-Cronjob (kein agentTurn noetig - reine Wartungsarbeit,
kein LLM-Urteilsvermoegen erforderlich), siehe die Cron-Automation
"session-compaction-sweep".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

OPENCLAW_PATH = os.environ.get("OPENCLAW_BIN", "/opt/homebrew/bin/openclaw")
SUBPROCESS_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
}
# Ab dieser Groesse gilt eine Session als "aufgeblaeht genug, um jetzt schon
# einzugreifen", statt auf den naechsten normalen Turn zu warten.
TOKEN_THRESHOLD = 50_000


def list_sessions() -> list[dict]:
    result = subprocess.run(
        [OPENCLAW_PATH, "sessions", "--all-agents", "--json", "--limit", "all"],
        capture_output=True,
        text=True,
        timeout=30,
        env=SUBPROCESS_ENV,
        check=True,
    )
    data = json.loads(result.stdout)
    return data.get("sessions", [])


def compact_session(key: str, agent_id: str) -> dict:
    result = subprocess.run(
        [OPENCLAW_PATH, "sessions", "compact", key, "--agent", agent_id, "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        env=SUBPROCESS_ENV,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}


def main() -> None:
    sessions = list_sessions()
    candidates = [
        session for session in sessions
        if isinstance(session.get("totalTokens"), (int, float)) and session["totalTokens"] > TOKEN_THRESHOLD
    ]
    if not candidates:
        print(json.dumps({"compacted": [], "message": "Keine Session ueber der Schwelle."}))
        return

    report = []
    for session in candidates:
        key = session["key"]
        agent_id = session.get("agentId", "main")
        outcome = compact_session(key, agent_id)
        report.append({
            "key": key,
            "tokens_before": session["totalTokens"],
            "tokens_after": outcome.get("result", {}).get("tokensAfter"),
            "ok": outcome.get("ok", False),
        })

    print(json.dumps({"compacted": report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
