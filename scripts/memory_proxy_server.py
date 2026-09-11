#!/usr/bin/env python3
"""Speicher-Proxy fuer JarvisApp (2026-09-11) - ersetzt den alten Backend-Pfad
(app/local_server.py -> app/memory.py -> long_memory.json) als Datenquelle fuer
die Gedaechtnis-Ansicht. Der alte Pfad ist inzwischen tot: OpenClaw ist jetzt
das eigentliche "Gehirn", sein Speicher liegt in
~/.openclaw/workspace/USER.md (kuratiere Nutzer-Direktiven) und
~/.openclaw/workspace/MEMORY.md (kuratierte Langzeitfakten, per naechtlichem
"Memory Dreaming"-Cron aus wiederholt abgerufenen Erinnerungen befuellt - kann
also anfangs leer sein, das ist normal, kein Fehler).

Liest NUR (kein Schreibzugriff auf USER.md - das ist OpenClaws eigene,
sorgfaeltig kuratierte Datei mit einem festen <!-- observed/status -->-Format;
ein zweiter, unkoordinierter Schreiber von aussen wuerde dieses Format leicht
kaputt machen). "Loeschen" in der App entfernt einen Eintrag zwar wirklich aus
der Quelldatei (der Nutzer soll falsche/veraltete Eintraege korrigieren
koennen), aber "Bestaetigen"/"Ablehnen" gibt es hier nicht mehr als Konzept -
alles hier ist bereits von OpenClaw selbst als dauerhaft kuratiert markiert,
liefert deshalb IMMER status "confirmed" (das laesst die bestehenden
Bestaetigen/Ablehnen-Knoepfe in MemoryView.swift automatisch verschwinden,
ganz ohne UI-Aenderung - siehe deren "if fact.status != confirmed"-Bedingung).

Tagesnotizen (memory/YYYY-MM-DD.md) werden bewusst NICHT eingelesen - das sind
freie, unstrukturierte Rohnotizen (Ueberschriften, Fliesstext, nummerierte
Listen), kein sauberes Fakten-Schema wie USER.md/MEMORY.md, und wuerden die
Graph-Ansicht nur mit Laerm fuellen statt echten, kuratierten Erinnerungen.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from mail_client import MailAccessError, list_inbox_messages  # noqa: E402
from notes_client import NotesAccessError, list_recent_notes  # noqa: E402

PORT = 18794
TOKEN_FILE = Path.home() / ".jarvis_memory_proxy_token"
OPENCLAW_BIN = "/opt/homebrew/bin/openclaw"
WORKSPACE = Path.home() / ".openclaw" / "workspace"
USER_MD_PATH = WORKSPACE / "USER.md"
MEMORY_MD_PATH = WORKSPACE / "MEMORY.md"
WHATSAPP_LOG_PATH = Path.home() / ".jarvis-whatsapp" / "messages.jsonl"
WHATSAPP_MAX_MESSAGES = 150
MAIL_MAX_MESSAGES = 60
MAIL_MAX_AGE_DAYS = 7

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
_MAIL_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*(\w+)\s+(\d{4})\s+um\s+(\d{1,2}):(\d{2}):(\d{2})"
)


def _parse_mail_received(value: str) -> datetime | None:
    """Parst Apple Mail's per-System-Locale formatiertes 'date received'-Datum, z.B.
    "Freitag, 11. September 2026 um 10:24:39" - nur fuer die 7-Tage-Filterung, nicht
    fuer irgendeine Anzeige. Liefert None statt zu werfen, wenn das Format mal
    abweicht (z.B. andere Locale) - eine nicht parsbare Mail wird dann sicherheitshalber
    trotzdem angezeigt statt stillschweigend zu verschwinden."""
    match = _MAIL_DATE_RE.search(value)
    if not match:
        return None
    day, month_name, year, hour, minute, second = match.groups()
    month = _GERMAN_MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), int(hour), int(minute), int(second))
    except ValueError:
        return None

_DIRECTIVE_COMMENT_RE = re.compile(
    r"<!--\s*observed:\s*([\d-]+)\s*\|\s*status:\s*(\w+)\s*-->"
)


def _load_or_create_token() -> str:
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return token


TOKEN = _load_or_create_token()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact_id(source_file: str, content: str) -> str:
    digest = hashlib.sha1(f"{source_file}:{content}".encode("utf-8")).hexdigest()
    return f"{source_file}-{digest[:16]}"


def _make_fact(
    *,
    fact_id: str,
    content: str,
    category: str,
    source_type: str,
    observed_at: str | None,
    status: str = "active",
) -> dict[str, Any]:
    timestamp = observed_at or _now()
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "scope": "personal",
        "source_type": source_type,
        "sensitivity": "normal",
        "confidence": 1.0,
        "retention_policy": "durable",
        "expires_at": None,
        "user_confirmed": True,
        # Immer "confirmed" - siehe Modulkommentar oben. "superseded"/veraltete
        # USER.md-Direktiven werden komplett uebersprungen (siehe parse-Funktion),
        # tauchen also gar nicht erst auf.
        "status": "confirmed" if status != "rejected" else "rejected",
        "tags": [],
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_used_at": None,
    }


def _parse_user_md() -> list[dict[str, Any]]:
    if not USER_MD_PATH.exists():
        return []
    facts: list[dict[str, Any]] = []
    lines = USER_MD_PATH.read_text(encoding="utf-8").splitlines()
    pending_date: str | None = None
    pending_status = "active"
    for line in lines:
        stripped = line.strip()
        comment_match = _DIRECTIVE_COMMENT_RE.search(stripped)
        if comment_match:
            pending_date, pending_status = comment_match.group(1), comment_match.group(2)
            continue
        if stripped.startswith("- ") and pending_date is not None:
            content = stripped[2:].strip()
            if content and pending_status == "active":
                facts.append(_make_fact(
                    fact_id=_fact_id("USER.md", content),
                    content=content,
                    category="Profil",
                    source_type="manual",
                    observed_at=pending_date,
                ))
            pending_date = None
            pending_status = "active"
    return facts


def _parse_memory_md() -> list[dict[str, Any]]:
    if not MEMORY_MD_PATH.exists():
        return []
    facts: list[dict[str, Any]] = []
    for line in MEMORY_MD_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:].strip()
            if content:
                facts.append(_make_fact(
                    fact_id=_fact_id("MEMORY.md", content),
                    content=content,
                    category="Langzeit",
                    source_type="auto",
                    observed_at=None,
                ))
    return facts


_SKILLS_DIR = WORKSPACE / "skills"


def _extract_frontmatter_field(frontmatter_lines: list[str], key: str) -> str:
    """Liest ein YAML-Frontmatter-Feld, inklusive gefalteter Blockskalare (`>`/`|`)
    wie bei mac-contacts/SKILL.md - eine einfache Ein-Zeilen-Regex allein wuerde dort
    nur die YAML-Steuerzeichen statt der eigentlichen Beschreibung liefern."""
    for index, line in enumerate(frontmatter_lines):
        match = re.match(rf"^{key}:[ \t]*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value in (">", "|", ">-", "|-"):
            block_lines: list[str] = []
            for next_line in frontmatter_lines[index + 1:]:
                if next_line.strip() == "" or next_line.startswith((" ", "\t")):
                    if next_line.strip():
                        block_lines.append(next_line.strip())
                    continue
                break
            return " ".join(block_lines)
        return value
    return ""


def _parse_skill_capabilities() -> list[dict[str, Any]]:
    """Eine Erinnerung pro installiertem Skill (~/.openclaw/workspace/skills/*/SKILL.md)
    - das ist die konkrete Antwort auf "zeig mir auch, was Jarvis alles nutzen/tun kann",
    nicht nur Fakten ueber den Nutzer. Echt dynamisch: kommt ein Skill dazu oder faellt
    einer weg, aendert sich diese Liste beim naechsten Abruf von selbst - keine
    statische Aufzaehlung."""
    if not _SKILLS_DIR.is_dir():
        return []
    facts: list[dict[str, Any]] = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        frontmatter_lines = (frontmatter_match.group(1) if frontmatter_match else text).splitlines()
        name = _extract_frontmatter_field(frontmatter_lines, "name") or skill_dir.name
        description = _extract_frontmatter_field(frontmatter_lines, "description")
        content = f"{name}: {description}" if description else name
        facts.append(_make_fact(
            fact_id=_fact_id("skills", content),
            content=content,
            category="Fähigkeiten",
            source_type="auto",
            observed_at=None,
        ))
    return facts


def _parse_whatsapp_messages() -> list[dict[str, Any]]:
    """Eine Erinnerung pro echter WhatsApp-Nachricht (whatsapp-bridge/index.mjs
    protokolliert jede ein-/ausgehende Nachricht bereits nach messages.jsonl) - live
    gewuenscht 2026-09-11: "jede Nachricht soll als Punkt gespeichert sein". Nur die
    letzten WHATSAPP_MAX_MESSAGES (nicht die komplette, unbegrenzt wachsende Historie),
    sonst wuerde die Kugel auf Dauer von einer einzigen Quelle ueberflutet. "note"-
    Eintraege (interne ntfy-Push-Protokollierung, keine echte WhatsApp-Nachricht)
    werden uebersprungen."""
    if not WHATSAPP_LOG_PATH.exists():
        return []
    lines = WHATSAPP_LOG_PATH.read_text(encoding="utf-8").splitlines()
    facts: list[dict[str, Any]] = []
    for line in lines[-WHATSAPP_MAX_MESSAGES:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        direction = entry.get("direction")
        if direction not in ("in", "out"):
            continue
        name = str(entry.get("name") or entry.get("jid") or "Unbekannt").strip()
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        arrow = "→" if direction == "out" else "←"
        content = f"{arrow} {name}: {text}"[:280]
        ts = str(entry.get("ts") or "")
        facts.append(_make_fact(
            fact_id=_fact_id("whatsapp", f"{ts}:{content}"),
            content=content,
            category="Nachrichten",
            source_type="auto",
            observed_at=ts or None,
        ))
    return facts


_mail_cache: dict[str, Any] = {"at": 0.0, "facts": []}
_MAIL_CACHE_SECONDS = 120.0


def _parse_mail_messages() -> list[dict[str, Any]]:
    """Eine Erinnerung pro Mail aus dem Posteingang der letzten MAIL_MAX_AGE_DAYS Tage
    (live gewuenscht 2026-09-11, eingegrenzt auf 7 Tage statt des kompletten Postfachs -
    sonst wuerden tausende alte Mails die Kugel fluten). Nutzt direkt
    app/mail_client.py::list_inbox_messages (AppleScript/Mail.app), gleiches
    Self-contained-Modul wie beim files/photos-Proxy. Kurz gecacht (2 Min) - ein
    AppleScript-Roundtrip zu Mail.app ist deutlich teurer als ein Dateizugriff und soll
    nicht bei jedem UI-Poll erneut ausgeloest werden."""
    now = datetime.now(timezone.utc).timestamp()
    if now - _mail_cache["at"] < _MAIL_CACHE_SECONDS:
        return _mail_cache["facts"]

    try:
        messages = list_inbox_messages(max_messages=MAIL_MAX_MESSAGES)
    except MailAccessError:
        return _mail_cache["facts"]

    cutoff = datetime.now() - timedelta(days=MAIL_MAX_AGE_DAYS)
    facts: list[dict[str, Any]] = []
    for message in messages:
        received_at = _parse_mail_received(message.received)
        if received_at is not None and received_at < cutoff:
            continue
        content = f"{message.sender}: {message.subject}"[:280]
        facts.append(_make_fact(
            fact_id=f"mail-{message.message_id or _fact_id('mail', content)}",
            content=content,
            category="Mail",
            source_type="auto",
            observed_at=None,
        ))

    _mail_cache["at"] = now
    _mail_cache["facts"] = facts
    return facts


_notes_cache: dict[str, Any] = {"at": 0.0, "facts": []}
_NOTES_CACHE_SECONDS = 120.0
NOTES_MAX = 100


def _parse_notes() -> list[dict[str, Any]]:
    """Eine Erinnerung pro Apple-Notiz (live gewuenscht 2026-09-11: "jede Notiz soll
    als Punkt abgespeichert sein"). Nutzt app/notes_client.py::list_recent_notes -
    liefert nur Titel + Aenderungsdatum, keinen Notiztext (die Kugel zeigt ohnehin nur
    kurze content-Strings, und der volle Notizinhalt landet nicht unnoetig in einem
    weiteren Speicher). Gleiches 2-Minuten-Caching wie bei Mail - AppleScript-
    Roundtrips zu Notes.app sind teuer, nicht bei jedem UI-Poll erneut ausloesen."""
    now = datetime.now(timezone.utc).timestamp()
    if now - _notes_cache["at"] < _NOTES_CACHE_SECONDS:
        return _notes_cache["facts"]

    try:
        notes = list_recent_notes(limit=NOTES_MAX)
    except NotesAccessError:
        return _notes_cache["facts"]

    facts: list[dict[str, Any]] = []
    for note in notes:
        title = str(note.get("title") or "").strip()
        if not title:
            continue
        modified = note.get("modified")
        observed_at = modified.isoformat() if hasattr(modified, "isoformat") else None
        facts.append(_make_fact(
            fact_id=_fact_id("notes", title),
            content=title[:280],
            category="Notizen",
            source_type="auto",
            observed_at=observed_at,
        ))

    _notes_cache["at"] = now
    _notes_cache["facts"] = facts
    return facts


def all_facts() -> list[dict[str, Any]]:
    return (
        _parse_user_md()
        + _parse_memory_md()
        + _parse_skill_capabilities()
        + _parse_whatsapp_messages()
        + _parse_mail_messages()
        + _parse_notes()
    )


def facts_payload(search: str = "", category: str = "") -> dict[str, Any]:
    facts = all_facts()
    if search:
        needle = search.lower()
        facts = [f for f in facts if needle in f["content"].lower()]
    if category:
        facts = [f for f in facts if f["category"] == category]
    return {"facts": facts, "total": len(facts)}


def _split_source_and_hash(fact_id: str) -> tuple[str, str]:
    source_file, _, digest = fact_id.rpartition("-")
    return source_file, digest


def delete_fact(fact_id: str) -> bool:
    source_file, _ = _split_source_and_hash(fact_id)
    path = USER_MD_PATH if source_file == "USER.md" else MEMORY_MD_PATH if source_file == "MEMORY.md" else None
    if path is None or not path.exists():
        return False

    target = next((f for f in all_facts() if f["id"] == fact_id), None)
    if target is None:
        return False
    content = target["content"]

    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    i = 0
    removed = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not removed and stripped.startswith(("- ", "* ")) and stripped[2:].strip() == content:
            # Fuer USER.md auch den vorangehenden <!-- observed --> Kommentar mit
            # entfernen, sonst bleibt ein verwaister, kontextloser Kommentar zurueck.
            if new_lines and _DIRECTIVE_COMMENT_RE.search(new_lines[-1].strip()):
                new_lines.pop()
            removed = True
            i += 1
            continue
        new_lines.append(line)
        i += 1

    if not removed:
        return False

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def _run_openclaw_json(args: list[str]) -> Any:
    # openclaw ist selbst ein Node-Skript - braucht node auf dem PATH. Der
    # LaunchAgent-Kontext dieses Proxys hat KEIN Login-Shell-PATH (anders als eine
    # interaktive ssh-Sitzung), deshalb ueber "zsh -l -c" starten, genau wie
    # scripts/*_launch.sh es fuer die anderen Proxys schon tun.
    command = " ".join([OPENCLAW_BIN, *args, "--json"])
    result = subprocess.run(
        ["/bin/zsh", "-l", "-c", command],
        capture_output=True, text=True, timeout=25,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"openclaw {' '.join(args)} fehlgeschlagen.")
    return json.loads(result.stdout)


_ACTIVITY_CACHE_SECONDS = 20.0
_activity_cache: dict[str, Any] = {"at": 0.0, "events": []}


def recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    """Echter "was macht Jarvis im Hintergrund"-Feed: der letzte Lauf jeder OpenClaw-
    Automation (Mail-/Kalender-Checks, News-Watcher, etc.). EIN einzelner `cron list`-
    Aufruf (nicht ein `cron runs` pro Job - das dauerte mit ~9 Jobs wegen Node-
    Kaltstart pro Aufruf ueber eine Minute und liess den Endpunkt praktisch haengen),
    daher gibt es hier nur Status+Zeitstempel aus `state`, keine ausfuehrliche
    Lauf-Zusammenfassung. Kurz gecacht (20s), damit haeufiges UI-Polling nicht bei
    jedem Tick erneut `openclaw` (Node-Prozess) starten muss. Kein Live-Stream
    laufender Werkzeug-Aufrufe (das braeuchte eine WebSocket-Anbindung an OpenClaws
    Gateway-Protokoll, siehe JarvisMobile/GatewayClient.swift fuer einen Ansatz dazu) -
    aber ein ehrliches, schnelles Bild dessen, was zuletzt tatsaechlich passiert ist."""
    now = datetime.now(timezone.utc).timestamp()
    if now - _activity_cache["at"] < _ACTIVITY_CACHE_SECONDS:
        return _activity_cache["events"]

    jobs = _run_openclaw_json(["cron", "list"]).get("jobs", [])
    events: list[dict[str, Any]] = []
    for job in jobs:
        state = job.get("state") or {}
        ts_ms = state.get("lastRunAtMs") or job.get("lastRunAtMs")
        if not isinstance(ts_ms, (int, float)):
            continue
        label = job.get("displayName") or job.get("name") or job.get("id")
        status = state.get("lastRunStatus") or job.get("lastRunStatus") or "unbekannt"
        description = str(job.get("description") or "").strip()
        reference = f"{status}" + (f" – {description}" if description else "")
        events.append({
            "type": "automation",
            "label": label,
            "reference": reference[:280],
            "at": ts_ms / 1000.0,
        })
    events.sort(key=lambda e: e["at"], reverse=True)
    events = events[:limit]
    _activity_cache["at"] = now
    _activity_cache["events"] = events
    return events


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        if self.path.startswith("/api/memory/facts"):
            from urllib.parse import urlparse, parse_qs
            query = parse_qs(urlparse(self.path).query)
            search = (query.get("search") or [""])[0]
            category = (query.get("category") or [""])[0]
            self._send_json(200, facts_payload(search=search, category=category))
        elif self.path.startswith("/api/memory/activity"):
            try:
                self._send_json(200, {"events": recent_activity()})
            except Exception as exc:  # noqa: BLE001
                self._send_json(502, {"error": str(exc) or type(exc).__name__})
        else:
            self._send_json(404, {"error": "Unbekannter Pfad."})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        body = self._read_json_body()
        try:
            if self.path == "/api/memory/facts/delete":
                fact_id = str(body.get("id") or "")
                ok = delete_fact(fact_id)
                if ok:
                    self._send_json(200, {"ok": True})
                else:
                    self._send_json(404, {"error": "Erinnerung nicht gefunden."})
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001
            self._send_json(502, {"error": str(exc) or type(exc).__name__})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[memory-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Speicher-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
