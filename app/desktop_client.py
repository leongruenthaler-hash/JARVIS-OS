from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class DesktopAccessError(RuntimeError):
    pass


@dataclass
class DesktopItem:
    name: str
    kind: str
    size: int
    modified: str
    path: str


def desktop_path() -> Path:
    path = Path.home() / "Desktop"
    if not path.exists():
        raise DesktopAccessError("Ich finde deinen Desktop-Ordner gerade nicht.")
    if not path.is_dir():
        raise DesktopAccessError("Dein Desktop-Pfad ist kein Ordner.")
    return path


def desktop_search_roots() -> list[Path]:
    roots: list[Path] = []
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop",
    ]
    for candidate in candidates:
        try:
            if not candidate.exists() or not candidate.is_dir():
                continue
            resolved = candidate.resolve()
        except OSError:
            continue
        if all(existing.resolve() != resolved for existing in roots):
            roots.append(candidate)

    if not roots:
        roots.append(desktop_path())
    return roots


def iter_desktop_roots():
    for root in desktop_search_roots():
        try:
            yield root
        except OSError:
            continue


def list_desktop_items(limit: int = 30, include_hidden: bool = False) -> list[DesktopItem]:
    root = desktop_path()
    items: list[DesktopItem] = []
    for path in root.iterdir():
        if not include_hidden and path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue

        kind = "Ordner" if path.is_dir() else "Datei"
        items.append(
            DesktopItem(
                name=path.name,
                kind=kind,
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                path=str(path),
            )
        )

    items.sort(key=lambda item: (item.kind != "Ordner", item.name.lower()))
    return items[:limit]


def summarize_desktop(limit: int = 12) -> str:
    items = list_desktop_items(limit=200)
    folders = [item for item in items if item.kind == "Ordner"]
    files = [item for item in items if item.kind == "Datei"]
    visible = items[:limit]
    if not visible:
        return "Dein Schreibtisch ist gerade leer."

    names = "; ".join(f"{item.kind}: {item.name}" for item in visible)
    return (
        f"Ich sehe auf deinem Schreibtisch {len(folders)} Ordner und {len(files)} Datei(en). "
        f"Die ersten Einträge sind: {names}."
    )


def create_desktop_folder(folder_name: str) -> str:
    cleaned_name = clean_desktop_name(folder_name)
    if not cleaned_name:
        return "Wie soll der Ordner auf dem Schreibtisch heißen?"

    folder = _safe_child(desktop_path(), cleaned_name)
    if folder.exists():
        return f"Der Ordner {folder.name} existiert auf deinem Schreibtisch schon."

    folder.mkdir(parents=False, exist_ok=False)
    return f"Erledigt. Ich habe den Ordner {folder.name} auf deinem Schreibtisch erstellt."


def search_desktop(query: str, max_results: int = 10) -> str:
    cleaned_query = normalize_name(clean_desktop_name(query))
    if not cleaned_query:
        return "Wonach soll ich auf deinem Schreibtisch suchen?"

    root = desktop_path()
    matches: list[Path] = []
    for path in root.rglob("*"):
        if len(matches) >= max_results:
            break
        if path.name.startswith("."):
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if name_matches_query(path.name, cleaned_query):
            matches.append(path)

    if not matches:
        return f"Ich finde auf deinem Schreibtisch nichts Passendes zu {query}."

    parts = []
    for path in matches:
        kind = "Ordner" if path.is_dir() else "Datei"
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path.name
        parts.append(f"{kind}: {relative}")

    return "Ich habe auf deinem Schreibtisch gefunden: " + "; ".join(str(part) for part in parts) + "."


def move_desktop_item(source_name: str, target_folder_name: str) -> str:
    root = desktop_path()
    source = find_desktop_item(source_name)
    if source is None:
        return f"Ich finde {source_name} auf deinem Schreibtisch nicht eindeutig."

    target_folder = _safe_child(root, clean_desktop_name(target_folder_name))
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    destination = target_folder / source.name
    if destination.exists():
        return f"Im Ordner {target_folder.name} gibt es bereits etwas mit dem Namen {source.name}. Ich habe nichts verschoben."

    shutil.move(str(source), str(destination))
    return f"Erledigt. Ich habe {source.name} in den Ordner {target_folder.name} verschoben."


def move_desktop_items_matching(query: str, target_folder_name: str, files_only: bool = True) -> str:
    primary_root = desktop_path()
    roots = list(iter_desktop_roots())
    cleaned_query = normalize_name(clean_desktop_name(query))
    target_name = clean_desktop_name(target_folder_name)
    if not cleaned_query or not target_name:
        return "Mir fehlt der Suchbegriff oder der Zielordner."

    target_folder = find_desktop_folder(target_name) or _safe_child(primary_root, target_name)
    if not target_folder.exists():
        target_folder.mkdir(parents=False, exist_ok=False)
    if not target_folder.is_dir():
        return f"{target_folder.name} ist kein Ordner."

    matches: list[Path] = []
    seen: set[Path] = set()
    similar_names: list[str] = []
    target_resolved = target_folder.resolve()
    for root in roots:
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for path in children:
            if path.name.startswith("."):
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved == target_resolved or resolved in seen:
                continue
            seen.add(resolved)
            if files_only and not path.is_file():
                continue
            if name_matches_query(path.name, cleaned_query):
                matches.append(path)
            elif "bewer" in normalize_name(path.name):
                similar_names.append(path.name)

    if not matches:
        if similar_names:
            sample = "; ".join(similar_names[:6])
            return (
                f"Ich sehe zwar Bewerbungs-Dateien auf deinem Schreibtisch, konnte sie aber nicht verschieben: {sample}. "
                "Das sieht nach einem macOS-Zugriffs- oder iCloud-Schreibtisch-Problem aus."
            )
        return f"Ich finde auf deinem Schreibtisch keine Datei mit {query} im Namen."

    moved = []
    skipped = []
    for source in matches:
        destination = target_folder / source.name
        if destination.exists():
            skipped.append(source.name)
            continue
        shutil.move(str(source), str(destination))
        moved.append(source.name)

    if not moved:
        return f"Ich habe nichts verschoben, weil im Ordner {target_folder.name} schon passende Dateien vorhanden sind."

    sample = "; ".join(moved[:5])
    extra_count = len(moved) - len(moved[:5])
    extra = f" und {extra_count} weitere" if extra_count > 0 else ""
    skipped_text = f" {len(skipped)} Datei(en) waren schon vorhanden und wurden übersprungen." if skipped else ""
    return f"Erledigt. Ich habe {len(moved)} Datei(en) mit {query} im Namen in den Ordner {target_folder.name} verschoben: {sample}{extra}.{skipped_text}"


def find_desktop_folder(name_query: str) -> Path | None:
    root = desktop_path()
    cleaned_query = normalize_name(clean_desktop_name(name_query))
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


def find_desktop_item(name_query: str) -> Path | None:
    root = desktop_path()
    cleaned_query = normalize_name(clean_desktop_name(name_query))
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
        for path in root.rglob("*")
        if not path.name.startswith(".") and cleaned_query in normalize_name(path.name)
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]

    return None


def clean_desktop_name(text: str) -> str:
    cleaned = str(text).strip(" .,!?:;\"'")
    cleaned = re.sub(
        r"^(?:bitte\s+|mal\s+)*(?:die|der|das|den|dem|eine|einen|einem)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:datei|ordner|folder)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(?:auf|am|in)\s+(?:meinem\s+|meinen\s+|meiner\s+)?(?:desktop|schreibtisch)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:erstelle|erstell|mach|mache|leg|lege)\s+(?:mir\s+)?(?:einen\s+|eine\s+|neuen\s+|neue\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(?:ordner|folder)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:auf|am|in|meinem|meinen|meiner|desktop|schreibtisch)\b", " ", cleaned, flags=re.IGNORECASE)
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
        terms.add("rechnung")
    if cleaned_query.startswith("versicherung"):
        terms.add("versicherung")
    return {term for term in terms if len(term) >= 4}

def _safe_child(root: Path, child_name: str) -> Path:
    if not child_name or "/" in child_name or "\\" in child_name:
        raise DesktopAccessError("Der Name ist für einen Schreibtisch-Ordner nicht sicher genug.")

    child = (root / child_name).resolve()
    try:
        child.relative_to(root.resolve())
    except ValueError as exc:
        raise DesktopAccessError("Ich arbeite hier nur innerhalb deines Schreibtischs.") from exc
    return child
