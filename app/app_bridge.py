from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

ORIGINAL_STDOUT = sys.stdout


def _safe_error(exc: Exception) -> str:
    return type(exc).__name__


def _safe_detail(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        missing = getattr(exc, "filename", None) or str(exc)
        print(f"Missing file path: {missing}", file=sys.stderr)
        return f"FileNotFoundError: missing_path={missing}"
    detail = str(exc).strip()
    return detail or type(exc).__name__


def respond(payload: dict[str, Any]) -> int:
    ORIGINAL_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    ORIGINAL_STDOUT.flush()
    return 0


def main() -> int:
    try:
        raw = sys.stdin.read().strip()
        request = json.loads(raw) if raw else {}
        if not isinstance(request, dict):
            return respond({"ok": False, "error": "invalid_request"})

        command = str(request.get("command") or "").strip()

        with contextlib.redirect_stdout(sys.stderr):
            from local_server import SERVER
            from secure_storage import check_secure_storage, delete_openai_api_key, set_openai_api_key
            from settings import save_config

            server = SERVER
            if command == "health":
                data = server.health()
            elif command == "chat":
                data = server.chat(
                    str(request.get("message") or ""),
                    history=list(request.get("history") or []),
                )
            elif command == "listen":
                data = server.listen_once(history=list(request.get("history") or []))
            elif command == "voice_transcribe":
                data = server.transcribe_voice(
                    str(request.get("audio_path") or ""),
                    request.get("sample_rate"),
                )
            elif command == "models":
                data = server.model_payload()
            elif command == "scan_status":
                data = server.scan_status_payload()
            elif command == "mail_scan_folders":
                data = server.start_mail_folder_scan()
            elif command == "mail_background_start":
                data = server.start_mail_background_scan()
            elif command == "photos_scan_start":
                data = server.start_photo_index_scan()
            elif command == "photos_permission_status":
                data = server.photo_permission_status()
            elif command == "photos_permission_request":
                data = server.request_photo_permission()
            elif command == "photos_reset_index":
                data = server.reset_photo_index()
            elif command == "photos_vision_status":
                data = server.local_photo_vision_status()
            elif command == "photos_vision_analyze":
                data = server.start_local_photo_vision_analysis()
            elif command == "photos_vision_reset":
                data = server.reset_local_photo_vision()
            elif command == "files_scan_start":
                data = server.start_file_index_scan()
                thread = getattr(server, "_file_scan_thread", None)
                if thread is not None:
                    thread.join()
                    data = server.scan_status_payload().get("files", data)
            elif command == "files_reset_index":
                data = server.reset_file_index()
            elif command == "files_search":
                data = server.search_file_index_payload(dict(request))
            elif command == "files_move_search_results":
                data = server.move_file_search_results(dict(request))
            elif command == "set_model":
                data = server.set_model(dict(request.get("payload") or {}))
            elif command == "privacy_status":
                data = {"status": server.dashboard.status()}
            elif command == "permissions":
                data = {"permissions": server.permissions.export()}
            elif command == "set_permission":
                permission = str(request.get("permission") or "").strip()
                allowed = bool(request.get("allowed"))
                if allowed:
                    server.permissions.grant(permission)
                else:
                    server.permissions.revoke(permission)
                data = {"permissions": server.permissions.export(), "status": server.dashboard.status()}
            elif command == "privacy_export":
                data = {"path": server.dashboard.export_data()}
            elif command == "delete_history":
                data = {"message": server.dashboard.delete_history()}
            elif command == "clear_logs":
                data = {"message": server.dashboard.clear_logs()}
            elif command == "set_openai_key":
                set_openai_api_key(str(request.get("api_key") or "").strip())
                data = {"ok": True}
            elif command == "delete_openai_key":
                data = {"deleted": delete_openai_api_key()}
            elif command == "secure_storage_check":
                data = check_secure_storage()
            elif command == "set_user_profile":
                user_name = str(request.get("user_name") or "").strip() or "Nutzer"
                salutation = str(request.get("salutation") or "").strip().lower()
                if salutation not in {"sir", "madam", "none"}:
                    salutation = "sir"
                SERVER.config["creator_name"] = user_name
                SERVER.config["user_salutation"] = salutation
                try:
                    SERVER.memory.data.setdefault("personality", {}).setdefault("assistant", {})["creator"] = user_name
                    SERVER.memory.save("personality")
                except Exception:
                    pass
                save_config(SERVER.config)
                data = {"user_name": user_name, "salutation": salutation}
            else:
                return respond({"ok": False, "error": "unknown_command"})

        return respond({"ok": True, "data": data})
    except Exception as exc:
        return respond({"ok": False, "error": _safe_error(exc), "detail": _safe_detail(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
