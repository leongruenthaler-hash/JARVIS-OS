from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from data_dir import data_root
from mail_calendar_actions import create_calendar_actions_from_messages
from mail_client import MailAccessError, MailMessage, list_inbox_messages
from permission_manager import PermissionManager


class MailBackgroundWorker:
    def __init__(self, config: dict[str, Any], base_path: Path | None = None):
        self.config = config
        self.permissions = PermissionManager(base_path)
        self.enabled = bool(config.get("background_mail_enabled", True))
        self.morning_time = str(config.get("background_mail_morning_time", "07:00"))
        self.overnight_time = str(config.get("background_mail_overnight_time", "02:30"))
        self.max_messages = int(config.get("background_mail_max_messages", 20))
        self.overnight_max_messages = int(config.get("background_mail_overnight_max_messages", 80))
        self.auto_calendar_enabled = bool(config.get("auto_calendar_from_mail_enabled", True))
        self.auto_calendar_process_existing = bool(
            config.get("auto_calendar_process_existing_on_overnight", False)
        )
        self.account_name = config.get("mail_inbox_account")
        self.mailbox_name = config.get("mail_inbox_mailbox")
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.base_path / "background_mail_cache.json"
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.scan_thread: threading.Thread | None = None

    def start(self):
        if not self.enabled:
            return

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def enable_overnight_scan(self) -> str:
        cache = self._load_cache()
        cache["overnight_enabled"] = True
        cache["overnight_requested_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_cache(cache)
        return (
            "Verstanden. Solange Jarvis läuft, lese ich nachts deine Mail-Übersichten im Hintergrund vor "
            "und halte morgens ein schnelles Update bereit. Wenn eine neue Mail eine klare Rechnung, "
            "Frist oder einen Termin mit Datum enthält, lege ich automatisch eine Erinnerung oder "
            f"einen Kalendereintrag an. Geplant ist {self.overnight_time} Uhr."
        )

    def request_scan(self, reason: str = "manual", max_messages: int | None = None) -> str:
        with self.lock:
            if self.scan_thread is not None and self.scan_thread.is_alive():
                return "Ich bereite die Mail-Übersicht bereits im Hintergrund vor."

            self.scan_thread = threading.Thread(
                target=self._scan_safely,
                kwargs={
                    "reason": reason,
                    "max_messages": max_messages or self.max_messages,
                },
                daemon=True,
            )
            self.scan_thread.start()

        return "Ich bereite die Mail-Übersicht im Hintergrund vor."

    def scan_now(self, reason: str = "manual", max_messages: int | None = None) -> str:
        with self.lock:
            if self.scan_thread is not None and self.scan_thread.is_alive():
                return "Ich bereite die Mail-Übersicht bereits im Hintergrund vor."

            self._scan_safely(
                reason=reason,
                max_messages=max_messages or self.max_messages,
            )

        return self.cached_update(max_age_hours=24) or "Mailcheck fertig, aber ich habe keine Zusammenfassung bekommen."

    def cached_update(self, max_age_hours: int = 18) -> str | None:
        cache = self._load_cache()
        scanned_at = cache.get("last_scan_at")
        if not scanned_at:
            return None

        try:
            age_hours = (datetime.now() - datetime.fromisoformat(scanned_at)).total_seconds() / 3600
        except ValueError:
            return None

        if age_hours > max_age_hours:
            return None

        if cache.get("last_error"):
            return f"Mein letzter Hintergrund-Mailcheck ist fehlgeschlagen: {cache['last_error']}"

        summary = cache.get("summary")
        if not summary:
            return None

        return f"Das habe ich vorbereitet: {summary}"

    def status_answer(self) -> str:
        cache = self._load_cache()
        active = self.thread is not None and self.thread.is_alive()
        scanning = self.scan_thread is not None and self.scan_thread.is_alive()
        last_scan = cache.get("last_scan_at") or "noch nie"
        new_count = len(cache.get("new_messages", []) or [])
        error = str(cache.get("last_error") or "").strip()
        if error:
            return f"Der Mail-Hintergrundscan ist {'aktiv' if active else 'nicht aktiv'}, der letzte Lauf hatte aber einen Fehler: {error}"
        if scanning:
            return f"Ja, der Mail-Hintergrundscan läuft gerade. Letzter abgeschlossener Scan: {last_scan}."
        return f"Der Mail-Hintergrundscan ist {'aktiv' if active else 'pausiert'}. Letzter Scan: {last_scan}. Neue Mails seit dem letzten bekannten Stand: {new_count}."

    def _run_loop(self):
        while not self.stop_event.is_set():
            # Automatic (unattended) scans only run once the user has explicitly
            # turned Mail on in Datenschutz - request_scan()/scan_now() (user- or
            # command-triggered) are intentionally NOT gated here, since those ARE
            # the "first actual use" that's allowed to surface the OS prompt.
            if not self.permissions.is_allowed("mail"):
                self.stop_event.wait(60)
                continue

            now = datetime.now()
            cache = self._load_cache()
            today = now.date().isoformat()

            if self._time_reached(now, self.morning_time) and cache.get("last_morning_scan_date") != today:
                self._scan_safely(reason="morning", max_messages=self.max_messages)
                cache = self._load_cache()
                cache["last_morning_scan_date"] = today
                self._save_cache(cache)

            overnight_enabled = bool(cache.get("overnight_enabled"))
            if (
                overnight_enabled
                and self._time_reached(now, self.overnight_time)
                and cache.get("last_overnight_scan_date") != today
            ):
                self._scan_safely(reason="overnight", max_messages=self.overnight_max_messages)
                cache = self._load_cache()
                cache["last_overnight_scan_date"] = today
                self._save_cache(cache)

            self.stop_event.wait(60)

    def _scan_safely(self, reason: str, max_messages: int):
        try:
            self._scan(reason=reason, max_messages=max_messages)
        except Exception as exc:
            cache = self._load_cache()
            cache["last_scan_at"] = datetime.now().isoformat(timespec="seconds")
            cache["last_error"] = str(exc)
            self._save_cache(cache)
            print("Hintergrund-Mailcheck Fehler:", type(exc).__name__)

    def _scan(self, reason: str, max_messages: int):
        previous_cache = self._load_cache()
        known_ids = set(previous_cache.get("known_message_ids", []))

        messages = list_inbox_messages(
            max_messages=max_messages,
            account_name=self.account_name,
            mailbox_name=self.mailbox_name,
            preview_chars=int(self.config.get("auto_calendar_mail_preview_chars", 900)),
            include_preview=self.auto_calendar_enabled,
        )
        current_ids = [message.message_id for message in messages if message.message_id]
        first_scan = not known_ids
        new_messages = [
            message
            for message in messages
            if message.message_id and message.message_id not in known_ids
        ]
        calendar_messages = []
        if self.auto_calendar_enabled:
            if first_scan and reason == "overnight" and self.auto_calendar_process_existing:
                calendar_messages = messages
            elif not first_scan:
                calendar_messages = new_messages

        existing_action_keys = set(previous_cache.get("created_calendar_action_keys", []))
        calendar_actions, new_action_keys = create_calendar_actions_from_messages(
            calendar_messages,
            self.config,
            existing_action_keys,
        )
        all_action_keys = sorted(existing_action_keys | set(new_action_keys))
        known_limit = int(self.config.get("background_mail_known_id_limit", 1000))
        all_known_ids = list(dict.fromkeys([*current_ids, *list(known_ids)]))[:known_limit]

        cache = {
            **previous_cache,
            "last_scan_at": datetime.now().isoformat(timespec="seconds"),
            "last_reason": reason,
            "last_error": "",
            "known_message_ids": all_known_ids,
            "created_calendar_action_keys": all_action_keys,
            "calendar_actions": calendar_actions[-20:],
            "messages": [self._message_to_dict(message) for message in messages[:20]],
            "new_messages": [self._message_to_dict(message) for message in new_messages[:10]],
            "summary": self._build_summary(messages, new_messages, calendar_actions),
        }
        self._save_cache(cache)
        created_count = len([action for action in calendar_actions if action.get("status") == "created"])
        print(
            f"Hintergrund-Mailcheck fertig: {len(messages)} gelesen, "
            f"{len(new_messages)} neu, {created_count} Kalender/Erinnerungen."
        )

    def _build_summary(
        self,
        messages: list[MailMessage],
        new_messages: list[MailMessage],
        calendar_actions: list[dict[str, str]] | None = None,
    ) -> str:
        if not messages:
            return "Ich sehe aktuell keine Mails im vorbereiteten Posteingang."

        calendar_actions = calendar_actions or []
        created_actions = [
            action for action in calendar_actions if action.get("status") == "created"
        ]
        focus = new_messages or messages[:5]
        intro = (
            f"Ich sehe {len(new_messages)} neue Mail(s)."
            if new_messages
            else f"Ich habe {len(messages)} Mail(s) im Posteingang vorbereitet."
        )
        snippets = "; ".join(
            f"{message.sender or 'Unbekannt'}: {message.subject}"
            for message in focus[:5]
        )
        calendar_text = ""
        if created_actions:
            titles = "; ".join(action["title"] for action in created_actions[:3])
            noun = "Eintrag" if len(created_actions) == 1 else "Einträge"
            calendar_text = f" Ich habe außerdem {len(created_actions)} Kalender- oder Erinnerungs-{noun} angelegt: {titles}."

        return f"{intro} Wichtigste Übersicht: {snippets}.{calendar_text}"

    def _message_to_dict(self, message: MailMessage) -> dict[str, str]:
        return {
            "id": message.message_id,
            "sender": message.sender,
            "subject": message.subject,
            "received": message.received,
            "preview": message.preview,
        }

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

    def _time_reached(self, now: datetime, time_text: str) -> bool:
        try:
            hour_text, minute_text = time_text.split(":", 1)
            target_hour = int(hour_text)
            target_minute = int(minute_text)
        except (ValueError, AttributeError):
            return False

        return (now.hour, now.minute) >= (target_hour, target_minute)
