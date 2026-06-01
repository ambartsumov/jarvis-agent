"""Smart hierarchical memory — token-efficient, agentmemory-inspired."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pds_ultimate.config import config, logger
from pds_ultimate.core.llm.client import llm_client
from pds_ultimate.core.llm.router import TaskKind
from pds_ultimate.core.memory.agentmemory_bridge import agentmemory_bridge
from pds_ultimate.core.memory.compressor import compress_zero_llm
from pds_ultimate.core.memory.store import MemoryStore
from pds_ultimate.core.memory.token_budget import estimate_tokens, trim_to_budget

# Lazy KG import to avoid circular dependencies
_kg = None


def _get_kg():
    global _kg
    if _kg is None:
        try:
            from pds_ultimate.core.memory.knowledge_graph import knowledge_graph
            _kg = knowledge_graph
        except Exception as exc:
            logger.warning(f"KnowledgeGraph unavailable: {exc}")
    return _kg


@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SessionMemory:
    user_id: int
    session_id: str = ""
    working: deque[Message] = field(default_factory=lambda: deque(maxlen=16))
    summary: str = ""
    observations: list[str] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.working.append(Message(role=role, content=content))
        obs = compress_zero_llm(role, content)
        self.observations.append(f"{obs.title}: {obs.narrative}")

    def as_messages(self, max_turns: int = 6) -> list[dict[str, str]]:
        recent = list(self.working)[-max_turns:]
        return [{"role": m.role, "content": m.content} for m in recent]


class HierarchicalMemory:
    """
    Token-efficient 3-layer memory:
    - Working: last N turns only (sliding window)
    - Episodic: compressed session summaries (LLM only when threshold hit)
    - Semantic: BM25-retrieved facts within token budget
    """

    def __init__(self) -> None:
        self.store = MemoryStore()
        self._sessions: dict[int, SessionMemory] = {}
        self.token_budget = config.memory.token_budget
        self.working_max = config.memory.working_turns
        self.summarize_after = config.memory.summarize_after
        self.llm_summarize = config.memory.llm_summarize
        from pds_ultimate.core.memory.agentmemory_bridge import agentmemory_bridge

        agentmemory_bridge.enabled = config.memory.agentmemory_export

    def session(self, user_id: int) -> SessionMemory:
        if user_id not in self._sessions:
            sid = f"tg-{user_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            self._sessions[user_id] = SessionMemory(
                user_id=user_id, session_id=sid)
        return self._sessions[user_id]

    def add_turn(self, user_id: int, role: str, content: str) -> None:
        sess = self.session(user_id)
        sess.add(role, content)
        agentmemory_bridge.observe(sess.session_id, role, content, user_id)

        # Auto-extract facts without LLM
        if role == "user" and len(content) > 20:
            obs = compress_zero_llm(role, content)
            for fact in obs.facts:
                self.store.remember(
                    user_id, fact, layer="semantic", importance=0.75)
            # Auto-extract entities into knowledge graph
            try:
                self.kg_auto_extract(user_id, content)
            except Exception as exc:
                logger.debug(f"KG auto-extract skipped: {exc}")

    def remember_fact(self, user_id: int, content: str, *, key: str = "", importance: float = 0.8, layer: str = "semantic") -> int:
        obs = compress_zero_llm("memory", content)
        return self.store.remember(
            user_id, content, layer=layer, key=key, importance=importance, compressed=obs.narrative
        )

    def recall(self, user_id: int, query: str = "", limit: int = 8) -> list[dict]:
        return self.store.recall(user_id, query, limit=limit)

    def recall_recent(self, user_id: int, hours: int = 24, limit: int = 20) -> list[dict]:
        return self.store.recall_recent(user_id, hours=hours, limit=limit)

    def recall_about(self, user_id: int, entity: str, limit: int = 10) -> list[dict]:
        return self.store.recall_about_entity(user_id, entity, limit=limit)

    def forget(self, user_id: int, query: str) -> int:
        return self.store.forget(user_id, query)

    # ── Knowledge Graph methods ───────────────────────────────────────────────

    def kg_upsert_entity(self, user_id: int, name: str, kind: str = "entity",
                         attributes: dict | None = None, importance: float = 0.5) -> int:
        kg = _get_kg()
        if kg is None:
            return -1
        return kg.upsert_entity(user_id, name, kind=kind, attributes=attributes, importance=importance)

    def kg_add_relation(self, user_id: int, from_name: str, to_name: str,
                        relation: str, context: str = "") -> None:
        kg = _get_kg()
        if kg is None:
            return
        kg.add_relation(user_id, from_name, to_name, relation, context=context)

    def kg_profile(self, user_id: int, entity_name: str) -> str:
        kg = _get_kg()
        if kg is None:
            return "Knowledge graph unavailable."
        return kg.full_profile(user_id, entity_name)

    def kg_search(self, user_id: int, query: str, limit: int = 10) -> list[dict]:
        kg = _get_kg()
        if kg is None:
            return []
        return kg.search_entities(user_id, query, limit=limit)

    def kg_list_important(self, user_id: int, limit: int = 20) -> list[dict]:
        kg = _get_kg()
        if kg is None:
            return []
        return kg.list_important(user_id, limit=limit)

    def kg_auto_extract(self, user_id: int, text: str, source_entity: str | None = None) -> list[str]:
        """Auto-extract and link entities from a text block."""
        kg = _get_kg()
        if kg is None:
            return []
        return kg.auto_extract_and_link(user_id, text, source_entity=source_entity)

    def build_context(self, user_id: int, query: str = "") -> str:
        """Build minimal context within token budget — saves DeepSeek tokens."""
        sess = self.session(user_id)
        parts: list[str] = []

        if sess.summary:
            parts.append(f"Эпизод: {sess.summary}")

        semantic = self.store.format_context(
            user_id, query=query, limit=6, budget_tokens=self.token_budget // 2
        )
        if semantic:
            parts.append(semantic)

        try:
            from pds_ultimate.core.contacts.book import contact_book

            contacts = contact_book.format_context(query, limit=20)
            if contacts:
                parts.append(contacts)
        except Exception as exc:
            logger.debug(f"Contacts context skipped: {exc}")

        # Recent observations compressed (zero-LLM)
        if sess.observations:
            recent_obs = trim_to_budget(
                sess.observations[-8:], self.token_budget // 4)
            if recent_obs:
                parts.append("Недавний контекст:\n" + recent_obs)

        result = trim_to_budget(parts, self.token_budget)
        saved = max(0, estimate_tokens(
            "\n\n".join(parts)) - estimate_tokens(result))
        if saved > 50:
            logger.debug(f"Memory token savings: ~{saved} tokens")
        return result

    async def maybe_summarize_session(self, user_id: int) -> None:
        sess = self.session(user_id)
        if len(sess.working) < self.summarize_after:
            return

        if not self.llm_summarize:
            # Zero-LLM fallback: concatenate compressed observations
            sess.summary = trim_to_budget(sess.observations[-12:], 400)
            self.store.remember(
                user_id, sess.summary, layer="episodic", key="session_summary", importance=0.6)
        else:
            transcript = "\n".join(f"{m.role}: {m.content[:300]}" for m in list(
                sess.working)[-self.summarize_after:])
            summary = await llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": "Сожми в 3-5 предложений. Только факты и решения. Без воды.",
                    },
                    {"role": "user", "content": transcript},
                ],
                kind=TaskKind.SUMMARIZE,
                temperature=0.1,
                max_tokens=256,
            )
            sess.summary = summary
            self.store.remember(user_id, summary, layer="episodic",
                                key="session_summary", importance=0.6)

        recent = list(sess.working)[-self.working_max:]
        sess.working.clear()
        sess.observations = sess.observations[-12:]
        for msg in recent:
            sess.working.append(msg)

        # Keep long-term memory bounded — prevents unbounded growth / token bloat
        try:
            self.store.prune(
                user_id, max_facts=config.memory.max_facts_per_user)
        except Exception as exc:
            logger.debug(f"Memory prune skipped: {exc}")


hierarchical_memory = HierarchicalMemory()
