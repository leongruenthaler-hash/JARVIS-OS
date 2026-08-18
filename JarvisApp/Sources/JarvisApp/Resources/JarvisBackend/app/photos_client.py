from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data_dir import data_root
from local_vision_service import LocalVisionError, LocalVisionService
from secure_storage import SecureStorageError, get_openai_api_key
from typing import Any


PHOTOS_HELPER_BUNDLE_ID = "com.leon.jarvis.photoshelper"


def _macos_sdk_path() -> str:
    """Ermittelt den SDK-Pfad, der tatsaechlich zum aktiven Xcode-Compiler passt
    (nicht der von "xcrun --show-sdk-path" ohne "-sdk macosx", das auf diesem Mac
    faelschlich die CommandLineTools-SDK liefert - siehe _ensure_helper()). Best
    effort: bei Fehlern leerer String, dann laesst swiftc die SDK-Wahl wie zuvor
    automatisch treffen, statt den Foto-Helfer-Kompilierlauf ganz scheitern zu
    lassen."""
    try:
        result = subprocess.run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


class PhotosAccessError(RuntimeError):
    pass


@dataclass
class PhotoMatch:
    photo_id: str
    score: int
    labels: list[str]
    texts: list[str]
    created_at: str
    filename: str = ""
    media_type: str = ""
    vision_description: str = ""


class PhotoIndex:
    def __init__(self, config: dict[str, Any], base_path: Path | None = None):
        self.config = config
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.base_path / "photos_index.json"
        self.progress_path = self.base_path / "photos_scan_progress.json"
        self.local_vision_progress_path = self.base_path / "photos_local_vision_progress.json"
        self.app_dir = Path(__file__).resolve().parent
        self.helper_source = self.app_dir / "photos_helper.swift"
        self.project_helper_bundle = data_root() / "PhotosHelper" / "Jarvis Photos Helper.app"
        self.helper_bundle = self._choose_helper_bundle()
        self.helper_contents = self.helper_bundle / "Contents"
        self.helper_macos = self.helper_contents / "MacOS"
        self.helper_resources = self.helper_contents / "Resources"
        self.helper_plist = self.helper_contents / "Info.plist"
        self.helper_binary = self.helper_macos / "JarvisPhotosHelper"

    def _choose_helper_bundle(self) -> Path:
        # Keep the helper at one stable path so macOS does not treat it like a new app
        # on every launch. A moving helper bundle tends to retrigger privacy prompts.
        return self.project_helper_bundle

    def scan(self, max_items: int | None = None) -> int:
        if max_items is None:
            max_items = int(self.config.get("photos_scan_max_items", 500))
        else:
            max_items = int(max_items)
        timeout = int(self.config.get("photos_scan_timeout_seconds", 3600))
        cache = self._load_cache()
        previous_entries = {
            str(entry.get("id")): entry
            for entry in cache.get("entries", [])
            if entry.get("id")
        }
        known_metadata = {
            record_id: str(entry.get("modifiedAt") or "")
            for record_id, entry in previous_entries.items()
            if str(entry.get("modifiedAt") or "")
        }
        known_path = Path(tempfile.gettempdir()) / f"jarvis_photos_known_{os.getpid()}_{time_safe_stamp()}.json"
        try:
            known_path.write_text(json.dumps(known_metadata), encoding="utf-8")
            output = self._run_helper(
                ["scan", str(max_items), "--known", str(known_path), "--progress", str(self.progress_path)],
                timeout=timeout,
            )
        finally:
            try:
                known_path.unlink()
            except OSError:
                pass
        try:
            payload = json.loads(output or "[]")
        except json.JSONDecodeError as exc:
            raise PhotosAccessError("Fotos-Scan hat keine lesbaren Daten geliefert.") from exc

        if isinstance(payload, dict):
            records = list(payload.get("records") or [])
            stats = dict(payload.get("stats") or {})
        else:
            records = list(payload or [])
            stats = {
                "photosFound": len(records),
                "videosFound": 0,
                "indexEntries": len(records),
                "durationSeconds": 0,
            }

        indexed_entries: dict[str, dict[str, Any]] = {}
        for record in records:
            record_id = str(record.get("id") or "")
            if record_id:
                previous = previous_entries.get(record_id, {})
                unchanged = (
                    previous
                    and str(previous.get("modifiedAt") or "")
                    and str(previous.get("modifiedAt") or "") == str(record.get("modifiedAt") or "")
                )
                if unchanged:
                    preserved = dict(previous)
                    preserved.update(
                        {
                            "filename": record.get("filename", preserved.get("filename", "")),
                            "mediaType": record.get("mediaType", preserved.get("mediaType", "")),
                            "createdAt": record.get("createdAt", preserved.get("createdAt", "")),
                            "modifiedAt": record.get("modifiedAt", preserved.get("modifiedAt", "")),
                            "width": record.get("width", preserved.get("width", 0)),
                            "height": record.get("height", preserved.get("height", 0)),
                            "favorite": record.get("favorite", preserved.get("favorite", False)),
                        }
                    )
                    record = preserved
                else:
                    if previous.get("vision_description"):
                        record["vision_description"] = previous.get("vision_description")
                    if previous.get("vision_analyzed_at"):
                        record["vision_analyzed_at"] = previous.get("vision_analyzed_at")
                    for key in (
                        "local_vision_description",
                        "local_vision_objects",
                        "local_vision_scene",
                        "local_vision_colors",
                        "local_vision_text",
                        "local_vision_search_terms",
                        "local_vision_model",
                        "local_vision_analyzed_at",
                    ):
                        if previous.get(key):
                            record[key] = previous.get(key)
                record["search_terms"] = sorted(entry_search_terms(record))
                indexed_entries[record_id] = record

        duration = float(stats.get("durationSeconds") or 0)
        photos_found = int(stats.get("photosFound") or 0)
        videos_found = int(stats.get("videosFound") or 0)
        index_entries = int(stats.get("indexEntries") or len(records))
        new_cache = {
            **cache,
            "last_scan_at": datetime.now().isoformat(timespec="seconds"),
            "last_error": "",
            "stats": {
                "photos_found": photos_found,
                "videos_found": videos_found,
                "index_entries": index_entries,
                "indexed_total": len(indexed_entries),
                "duration_seconds": duration,
                "database_bytes": self.cache_path.stat().st_size if self.cache_path.exists() else 0,
            },
            "entries": list(indexed_entries.values()),
        }
        self._save_cache(new_cache)
        saved_size = self.cache_path.stat().st_size if self.cache_path.exists() else 0
        cache = self._load_cache()
        cache.setdefault("stats", {})["database_bytes"] = saved_size
        self._save_cache(cache)
        print(f"Fotos gefunden: {photos_found}")
        print(f"Videos gefunden: {videos_found}")
        print(f"Indexeinträge: {index_entries}")
        print(f"Indexdauer: {duration:.2f}s")
        return len(records)

    def permission_status(self) -> str:
        output = self._run_helper(["status"], timeout=20)
        return output.strip() or "unknown"

    def request_permission(self) -> str:
        try:
            current_status = self.permission_status()
        except PhotosAccessError:
            current_status = "unknown"

        if current_status == "restricted":
            return (
                "macOS blockiert den Fotos-Zugriff gerade grundsätzlich. "
                "Das ist kein normaler Ablehnen-Status, sondern eine Einschränkung durch das System."
            )

        if current_status == "denied":
            reset_ok, reset_error = self._reset_permission()
            if not reset_ok:
                return (
                    "Der Fotos-Zugriff ist aktuell von macOS abgelehnt, und ich konnte den Reset nicht selbst ausführen. "
                    "Bitte beende Jarvis kurz und führe im normalen Terminal aus: "
                    f"tccutil reset Photos {PHOTOS_HELPER_BUNDLE_ID}. "
                    "Starte Jarvis danach neu und sag: Jarvis, fordere Fotos-Freigabe an."
                    + (f" Technische Meldung: {reset_error}" if reset_error else "")
                )

        try:
            output = self._run_helper(["authorize"], timeout=35)
        except PhotosAccessError as exc:
            return (
                "Ich konnte den Fotos-Freigabe-Dialog gerade nicht sauber auslösen. "
                "Beende Jarvis kurz und führe im normalen Terminal aus: "
                f"tccutil reset Photos {PHOTOS_HELPER_BUNDLE_ID}. "
                "Starte Jarvis danach neu und sag: Jarvis, fordere Fotos-Freigabe an. "
                f"Technische Meldung: {exc}"
            )

        status = output.strip()
        if status in {"authorized", "limited"}:
            return "Fotos-Zugriff ist erlaubt. Sie können jetzt sagen: Jarvis, scanne meine Fotos im Hintergrund."

        return (
            f"Der Fotos-Zugriff ist noch nicht erlaubt. Aktueller macOS-Status: {status}. "
            "Falls kein Freigabe-Dialog erschienen ist, beende Jarvis kurz und führe im Terminal aus: "
            f"tccutil reset Photos {PHOTOS_HELPER_BUNDLE_ID}. "
            "Danach starte Jarvis neu und fordere die Fotos-Freigabe erneut an."
        )

    def search(self, query: str, max_results: int | None = None) -> list[PhotoMatch]:
        max_results = int(max_results or self.config.get("photos_search_max_results", 25))
        cache = self._load_cache()
        entries = cache.get("entries", [])

        terms = expand_photo_query(query)
        scored: list[PhotoMatch] = []
        for entry in entries:
            score = score_photo_entry(entry, terms, query)
            if score <= 0:
                continue

            scored.append(
                PhotoMatch(
                    photo_id=str(entry.get("id", "")),
                    score=score,
                    labels=list(entry.get("labels", [])),
                    texts=list(entry.get("texts", [])),
                    created_at=str(entry.get("createdAt", "")),
                    filename=str(entry.get("filename", "")),
                    media_type=str(entry.get("mediaType", "")),
                    vision_description=str(entry.get("vision_description", "")),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max_results]

    def create_album_from_search(self, query: str, max_results: int | None = None) -> tuple[str, int]:
        matches = self.search(query, max_results=max_results)
        if not matches:
            return "", 0

        album_name = make_album_name(query, self.config)
        ids = [match.photo_id for match in matches if match.photo_id]
        output = self._run_helper(["album", album_name, *ids], timeout=60)
        try:
            count = int((output or "0").strip())
        except ValueError:
            count = len(ids)

        return album_name, count

    def export_search_to_desktop_folder(
        self,
        query: str,
        max_results: int | None = None,
        preview_size: int | None = None,
    ) -> tuple[Path, int]:
        matches = self.search(query, max_results=max_results)
        if not matches:
            return Path(), 0

        try:
            folder = unique_desktop_folder(make_desktop_folder_name(query, self.config))
            folder.mkdir(parents=True, exist_ok=False)
        except PermissionError as exc:
            raise PhotosAccessError(
                "Ich habe passende Fotos gefunden, darf aber gerade keinen Ordner auf Ihrem Schreibtisch erstellen. "
                "Aktivieren Sie in Jarvis die Datei-Berechtigung und erlauben Sie macOS den Zugriff auf den Schreibtisch."
            ) from exc
        except FileExistsError as exc:
            # unique_desktop_folder() checked for a free name and mkdir(exist_ok=False)
            # re-checks it - a real but narrow race (something else creating the same
            # folder name in between) previously surfaced as an unhandled crash instead
            # of the same friendly error every other export failure gets here.
            raise PhotosAccessError(
                "Ich habe passende Fotos gefunden, aber der Zielordner auf Ihrem Schreibtisch wurde gerade "
                "anderweitig angelegt. Versuchen Sie es gleich noch einmal."
            ) from exc
        size = int(preview_size or self.config.get("photos_desktop_export_preview_size", 1800))
        exported = 0
        for index, match in enumerate(matches, start=1):
            if not match.photo_id:
                continue
            safe_name = sanitize_photo_filename(match.filename or f"Foto_{index}.jpg")
            if not Path(safe_name).suffix:
                safe_name += ".jpg"
            destination = folder / f"{index:02d}_{safe_name}"
            try:
                self._export_preview(match.photo_id, destination, size)
                exported += 1
                from core.activity_log import record_activity
                record_activity("photo", safe_name)
            except Exception as exc:
                print(f"Foto-Schreibtisch-Export Fehler fuer ein Foto: {type(exc).__name__}")

        if exported == 0:
            try:
                folder.rmdir()
            except OSError:
                pass
            return Path(), 0

        return folder, exported

    def analyze_with_openai_vision(self, max_items: int | None = None) -> tuple[int, int]:
        if not bool(self.config.get("openai_photo_vision_enabled", False)):
            raise PhotosAccessError("OpenAI-Fotoanalyse ist deaktiviert. Aktiviere openai_photo_vision_enabled in config.json.")

        # openai_photo_vision_enabled alone was previously enough to start sending photo
        # previews to OpenAI - no explicit consent moment, unlike every other
        # data-leaves-the-device path in this codebase, which is gated behind the
        # Datenschutz permission system (see PERMISSION_DEFINITIONS["external_api"]).
        # Same gate here, so flipping the config flag alone can no longer trigger it.
        from permission_manager import PermissionManager

        if not PermissionManager().is_allowed("external_api"):
            raise PhotosAccessError(
                "Für die OpenAI-Fotoanalyse fehlt noch Ihre Zustimmung. Aktivieren Sie die "
                "Berechtigung 'Externe APIs' im Datenschutz-Bereich - erst danach verlassen "
                "Foto-Vorschaubilder Ihr Gerät."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise PhotosAccessError("Das Python-Paket openai ist nicht installiert.") from exc

        cache = self._load_cache()
        entries = list(cache.get("entries", []))
        if not entries:
            raise PhotosAccessError("Im Fotoindex sind noch keine Fotos. Scannen Sie zuerst Ihre Fotos im Hintergrund.")

        limit = int(max_items or self.config.get("openai_photo_vision_max_per_run", 20))
        limit = max(1, min(limit, 100))
        preview_size = int(self.config.get("openai_photo_vision_preview_size", 900))
        model = str(self.config.get("openai_photo_vision_model") or self.config.get("openai_model") or "gpt-5.4-nano")
        max_tokens = int(self.config.get("openai_photo_vision_max_output_tokens", 120))
        try:
            api_key = get_openai_api_key()
        except SecureStorageError as exc:
            raise PhotosAccessError(str(exc)) from exc
        if not api_key:
            raise PhotosAccessError("OpenAI API-Key fehlt. Speichere ihn sicher mit: python3 app/jarvis.py --set-openai-key")
        client = OpenAI(api_key=api_key, timeout=float(self.config.get("openai_timeout", 30)))

        analyzed = 0
        failed = 0
        for entry in entries:
            if analyzed >= limit:
                break
            if entry.get("vision_description"):
                continue

            photo_id = str(entry.get("id") or "")
            if not photo_id:
                continue

            preview_path = Path(tempfile.gettempdir()) / f"jarvis_photo_preview_{os.getpid()}_{time_safe_stamp()}.jpg"
            try:
                self._export_preview(photo_id, preview_path, preview_size)
                description = self._describe_preview_with_openai(client, model, preview_path, max_tokens)
            except Exception as exc:
                failed += 1
                print(f"OpenAI-Fotoanalyse Fehler fuer ein Foto: {type(exc).__name__}")
                continue
            finally:
                try:
                    preview_path.unlink()
                except OSError:
                    pass

            if description:
                entry["vision_description"] = description
                entry["vision_analyzed_at"] = datetime.now().isoformat(timespec="seconds")
                analyzed += 1

        cache["entries"] = entries
        cache["last_vision_scan_at"] = datetime.now().isoformat(timespec="seconds")
        cache["last_vision_error"] = "" if analyzed else ("Keine neuen Fotos analysiert." if not failed else "Einige Fotos konnten nicht analysiert werden.")
        self._save_cache(cache)
        return analyzed, failed

    def local_vision_status(self) -> dict[str, Any]:
        service = LocalVisionService(self.config)
        status = service.status()
        return {
            "available": status.available,
            "model": status.model,
            "installed_models": status.installed_models,
            "message": status.message,
        }

    def analyze_with_local_vision(self, max_items: int | None = None) -> tuple[int, int]:
        cache = self._load_cache()
        entries = list(cache.get("entries", []))
        if not entries:
            raise PhotosAccessError("Im Fotoindex sind noch keine Fotos. Scannen Sie zuerst Ihre Fotos.")

        service = LocalVisionService(self.config)
        status = service.status()
        if not status.available:
            raise PhotosAccessError(status.message)

        limit = int(max_items or self.config.get("local_photo_vision_max_per_run", 20))
        limit = max(1, min(limit, 200))
        preview_size = int(self.config.get("local_photo_vision_preview_size", 768))
        retry_after_days = float(self.config.get("local_photo_vision_unavailable_retry_days", 14))

        def _is_pending(entry: dict[str, Any]) -> bool:
            if not str(entry.get("id") or "").strip():
                return False
            if str(entry.get("mediaType") or "image") != "image":
                return False
            if str(entry.get("local_vision_analyzed_at") or "").strip():
                return False
            unavailable_since = str(entry.get("local_vision_unavailable_since") or "").strip()
            if not unavailable_since:
                return True
            try:
                marked_at = datetime.fromisoformat(unavailable_since)
            except ValueError:
                return True
            return (datetime.now() - marked_at).total_seconds() / 86400 >= retry_after_days

        pending = [entry for entry in entries if _is_pending(entry)][:limit]

        started_at = datetime.now().isoformat(timespec="seconds")
        total = len(pending)
        analyzed = 0
        failed = 0
        self._save_local_vision_progress(
            "preparing",
            "Lokale Fotoanalyse wird vorbereitet.",
            current_item=0,
            total_items=total,
            started_at=started_at,
            stats={"model": status.model, "errors": 0},
        )

        for index, entry in enumerate(pending, start=1):
            photo_id = str(entry.get("id") or "")
            filename = str(entry.get("filename") or photo_id)
            self._save_local_vision_progress(
                "indexing",
                f"Analysiere {filename}",
                current_item=index - 1,
                total_items=total,
                started_at=started_at,
                stats={"model": status.model, "errors": failed, "current_photo": filename},
            )

            # Einmaliger Retry mit kurzer Pause statt sofort aufzugeben - live
            # beobachtet (2026-08-16): ein Foto, das isoliert anstandslos
            # exportierte, scheiterte im 200er-Batch reihenweise (bis zu 82%
            # Fehlerquote trotz freiem Speicherplatz, kein Format-Unterschied
            # zwischen JPG/DNG). Deutet auf kurzzeitige Ueberlastung der
            # Foto-App-Hintergrunddienste unter Dauerlast hin, nicht auf ein
            # Problem mit dem einzelnen Foto - genau das Symptom-Muster, das ein
            # zweiter Versuch nach kurzer Pause behebt.
            result: dict[str, Any] | None = None
            last_exc: Exception | None = None
            for attempt in range(2):
                preview_path = Path(tempfile.gettempdir()) / f"jarvis_local_photo_preview_{os.getpid()}_{time_safe_stamp()}.jpg"
                try:
                    if attempt:
                        time.sleep(2)
                    self._export_preview(photo_id, preview_path, preview_size)
                    result = service.describe_image(preview_path)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                finally:
                    try:
                        preview_path.unlink()
                    except OSError:
                        pass

            if result is not None:
                entry["local_vision_description"] = str(result.get("description") or "")
                entry["local_vision_objects"] = list(result.get("objects") or [])
                entry["local_vision_scene"] = str(result.get("scene") or "")
                entry["local_vision_colors"] = list(result.get("colors") or [])
                entry["local_vision_text"] = str(result.get("text") or "")
                entry["local_vision_search_terms"] = sorted(set(result.get("search_terms") or []))
                entry["local_vision_model"] = str(result.get("model") or status.model)
                entry["local_vision_analyzed_at"] = datetime.now().isoformat(timespec="seconds")
                entry["search_terms"] = sorted(entry_search_terms(entry))
                entry.pop("local_vision_unavailable_since", None)
                entry.pop("local_vision_last_error", None)
                analyzed += 1
            else:
                failed += 1
                # Als "aktuell nicht abrufbar" markieren statt endlos jede Nacht
                # neu zu versuchen - live entdeckt (2026-08-17): manche Fotos
                # scheitern zuverlaessig mit einer echten Zeitueberschreitung beim
                # Laden aus iCloud (siehe exportPreview() in photos_helper.swift),
                # kein kurzzeitiges Problem, das ein Retry beheben wuerde. Zeitstempel
                # + konkrete Fehlermeldung statt eines dauerhaften stillen Ausschlusses,
                # damit pending() unten nach local_photo_vision_unavailable_retry_days
                # von selbst wieder einen neuen Versuch erlaubt.
                entry["local_vision_unavailable_since"] = datetime.now().isoformat(timespec="seconds")
                entry["local_vision_last_error"] = str(last_exc) if last_exc else "Unbekannter Fehler."
                print(f"Lokale Fotoanalyse Fehler fuer ein Foto (nach Retry): {entry['local_vision_last_error']}")

            self._save_local_vision_progress(
                "indexing",
                f"Analysiert: {filename}",
                current_item=index,
                total_items=total,
                started_at=started_at,
                stats={"model": status.model, "errors": failed, "current_photo": filename},
            )

        cache["entries"] = entries
        cache["last_local_vision_scan_at"] = datetime.now().isoformat(timespec="seconds")
        cache["last_local_vision_error"] = "" if failed == 0 else f"{failed} Foto(s) konnten nicht lokal analysiert werden."
        self._save_cache(cache)
        self._save_local_vision_progress(
            "completed",
            "Lokale Fotoanalyse fertig.",
            current_item=total,
            total_items=total,
            started_at=started_at,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            stats={"model": status.model, "analyzed": analyzed, "errors": failed, "local_descriptions": count_local_descriptions(entries)},
        )
        return analyzed, failed

    def local_vision_run_summary(self) -> dict[str, Any]:
        """Liest den zuletzt gespeicherten Fortschritt/Abschluss der lokalen
        Foto-Vision-Analyse fuer die Proactivity-Regel in proactivity_rules.py -
        liefert nur ein aufbereitetes Dict, keine Rohdatei-Struktur, damit
        proactivity_rules.py das Dateiformat von photos_client.py nicht kennen muss."""
        if not self.local_vision_progress_path.exists():
            return {}
        try:
            payload = json.loads(self.local_vision_progress_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(payload, dict):
            return {}
        stats = payload.get("stats") or {}
        return {
            "status": str(payload.get("status") or ""),
            "finished_at": str(payload.get("finishedAt") or ""),
            "analyzed": int(stats.get("analyzed") or 0),
            "errors": int(stats.get("errors") or 0),
        }

    def reset_local_vision_descriptions(self) -> int:
        cache = self._load_cache()
        entries = list(cache.get("entries", []))
        removed = 0
        keys = (
            "local_vision_description",
            "local_vision_objects",
            "local_vision_scene",
            "local_vision_colors",
            "local_vision_text",
            "local_vision_search_terms",
            "local_vision_model",
            "local_vision_analyzed_at",
            "local_vision_unavailable_since",
            "local_vision_last_error",
        )
        for entry in entries:
            if any(entry.get(key) for key in keys):
                removed += 1
            for key in keys:
                entry.pop(key, None)
            entry["search_terms"] = sorted(entry_search_terms(entry))
        cache["entries"] = entries
        cache["last_local_vision_scan_at"] = ""
        cache["last_local_vision_error"] = ""
        self._save_cache(cache)
        try:
            self.local_vision_progress_path.unlink()
        except OSError:
            pass
        return removed

    def _save_local_vision_progress(
        self,
        status: str,
        label: str,
        *,
        current_item: int = 0,
        total_items: int = 0,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        percentage = 0.0
        if total_items > 0:
            percentage = min(100.0, max(0.0, (float(current_item) / float(total_items)) * 100.0))
        payload = {
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
        self.local_vision_progress_path.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")

    def _export_preview(self, photo_id: str, destination: Path, max_size: int):
        self._run_helper(["export", photo_id, str(destination), str(max_size)], timeout=60)
        if not destination.exists() or destination.stat().st_size <= 0:
            raise PhotosAccessError("Foto-Vorschau wurde nicht exportiert.")

    def _describe_preview_with_openai(self, client, model: str, image_path: Path, max_tokens: int) -> str:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "Beschreibe dieses private Foto fuer einen lokalen Fotoindex auf Deutsch. "
            "Sei konkret und kurz. Erwaehne sichtbare Hauptmotive wie Katze, Person, Dokument, Rechnung, Essen, Auto, Ort, Text. "
            "Identifiziere unbekannte Personen nicht namentlich. Wenn Text/Datum/Betrag sichtbar ist, fasse ihn knapp zusammen. "
            "Maximal zwei kurze Saetze, keine Markdown-Liste."
        )
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_b64}"},
                    ],
                }
            ],
            max_output_tokens=max_tokens,
        )
        return str(getattr(response, "output_text", "") or "").strip()

    def cached_status(self) -> str:
        cache = self._load_cache()
        entries = cache.get("entries", [])
        last_scan = cache.get("last_scan_at")
        last_error = str(cache.get("last_error") or "").strip()
        if last_error in {"authorized", "limited"}:
            cache["last_error"] = ""
            self._save_cache(cache)
            last_error = ""

        if last_error:
            return f"Fotos-Index ist bereit, der letzte Scan hatte aber einen Fehler: {last_error}"

        if cache.get("scan_started_at") and cache.get("scan_started_at") != cache.get("last_scan_at"):
            return "Fotos-Index wird gerade im Hintergrund aufgebaut."

        if not last_scan:
            return "Fotos-Index ist bereit, aber noch nicht gescannt."

        return (
            f"Fotos-Index ist bereit. Letzter Scan: {last_scan}, aktuell sichtbare Fotos: {len(entries)}. "
            "Ich scanne alle Fotos, die macOS in der lokalen Fotos-Mediathek freigibt. "
            "Wenn hier zu wenig steht, ist die iCloud-Fotomediathek auf diesem Mac vermutlich noch nicht vollständig synchronisiert."
        )

    def summarize_index(self, max_terms: int = 8) -> str:
        cache = self._load_cache()
        entries = cache.get("entries", [])
        last_scan = cache.get("last_scan_at")
        if not entries:
            return "Ich sehe im Fotoindex noch keine Fotos. Sag: Jarvis, scanne meine Fotos im Hintergrund."

        descriptions = [
            str(entry.get("local_vision_description") or entry.get("vision_description", "")).strip()
            for entry in entries
            if str(entry.get("local_vision_description") or entry.get("vision_description", "")).strip()
        ]
        if descriptions:
            preview = " ".join(description.rstrip(" .") + "." for description in descriptions[:4])
            parts = [f"Ich sehe aktuell {len(entries)} Foto(s) im Index, davon {len(descriptions)} genauer analysiert"]
            if last_scan:
                parts.append(f"letzter Scan: {last_scan}")
            parts.append(f"Inhaltlich erkenne ich unter anderem: {preview}")
            return ". ".join(parts) + "."

        label_counts: dict[str, int] = {}
        text_counts: dict[str, int] = {}
        for entry in entries:
            for label in entry.get("labels", []) or []:
                label = german_photo_label(str(label).strip().lower())
                if len(label) >= 3:
                    label_counts[label] = label_counts.get(label, 0) + 1
            for text in entry.get("texts", []) or []:
                text = str(text).strip().lower()
                if len(text) >= 3:
                    text_counts[text] = text_counts.get(text, 0) + 1

        top_labels = sorted(label_counts.items(), key=lambda item: item[1], reverse=True)[:max_terms]
        top_texts = sorted(text_counts.items(), key=lambda item: item[1], reverse=True)[:4]
        label_text = ", ".join(f"{label} ({count})" for label, count in top_labels)
        text_text = ", ".join(text for text, _count in top_texts)

        parts = [f"Ich sehe aktuell {len(entries)} Foto(s) im Index"]
        if last_scan:
            parts.append(f"letzter Scan: {last_scan}")
        if label_text:
            parts.append(f"grobe lokale Motive: {label_text}")
        if text_text:
            parts.append(f"erkannter Text: {text_text}")
        parts.append("Für echte Bildbeschreibungen sag: Jarvis, analysiere meine Fotos lokal")

        return ". ".join(parts) + "."

    def debug_statistics(self) -> str:
        cache = self._load_cache()
        entries = list(cache.get("entries", []))
        stats = dict(cache.get("stats") or {})
        labels: set[str] = set()
        indexed_with_labels = 0
        indexed_with_text = 0
        for entry in entries:
            entry_labels = [str(label).strip() for label in entry.get("labels", []) if str(label).strip()]
            labels.update(entry_labels)
            if entry_labels:
                indexed_with_labels += 1
            if any(str(text).strip() for text in entry.get("texts", [])):
                indexed_with_text += 1

        database_bytes = self.cache_path.stat().st_size if self.cache_path.exists() else 0
        photos_total = int(stats.get("photos_found") or len([entry for entry in entries if str(entry.get("mediaType") or "image") == "image"]))
        videos_total = int(stats.get("videos_found") or len([entry for entry in entries if str(entry.get("mediaType") or "") == "video"]))
        return (
            "Index-Statistik: "
            f"Fotos insgesamt: {photos_total}. "
            f"Videos insgesamt: {videos_total}. "
            f"Indexierte Fotos/Videos: {len(entries)}. "
            f"Indexeinträge letzter Scan: {int(stats.get('index_entries') or len(entries))}. "
            f"Einträge mit Labels: {indexed_with_labels}. "
            f"Einträge mit OCR-Text: {indexed_with_text}. "
            f"Erkannte Labels: {len(labels)}. "
            f"Größe der Datenbank: {database_bytes} Bytes. "
            f"Letzte Aktualisierung: {cache.get('last_scan_at') or 'noch nie'}."
        )

    def count_matches(self, query: str) -> tuple[int, set[str]]:
        terms = expand_photo_query(query)
        return len(self.search(query, max_results=10_000)), terms

    def has_entries(self) -> bool:
        cache = self._load_cache()
        return bool(cache.get("entries"))

    def _ensure_helper(self) -> Path:
        self._ensure_helper_bundle()
        needs_compile = not self.helper_binary.exists()
        if not needs_compile:
            binary_mtime = self.helper_binary.stat().st_mtime
            needs_compile = (
                self.helper_source.stat().st_mtime > binary_mtime
                or self.helper_plist.stat().st_mtime > binary_mtime
            )

        if not needs_compile:
            self._register_helper_bundle()
            return self.helper_binary

        command = [
            "xcrun",
            "swiftc",
            str(self.helper_source),
            "-o",
            str(self.helper_binary),
            # Ohne explizites Ziel kompiliert swiftc gegen die aktuell installierte
            # (teils Beta-)SDK-Version und schreibt deren Mindestversion fest ins
            # Binary - auf Leons Mac (macOS 27.0) fuehrte das dazu, dass der Helfer
            # macOS 28.0 verlangte und LaunchServices ihn komplett verweigerte
            # (Fehler -10825, "requires conditional 28.0, run on 27.0"), lange bevor
            # es ueberhaupt zu einer Fotos-Berechtigungsfrage kam. -target allein
            # reicht nicht: ohne explizites -sdk greift auf diesem Mac faelschlich
            # die (aeltere, nicht zum Compiler passende) CommandLineTools-SDK statt
            # der zu Xcode gehoerenden - deshalb beides fest zusammen angeben, damit
            # immer dieselbe, zum aktiven Compiler passende SDK verwendet wird.
            "-target",
            "arm64-apple-macosx14.0",
        ]
        sdk_path = _macos_sdk_path()
        if sdk_path:
            command += ["-sdk", sdk_path]
        command += [
            "-Xlinker",
            "-sectcreate",
            "-Xlinker",
            "__TEXT",
            "-Xlinker",
            "__info_plist",
            "-Xlinker",
            str(self.helper_plist),
            "-module-cache-path",
            "/private/tmp/jarvis_photos_swift_module_cache",
            "-framework",
            "Photos",
            "-framework",
            "Vision",
            "-framework",
            "AppKit",
            "-framework",
            "CoreGraphics",
        ]
        env = os.environ.copy()
        env["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/jarvis_photos_clang_cache"
        _run(command, timeout=60, env=env)
        self._codesign_helper()
        self._register_helper_bundle()
        return self.helper_binary

    def _run_helper(self, args: list[str], timeout: int) -> str:
        self._ensure_helper()
        output_file = Path(tempfile.gettempdir()) / f"jarvis_photos_helper_{os.getpid()}_{time_safe_stamp()}.txt"
        result, output = self._run_helper_app(args, output_file, timeout)

        if result.returncode != 0 and _is_launch_services_error(result):
            self._register_helper_bundle()
            result, output = self._run_helper_app(args, output_file, timeout)

        if result.returncode != 0 and _is_launch_services_error(result):
            result, output = self._run_helper_binary(args, output_file, timeout)

        if args and args[0] == "scan" and result.stderr:
            print(result.stderr.strip())

        clean_output = output.strip()
        if args and args[0] in {"status", "authorize"} and clean_output in {"authorized", "limited", "notDetermined", "denied", "restricted"}:
            return clean_output

        if result.returncode != 0 or output.startswith("ERROR:"):
            error = output.removeprefix("ERROR:").strip()
            if not error:
                error = (result.stderr or result.stdout).strip()
            if "nicht erlaubt" in error.lower() or "denied" in error.lower() or "restricted" in error.lower():
                raise PhotosAccessError(
                    error
                    + " Öffne Systemeinstellungen > Datenschutz & Sicherheit > Fotos "
                    "und erlaube Jarvis Photos Helper den Zugriff."
                )
            raise PhotosAccessError(error or "Fotos konnte nicht gelesen werden.")

        return output

    def _run_helper_app(
        self,
        args: list[str],
        output_file: Path,
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        command = [
            "open",
            "-W",
            str(self.helper_bundle),
            "--args",
            *args,
            "--output",
            str(output_file),
        ]
        result = _run_process(command, timeout=timeout)
        return result, _read_and_remove(output_file)

    def _run_helper_binary(
        self,
        args: list[str],
        output_file: Path,
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        command = [
            str(self.helper_binary),
            *args,
            "--output",
            str(output_file),
        ]
        result = _run_process(command, timeout=timeout)
        return result, _read_and_remove(output_file)

    def _ensure_helper_bundle(self):
        self.helper_macos.mkdir(parents=True, exist_ok=True)
        self.helper_resources.mkdir(parents=True, exist_ok=True)
        plist_text = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>de</string>
    <key>CFBundleDisplayName</key>
    <string>Jarvis Photos Helper</string>
    <key>CFBundleExecutable</key>
    <string>JarvisPhotosHelper</string>
    <key>CFBundleIdentifier</key>
    <string>com.leon.jarvis.photoshelper</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Jarvis Photos Helper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>3</string>
    <key>NSPhotoLibraryUsageDescription</key>
    <string>Jarvis braucht Zugriff, um Ihre Fotos lokal zu durchsuchen und passende Alben zu erstellen.</string>
    <key>NSPhotoLibraryAddUsageDescription</key>
    <string>Jarvis braucht Zugriff, um gefundene Fotos in neue Fotos-Alben zu legen.</string>
</dict>
</plist>
"""
        if not self.helper_plist.exists() or self.helper_plist.read_text(encoding="utf-8") != plist_text:
            self.helper_plist.write_text(plist_text, encoding="utf-8")

    def _codesign_helper(self):
        try:
            subprocess.run(
                ["xattr", "-cr", str(self.helper_bundle)],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            # Not fatal (codesign below can still succeed without this), but a failure
            # here used to vanish with no trace - the user would just see a generic
            # Photos permission error later with no way to connect it back to this step.
            print(f"Photos-Helper: xattr -cr fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

        commands = (
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--identifier",
                PHOTOS_HELPER_BUNDLE_ID,
                str(self.helper_binary),
            ],
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                "--identifier",
                PHOTOS_HELPER_BUNDLE_ID,
                str(self.helper_bundle),
            ],
        )
        for command in commands:
            try:
                subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as exc:
                print(f"Photos-Helper: codesign fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

    def _register_helper_bundle(self):
        commands = (
            [
                "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                "-f",
                str(self.helper_bundle),
            ],
        )
        for command in commands:
            try:
                subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception as exc:
                print(f"Photos-Helper: lsregister fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

    def _reset_permission(self) -> tuple[bool, str]:
        self._ensure_helper()
        errors: list[str] = []
        for service in ("Photos", "PhotosAdd"):
            try:
                result = subprocess.run(
                    ["tccutil", "reset", service, PHOTOS_HELPER_BUNDLE_ID],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception as exc:
                errors.append(f"{service}: {exc}")
                continue

            if result.returncode == 0:
                return True, ""

            error = (result.stderr or result.stdout).strip()
            if error:
                errors.append(f"{service}: {error}")

        return False, "; ".join(errors)

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}

        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_cache(self, cache: dict[str, Any]):
        temp_path = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(cache, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(self.cache_path)


class PhotoBackgroundWorker:
    def __init__(self, config: dict[str, Any], base_path: Path | None = None):
        self.config = config
        self.enabled = bool(config.get("photos_background_enabled", True))
        self.scan_time = str(config.get("photos_background_scan_time", "03:15"))
        self.vision_background_enabled = bool(config.get("local_photo_vision_background_enabled", True))
        self.index = PhotoIndex(config, base_path=base_path)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.scan_thread: threading.Thread | None = None
        self.vision_thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def start(self):
        if not self.enabled:
            return

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def request_scan(self) -> str:
        with self.lock:
            if self.scan_thread is not None and self.scan_thread.is_alive():
                return "Ich scanne Ihre Fotos bereits im Hintergrund."

            self.scan_thread = threading.Thread(target=self._scan_safely, daemon=True)
            self.scan_thread.start()

        return "Ich scanne Ihre Fotos im Hintergrund und baue den Suchindex auf."

    def request_vision_analysis(self) -> str:
        if not bool(self.config.get("openai_photo_vision_enabled", False)):
            return "Die OpenAI-Fotoanalyse ist deaktiviert. Ich schicke ohne Freigabe keine Bilder irgendwohin. Fast schon anständig."

        with self.lock:
            if self.vision_thread is not None and self.vision_thread.is_alive():
                return "Ich analysiere Ihre Fotos bereits genauer mit OpenAI."

            self.vision_thread = threading.Thread(target=self._vision_safely, daemon=True)
            self.vision_thread.start()

        limit = int(self.config.get("openai_photo_vision_max_per_run", 20))
        return (
            f"Ich analysiere bis zu {limit} Foto-Vorschauen mit OpenAI und speichere die Beschreibungen lokal im Fotoindex. "
            "Ich nutze dafür nur verkleinerte Vorschaubilder."
        )

    def search_to_album(self, query: str) -> str:
        return self.search_to_desktop_folder(query)

    def search_to_desktop_folder(self, query: str) -> str:
        if self.scan_thread is not None and self.scan_thread.is_alive():
            return (
                "Ich baue den Fotoindex gerade noch auf. "
                "Sobald der Scan fertig ist, kann ich die Treffer auf Ihren Schreibtisch legen."
            )

        if not self.index.has_entries():
            self.request_scan()
            return (
                "Ich habe noch keinen fertigen Fotoindex. "
                "Ich starte den Scan jetzt im Hintergrund und blockiere Jarvis dabei nicht."
            )

        folder, count = self.index.export_search_to_desktop_folder(query)
        if count <= 0:
            return (
                f"Ich habe in meinem Fotoindex keine passenden Treffer für {query} gefunden. "
                "Sag: Jarvis, scanne meine Fotos im Hintergrund, wenn der Index noch frisch aufgebaut werden soll."
            )

        return (
            f"Erledigt. Ich habe {count} passende Foto(s) in den neuen Ordner {folder.name} auf Ihrem Schreibtisch gelegt."
        )

    def count_search(self, query: str) -> str:
        if self.scan_thread is not None and self.scan_thread.is_alive():
            return "Ich baue den Fotoindex gerade noch auf. Die Zählung wäre jetzt ungefähr so präzise wie Wetterbericht von gestern."
        if not self.index.has_entries():
            self.request_scan()
            return "Ich habe noch keinen fertigen Fotoindex. Ich starte den Scan jetzt im Hintergrund."

        count, terms = self.index.count_matches(query)
        readable_terms = ", ".join(sorted(terms)[:8])
        if count == 0:
            return f"Ich finde aktuell keine passenden Fotos für {query}. Gesucht habe ich unter anderem nach: {readable_terms}."
        return f"Ich finde aktuell {count} passende Foto(s) für {query}. Gesucht habe ich unter anderem nach: {readable_terms}."

    def index_statistics(self) -> str:
        return self.index.debug_statistics()

    def progress_answer(self) -> str:
        cache = self.index._load_cache()
        progress = dict(cache.get("progress") or {})
        entries = list(cache.get("entries", []) or [])
        stats = dict(cache.get("stats") or {})
        total = int(progress.get("totalItems") or stats.get("photos_found") or len(entries) or 0)
        current = int(progress.get("currentItem") or len(entries) or 0)
        percent = 0
        if total > 0:
            percent = int(min(100, max(0, (current / total) * 100)))
        label = str(progress.get("currentLabel") or "Fotoindex ist bereit.")
        last_scan = cache.get("last_scan_at") or "noch nie"
        return f"Der Fotoindex steht bei {percent} %. {current} von {total} Elementen sind verarbeitet. Status: {label} Letzter erfolgreicher Lauf: {last_scan}."

    def status(self) -> str:
        try:
            permission = self.index.permission_status()
        except PhotosAccessError as exc:
            recovered_status = str(exc).strip().lower()
            if recovered_status in {"authorized", "limited"}:
                return self.index.cached_status()
            return f"Fotos-Index ist erreichbar, aber der Berechtigungsstatus konnte nicht gelesen werden: {exc}"

        if permission in {"authorized", "limited"}:
            return self.index.cached_status()

        if permission in {"denied", "restricted"}:
            return (
                "Fotos-Zugriff ist noch nicht erlaubt. "
                "Sag: Jarvis, fordere Fotos-Freigabe an. Wenn kein Dialog erscheint, öffne "
                "Systemeinstellungen > Datenschutz & Sicherheit > Fotos und erlaube Jarvis Photos Helper den Zugriff. "
                "Falls Jarvis Photos Helper dort nicht auftaucht, führe im Terminal aus: "
                "tccutil reset Photos com.leon.jarvis.photoshelper."
            )

        if permission == "notDetermined":
            return "Fotos-Zugriff wurde noch nicht angefragt. Sag: Jarvis, fordere Fotos-Freigabe an."

        return self.index.cached_status()

    def summary(self) -> str:
        if self.scan_thread is not None and self.scan_thread.is_alive():
            return "Ich baue den Fotoindex gerade noch auf. Frag mich gleich noch einmal, dann sehe ich klarer."
        if self.vision_thread is not None and self.vision_thread.is_alive():
            return "Ich analysiere gerade einige Fotos genauer mit OpenAI. Frag mich gleich noch einmal; ich starre dann weniger dumm auf Labels."
        return self.index.summarize_index()

    def request_permission(self) -> str:
        return self.index.request_permission()

    def _run_loop(self):
        while not self.stop_event.is_set():
            self._tick(datetime.now())
            self.stop_event.wait(60)

    def _tick(self, now: datetime):
        cache = self.index._load_cache()
        today = now.date().isoformat()
        if self._time_reached(now, self.scan_time) and cache.get("last_background_scan_date") != today:
            self._scan_safely()
            cache = self.index._load_cache()
            cache["last_background_scan_date"] = today
            self.index._save_cache(cache)

            # Vision-Lauf bewusst direkt nach dem Scan derselben Nacht, nicht als
            # eigener Zeitpunkt - siehe
            # plans/2026-08-10-jarvis-foto-vision-lokal-aktivieren.md. Vorher blieb
            # die lokale Bildbeschreibung ausschliesslich manuellen Sprachbefehlen
            # vorbehalten, obwohl der naechtliche Scan laengst lief (sobald er ueber
            # _ensure_photo_worker() ueberhaupt gestartet wurde) - der Fotoindex hatte
            # zwar Eintraege, aber nie automatisch erzeugte Bildbeschreibungen.
            if self.vision_background_enabled:
                self._vision_safely()
                cache = self.index._load_cache()
                cache["last_background_vision_date"] = today
                self.index._save_cache(cache)

    def _vision_safely(self):
        try:
            status = self.index.local_vision_status()
            if not bool(status.get("available")):
                print(f"Fotos-Hintergrund-Vision uebersprungen: {status.get('message')}")
                return

            analyzed, failed = self.index.analyze_with_local_vision()
            print(f"Fotos-Hintergrund-Vision fertig: {analyzed} analysiert, {failed} fehlgeschlagen.")
        except PhotosAccessError as exc:
            print(f"Fotos-Hintergrund-Vision uebersprungen: {exc}")
        except Exception as exc:
            print("Fotos-Hintergrund-Vision Fehler:", type(exc).__name__)

    def _scan_safely(self):
        cache = self.index._load_cache()
        cache["scan_started_at"] = datetime.now().isoformat(timespec="seconds")
        cache["last_error"] = ""
        self.index._save_cache(cache)
        try:
            permission = self.index.permission_status()
            if permission == "notDetermined":
                cache = self.index._load_cache()
                cache["last_error"] = "Fotos-Freigabe wurde noch nicht angefragt. Sag: Jarvis, fordere Fotos-Freigabe an."
                cache["last_scan_at"] = datetime.now().isoformat(timespec="seconds")
                cache["scan_started_at"] = cache["last_scan_at"]
                self.index._save_cache(cache)
                print("Fotos-Hintergrundscan wartet auf Freigabe.")
                return

            if permission in {"denied", "restricted"}:
                cache = self.index._load_cache()
                cache["last_error"] = "Fotos-Zugriff wurde von macOS noch nicht erlaubt."
                cache["last_scan_at"] = datetime.now().isoformat(timespec="seconds")
                cache["scan_started_at"] = cache["last_scan_at"]
                self.index._save_cache(cache)
                print("Fotos-Hintergrundscan wartet auf macOS-Freigabe.")
                return

            count = self.index.scan()
            cache = self.index._load_cache()
            cache["scan_started_at"] = cache.get("last_scan_at", "")
            self.index._save_cache(cache)
            stats = dict(cache.get("stats") or {})
            print(
                "Fotos-Hintergrundscan fertig: "
                f"Fotos gefunden: {int(stats.get('photos_found') or count)}, "
                f"Videos gefunden: {int(stats.get('videos_found') or 0)}, "
                f"Indexeinträge: {int(stats.get('index_entries') or count)}, "
                f"Dauer: {float(stats.get('duration_seconds') or 0):.2f}s."
            )
        except Exception as exc:
            cache = self.index._load_cache()
            cache["last_error"] = str(exc)
            cache["last_scan_at"] = datetime.now().isoformat(timespec="seconds")
            self.index._save_cache(cache)
            print("Fotos-Hintergrundscan Fehler:", type(exc).__name__)

    def _time_reached(self, now: datetime, time_text: str) -> bool:
        try:
            hour_text, minute_text = time_text.split(":", 1)
            target_hour = int(hour_text)
            target_minute = int(minute_text)
        except (ValueError, AttributeError):
            return False

        return (now.hour, now.minute) >= (target_hour, target_minute)


def extract_photo_query(text: str) -> str:
    patterns = (
        r"(?:foto|fotos|bild|bilder).*(?:mit|von|vom|von der|wo|worauf|in dem|indem|drauf)\s+(.+?)(?:\s+(?:vorkommt|vorkommen|zu sehen ist|sind|raus|heraus|suchen|such))?[.?!]*$",
        r"(?:such|suche|finde|zeig|zeige).*(?:foto|fotos|bild|bilder).*?(?:mit|von|vom|von der|wo|worauf|in dem|indem|drauf)?\s+(.+?)[.?!]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_photo_query(match.group(1))

    return ""


def extract_photo_count_query(text: str) -> str:
    normalized = normalize(text)
    count_words = ("wie viele", "wieviele", "anzahl", "zaehl", "zähl")
    if not any(word in normalized for word in count_words):
        return ""

    match = re.search(
        r"(?:mit|von|vom|wo|worauf|drauf|zeigen|enthaelt|enthalten)\s+(.+?)(?:\s+(?:habe|hab|sind|gibt|gibt es))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return clean_photo_query(match.group(1))

    return clean_photo_query(text)


def clean_photo_query(query: str) -> str:
    query = re.split(
        r"\b(?:und\s+)?(?:lege|leg|packe|pack|erstelle|mach|mache|schicke|send(?:e)?|als\s+album|aufs?\s+iphone|auf\s+dem\s+iphone|in\s+icloud)\b",
        query,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    query = re.sub(
        r"\b(?:bitte|mal|meine|meinen|meiner|ich|habe|hab|hast|du|schon|noch|bereits|wie|viele|wieviele|anzahl|zaehl|zähl|zähle|ein|eine|einen|raus|heraus|suchen|such|finde|zeig|zeige|fotos|foto|bilder|bild|album|icloud|iphone)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+", " ", query)
    return query.strip(" .,!?:;")


def make_album_name(query: str, config: dict[str, Any]) -> str:
    prefix = str(config.get("photos_album_prefix", "Jarvis"))
    cleaned = clean_photo_query(query) or "Suche"
    cleaned = re.sub(r"[/:]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f"{prefix} - {cleaned[:40]}"


def make_desktop_folder_name(query: str, config: dict[str, Any]) -> str:
    prefix = str(config.get("photos_desktop_folder_prefix", "Jarvis"))
    cleaned = clean_photo_query(query) or "Fotos"
    cleaned = re.sub(r"[/:\\\\]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    if not cleaned:
        cleaned = "Fotos"
    return f"{prefix} {cleaned[:42]}".strip()


def unique_desktop_folder(folder_name: str) -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_photo_filename(folder_name).strip(" ._-") or "Jarvis Fotos"
    candidate = desktop / safe_name
    if not candidate.exists():
        return candidate

    for number in range(2, 200):
        candidate = desktop / f"{safe_name} {number}"
        if not candidate.exists():
            return candidate
    raise PhotosAccessError("Ich konnte keinen freien Ordnernamen auf dem Schreibtisch finden.")


def sanitize_photo_filename(value: str) -> str:
    cleaned = re.sub(r"[/:\\\\]", " ", str(value or ""))
    cleaned = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:90] or "Foto.jpg"


def expand_photo_query(query: str) -> set[str]:
    normalized = normalize(query)
    terms = {word for word in normalized.split() if len(word) >= 2}
    if normalized:
        terms.add(normalized)

    synonyms = {
        "auto": {"auto", "pkw", "car", "cars", "vehicle", "vehicles", "automobile", "automobil", "sports car", "convertible", "conveyance"},
        "autos": {"auto", "pkw", "car", "cars", "vehicle", "vehicles", "automobile", "automobil", "sports car", "convertible", "conveyance"},
        "pkw": {"auto", "pkw", "car", "vehicle", "automobile", "automobil"},
        "car": {"auto", "pkw", "car", "vehicle", "automobile", "automobil", "conveyance"},
        "vehicle": {"auto", "pkw", "car", "vehicle", "automobile", "automobil", "conveyance"},
        "lamborghini": {"lamborghini", "sports car", "car", "automobile", "vehicle"},
        "hund": {"hund", "dog", "pet", "animal"},
        "katze": {"katze", "cat", "pet", "animal"},
        "strand": {"strand", "beach", "coast", "sea", "ocean"},
        "meer": {"meer", "sea", "ocean", "water", "beach"},
        "rechnung": {"rechnung", "invoice", "receipt", "document"},
        "essen": {"essen", "food", "meal", "dish"},
        "person": {"person", "people", "human", "portrait"},
        "menschen": {"person", "people", "human"},
        "text": {"text", "document", "screenshot"},
        "screenshot": {"screenshot", "screen", "text"},
        "schreibtisch": {"schreibtisch", "desk", "table", "workspace", "office", "computer", "monitor"},
        "desktop": {"schreibtisch", "desk", "table", "workspace", "office", "computer", "monitor"},
        "werkzeug": {"werkzeug", "tool", "tools", "hammer", "screwdriver", "wrench", "bohrer"},
        "fahrrad": {"fahrrad", "bike", "bicycle", "cycle", "rad"},
        "rad": {"fahrrad", "bike", "bicycle", "cycle", "rad"},
    }

    expanded = set(terms)
    for term in list(terms):
        expanded.update(synonyms.get(term, set()))

    return {term for term in expanded if term}


def score_photo_entry(entry: dict[str, Any], terms: set[str], raw_query: str) -> int:
    labels = [normalize(label) for label in entry.get("labels", [])]
    objects = [normalize(label) for label in entry.get("objects", [])]
    scenes = [normalize(label) for label in entry.get("scenes", [])]
    people = [normalize(label) for label in entry.get("people", [])]
    texts = [normalize(text) for text in entry.get("texts", [])]
    search_terms = [normalize(text) for text in entry.get("search_terms", [])]
    filename = normalize(str(entry.get("filename", "")))
    description = normalize(str(entry.get("vision_description", "")))
    local_description = normalize(str(entry.get("local_vision_description", "")))
    local_scene = normalize(str(entry.get("local_vision_scene", "")))
    local_objects = [normalize(label) for label in entry.get("local_vision_objects", [])]
    local_colors = [normalize(label) for label in entry.get("local_vision_colors", [])]
    local_text = normalize(str(entry.get("local_vision_text", "")))
    local_terms = [normalize(label) for label in entry.get("local_vision_search_terms", [])]
    haystack = " ".join(
        labels
        + objects
        + scenes
        + people
        + texts
        + search_terms
        + local_objects
        + local_colors
        + local_terms
        + [filename, description, local_description, local_scene, local_text]
    )
    raw = normalize(raw_query)

    score = 0
    if raw and raw in haystack:
        score += 100

    for term in terms:
        if not term:
            continue
        if term in texts:
            score += 80
        if any(term == label for label in labels + objects + scenes + people + search_terms):
            score += 50
        elif term in haystack:
            score += 25

    return score


def entry_search_terms(entry: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for key in ("labels", "objects", "scenes", "people", "texts"):
        for value in entry.get(key, []) or []:
            normalized = normalize(str(value))
            if normalized:
                terms.add(normalized)
    for key in ("local_vision_objects", "local_vision_colors", "local_vision_search_terms"):
        for value in entry.get(key, []) or []:
            normalized = normalize(str(value))
            if normalized:
                terms.add(normalized)
    for key in ("local_vision_description", "local_vision_scene", "local_vision_text"):
        normalized = normalize(str(entry.get(key, "")))
        if normalized:
            terms.add(normalized)
            terms.update(part for part in normalized.split() if len(part) >= 3)
    filename = normalize(str(entry.get("filename", "")))
    if filename:
        terms.update(part for part in filename.split() if len(part) >= 2)
    expanded: set[str] = set()
    for term in terms:
        expanded.update(expand_photo_query(term))
    return terms | expanded


def count_local_descriptions(entries: list[dict[str, Any]]) -> int:
    return len([entry for entry in entries if str(entry.get("local_vision_description") or "").strip()])


def german_photo_label(label: str) -> str:
    mapping = {
        "people": "Personen",
        "person": "Person",
        "adult": "Person",
        "cat": "Katze",
        "dog": "Hund",
        "pet": "Haustier",
        "animal": "Tier",
        "document": "Dokument",
        "printed_page": "bedrucktes Papier",
        "text": "Text",
        "receipt": "Beleg",
        "invoice": "Rechnung",
        "food": "Essen",
        "car": "Auto",
        "vehicle": "Fahrzeug",
        "textile": "Stoff oder Kleidung",
        "material": "Material",
        "art": "grafisches Motiv",
        "illustrations": "Illustration",
    }
    return mapping.get(label, label)


def normalize(text: str) -> str:
    text = str(text).lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def time_safe_stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def _run_process(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotosAccessError("Fotos hat zu lange nicht geantwortet.") from exc


def _read_and_remove(path: Path) -> str:
    if not path.exists():
        return ""

    output = path.read_text(encoding="utf-8", errors="replace").strip()
    try:
        path.unlink()
    except OSError:
        pass
    return output


def _is_launch_services_error(result: subprocess.CompletedProcess[str]) -> bool:
    error = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return any(
        marker in error
        for marker in (
            "_lsopenurlswithcompletionhandler",
            "error -10825",
            "cannot be opened",
            "konnte nicht geöffnet werden",
            "kann nicht geöffnet werden",
        )
    )


def _run(
    command: list[str],
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotosAccessError("Fotos hat zu lange nicht geantwortet.") from exc

    if result.returncode != 0:
        error = (result.stderr or result.stdout).strip()
        if "nicht erlaubt" in error.lower() or "denied" in error.lower() or "restricted" in error.lower():
            raise PhotosAccessError(
                error
                + " Öffne Systemeinstellungen > Datenschutz & Sicherheit > Fotos "
                "und erlaube Jarvis Photos Helper den Zugriff."
            )
        raise PhotosAccessError(error or "Fotos konnte nicht gelesen werden.")

    return result


def _open_photos_privacy_settings():
    commands = (
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Photos"],
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy"],
        ["open", "/System/Library/PreferencePanes/Security.prefPane"],
        ["open", "-b", "com.apple.systempreferences"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue

        if result.returncode == 0:
            return


def open_photos_privacy_settings():
    try:
        PhotoIndex({})._ensure_helper()
    except Exception:
        pass
    _open_photos_privacy_settings()
