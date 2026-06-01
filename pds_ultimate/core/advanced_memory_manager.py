"""Compatibility shim — delegates to hierarchical memory v3."""

from __future__ import annotations

from dataclasses import dataclass

from pds_ultimate.config import config
from pds_ultimate.core.memory.hierarchy import hierarchical_memory


@dataclass
class MemoryEntry:
    content: str
    memory_type: str = "semantic"
    importance: float = 0.5


class AdvancedMemoryManager:
    def recall(self, query: str = "", top_k: int = 10, **kwargs) -> list[MemoryEntry]:
        uid = config.telegram.owner_id or 0
        rows = hierarchical_memory.recall(uid, query, limit=top_k)
        return [MemoryEntry(content=r["content"], memory_type=r["layer"]) for r in rows]

    def recall_all(self, top_k: int = 100) -> list[MemoryEntry]:
        return self.recall("", top_k=top_k)

    def remember(self, content: str, **kwargs) -> None:
        uid = config.telegram.owner_id or 0
        hierarchical_memory.remember_fact(uid, content)


class ContextCompressor:
    @staticmethod
    def compress(text: str, max_chars: int = 4000) -> str:
        return text[:max_chars]


advanced_memory_manager = AdvancedMemoryManager()
