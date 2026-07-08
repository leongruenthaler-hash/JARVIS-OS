import json
from pathlib import Path
from typing import Any


class Memory:
    """JARVIS Memory Engine V1.1"""

    def __init__(self):
        self.base_path = Path(__file__).parent.parent / "memory"
        self.base_path.mkdir(exist_ok=True)

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
                    "humor": "trocken",
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

        self.data = {}
        self.load_all()

    def load_all(self):
        for key, file in self.files.items():
            if not file.exists():
                file.write_text(
                    json.dumps(
                        self.defaults[key],
                        indent=4,
                        ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
            self.data[key] = json.loads(file.read_text(encoding="utf-8"))

    def save(self, key: str):
        self.files[key].write_text(
            json.dumps(
                self.data[key],
                indent=4,
                ensure_ascii=False
            ),
            encoding="utf-8",
        )

    def save_all(self):
        for key in self.files:
            self.save(key)

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any):
        self.data[key] = value
        self.save(key)

    def remember(self, category: str, key: str, value: str):
        lm = self.data["long_memory"]
        if category not in lm:
            lm[category] = {}
        lm[category][key] = value
        self.save("long_memory")

    def forget(self, category: str, key: str):
        lm = self.data["long_memory"]
        if category in lm and key in lm[category]:
            del lm[category][key]
            self.save("long_memory")

    def search(self, category: str, key: str):
        return self.data["long_memory"].get(category, {}).get(key)

    def add_conversation(self, role: str, content: str):
        self.data["conversation"].append(
            {"role": role, "content": content}
        )
        self.save("conversation")

    def clear_conversation(self):
        self.data["conversation"] = []
        self.save("conversation")


if __name__ == "__main__":
    memory = Memory()
    memory.remember("Vorlieben", "Kaffee", "ohne Zucker")
    print("Memory erfolgreich geladen.")
    print("Test:", memory.search("Vorlieben", "Kaffee"))