from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from data_dir import data_root

CAMERA_HELPER_BUNDLE_ID = "com.leon.jarvis.camerahelper"


class CameraAccessError(RuntimeError):
    pass


def _macos_sdk_path() -> str:
    """Siehe photos_client.py::_macos_sdk_path() - identisches Vorgehen, damit der
    Kamera-Helfer nicht dieselbe SDK/Ziel-Falle trifft, die den Foto-Helfer auf
    Leons Mac zunaechst komplett am Start hinderte (macOS-Mindestversion falsch
    festgeschrieben, LaunchServices verweigerte den Start still, lange bevor es
    ueberhaupt zu einer Berechtigungsfrage kam)."""
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


def _run_process(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CameraAccessError("Kamera hat zu lange nicht geantwortet.") from exc


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


class CameraClient:
    """Nimmt auf Zuruf genau EIN Kamerabild auf, lokal ueber einen kleinen,
    zur Laufzeit kompilierten Swift-Helfer (analog photos_client.py::PhotoIndex -
    exakt dasselbe Compile-/Signier-/LaunchServices-Fallback-Muster, inkl. der
    dort bereits geloesten SDK/Ziel-Falle). Das aufgenommene Bild wird von
    handle_camera_command() in jarvis.py nach der Vision-Analyse sofort wieder
    geloescht - dieser Client speichert nichts dauerhaft."""

    def __init__(self, base_path: Path | None = None):
        self.app_dir = Path(__file__).resolve().parent
        self.helper_source = self.app_dir / "camera_helper.swift"
        self.helper_bundle = (base_path or data_root()) / "CameraHelper" / "Jarvis Camera Helper.app"
        self.helper_contents = self.helper_bundle / "Contents"
        self.helper_macos = self.helper_contents / "MacOS"
        self.helper_resources = self.helper_contents / "Resources"
        self.helper_plist = self.helper_contents / "Info.plist"
        self.helper_binary = self.helper_macos / "JarvisCameraHelper"

    def capture_photo(self, timeout: int = 20) -> Path:
        """Nimmt ein Foto auf, gibt den Pfad zur (temporaeren) Bilddatei zurueck.
        Der Aufrufer ist dafuer verantwortlich, die Datei nach Gebrauch zu
        loeschen (siehe discard_photo())."""
        self._ensure_helper()
        photo_path = Path(tempfile.gettempdir()) / f"jarvis_camera_{os.getpid()}_{uuid.uuid4().hex}.jpg"
        output_file = Path(tempfile.gettempdir()) / f"jarvis_camera_result_{os.getpid()}_{uuid.uuid4().hex}.txt"

        result, output = self._run_helper_app(["capture", "--photo", str(photo_path)], output_file, timeout)
        if result.returncode != 0 and _is_launch_services_error(result):
            self._register_helper_bundle()
            result, output = self._run_helper_app(["capture", "--photo", str(photo_path)], output_file, timeout)
        if result.returncode != 0 and _is_launch_services_error(result):
            result, output = self._run_helper_binary(["capture", "--photo", str(photo_path)], output_file, timeout)

        clean_output = output.strip()
        if clean_output.startswith("ERROR:") or result.returncode != 0 or not photo_path.exists():
            error = clean_output.removeprefix("ERROR:").strip() or (result.stderr or result.stdout).strip()
            discard_photo(photo_path)
            if "nicht erlaubt" in error.lower() or "denied" in error.lower() or "restricted" in error.lower():
                raise CameraAccessError(
                    error
                    + " Öffne Systemeinstellungen > Datenschutz & Sicherheit > Kamera "
                    "und erlaube Jarvis Camera Helper den Zugriff."
                )
            raise CameraAccessError(error or "Kamera konnte kein Foto aufnehmen.")

        return photo_path

    def _run_helper_app(
        self,
        args: list[str],
        output_file: Path,
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        command = ["open", "-W", str(self.helper_bundle), "--args", *args, "--output", str(output_file)]
        result = _run_process(command, timeout=timeout)
        return result, _read_and_remove(output_file)

    def _run_helper_binary(
        self,
        args: list[str],
        output_file: Path,
        timeout: int,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        command = [str(self.helper_binary), *args, "--output", str(output_file)]
        result = _run_process(command, timeout=timeout)
        return result, _read_and_remove(output_file)

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
            "/private/tmp/jarvis_camera_swift_module_cache",
            "-framework",
            "AVFoundation",
            "-framework",
            "AppKit",
        ]
        env = os.environ.copy()
        env["CLANG_MODULE_CACHE_PATH"] = "/private/tmp/jarvis_camera_clang_cache"
        result = _run_process(command, timeout=60)
        if result.returncode != 0:
            raise CameraAccessError(
                "Kamera-Helfer konnte nicht kompiliert werden: " + (result.stderr or result.stdout).strip()
            )
        self._codesign_helper()
        self._register_helper_bundle()
        return self.helper_binary

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
    <string>Jarvis Camera Helper</string>
    <key>CFBundleExecutable</key>
    <string>JarvisCameraHelper</string>
    <key>CFBundleIdentifier</key>
    <string>com.leon.jarvis.camerahelper</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>Jarvis Camera Helper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>NSCameraUsageDescription</key>
    <string>Jarvis braucht kurz Zugriff auf die Kamera, um auf deinen Zuruf ein einzelnes Foto aufzunehmen. Das Bild wird nach der Analyse sofort gelöscht, nie gespeichert.</string>
</dict>
</plist>
"""
        if not self.helper_plist.exists() or self.helper_plist.read_text(encoding="utf-8") != plist_text:
            self.helper_plist.write_text(plist_text, encoding="utf-8")

    def _codesign_helper(self):
        try:
            subprocess.run(["xattr", "-cr", str(self.helper_bundle)], capture_output=True, text=True, timeout=20)
        except Exception as exc:
            print(f"Kamera-Helper: xattr -cr fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

        commands = (
            ["codesign", "--force", "--sign", "-", "--identifier", CAMERA_HELPER_BUNDLE_ID, str(self.helper_binary)],
            ["codesign", "--force", "--deep", "--sign", "-", "--identifier", CAMERA_HELPER_BUNDLE_ID, str(self.helper_bundle)],
        )
        for command in commands:
            try:
                subprocess.run(command, capture_output=True, text=True, timeout=30)
            except Exception as exc:
                print(f"Kamera-Helper: codesign fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)

    def _register_helper_bundle(self):
        command = [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-f",
            str(self.helper_bundle),
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, timeout=10)
        except Exception as exc:
            print(f"Kamera-Helper: lsregister fehlgeschlagen: {type(exc).__name__}", file=sys.stderr)


def discard_photo(path: Path) -> None:
    """Loescht das aufgenommene Kamerabild - wird von handle_camera_command()
    immer im finally-Block aufgerufen, auch wenn die Vision-Analyse fehlschlaegt,
    damit nie ein Kamerabild liegen bleibt (Leons ausdrueckliche Vorgabe)."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
