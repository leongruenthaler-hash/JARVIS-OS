from __future__ import annotations

from datetime import datetime
from typing import Any

from memory import Memory, re_split_words


DEFAULT_MAX_CHARS = 600
DEFAULT_MAX_FACTS = 12


class ContextEngine:
    """Central place that decides which stored facts are relevant enough to end up
    in a prompt.

    Replaces jarvis.py's old build_memory_summary(), which just concatenated the N
    most-recently-updated facts regardless of what the current question was about,
    with no budget beyond a flat character cutoff and no awareness of expiry/status/
    Context Packs. See docs/context-and-memory.md for the full picture.
    """

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS, max_facts: int = DEFAULT_MAX_FACTS) -> None:
        self.max_chars = max_chars
        self.max_facts = max_facts

    def select_facts(
        self,
        memory: Memory,
        query: str,
        *,
        context_pack: dict[str, Any] | None = None,
        touch: bool = True,
    ) -> list[dict[str, Any]]:
        """Returns the facts that should go into the current prompt, most relevant
        first. `touch=True` (the default for real requests) marks selected facts as
        just-used; pass False for previews/tests that shouldn't affect that."""
        candidates = [
            fact
            for fact in memory.all_facts()
            if fact.get("status", "confirmed") != "pending_confirmation"
        ]

        candidates = self._apply_context_pack(candidates, context_pack)

        query_words = {word for word in re_split_words(query) if len(word) > 2}

        def sort_key(fact: dict[str, Any]) -> tuple[int, str]:
            content_words = set(re_split_words(str(fact.get("content", ""))))
            relevance = len(query_words & content_words) if query_words else 0
            recency = str(fact.get("updated_at") or fact.get("created_at") or "")
            return (relevance, recency)

        # Sorted by (relevance, recency) descending: a fact that actually matches the
        # question wins over a merely-recent one; among equally (ir)relevant facts,
        # the most recently updated wins - so a query with zero keyword overlap still
        # degrades gracefully into the old recency-only behaviour instead of returning
        # nothing.
        candidates.sort(key=sort_key, reverse=True)

        selected: list[dict[str, Any]] = []
        used_chars = 0
        for fact in candidates:
            if len(selected) >= self.max_facts:
                break
            content = str(fact.get("content") or "")
            if not content:
                continue
            if used_chars and used_chars + len(content) > self.max_chars:
                continue
            selected.append(fact)
            used_chars += len(content)

        if touch:
            for fact in selected:
                fact_id = fact.get("id")
                if fact_id:
                    try:
                        memory.touch_fact(fact_id)
                    except Exception:
                        pass

        return selected

    def build_memory_summary(
        self,
        memory: Memory,
        query: str,
        *,
        context_pack: dict[str, Any] | None = None,
        touch: bool = True,
    ) -> str:
        facts = self.select_facts(memory, query, context_pack=context_pack, touch=touch)
        if not facts:
            return "Keine wichtigen Langzeitnotizen."
        parts = [str(fact.get("content") or "") for fact in facts if fact.get("content")]
        summary = "; ".join(parts) if parts else "Keine wichtigen Langzeitnotizen."
        return summary[: self.max_chars]

    @staticmethod
    def _apply_context_pack(
        facts: list[dict[str, Any]], context_pack: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        if not context_pack:
            return facts
        allowed_categories = set(context_pack.get("categories") or [])
        allowed_tags = set(context_pack.get("tags") or [])
        if not allowed_categories and not allowed_tags:
            return facts
        return [
            fact
            for fact in facts
            if fact.get("category") in allowed_categories
            or (allowed_tags & set(fact.get("tags") or []))
        ]


CONTEXT_ENGINE = ContextEngine()


def active_context_pack(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolves the currently active Context Pack from config, if any is set.
    See Abschnitt 7.6 im Master-Plan / docs/context-and-memory.md."""
    config = config or {}
    active_name = str(config.get("active_context_pack") or "").strip()
    if not active_name:
        return None
    packs = config.get("context_packs") or {}
    pack = packs.get(active_name)
    return pack if isinstance(pack, dict) else None
