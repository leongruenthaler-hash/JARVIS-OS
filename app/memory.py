from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any
from datetime import datetime

from data_dir import data_root

# Structured fact metadata (Phase B / Context Engine). See docs/context-and-memory.md.
SENSITIVITY_LEVELS = ("normal", "personal", "confidential", "highly-sensitive")
FACT_STATUSES = ("confirmed", "pending_confirmation", "rejected")
RETENTION_POLICIES = ("until_deleted", "session", "expires")


def _new_fact_id() -> str:
    return uuid.uuid4().hex[:12]


# forget_facts_matching() verglich bisher nur die Wortlaenge (>2 Zeichen), nicht
# ob ein Wort ueberhaupt bedeutungstragend ist - deutsche Fuellwoerter wie
# "ich"/"bin"/"hat"/"war"/"mein" sind alle laenger als 2 Zeichen und zaehlten
# damit als echtes Treffersignal. Bei einer kurzen Vergiss-Anfrage (<=6
# Inhaltswoerter) reichte dann oft schon EIN gemeinsames Fuellwort, um einen
# komplett unabhaengigen Fakt versehentlich mitzuloeschen (z.B. "Vergiss, dass
# ich Vegetarier bin" loeschte auch einen unabhaengigen "Ich bin bei der
# Techniker Krankenkasse versichert"-Fakt, weil beide "ich"/"bin" teilen).
# Live beobachtet 2026-08-20 im Mehrfach-Audit.
_MEMORY_FORGET_STOPWORDS = frozenset(
    {
        "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "sich", "uns", "euch",
        "mir", "dir", "ihm", "ihr", "ihnen",
        "mein", "meine", "meiner", "meinem", "meinen", "meins",
        "dein", "deine", "deiner", "deinem", "deinen",
        "bin", "bist", "ist", "sind", "seid", "war", "warst", "waren", "wart",
        "hab", "habe", "hast", "hat", "haben", "habt", "hatte", "hatten",
        "und", "oder", "aber", "doch", "auch", "noch", "nur", "schon", "dass",
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "einem", "einen",
        "für", "fuer", "von", "vor", "bei", "aus", "auf", "mit", "zum", "zur", "als",
    }
)


def _new_fact_entry(
    content: str,
    category: str,
    source: str,
    *,
    scope: str = "private",
    sensitivity: str = "normal",
    confidence: float = 1.0,
    retention_policy: str = "until_deleted",
    expires_at: str | None = None,
    tags: list[str] | None = None,
    status: str = "confirmed",
    user_confirmed: bool = True,
    source_reference: str | None = None,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "id": _new_fact_id(),
        "content": content,
        "category": category,
        "scope": scope,
        "source_type": source,
        "source_reference": source_reference,
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
        "confidence": confidence,
        "sensitivity": sensitivity if sensitivity in SENSITIVITY_LEVELS else "normal",
        "retention_policy": retention_policy if retention_policy in RETENTION_POLICIES else "until_deleted",
        "expires_at": expires_at,
        "user_confirmed": user_confirmed,
        # An unrecognized status value is a data problem, not a green light - fail
        # safe into the review queue rather than silently trusting the fact.
        "status": status if status in FACT_STATUSES else "pending_confirmation",
        "tags": list(tags or []),
        "related_entities": [],
    }


def _ensure_fact_fields(entry: dict[str, Any], category: str) -> dict[str, Any]:
    """Lazily upgrades a fact entry written before Phase B (or by an older Memory
    Engine version) to the current schema, in place. Existing fields are never
    overwritten - only missing ones get a safe default derived from what's already
    there, so nothing already stored is reinterpreted or lost."""
    if not isinstance(entry, dict):
        return entry
    entry.setdefault("id", _new_fact_id())
    entry.setdefault("category", category)
    entry.setdefault("scope", "private")
    entry.setdefault("source_type", entry.get("source", "unknown"))
    entry.setdefault("source_reference", None)
    fallback_time = entry.get("updated_at") or entry.get("created_at") or datetime.now().isoformat(timespec="seconds")
    entry.setdefault("created_at", fallback_time)
    entry.setdefault("updated_at", fallback_time)
    entry.setdefault("last_used_at", None)
    entry.setdefault("confidence", 1.0)
    if entry.get("sensitivity") not in SENSITIVITY_LEVELS:
        entry["sensitivity"] = "normal"
    if entry.get("retention_policy") not in RETENTION_POLICIES:
        entry["retention_policy"] = "until_deleted"
    entry.setdefault("expires_at", None)
    # Facts written before Phase B all went through the strict auto-extraction /
    # manual-command gates in jarvis.py, so treating them as already-confirmed on
    # migration is correct, not a laxer default.
    entry.setdefault("user_confirmed", True)
    entry.setdefault("status", "confirmed")
    entry.setdefault("tags", [])
    entry.setdefault("related_entities", [])
    return entry


def is_fact_expired(entry: dict[str, Any]) -> bool:
    expires_at = entry.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(str(expires_at)) < datetime.now()
    except ValueError:
        return False


def _restrict_to_owner(path: Path) -> None:
    """Personal facts and conversation history have no encryption at rest, so file
    permissions are the only thing standing between another local account (or an
    unencrypted backup) and this data. 0600 = only this user can read/write it."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class Memory:
    """JARVIS Memory Engine V1.2"""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or data_root() / "memory"
        self.base_path.mkdir(parents=True, exist_ok=True)

        self.files = {
            "personality": self.base_path / "personality.json",
            "long_memory": self.base_path / "long_memory.json",
            "conversation": self.base_path / "conversation.json",
            "projects": self.base_path / "projects.json",
            "settings": self.base_path / "settings.json",
            "tasks": self.base_path / "tasks.json",
        }

        self.defaults = {
            "personality": {
                "assistant": {
                    "name": "Jarvis",
                    "creator": "Leon",
                    "language": "Deutsch",
                },
                "behavior": {
                    "tone": "höflich",
                    "humor": "trocken-sarkastisch",
                    "calm": True,
                    "permission_required": True,
                },
            },
            "long_memory": {},
            "conversation": [],
            "projects": {},
            "settings": {
                "model": "gpt-5-nano",
                "wake_word": "jarvis",
                "voice": "Siri",
            },
            "tasks": [],
        }

        self.data: dict[str, Any] = {}
        # The HTTP server (local_server.py) handles requests on a fresh thread each,
        # all sharing this one Memory instance. Without a lock, two concurrent
        # read-modify-write calls (e.g. remember_fact + set("settings", ...)) can
        # interleave and lose one of the writes - reentrant so a method that both
        # mutates data and calls self.save()/self.set() from the same thread doesn't
        # deadlock on itself.
        self._lock = threading.RLock()
        self.load_all()

    def load_all(self):
        for key, file in self.files.items():
            if not file.exists():
                # deepcopy: self.defaults[key] holds mutable containers (dict/list).
                # Without the copy, self.data[key] would be the *same* object, so
                # every later in-place mutation (setdefault/append/etc.) would also
                # silently mutate self.defaults, corrupting the "factory default".
                self.data[key] = copy.deepcopy(self.defaults[key])
                self.save(key)
                continue

            try:
                self.data[key] = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                broken_file = file.with_suffix(file.suffix + ".broken")
                file.rename(broken_file)
                self.data[key] = copy.deepcopy(self.defaults[key])
                self.save(key)
                print(f"Defekte Memory-Datei ersetzt: {broken_file.name}")

    def save(self, key: str):
        if key not in self.files:
            raise KeyError(f"Unbekannter Memory-Bereich: {key}")

        with self._lock:
            temp_file = self.files[key].with_suffix(self.files[key].suffix + ".tmp")
            temp_file.write_text(
                json.dumps(self.data[key], indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            _restrict_to_owner(temp_file)
            temp_file.replace(self.files[key])

    def save_all(self):
        for key in self.files:
            self.save(key)

    def get(self, key: str) -> Any:
        with self._lock:
            return self.data.get(key)

    def set(self, key: str, value: Any):
        if key not in self.files:
            raise KeyError(f"Unbekannter Memory-Bereich: {key}")

        with self._lock:
            self.data[key] = value
            self.save(key)

    def remember(self, category: str, key: str, value: str):
        with self._lock:
            long_memory = self.data["long_memory"]
            bucket = long_memory.setdefault(category, {})

            if isinstance(bucket, list):
                now = datetime.now().isoformat(timespec="seconds")
                prefix = f"{key}: "
                content = f"{prefix}{value}"
                for item in bucket:
                    if isinstance(item, dict) and str(item.get("content", "")).startswith(prefix):
                        item["content"] = content
                        item["updated_at"] = now
                        break
                else:
                    bucket.append(
                        {
                            "content": content,
                            "created_at": now,
                            "updated_at": now,
                            "category": category,
                            "source": "manual",
                        }
                    )
            else:
                bucket[key] = value

            self.save("long_memory")

    def remember_fact(
        self,
        content: str,
        category: str = "facts",
        source: str = "manual",
        *,
        scope: str = "private",
        sensitivity: str = "normal",
        confidence: float = 1.0,
        retention_policy: str = "until_deleted",
        expires_at: str | None = None,
        tags: list[str] | None = None,
        status: str = "confirmed",
    ) -> None:
        content = normalize_memory_text(content)
        if not content:
            return

        with self._lock:
            long_memory = self.data["long_memory"]
            long_memory.setdefault(category, [])
            long_memory[category].append(
                _new_fact_entry(
                    content,
                    category,
                    source,
                    scope=scope,
                    sensitivity=sensitivity,
                    confidence=confidence,
                    retention_policy=retention_policy,
                    expires_at=expires_at,
                    tags=tags,
                    status=status,
                    user_confirmed=status == "confirmed",
                )
            )
            self.save("long_memory")

    def upsert_fact(
        self,
        content: str,
        category: str = "facts",
        source: str = "auto",
        *,
        scope: str = "private",
        sensitivity: str = "normal",
        confidence: float = 1.0,
        retention_policy: str = "until_deleted",
        expires_at: str | None = None,
        tags: list[str] | None = None,
        status: str = "confirmed",
    ) -> str:
        content = normalize_memory_text(content)
        if not content:
            return "ignored"

        with self._lock:
            long_memory = self.data["long_memory"]
            bucket = long_memory.setdefault(category, [])

            if isinstance(bucket, dict):
                bucket = [
                    _new_fact_entry(f"{key}: {value}", category, "manual")
                    for key, value in bucket.items()
                ]
                long_memory[category] = bucket
                print(
                    f"Memory: Kategorie '{category}' von Dict- auf Listen-Schema konvertiert "
                    f"({len(bucket)} Eintraege uebernommen)."
                )
            elif not isinstance(bucket, list):
                bucket = []
                long_memory[category] = bucket

            normalized_content = normalize_for_match(content)
            now = datetime.now().isoformat(timespec="seconds")

            for item in long_memory[category]:
                if not isinstance(item, dict):
                    continue

                existing = normalize_for_match(str(item.get("content", "")))
                if existing == normalized_content:
                    _ensure_fact_fields(item, category)
                    item["updated_at"] = now
                    item["category"] = category
                    item["source_type"] = source
                    item["confidence"] = confidence
                    if sensitivity in SENSITIVITY_LEVELS:
                        item["sensitivity"] = sensitivity
                    # Fehlte bisher: ein bereits als "pending_confirmation"
                    # gespeicherter Fakt (z.B. aus Screen-Vision/LLM-Auto-
                    # Extraktion) blieb dauerhaft unbestaetigt, selbst wenn der
                    # Nutzer denselben Inhalt danach explizit bestaetigte ("Merk
                    # dir, dass ...") - der "updated"-Zweig schrieb den vom
                    # Aufrufer uebergebenen status/user_confirmed nie auf den
                    # bestehenden Eintrag. Live beobachtet 2026-08-20 im
                    # Mehrfach-Audit.
                    # Nur "aufwerten", nie stillschweigend abwerten: eine
                    # explizite Bestaetigung (status="confirmed") gewinnt immer,
                    # aber ein bereits bestaetigter Fakt soll nicht durch eine
                    # spaetere, ggf. niedrig-confidente Auto-Extraktion mit
                    # status="pending_confirmation" wieder zurueckgestuft werden.
                    if status == "confirmed" or item.get("status") != "confirmed":
                        item["status"] = status
                        item["user_confirmed"] = status == "confirmed"
                    self.save("long_memory")
                    return "updated"

            long_memory[category].append(
                _new_fact_entry(
                    content,
                    category,
                    source,
                    scope=scope,
                    sensitivity=sensitivity,
                    confidence=confidence,
                    retention_policy=retention_policy,
                    expires_at=expires_at,
                    tags=tags,
                    status=status,
                    user_confirmed=status == "confirmed",
                )
            )
            self.save("long_memory")
            return "created"

    def forget_facts_matching(self, query: str) -> int:
        query_words = {
            word
            for word in re_split_words(query)
            if len(word) > 2 and word not in _MEMORY_FORGET_STOPWORDS
        }
        if not query_words:
            return 0

        removed = 0
        with self._lock:
            long_memory = self.data["long_memory"]

            for category, values in list(long_memory.items()):
                if isinstance(values, list):
                    kept = []
                    for item in values:
                        content = str(item.get("content", "")) if isinstance(item, dict) else str(item)
                        content_words = {
                            word for word in re_split_words(content) if word not in _MEMORY_FORGET_STOPWORDS
                        }
                        score = len(query_words & content_words)
                        if score >= max(1, min(3, len(query_words) // 2)):
                            removed += 1
                        else:
                            kept.append(item)
                    long_memory[category] = kept

                elif isinstance(values, dict):
                    for key, value in list(values.items()):
                        content_words = set(re_split_words(f"{key} {value}"))
                        score = len(query_words & content_words)
                        if score >= max(1, min(3, len(query_words) // 2)):
                            del values[key]
                            removed += 1

            if removed:
                self.save("long_memory")

        return removed

    def forget_exact(self, content: str) -> bool:
        target = normalize_for_match(content)
        if not target:
            return False

        with self._lock:
            long_memory = self.data["long_memory"]
            for values in long_memory.values():
                if isinstance(values, list):
                    for index, item in enumerate(values):
                        item_content = str(item.get("content", "")) if isinstance(item, dict) else str(item)
                        if normalize_for_match(item_content) == target:
                            del values[index]
                            self.save("long_memory")
                            return True
                elif isinstance(values, dict):
                    for key, value in list(values.items()):
                        if normalize_for_match(f"{key}: {value}") == target:
                            del values[key]
                            self.save("long_memory")
                            return True

        return False

    def trim_facts(self, max_facts: int = 120):
        if max_facts <= 0:
            return

        with self._lock:
            long_memory = self.data["long_memory"]
            for category, values in long_memory.items():
                if isinstance(values, list) and len(values) > max_facts:
                    long_memory[category] = values[-max_facts:]

            self.save("long_memory")

    def all_facts(self, *, include_expired: bool = False, include_rejected: bool = False) -> list[dict[str, Any]]:
        """Returns fact entries with the full Phase-B schema. By default excludes
        expired and rejected facts (matches the Context Engine's contract: a fact
        that shouldn't be used anymore shouldn't quietly leak back into a prompt).
        Pass include_expired/include_rejected=True for the Memory management view,
        where the user needs to see and clean those up, not just facts fit for use."""
        entries: list[dict[str, Any]] = []

        with self._lock:
            for category, values in self.data["long_memory"].items():
                if category == "facts":
                    continue

                if isinstance(values, dict):
                    for key, value in values.items():
                        entries.append(
                            {
                                "category": category,
                                "key": key,
                                "content": f"{key}: {value}",
                            }
                        )

            for category, values in self.data["long_memory"].items():
                if isinstance(values, list):
                    for item in values:
                        if isinstance(item, dict):
                            # Mutates item in place (still referencing self.data) so the
                            # upgrade is picked up by the next save(), not just this read.
                            _ensure_fact_fields(item, category)
                            if not include_rejected and item.get("status") == "rejected":
                                continue
                            if not include_expired and is_fact_expired(item):
                                continue
                            entries.append(dict(item))
                        elif item:
                            entries.append({"category": category, "content": str(item)})

        return entries

    def get_fact_by_id(self, fact_id: str) -> dict[str, Any] | None:
        with self._lock:
            for category, values in self.data["long_memory"].items():
                if not isinstance(values, list):
                    continue
                for item in values:
                    if isinstance(item, dict) and item.get("id") == fact_id:
                        _ensure_fact_fields(item, category)
                        return item
        return None

    def touch_fact(self, fact_id: str) -> None:
        """Marks a fact as just-used (by the Context Engine) - lets the Memory view
        show "zuletzt verwendet am" and lets a future relevance/cleanup pass tell a
        fact nothing has referenced in a year from one used yesterday."""
        item = self.get_fact_by_id(fact_id)
        if item is None:
            return
        with self._lock:
            item["last_used_at"] = datetime.now().isoformat(timespec="seconds")
            self.save("long_memory")
            # activity_log is an in-memory ring buffer feeding a "what just happened"
            # UI feed - fine for normal facts, but confidential/highly-sensitive
            # content (health, finance, passwords) must not be echoed there in
            # plaintext just because the Context Engine used it.
            sensitivity = item.get("sensitivity", "normal")
            if sensitivity in ("confidential", "highly-sensitive"):
                label = "Vertraulicher Fakt verwendet"
            else:
                label = str(item.get("content", ""))[:60]
        from core.activity_log import record_activity
        record_activity("memory", label, reference=fact_id)

    def update_fact(self, fact_id: str, **fields: Any) -> bool:
        """Edits a fact's editable metadata (content, category, sensitivity, scope,
        retention_policy, expires_at, tags, status). Unknown keys are ignored rather
        than raising, so a client can send a partial update payload."""
        editable = {
            "content", "category", "scope", "sensitivity", "retention_policy",
            "expires_at", "tags", "status", "confidence",
        }
        item = self.get_fact_by_id(fact_id)
        if item is None:
            return False
        with self._lock:
            for key, value in fields.items():
                if key not in editable:
                    continue
                if key == "sensitivity" and value not in SENSITIVITY_LEVELS:
                    continue
                if key == "retention_policy" and value not in RETENTION_POLICIES:
                    continue
                if key == "status" and value not in FACT_STATUSES:
                    continue
                item[key] = value
            item["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.save("long_memory")
        return True

    def confirm_fact(self, fact_id: str) -> bool:
        # Set status and user_confirmed under one lock acquisition/save instead of
        # two separate get_fact_by_id()+lock round trips - the previous two-call
        # version could race with a concurrent delete_fact_by_id() between the two
        # calls (status set, but user_confirmed flip silently lost) and always did
        # two full-store writes for one logical change.
        item = self.get_fact_by_id(fact_id)
        if item is None:
            return False
        with self._lock:
            item["status"] = "confirmed"
            item["user_confirmed"] = True
            item["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.save("long_memory")
        return True

    def reject_fact(self, fact_id: str) -> bool:
        item = self.get_fact_by_id(fact_id)
        if item is None:
            return False
        with self._lock:
            item["status"] = "rejected"
            item["user_confirmed"] = False
            item["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.save("long_memory")
        return True

    def delete_fact_by_id(self, fact_id: str) -> bool:
        with self._lock:
            for values in self.data["long_memory"].values():
                if not isinstance(values, list):
                    continue
                for index, item in enumerate(values):
                    if isinstance(item, dict) and item.get("id") == fact_id:
                        del values[index]
                        self.save("long_memory")
                        return True
        return False

    def search_facts(
        self, topic: str, *, include_expired: bool = False, include_rejected: bool = False
    ) -> list[dict[str, str]]:
        # War bisher fest auf all_facts()s Standardwerte (beide False) verdrahtet -
        # anders als die Memory-Verwaltungsansicht, deren nicht-durchsuchte
        # Browse-Liste bewusst include_expired=True/include_rejected=True nutzt,
        # damit abgelehnte/abgelaufene Fakten sichtbar und erneut bestaetigbar
        # bleiben ("nichts davon ist versteckt"). Ohne Parameter verschwand ein
        # abgelehnter Fakt aus den Ergebnissen, sobald der Nutzer etwas in das
        # Suchfeld tippte - inkonsistent mit der eigenen Zusage der Ansicht.
        # Live beobachtet 2026-08-20 im Mehrfach-Audit.
        topic_words = {
            word
            for word in re_split_words(topic)
            if len(word) > 2
        }

        if not topic_words:
            return []

        scored_results = []
        for fact in self.all_facts(include_expired=include_expired, include_rejected=include_rejected):
            content = fact.get("content", "")
            content_words = set(re_split_words(content))
            score = len(topic_words & content_words)
            if score:
                scored_results.append((score, fact))

        scored_results.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in scored_results]

    def forget(self, category: str, key: str):
        with self._lock:
            long_memory = self.data["long_memory"]
            if category in long_memory and key in long_memory[category]:
                del long_memory[category][key]
                self.save("long_memory")

    def search(self, category: str, key: str):
        # A category can be a dict bucket (remember()) or a list bucket (Phase B
        # facts via remember_fact()/upsert_fact()) - .get(key) on a list crashes
        # with AttributeError, so guard the type before calling it.
        values = self.data["long_memory"].get(category)
        if not isinstance(values, dict):
            return None
        return values.get(key)

    def add_conversation(self, role: str, content: str):
        with self._lock:
            self.data["conversation"].append({"role": role, "content": content})
            self.save("conversation")

    def trim_conversation(self, max_messages: int = 40):
        with self._lock:
            self.data["conversation"] = self.data["conversation"][-max_messages:]
            self.save("conversation")

    def clear_conversation(self):
        with self._lock:
            self.data["conversation"] = []
            self.save("conversation")


def re_split_words(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return cleaned.split()


def normalize_memory_text(text: str) -> str:
    if text is None:
        return ""
    cleaned = " ".join(str(text).strip().split())
    return cleaned.strip(" .,!?:;")


def normalize_for_match(text: str) -> str:
    return " ".join(re_split_words(text))


if __name__ == "__main__":
    memory = Memory()
    memory.remember("Vorlieben", "Kaffee", "ohne Zucker")
    print("Memory erfolgreich geladen.")
    print("Test:", memory.search("Vorlieben", "Kaffee"))
