from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime

from data_dir import data_root


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
        }

        self.data: dict[str, Any] = {}
        self.load_all()

    def load_all(self):
        for key, file in self.files.items():
            if not file.exists():
                self.data[key] = self.defaults[key]
                self.save(key)
                continue

            try:
                self.data[key] = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                broken_file = file.with_suffix(file.suffix + ".broken")
                file.rename(broken_file)
                self.data[key] = self.defaults[key]
                self.save(key)
                print(f"Defekte Memory-Datei ersetzt: {broken_file.name}")

    def save(self, key: str):
        if key not in self.files:
            raise KeyError(f"Unbekannter Memory-Bereich: {key}")

        temp_file = self.files[key].with_suffix(self.files[key].suffix + ".tmp")
        temp_file.write_text(
            json.dumps(self.data[key], indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_file.replace(self.files[key])

    def save_all(self):
        for key in self.files:
            self.save(key)

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any):
        if key not in self.files:
            raise KeyError(f"Unbekannter Memory-Bereich: {key}")

        self.data[key] = value
        self.save(key)

    def remember(self, category: str, key: str, value: str):
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

    def remember_fact(self, content: str, category: str = "facts", source: str = "manual"):
        content = normalize_memory_text(content)
        if not content:
            return

        long_memory = self.data["long_memory"]
        long_memory.setdefault(category, [])
        long_memory[category].append(
            {
                "content": content,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "category": category,
                "source": source,
            }
        )
        self.save("long_memory")

    def upsert_fact(self, content: str, category: str = "facts", source: str = "auto") -> str:
        content = normalize_memory_text(content)
        if not content:
            return "ignored"

        long_memory = self.data["long_memory"]
        bucket = long_memory.setdefault(category, [])

        if isinstance(bucket, dict):
            now = datetime.now().isoformat(timespec="seconds")
            bucket = [
                {
                    "content": f"{key}: {value}",
                    "created_at": now,
                    "updated_at": now,
                    "category": category,
                    "source": "manual",
                }
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
                item["updated_at"] = now
                item["category"] = category
                item["source"] = source
                self.save("long_memory")
                return "updated"

        long_memory[category].append(
            {
                "content": content,
                "created_at": now,
                "updated_at": now,
                "category": category,
                "source": source,
            }
        )
        self.save("long_memory")
        return "created"

    def forget_facts_matching(self, query: str) -> int:
        query_words = {
            word
            for word in re_split_words(query)
            if len(word) > 2
        }
        if not query_words:
            return 0

        removed = 0
        long_memory = self.data["long_memory"]

        for category, values in list(long_memory.items()):
            if isinstance(values, list):
                kept = []
                for item in values:
                    content = str(item.get("content", "")) if isinstance(item, dict) else str(item)
                    content_words = set(re_split_words(content))
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

        long_memory = self.data["long_memory"]
        for category, values in long_memory.items():
            if isinstance(values, list) and len(values) > max_facts:
                long_memory[category] = values[-max_facts:]

        self.save("long_memory")

    def all_facts(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []

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
                        entry = dict(item)
                        entry.setdefault("category", category)
                        entries.append(entry)
                    elif item:
                        entries.append({"category": category, "content": str(item)})

        return entries

    def search_facts(self, topic: str) -> list[dict[str, str]]:
        topic_words = {
            word
            for word in re_split_words(topic)
            if len(word) > 2
        }

        if not topic_words:
            return []

        scored_results = []
        for fact in self.all_facts():
            content = fact.get("content", "")
            content_words = set(re_split_words(content))
            score = len(topic_words & content_words)
            if score:
                scored_results.append((score, fact))

        scored_results.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in scored_results]

    def forget(self, category: str, key: str):
        long_memory = self.data["long_memory"]
        if category in long_memory and key in long_memory[category]:
            del long_memory[category][key]
            self.save("long_memory")

    def search(self, category: str, key: str):
        return self.data["long_memory"].get(category, {}).get(key)

    def add_conversation(self, role: str, content: str):
        self.data["conversation"].append({"role": role, "content": content})
        self.save("conversation")

    def trim_conversation(self, max_messages: int = 40):
        self.data["conversation"] = self.data["conversation"][-max_messages:]
        self.save("conversation")

    def clear_conversation(self):
        self.data["conversation"] = []
        self.save("conversation")


def re_split_words(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return cleaned.split()


def normalize_memory_text(text: str) -> str:
    cleaned = " ".join(str(text).strip().split())
    return cleaned.strip(" .,!?:;")


def normalize_for_match(text: str) -> str:
    return " ".join(re_split_words(text))


if __name__ == "__main__":
    memory = Memory()
    memory.remember("Vorlieben", "Kaffee", "ohne Zucker")
    print("Memory erfolgreich geladen.")
    print("Test:", memory.search("Vorlieben", "Kaffee"))
