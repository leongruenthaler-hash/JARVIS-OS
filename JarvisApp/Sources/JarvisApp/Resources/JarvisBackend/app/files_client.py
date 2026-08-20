from __future__ import annotations

import re
import shutil
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data_dir import data_root


class FileAccessError(RuntimeError):
    pass


@dataclass
class FileItem:
    name: str
    kind: str
    size: int
    modified: str
    path: str


DEFAULT_ROOTS = ("desktop", "documents", "downloads", "home", "jarvis")
PROJECT_ROOT = data_root()
FILE_INDEX_PATH = PROJECT_ROOT / "memory" / "file_index.json"
# Hard cap on filesystem entries a live (non-indexed) recursive search will walk.
# Without this, searching a broad root like "home" recurses through the entire
# user home directory (Library, node_modules, etc.) with no bound, which can hang
# the app on large disks. This mirrors the photos_scan_max_items cap in photos_client.py.
MAX_LIVE_SCAN_NODES = 20000


def configured_roots(config: dict | None = None) -> dict[str, Path]:
    repo_root = data_root()
    home = Path.home()
    roots = {
        "desktop": home / "Desktop",
        "schreibtisch": home / "Desktop",
        "documents": home / "Documents",
        "dokumente": home / "Documents",
        "downloads": home / "Downloads",
        "download": home / "Downloads",
        "home": home,
        "benutzerordner": home,
        "dateien": home,
        "alle dateien": home,
        "allen dateien": home,
        "jarvis": repo_root,
        "projekt": repo_root,
        "code": repo_root,
        "jarvis code": repo_root,
    }

    for path_text in (config or {}).get("file_access_roots", []):
        path = Path(str(path_text)).expanduser()
        if path.exists() and path.is_dir():
            roots[normalize_name(path.name)] = path

    return roots


def resolve_root(root_hint: str | None = None, config: dict | None = None) -> tuple[str, Path]:
    roots = configured_roots(config)
    normalized_hint = normalize_name(root_hint or "")
    if normalized_hint:
        for name, path in roots.items():
            if normalized_hint == name or normalized_hint in name or name in normalized_hint:
                return name, path

    return "desktop", roots["desktop"]


def list_items(root_hint: str | None = None, config: dict | None = None, limit: int = 25) -> list[FileItem]:
    _root_name, root = resolve_root(root_hint, config)
    if not root.exists():
        raise FileAccessError(f"Ich finde den Ordner {root} gerade nicht.")

    items: list[FileItem] = []
    for path in root.iterdir():
        if path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue

        items.append(
            FileItem(
                name=path.name,
                kind="Ordner" if path.is_dir() else "Datei",
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                path=str(path),
            )
        )

    items.sort(key=lambda item: (item.kind != "Ordner", item.name.lower()))
    return items[:limit]


def summarize_folder(root_hint: str | None = None, config: dict | None = None, limit: int = 12) -> str:
    root_name, root = resolve_root(root_hint, config)
    items = list_items(root_hint, config, limit=200)
    folders = [item for item in items if item.kind == "Ordner"]
    files = [item for item in items if item.kind == "Datei"]
    visible = items[:limit]
    label = friendly_root_name(root_name, root)
    if not visible:
        return f"{label} ist gerade leer."

    names = "; ".join(f"{item.kind}: {item.name}" for item in visible)
    return f"Ich sehe in {label} {len(folders)} Ordner und {len(files)} Datei(en). Die ersten Einträge sind: {names}."


def search_files(query: str, root_hint: str | None = None, config: dict | None = None, max_results: int = 12) -> str:
    cleaned_query = normalize_name(clean_file_name(query))
    if not cleaned_query:
        return "Wonach soll ich suchen?"

    root_name, root = resolve_root(root_hint, config)
    indexed_answer = search_file_index(cleaned_query, root_name=root_name, root=root, max_results=max_results)
    if indexed_answer is not None:
        return indexed_answer

    matches: list[Path] = []
    for path in iter_visible_paths(root):
        if len(matches) >= max_results:
            break
        if name_matches_query(path.name, cleaned_query):
            matches.append(path)

    label = friendly_root_name(root_name, root)
    if not matches:
        return f"Ich finde in {label} nichts Passendes zu {query}."

    parts = []
    for path in matches:
        kind = "Ordner" if path.is_dir() else "Datei"
        parts.append(f"{kind}: {path.relative_to(root)}")
    return f"Ich habe in {label} gefunden: " + "; ".join(str(part) for part in parts) + "."


def search_file_index(cleaned_query: str, root_name: str, root: Path, max_results: int = 12) -> str | None:
    matches = search_file_index_entries(cleaned_query, root_name=root_name, max_results=max_results)
    if matches is None:
        return None

    label = friendly_root_name(root_name, root)
    if not matches:
        return f"Ich finde im Dateiindex in {label} nichts Passendes zu {cleaned_query}. Starte den Dateiindex neu, falls die Dateien ganz frisch hinzugekommen sind."

    return format_file_search_results(matches, cleaned_query)


def search_file_index_entries(
    query: str,
    root_name: str | None = None,
    max_results: int = 30,
) -> list[dict] | None:
    if not FILE_INDEX_PATH.exists():
        return None

    try:
        payload = json.loads(FILE_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return None

    cleaned_query = normalize_name(clean_file_name(query))
    if not cleaned_query:
        return []

    root_filter = normalize_name(root_name or "")
    broad_roots = {"home", "benutzerordner", "dateien", "alle dateien", "allen dateien"}
    matches: list[dict] = []
    terms = query_match_terms(cleaned_query)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_root = normalize_name(str(entry.get("root") or ""))
        if root_filter and root_filter not in broad_roots and entry_root and root_filter != entry_root:
            continue

        name = str(entry.get("name") or "")
        relative = str(entry.get("relative_path") or name)
        if should_hide_file_search_result(name, relative):
            continue
        extension = normalize_name(str(entry.get("extension") or ""))
        haystack = normalize_name(" ".join([name, relative, extension, str(entry.get("kind") or "")]))
        if name_matches_query(name, cleaned_query) or any(term in haystack for term in terms):
            matches.append(normalize_file_index_entry(entry))
            if len(matches) >= max_results:
                break

    return matches


def normalize_file_index_entry(entry: dict) -> dict:
    name = str(entry.get("name") or "Unbenannt").strip()
    kind = "folder" if str(entry.get("kind") or "") == "folder" else "file"
    relative = str(entry.get("relative_path") or name).strip()
    root = str(entry.get("root") or "").strip()
    path = str(entry.get("path") or "").strip()
    extension = str(entry.get("extension") or "").strip()
    size = entry.get("size") or 0
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 0
    return {
        "name": name,
        "kind": kind,
        "root": root,
        "relative_path": relative,
        "path": path,
        "modified": str(entry.get("modified") or ""),
        "size": size,
        "extension": extension,
    }


def move_indexed_matches_to_folder(
    query: str,
    target_folder_name: str,
    root_hint: str | None = None,
    config: dict | None = None,
    max_results: int = 80,
) -> str:
    cleaned_query = normalize_name(clean_file_name(query))
    target_name = clean_file_name(target_folder_name)
    if not cleaned_query or not target_name:
        return "Mir fehlt der Suchbegriff oder der Zielordner."

    root_name, root = resolve_root(root_hint or "desktop", config)
    target_folder = find_folder(target_name, root_hint=root_name, config=config) or safe_child(root, target_name)
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    indexed_matches = search_file_index_entries(cleaned_query, root_name=None, max_results=max_results)
    if indexed_matches is None:
        return "Der Dateiindex ist noch nicht aufgebaut. Starte zuerst den Dateiindex."

    moved: list[str] = []
    skipped: list[str] = []
    for entry in indexed_matches:
        if str(entry.get("kind") or "") != "file":
            continue
        source_text = str(entry.get("path") or "")
        if not source_text:
            continue
        source = Path(source_text).expanduser()
        try:
            if not source.exists() or not source.is_file():
                skipped.append(str(entry.get("name") or source.name))
                continue
            if not _is_within_configured_roots(source, config):
                skipped.append(str(entry.get("name") or source.name))
                continue
            if source.resolve().parent == target_folder.resolve():
                skipped.append(source.name)
                continue
            destination = target_folder / source.name
            if destination.exists():
                skipped.append(source.name)
                continue
            shutil.move(str(source), str(destination))
            moved.append(source.name)
            from core.activity_log import record_activity
            record_activity("file", source.name)
        except OSError:
            skipped.append(str(entry.get("name") or source.name))

    if not moved:
        return f"Ich habe nichts verschoben. Entweder lagen die Treffer schon im Ordner {target_folder.name}, waren Ordner statt Dateien oder existieren nicht mehr am gespeicherten Ort."

    sample = "; ".join(moved[:6])
    extra = f" {len(skipped)} Treffer habe ich übersprungen." if skipped else ""
    return f"Erledigt. Ich habe {len(moved)} Datei(en) nach {target_folder.name} verschoben: {sample}.{extra}"


def create_folder(folder_name: str, root_hint: str | None = None, config: dict | None = None) -> str:
    cleaned_name = clean_file_name(folder_name)
    if not cleaned_name:
        return "Wie soll der Ordner heißen?"

    root_name, root = resolve_root(root_hint, config)
    folder = safe_child(root, cleaned_name)
    if folder.exists():
        return f"Der Ordner {folder.name} existiert in {friendly_root_name(root_name, root)} schon."

    folder.mkdir(parents=False, exist_ok=False)
    return f"Erledigt. Ich habe den Ordner {folder.name} in {friendly_root_name(root_name, root)} erstellt."


def move_item(source_name: str, target_folder_name: str, root_hint: str | None = None, config: dict | None = None) -> str:
    root_name, root = resolve_root(root_hint, config)
    source = find_item(source_name, root_hint=root_name, config=config)
    if source is None:
        return f"Ich finde {source_name} in {friendly_root_name(root_name, root)} nicht eindeutig."

    target_folder = safe_child(root, clean_file_name(target_folder_name))
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    destination = target_folder / source.name
    if destination.exists():
        return f"Im Ordner {target_folder.name} gibt es bereits etwas mit dem Namen {source.name}. Ich habe nichts verschoben."

    shutil.move(str(source), str(destination))
    from core.activity_log import record_activity
    record_activity("file", source.name)
    return f"Erledigt. Ich habe {source.name} in den Ordner {target_folder.name} verschoben."


def move_items_matching(query: str, target_folder_name: str, root_hint: str | None = None, config: dict | None = None, files_only: bool = True) -> str:
    root_name, root = resolve_root(root_hint, config)
    cleaned_query = normalize_name(clean_file_name(query))
    target_name = clean_file_name(target_folder_name)
    if not cleaned_query or not target_name:
        return "Mir fehlt der Suchbegriff oder der Zielordner."

    target_folder = find_folder(target_name, root_hint=root_name, config=config) or safe_child(root, target_name)
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    matches = []
    for path in root.iterdir():
        if path.name.startswith("."):
            continue
        if path.resolve() == target_folder.resolve():
            continue
        if files_only and not path.is_file():
            continue
        if name_matches_query(path.name, cleaned_query):
            matches.append(path)

    label = friendly_root_name(root_name, root)
    if not matches:
        return f"Ich finde in {label} keine Datei mit {query} im Namen."

    moved = []
    skipped = []
    for source in matches:
        destination = target_folder / source.name
        if destination.exists():
            skipped.append(source.name)
            continue
        shutil.move(str(source), str(destination))
        moved.append(source.name)
        from core.activity_log import record_activity
        record_activity("file", source.name)

    if not moved:
        return f"Ich habe nichts verschoben, weil im Ordner {target_folder.name} schon passende Dateien vorhanden sind."

    sample = "; ".join(moved[:5])
    extra = f" {len(skipped)} Datei(en) waren schon vorhanden und wurden übersprungen." if skipped else ""
    return f"Erledigt. Ich habe {len(moved)} Datei(en) mit {query} im Namen in den Ordner {target_folder.name} verschoben: {sample}.{extra}"


def copy_item(source_name: str, target_folder_name: str, root_hint: str | None = None, config: dict | None = None) -> str:
    root_name, root = resolve_root(root_hint, config)
    source = find_item(source_name, root_hint=root_name, config=config)
    if source is None:
        return f"Ich finde {source_name} in {friendly_root_name(root_name, root)} nicht eindeutig."

    target_folder = safe_child(root, clean_file_name(target_folder_name))
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    destination = target_folder / source.name
    if destination.exists():
        return f"Im Ordner {target_folder.name} gibt es bereits etwas mit dem Namen {source.name}. Ich habe nichts kopiert."

    if source.is_dir():
        shutil.copytree(str(source), str(destination))
    else:
        shutil.copy2(str(source), str(destination))
    from core.activity_log import record_activity
    record_activity("file", source.name)
    return f"Erledigt. Ich habe {source.name} in den Ordner {target_folder.name} kopiert."


def find_item(name_query: str, root_hint: str | None = None, config: dict | None = None) -> Path | None:
    _root_name, root = resolve_root(root_hint, config)
    cleaned_query = normalize_name(clean_file_name(name_query))
    if not cleaned_query:
        return None

    direct_matches = [
        path
        for path in root.iterdir()
        if not path.name.startswith(".") and normalize_name(path.name) == cleaned_query
    ]
    if len(direct_matches) == 1:
        return direct_matches[0]

    partial_matches = [
        path
        for path in iter_visible_paths(root)
        if cleaned_query in normalize_name(path.name)
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]

    return None


def find_folder(name_query: str, root_hint: str | None = None, config: dict | None = None) -> Path | None:
    _root_name, root = resolve_root(root_hint, config)
    cleaned_query = normalize_name(clean_file_name(name_query))
    if not cleaned_query:
        return None

    direct_matches = [
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and normalize_name(path.name) == cleaned_query
    ]
    if len(direct_matches) == 1:
        return direct_matches[0]

    partial_matches = [
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and cleaned_query in normalize_name(path.name)
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]

    return None


def detect_root_hint(text: str) -> str:
    normalized = normalize_name(text)
    checks = (
        ("desktop", ("desktop", "schreibtisch")),
        ("documents", ("dokumente", "documents")),
        ("downloads", ("downloads", "download")),
        ("home", ("home", "benutzerordner", "dateien", "alle dateien", "allen dateien", "ganzer mac", "mein mac")),
        ("jarvis", ("jarvis", "projekt", "code", "jarvis code")),
    )
    for root_name, terms in checks:
        if any(term in normalized for term in terms):
            return root_name
    return "desktop"


def clean_file_name(text: str) -> str:
    cleaned = str(text).strip(" .,!?:;\"'")
    cleaned = re.sub(r"^(?:bitte\s+|mal\s+)*(?:die|der|das|den|dem|eine|einen|einem)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:datei|ordner|folder)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(?:erstelle|erstell|mach|mache|leg|lege)\s+(?:mir\s+)?(?:einen\s+|eine\s+|neuen\s+|neue\s+)?(?:ordner\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(?:ordner|folder)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(?:auf|am|in|aus|von)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch|dokumente|dokumenten|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:auf|am|in|unter|bei|meinem|meinen|meiner|desktop|schreibtisch|dokumente|dokumenten|documents|downloads|download|home|benutzerordner|dateien|alle dateien|allen dateien|jarvis|projekt|code)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Verb-finale deutsche Saetze ("... nach Projekte verschieben.") lassen das
    # Verb ganz am Ende stehen, hinter dem Zielordnernamen - ohne diesen Strip
    # landet es als Teil des extrahierten Namens. Live beobachtet 2026-08-20 im
    # Mehrfach-Audit: "Soll ich ... in den Ordner Projekte verschieben verschieben?"
    # (Verb doppelt, einmal aus dem extrahierten Namen, einmal aus der eigenen
    # Bestaetigungsvorlage).
    cleaned = re.sub(
        r"\s+(?:verschieben|verschiebe|kopieren|kopiere|einsortieren|einsortiere|packen|packe)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,!?:;\"'")


def normalize_name(text: str) -> str:
    text = str(text).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9._ -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_matches_query(name: str, cleaned_query: str) -> bool:
    normalized_name = normalize_name(name)
    terms = query_match_terms(cleaned_query)
    if any(term and term in normalized_name for term in terms):
        return True

    if "bewerb" in terms:
        if "lebenslauf" in normalized_name or normalized_name.startswith(("be ", "be_", "be-")):
            return True

    return False


def query_match_terms(cleaned_query: str) -> set[str]:
    terms = {cleaned_query}
    if cleaned_query.endswith("en") and len(cleaned_query) > 4:
        terms.add(cleaned_query[:-2])
    if cleaned_query.endswith("e") and len(cleaned_query) > 4:
        terms.add(cleaned_query[:-1])
    if cleaned_query.endswith("s") and len(cleaned_query) > 4:
        terms.add(cleaned_query[:-1])

    for suffix in ("ungen", "ung", "bungen", "bung"):
        if cleaned_query.endswith(suffix) and len(cleaned_query) > len(suffix) + 3:
            terms.add(cleaned_query[: -len(suffix)])

    if cleaned_query.startswith("bewerb"):
        terms.add("bewerb")
    if cleaned_query.startswith("rechnung"):
        terms.update({"rechnung", "rechn", "invoice", "beleg", "receipt", "abrechnung", "lohnabrechnung"})
    if cleaned_query.startswith("beleg"):
        terms.update({"beleg", "receipt", "rechnung"})
    if cleaned_query.startswith("abrechnung") or cleaned_query.startswith("lohnabrechnung"):
        terms.update({"abrechnung", "lohnabrechnung", "rechnung"})
    if cleaned_query.startswith("versicherung"):
        terms.add("versicherung")
    return {term for term in terms if len(term) >= 4}


def friendly_index_root_name(root_name: str) -> str:
    mapping = {
        "desktop": "Schreibtisch",
        "documents": "Dokumente",
        "downloads": "Downloads",
        "jarvis": "Jarvis",
    }
    return mapping.get(normalize_name(root_name), root_name)


def should_hide_file_search_result(name: str, relative_path: str) -> bool:
    normalized = normalize_name(f"{name} {relative_path}")
    stale_phrases = (
        "neuen ordner auf meinem schreibtisch mit dem titel",
        "neuer ordner auf meinem schreibtisch mit dem titel",
        "ordner auf meinem schreibtisch mit dem titel",
    )
    return any(phrase in normalized for phrase in stale_phrases)


def format_file_search_results(matches: list[dict], query: str) -> str:
    visible = [entry for entry in matches if not should_hide_file_search_result(str(entry.get("name") or ""), str(entry.get("relative_path") or ""))]
    if not visible:
        return f"Ich habe im Dateiindex keine brauchbaren Treffer für {query} gefunden. Ein paar alte falsch benannte Ordner habe ich dabei bewusst ignoriert."

    descriptions = [describe_file_index_entry(entry) for entry in visible[:8]]
    count = len(visible)
    prefix = f"Ich habe {count} Treffer gefunden"
    if count == 1:
        prefix = "Ich habe einen Treffer gefunden"
    extra = "" if count <= 8 else f" Weitere {count - 8} Treffer lasse ich erstmal weg, sonst wird es eine Lesung."
    return prefix + ": " + join_human_list(descriptions) + "." + extra


def describe_file_index_entry(entry: dict) -> str:
    name = str(entry.get("name") or "Unbenannt").strip()
    kind = "Ordner" if str(entry.get("kind") or "") == "folder" else "Datei"
    root = friendly_index_root_name(str(entry.get("root") or ""))
    relative = str(entry.get("relative_path") or name).strip()
    parent = Path(relative).parent
    location = root
    if str(parent) not in {"", "."}:
        location = f"{root}/{parent}" if root else str(parent)

    article = "den" if kind == "Ordner" else "die"
    if location:
        return f"{article} {kind} {name} in {location}"
    return f"{article} {kind} {name}"


def join_human_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} und {items[1]}"
    return ", ".join(items[:-1]) + f" und {items[-1]}"

def _is_within_configured_roots(path: Path, config: dict | None = None) -> bool:
    """Guards against a stale/corrupted file_index.json entry (or a symlink) pointing
    outside the folders Jarvis is actually allowed to touch. Unlike safe_child(), which
    only checks a name against one already-chosen root, this checks an absolute path
    (as stored in the index) against every configured root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in configured_roots(config).values():
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def safe_child(root: Path, child_name: str) -> Path:
    if not child_name or "/" in child_name or "\\" in child_name:
        raise FileAccessError("Der Name ist für einen Ordner nicht sicher genug.")

    child = (root / child_name).resolve()
    try:
        child.relative_to(root.resolve())
    except ValueError as exc:
        raise FileAccessError("Ich arbeite hier nur innerhalb der erlaubten Dateiordner.") from exc
    return child


def iter_visible_paths(root: Path):
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

            yield child

            try:
                if child.is_dir():
                    pending.append(child)
            except OSError:
                continue


# --- Speicherplatz-Aufraeum-Vorschlaege ------------------------------------
# Siehe plans/2026-08-13-jarvis-speicherplatz-aufraeumen-per-chat.md. Leons
# ausdrueckliche Vorgabe: alles innerhalb von Ordnern, die er selbst angelegt
# hat (allen voran Projekt-/Code-Ordner), ist von Vorschlaegen komplett
# ausgeschlossen - unabhaengig von Groesse/Alter, kein Gewichten, ein harter
# Filter. Geloescht wird ausserdem nie sofort endgueltig, sondern immer erst
# in den Papierkorb ("sehr wichtig, damit ich das noch mal nachkorrigieren
# kann").

DEFAULT_CLEANUP_MIN_SIZE_MB = 50
DEFAULT_CLEANUP_MIN_AGE_DAYS = 30
DEFAULT_CLEANUP_MAX_RESULTS = 10

# Ordner-/Pfadbestandteile, die eine Datei IMMER von Aufraeum-Vorschlaegen
# ausschliessen, unabhaengig von CONFIG - Erkennungsmuster fuer eigene
# Projekt-/Code-Ordner unabhaengig davon, unter welcher Index-Wurzel sie
# gerade auftauchen (z.B. "Projekte/Screenshot KI" liegt unterhalb des
# "desktop"-Index, nicht nur unterhalb der "jarvis"-Wurzel).
CLEANUP_ALWAYS_EXCLUDED_NAME_HINTS = {
    "projekte",
    "projects",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "jarvis-os",
    "jarvisapp",
    "photos library.photoslibrary",
    "library",
}


def _cleanup_excluded_names(config: dict | None) -> set[str]:
    return {normalize_name(str(name)) for name in (config or {}).get("cleanup_excluded_root_folders", []) if str(name).strip()}


def _under_git_repo(directory: Path, stop_at: Path, cache: dict[Path, bool]) -> bool:
    """Ist `directory` selbst oder einer ihrer Vorfahren (bis `stop_at`) ein
    Git-Repo (hat einen .git-Unterordner)? Mit Memoisierung, damit viele
    Dateien im selben Baum nicht wiederholt dieselben Vorfahren pruefen."""
    if directory in cache:
        return cache[directory]
    try:
        is_repo_here = (directory / ".git").exists()
    except OSError:
        is_repo_here = False
    if is_repo_here:
        cache[directory] = True
        return True
    if directory == stop_at or directory.parent == directory:
        cache[directory] = False
        return False
    result = _under_git_repo(directory.parent, stop_at, cache)
    cache[directory] = result
    return result


def _is_cleanup_excluded(path: Path, git_cache: dict[Path, bool], home: Path, excluded_names: set[str]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    parts_normalized = {normalize_name(part) for part in resolved.parts}
    if parts_normalized & CLEANUP_ALWAYS_EXCLUDED_NAME_HINTS:
        return True
    if parts_normalized & excluded_names:
        return True
    directory = resolved.parent if resolved.is_file() else resolved
    return _under_git_repo(directory, home, git_cache)


def _format_cleanup_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def list_cleanup_candidates(config: dict | None = None, max_results: int = DEFAULT_CLEANUP_MAX_RESULTS) -> list[dict]:
    """Grosse, alte Dateien ausserhalb aller erkannten Projekt-/eigenen Ordner,
    sortiert nach Groesse absteigend. Liest den bestehenden Dateiindex - baut
    keinen eigenen, zweiten Index auf. Gibt eine leere Liste zurueck, wenn der
    Index fehlt oder nichts passt (kein Fehler - Aufrufer entscheiden, wie sie
    das kommunizieren)."""
    config = config or {}
    if not FILE_INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(FILE_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []

    min_size_bytes = int(float(config.get("cleanup_suggestion_min_size_mb", DEFAULT_CLEANUP_MIN_SIZE_MB)) * 1024 * 1024)
    min_age_days = float(config.get("cleanup_suggestion_min_age_days", DEFAULT_CLEANUP_MIN_AGE_DAYS))
    now = datetime.now()
    excluded_names = _cleanup_excluded_names(config)
    home = Path.home()
    git_cache: dict[Path, bool] = {}

    candidates: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("kind") or "") != "file":
            continue
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if size < min_size_bytes:
            continue
        path_text = str(entry.get("path") or "")
        if not path_text:
            continue
        path = Path(path_text)
        try:
            modified_at = datetime.fromisoformat(str(entry.get("modified") or ""))
        except ValueError:
            continue
        age_days = (now - modified_at).total_seconds() / 86400
        if age_days < min_age_days:
            continue
        if _is_cleanup_excluded(path, git_cache, home, excluded_names):
            continue
        if not path.exists() or not path.is_file():
            continue
        candidates.append(
            {
                "name": str(entry.get("name") or path.name),
                "path": str(path),
                "size": size,
                "age_days": round(age_days, 1),
            }
        )

    candidates.sort(key=lambda item: item["size"], reverse=True)
    return candidates[:max_results]


def suggest_cleanup_files(config: dict | None = None, max_results: int = DEFAULT_CLEANUP_MAX_RESULTS) -> tuple[str, list[dict]]:
    """Text-Antwort + strukturierte Kandidaten fuer eine Speicherplatz-
    Aufraeum-Anfrage im Chat. Loescht nichts - der Aufrufer (jarvis.py) merkt
    sich die Kandidaten fuer eine spaetere, explizite Bestaetigung."""
    if not FILE_INDEX_PATH.exists():
        return (
            "Ich habe noch keinen Dateiindex aufgebaut. Starte zuerst den Dateiindex, "
            "dann kann ich Ihnen konkrete Aufräum-Vorschläge machen.",
            [],
        )

    candidates = list_cleanup_candidates(config=config, max_results=max_results)
    if not candidates:
        min_size = float((config or {}).get("cleanup_suggestion_min_size_mb", DEFAULT_CLEANUP_MIN_SIZE_MB))
        min_age = float((config or {}).get("cleanup_suggestion_min_age_days", DEFAULT_CLEANUP_MIN_AGE_DAYS))
        return (
            f"Ich finde gerade keine großen, älteren Dateien außerhalb Ihrer Projekt-Ordner "
            f"(Schwelle: über {min_size:.0f} MB, älter als {min_age:.0f} Tage), die ich zum "
            "Aufräumen vorschlagen würde.",
            [],
        )

    descriptions = [f"{item['name']} ({_format_cleanup_size(item['size'])})" for item in candidates]
    total_mb = sum(item["size"] for item in candidates) / (1024 * 1024)
    text = (
        f"Ich habe {len(candidates)} große, ältere Datei(en) außerhalb Ihrer Projekt-Ordner gefunden, "
        f"die zusammen rund {_format_cleanup_size(int(total_mb * 1024 * 1024))} belegen: "
        + join_human_list(descriptions)
        + ". Sagen Sie mir, ob ich die in den Papierkorb legen soll - ich lösche nichts ohne Ihre Bestätigung."
    )
    return text, candidates


def move_to_trash(paths: list[Path]) -> tuple[list[str], list[str]]:
    """Verschiebt Dateien in den macOS-Papierkorb (rueckgaengig machbar ueber
    den Finder) statt sie endgueltig zu loeschen - Leons ausdrueckliche
    Vorgabe. Nutzt Finder/AppleScript, dasselbe Muster wie die uebrigen
    macOS-Integrationen im Projekt (z.B. calendar_client.py::_run_applescript)."""
    moved: list[str] = []
    skipped: list[str] = []
    existing = [path for path in paths if path.exists()]
    skipped.extend(path.name for path in paths if path not in existing)
    if not existing:
        return moved, skipped

    posix_list = ", ".join(f'POSIX file "{str(path)}"' for path in existing)
    script = f'tell application "Finder" to delete {{{posix_list}}}'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            moved.extend(path.name for path in existing)
        else:
            skipped.extend(path.name for path in existing)
    except (OSError, subprocess.TimeoutExpired):
        skipped.extend(path.name for path in existing)
    return moved, skipped


def friendly_root_name(root_name: str, root: Path) -> str:
    if root_name in {"desktop", "schreibtisch"}:
        return "Ihrem Schreibtisch"
    if root_name in {"documents", "dokumente"}:
        return "Ihren Dokumenten"
    if root_name in {"downloads", "download"}:
        return "Ihren Downloads"
    if root_name in {"home", "benutzerordner", "dateien", "alle dateien", "allen dateien"}:
        return "Ihrem Benutzerordner"
    if root_name in {"jarvis", "projekt", "code", "jarvis code"}:
        return "Ihrem Jarvis-Projektordner"
    return str(root)
