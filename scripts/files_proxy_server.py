#!/usr/bin/env python3
"""Eigenstaendiger Datei-Such-Proxy fuer JarvisApp (2026-09-10) - Ersatz fuer
den Teil des alten Backends (app/local_server.py), der bisher
/api/files/scan|search|move-search-results|reset bediente. Importiert
app/files_client.py (self-containted, nur data_dir.py als Abhaengigkeit)
direkt, portiert aber die Scan-Fortschritts-/Threading-Logik aus
JarvisLocalServer als eigene, schlanke Funktionen hierher - im alten
Backend war das ueber einen gemeinsamen Multi-Feature-Status-Endpunkt
(Mail/Fotos/Dateien/Modell-Download zusammen) verdrahtet, den wir hier
bewusst NICHT mit uebernehmen: dieser Proxy kennt nur Dateien, mit einem
eigenen /api/files/status-Endpunkt statt des alten gemeinsamen Bundles.

Gleiches Muster wie scripts/tts_proxy_server.py: ThreadingHTTPServer,
Bearer-Token aus einer einmalig erzeugten Token-Datei, gebunden an
0.0.0.0 (ueber Tailscale direkt erreichbar - siehe die Portfreigabe, die
schon beim TTS-Proxy noetig war).

Installation auf dem Mac Mini: siehe scripts/files_proxy_launch.sh und
scripts/com.leon.jarvis.filesproxy.plist im selben Ordner.
"""
from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from data_dir import data_root  # noqa: E402
from files_client import (  # noqa: E402
    FILE_INDEX_PATH,
    configured_roots,
    move_indexed_matches_to_folder,
    search_file_index_entries,
    search_files,
)

PORT = 18792
TOKEN_FILE = Path.home() / ".jarvis_files_proxy_token"
FILE_SCAN_STATUS_PATH = data_root() / "memory" / "file_scan_status.json"


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


def _now_from_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _safe_error(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


# ---------------------------------------------------------------------------
# Scan-Fortschritt: direkter Port von JarvisLocalServer._scan_progress/
# _save_scan_status/_load_scan_status/_files_status (app/local_server.py) -
# hier als freie Funktionen statt Methoden einer grossen Server-Klasse.
# ---------------------------------------------------------------------------

def _scan_progress(
    status: str,
    label: str,
    *,
    current_item: int = 0,
    total_items: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
    error_message: str | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    percentage = 0.0
    if total_items > 0:
        percentage = min(100.0, max(0.0, (float(current_item) / float(total_items)) * 100.0))
    return {
        "status": status,
        "currentItem": int(current_item),
        "totalItems": int(total_items),
        "percentage": percentage,
        "currentLabel": label,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "errorMessage": error_message,
        "stats": stats or {},
    }


def _save_scan_status(payload: dict[str, Any]) -> None:
    FILE_SCAN_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE_SCAN_STATUS_PATH.with_suffix(FILE_SCAN_STATUS_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE_SCAN_STATUS_PATH)


def _load_scan_status() -> dict[str, Any]:
    fallback = _scan_progress("idle", "Noch kein Dateiindex.")
    if not FILE_SCAN_STATUS_PATH.exists():
        return fallback
    try:
        payload = json.loads(FILE_SCAN_STATUS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else fallback
    except Exception:
        return fallback


def files_status() -> dict[str, Any]:
    status = _load_scan_status()
    if not FILE_INDEX_PATH.exists():
        return status
    try:
        index = json.loads(FILE_INDEX_PATH.read_text(encoding="utf-8"))
        if not isinstance(index, dict):
            return status
        stats = dict(index.get("stats") or {})
        entries = list(index.get("entries") or [])
        status_stats = dict(status.get("stats") or {})
        status["stats"] = {
            **stats,
            **status_stats,
            "last_successful_scan": index.get("last_scan_at", ""),
            "database_bytes": FILE_INDEX_PATH.stat().st_size,
            "index_entries": len(entries),
        }
        if status.get("status") in {"idle", "completed"}:
            status["status"] = "completed"
            status["currentLabel"] = "Dateiindex bereit."
            status["currentItem"] = int(stats.get("items_indexed") or len(entries))
            status["totalItems"] = int(stats.get("items_indexed") or len(entries))
            status["percentage"] = 100.0 if entries else 0.0
            status["finishedAt"] = index.get("last_scan_at")
    except Exception:
        pass
    return status


# ---------------------------------------------------------------------------
# Scan-Wurzeln + rekursive Traversierung - direkter Port von
# JarvisLocalServer._file_scan_roots/_iter_file_index_paths.
# ---------------------------------------------------------------------------

_EXCLUDED_NAMES = {
    ".git", ".venv", "__pycache__", ".cache", ".build", "DerivedData",
    "node_modules", "Library", "System", "Applications", "Volumes",
}
_EXCLUDED_SUFFIXES = {
    ".app", ".framework", ".xcframework", ".sdk", ".xcodeproj",
    ".xcworkspace", ".playground", ".bundle", ".plugin",
}


def _file_scan_roots() -> list[tuple[str, Path]]:
    roots = configured_roots()
    preferred_names = ["desktop", "documents", "downloads", "jarvis"]
    result: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for name in preferred_names:
        path = roots.get(name)
        if path is None:
            continue
        resolved = str(path.expanduser().resolve())
        if resolved in seen or not path.exists() or not path.is_dir():
            continue
        result.append((name, path))
        seen.add(resolved)
    return result


def _iter_file_index_paths(root: Path):
    resolved_root = root.resolve()
    pending = [resolved_root]
    while pending:
        current = pending.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                relative = child.relative_to(resolved_root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
            if child.name in _EXCLUDED_NAMES:
                continue
            if any(child.name.endswith(suffix) for suffix in _EXCLUDED_SUFFIXES):
                continue
            yield child
            try:
                if child.is_dir():
                    pending.append(child)
            except OSError:
                continue


_scan_lock = threading.Lock()
_scan_thread: threading.Thread | None = None


def start_file_index_scan() -> dict[str, Any]:
    global _scan_thread
    started_at = _now()
    _save_scan_status(_scan_progress("preparing", "Dateiwurzeln werden vorbereitet.", started_at=started_at))
    with _scan_lock:
        if _scan_thread is not None and _scan_thread.is_alive():
            return files_status()
        _scan_thread = threading.Thread(target=_run_file_index_scan, args=(started_at,), daemon=True)
        _scan_thread.start()
    return files_status()


def reset_file_index() -> dict[str, Any]:
    for path in (FILE_INDEX_PATH, FILE_SCAN_STATUS_PATH):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    status = _scan_progress("idle", "Dateiindex wurde zurückgesetzt.")
    _save_scan_status(status)
    return status


def _run_file_index_scan(started_at: str) -> None:
    started = time.monotonic()
    try:
        roots = _file_scan_roots()
        total_items = 0
        root_summaries: list[dict[str, Any]] = []
        _save_scan_status(_scan_progress(
            "preparing", "Dateien werden gezählt.", started_at=started_at,
            stats={"roots_found": len(roots), "roots_scanned": 0},
        ))
        for name, root in roots:
            count = 0
            try:
                for _path in _iter_file_index_paths(root):
                    count += 1
            except Exception as exc:
                print(f"Datei-Index: Zählung für {root} fehlgeschlagen: {_safe_error(exc)}", file=sys.stderr)
                count = 0
            total_items += count
            root_summaries.append({"name": name, "path": str(root), "count": count})

        entries: list[dict[str, Any]] = []
        folders_found = 0
        files_found = 0
        bytes_total = 0
        extension_counts: dict[str, int] = {}
        roots_scanned = 0
        current_item = 0

        for root_info, (_name, root) in zip(root_summaries, roots):
            roots_scanned += 1
            _save_scan_status(_scan_progress(
                "scanning", f"Scanne {root_info['name']}",
                current_item=current_item, total_items=total_items, started_at=started_at,
                stats={
                    "roots_found": len(roots), "roots_scanned": roots_scanned - 1,
                    "files_found": files_found, "folders_found": folders_found,
                    "current_root": root_info["path"],
                },
            ))
            for path in _iter_file_index_paths(root):
                current_item += 1
                try:
                    stat = path.stat()
                except OSError:
                    continue
                is_dir = path.is_dir()
                if is_dir:
                    folders_found += 1
                else:
                    files_found += 1
                    bytes_total += int(stat.st_size)
                    suffix = path.suffix.lower().lstrip(".") or "ohne_endung"
                    extension_counts[suffix] = extension_counts.get(suffix, 0) + 1

                try:
                    relative = str(path.relative_to(root))
                except ValueError:
                    relative = path.name
                entries.append({
                    "root": root_info["name"], "name": path.name,
                    "kind": "folder" if is_dir else "file",
                    "relative_path": relative, "path": str(path),
                    "size": int(stat.st_size),
                    "modified": _now_from_timestamp(stat.st_mtime),
                    "extension": path.suffix.lower().lstrip("."),
                })
                if current_item == 1 or current_item % 25 == 0:
                    _save_scan_status(_scan_progress(
                        "indexing", f"Indexiere {path.name}",
                        current_item=current_item, total_items=total_items, started_at=started_at,
                        stats={
                            "roots_found": len(roots), "roots_scanned": roots_scanned,
                            "files_found": files_found, "folders_found": folders_found,
                            "items_indexed": len(entries), "current_root": root_info["path"],
                            "current_item": path.name, "total_bytes": bytes_total,
                        },
                    ))

        finished_at = _now()
        duration_seconds = round(time.monotonic() - started, 2)
        top_extensions = ", ".join(
            f"{ext}: {count}"
            for ext, count in sorted(extension_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        )
        index_payload = {
            "last_scan_at": finished_at, "scan_started_at": started_at,
            "roots": root_summaries, "entries": entries,
            "stats": {
                "roots_found": len(roots), "roots_scanned": len(roots),
                "files_found": files_found, "folders_found": folders_found,
                "items_indexed": len(entries), "total_bytes": bytes_total,
                "top_extensions": top_extensions, "duration_seconds": duration_seconds,
            },
        }
        FILE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE_INDEX_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index_payload, indent=4, ensure_ascii=False), encoding="utf-8")
        tmp.replace(FILE_INDEX_PATH)

        status = _scan_progress(
            "completed", "Dateiindex fertig.",
            current_item=len(entries), total_items=max(total_items, len(entries)),
            started_at=started_at, finished_at=finished_at,
            stats={
                **index_payload["stats"],
                "last_successful_scan": finished_at,
                "database_bytes": FILE_INDEX_PATH.stat().st_size if FILE_INDEX_PATH.exists() else 0,
            },
        )
    except Exception as exc:
        status = _scan_progress(
            "failed", "Dateiindex fehlgeschlagen.",
            started_at=started_at, finished_at=_now(), error_message=_safe_error(exc),
        )
    _save_scan_status(status)


def search_file_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    root_name = str(payload.get("root") or "").strip() or None
    results = search_file_index_entries(query, root_name=root_name, max_results=40) or []
    message = search_files(query, root_hint=root_name or "home", max_results=12)
    return {"query": query, "message": message, "results": results}


def move_file_search_results(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    target_folder = str(payload.get("target_folder") or "").strip()
    root = str(payload.get("root") or "desktop").strip()
    message = move_indexed_matches_to_folder(query, target_folder, root_hint=root)
    return {"message": message, "progress": files_status()}


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
        if self.path == "/api/files/status":
            self._send_json(200, files_status())
        else:
            self._send_json(404, {"error": "Unbekannter Pfad."})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "Ungueltiges oder fehlendes Token."})
            return
        body = self._read_json_body()
        try:
            if self.path == "/api/files/scan":
                self._send_json(200, start_file_index_scan())
            elif self.path == "/api/files/search":
                self._send_json(200, search_file_index_payload(body))
            elif self.path == "/api/files/move-search-results":
                self._send_json(200, move_file_search_results(body))
            elif self.path == "/api/files/reset":
                self._send_json(200, reset_file_index())
            else:
                self._send_json(404, {"error": "Unbekannter Pfad."})
        except Exception as exc:  # noqa: BLE001 - als 502 durchreichen statt den Prozess zu killen
            self._send_json(502, {"error": _safe_error(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[files-proxy] {format % args}")


def main() -> None:
    print(f"Jarvis Datei-Proxy laeuft auf 0.0.0.0:{PORT}")
    print(f"Token (einmalig in JarvisApp -> Verbindung eintragen): {TOKEN}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
