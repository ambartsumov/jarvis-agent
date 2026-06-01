"""
PDS-Ultimate Unified Memory System v1.0 — World-Class
========================================================
ЕДИНАЯ система памяти, заменяющая 4 старых:
  memory.py, memory_v2.py, advanced_memory.py, advanced_memory_manager.py

Архитектура (вдохновлено MemGPT/Letta):
    ┌─────────────────────────────────────────────────────┐
    │                  UnifiedMemory                      │
    │                                                     │
    │  ┌──────────────┐  ┌──────────────┐                │
    │  │WorkingMemory │  │  SkillLibrary│                │
    │  │(per-chat RAM)│  │  (global)    │                │
    │  └──────────────┘  └──────────────┘                │
    │                                                     │
    │  ┌──────────────────────────────────────────┐      │
    │  │         Long-Term Store (SQLite)          │      │
    │  │  episodic │ semantic │ procedural │ ...   │      │
    │  └──────────────────────────────────────────┘      │
    │                                                     │
    │  ┌──────────────────────────────────────────┐      │
    │  │     Semantic Index (embeddings/TF-IDF)    │      │
    │  └──────────────────────────────────────────┘      │
    │                                                     │
    │  ┌──────────────────────────────────────────┐      │
    │  │       Failure Learning Engine             │      │
    │  └──────────────────────────────────────────┘      │
    └─────────────────────────────────────────────────────┘

Слои памяти:
  1. Working Memory  — текущий контекст (in-RAM, per-chat, 10 записей)
  2. Short-term      — факты текущей сессии (TTL 24h)
  3. Long-term       — проверенные знания (permanent)
  4. Semantic        — similarity search (embeddings)
  5. Procedural      — успешные паттерны/навыки

Ключевые улучшения vs старая система:
  ✅ Единый API: add() / search() / recall() / get_context()
  ✅ Layered storage: working → short-term → long-term
  ✅ Hybrid search: embedding + keyword + recency + importance
  ✅ Failure-driven learning в том же хранилище
  ✅ Skill library для повторяемых паттернов
  ✅ Per-chat isolation через WorkingMemory
  ✅ Auto-consolidation: дедупликация + merge
  ✅ Auto-pruning: устаревшее удаляется
  ✅ SQLAlchemy-compatible: save_to_db/load_from_db
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pds_ultimate.config import DATA_DIR, logger

# Optional: sentence-transformers for semantic search
try:
    from sentence_transformers import SentenceTransformer
    _HAS_SBERT = True
except ImportError:
    _HAS_SBERT = False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONSTANTS & TYPES
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryType(str, Enum):
    """Типы памяти (single source of truth)."""
    EPISODIC = "episodic"          # Конкретные события
    SEMANTIC = "semantic"          # Обобщённые знания
    PROCEDURAL = "procedural"      # Как делать задачи
    STRATEGIC = "strategic"        # Стратегические решения
    FAILURE = "failure"            # Ошибки и уроки
    FACT = "fact"                  # Факты
    PREFERENCE = "preference"      # Предпочтения пользователя
    RULE = "rule"                  # Бизнес-правила


class MemoryLayer(str, Enum):
    """Слой хранения."""
    WORKING = "working"        # RAM, per-chat, TTL=session
    SHORT_TERM = "short_term"  # SQLite, TTL=24h
    LONG_TERM = "long_term"    # SQLite, permanent


# Stop-words for tokenization (RU + EN)
_STOP_WORDS = frozenset({
    "и", "в", "на", "с", "по", "для", "из", "что", "это", "как",
    "не", "но", "от", "к", "за", "то", "он", "она", "мы", "вы",
    "я", "ты", "его", "её", "их", "мой", "свой", "все", "так",
    "да", "нет", "уже", "ещё", "бы", "ли", "же", "если", "когда",
    "a", "the", "is", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "it", "this", "that", "with", "from", "by", "be",
    "are", "was", "were", "been", "will", "would", "can", "could",
})


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MEMORY ENTRY — единая единица памяти
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """
    Единая единица памяти (заменяет MemoryEntry + AdvancedMemoryEntry).

    Features:
    - Importance + confidence + decay
    - Bigram & keyword extraction для fast matching
    - Embedding-ready (lazy compute)
    - Time-aware relevance scoring
    - Success/failure tracking
    """
    content: str
    memory_type: MemoryType = MemoryType.EPISODIC
    layer: MemoryLayer = MemoryLayer.LONG_TERM
    importance: float = 0.5
    confidence: float = 0.8
    decay_rate: float = 0.1          # 0=permanent, 1=fast decay
    tags: list[str] = field(default_factory=list)
    source: str = "agent"
    metadata: dict[str, Any] = field(default_factory=dict)
    chat_id: int | None = None

    # Timing
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    expires_at: float | None = None  # Unix timestamp, None=never

    # Usage tracking
    access_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    # Embedding (lazy)
    embedding: list[float] | None = None

    # DB
    db_id: int | None = None

    # Failure-specific fields
    error_context: str = ""
    correction: str = ""
    severity: str = ""  # low/medium/high/critical

    # Precomputed (set in __post_init__)
    _keywords: set[str] = field(default_factory=set, repr=False)
    _bigrams: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _content_hash: str = field(default="", repr=False)

    def __post_init__(self):
        self._keywords = self._extract_keywords(self.content)
        self._bigrams = self._extract_bigrams(self.content)
        self._content_hash = hashlib.md5(
            self.content.lower().strip().encode()
        ).hexdigest()[:16]

    # ─── Static helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        tokens = set(re.findall(r'\b\w{3,}\b', text.lower()))
        return tokens - _STOP_WORDS

    @staticmethod
    def _extract_bigrams(text: str) -> set[tuple[str, str]]:
        words = [w for w in re.findall(r'\b\w{2,}\b', text.lower())
                 if w not in _STOP_WORDS]
        return set(zip(words, words[1:]))

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600

    @property
    def age_days(self) -> float:
        return self.age_hours / 24

    @property
    def is_expired(self) -> bool:
        if self.expires_at and time.time() > self.expires_at:
            return True
        return self.metadata.get("expired", False)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    # ─── Scoring ─────────────────────────────────────────────────────────

    def effective_importance(self) -> float:
        """
        Эффективная важность с decay, confidence, success ratio.
        Формула: importance × confidence × decay × success_bonus + access_bonus
        """
        if self.is_expired:
            return 0.0

        # Exponential decay (30-day half-life, modulated by decay_rate)
        half_life_hours = 720 / max(self.decay_rate, 0.01)
        decay_factor = 0.5 ** (self.age_hours / half_life_hours)

        # Access bonus (capped at 0.2)
        access_bonus = min(0.2, self.access_count * 0.015)

        # Success bonus
        success_factor = 0.5 + 0.5 * self.success_rate

        eff = (
            self.importance
            * self.confidence
            * decay_factor
            * success_factor
            + access_bonus
        )
        return min(1.0, max(0.0, eff))

    def relevance_to(self, query: str) -> float:
        """Keyword-based relevance score to a query (no embeddings)."""
        q_keywords = self._extract_keywords(query)
        q_bigrams = self._extract_bigrams(query)

        if not q_keywords:
            return 0.0

        kw_overlap = len(q_keywords & self._keywords)
        bg_overlap = len(q_bigrams & self._bigrams)

        kw_score = kw_overlap / max(len(q_keywords), 1)
        bg_score = bg_overlap * 0.15

        return min(1.0, kw_score + bg_score)

    # ─── Mutations ───────────────────────────────────────────────────────

    def touch(self) -> None:
        self.access_count += 1
        self.last_accessed = time.time()

    def mark_success(self) -> None:
        self.success_count += 1
        self.confidence = min(1.0, self.confidence + 0.05)
        self.importance = min(1.0, self.importance + 0.02)
        self.touch()

    def mark_failure(self) -> None:
        self.failure_count += 1
        self.confidence = max(0.0, self.confidence - 0.1)
        if self.failure_count >= 3:
            self.importance = max(0.1, self.importance - 0.1)

    def promote(self) -> None:
        """Promote from short-term to long-term."""
        if self.layer == MemoryLayer.SHORT_TERM:
            self.layer = MemoryLayer.LONG_TERM
            self.expires_at = None

    # ─── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "memory_type": self.memory_type.value,
            "layer": self.layer.value,
            "importance": round(self.importance, 3),
            "confidence": round(self.confidence, 3),
            "decay_rate": self.decay_rate,
            "tags": self.tags,
            "source": self.source,
            "metadata": self.metadata,
            "chat_id": self.chat_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "error_context": self.error_context,
            "correction": self.correction,
            "severity": self.severity,
        }

    def __repr__(self) -> str:
        eff = self.effective_importance()
        return (
            f"<Memory [{self.memory_type.value}:{self.layer.value}] "
            f"imp={self.importance:.1f} eff={eff:.2f}: "
            f"{self.content[:50]}...>"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. WORKING MEMORY — per-chat in-RAM context
# ═══════════════════════════════════════════════════════════════════════════════

class WorkingMemory:
    """
    Per-chat working memory: goals, plan, scratchpad, tool results.
    Lives in RAM, reset per session.
    """

    MAX_SCRATCHPAD = 30
    MAX_TOOL_RESULTS = 15

    def __init__(self, chat_id: int = 0):
        self.chat_id = chat_id
        self.primary_goal: str = ""
        self.sub_goals: list[dict[str, Any]] = []
        self.plan: list[dict[str, Any]] = []
        self.scratchpad: list[str] = []
        self.tool_results: list[dict[str, Any]] = []
        self.hypotheses: list[dict[str, Any]] = []
        self.context_vars: dict[str, Any] = {}
        self.iteration: int = 0
        self.start_time: float | None = None

    def set_goal(self, goal: str) -> None:
        self.primary_goal = goal
        self.sub_goals.clear()
        self.plan.clear()
        self.scratchpad.clear()
        self.tool_results.clear()
        self.hypotheses.clear()
        self.iteration = 0
        self.start_time = time.time()

    def add_plan_step(
        self, step: str, depends_on: list[int] | None = None
    ) -> int:
        entry = {
            "step": step,
            "status": "pending",
            "result": None,
            "depends_on": depends_on or [],
            "started_at": None,
            "completed_at": None,
        }
        self.plan.append(entry)
        return len(self.plan) - 1

    def complete_step(self, index: int, result: str) -> None:
        if 0 <= index < len(self.plan):
            self.plan[index]["status"] = "completed"
            self.plan[index]["result"] = result
            self.plan[index]["completed_at"] = time.time()

    def fail_step(self, index: int, error: str) -> None:
        if 0 <= index < len(self.plan):
            self.plan[index]["status"] = "failed"
            self.plan[index]["result"] = error
            self.plan[index]["completed_at"] = time.time()

    def get_ready_steps(self) -> list[tuple[int, dict]]:
        """Steps whose dependencies are all completed."""
        ready = []
        for i, step in enumerate(self.plan):
            if step["status"] != "pending":
                continue
            deps_ok = all(
                self.plan[d]["status"] == "completed"
                for d in step.get("depends_on", [])
                if 0 <= d < len(self.plan)
            )
            if deps_ok:
                ready.append((i, step))
        return ready

    def add_note(self, note: str) -> None:
        self.scratchpad.append(note)
        if len(self.scratchpad) > self.MAX_SCRATCHPAD:
            self.scratchpad = self.scratchpad[-self.MAX_SCRATCHPAD:]

    def add_tool_result(
        self, tool_name: str, result: str, success: bool
    ) -> None:
        self.tool_results.append({
            "tool": tool_name,
            "result": result[:2000],
            "success": success,
            "iteration": self.iteration,
            "ts": time.time(),
        })
        if len(self.tool_results) > self.MAX_TOOL_RESULTS:
            self.tool_results = self.tool_results[-self.MAX_TOOL_RESULTS:]

    def add_hypothesis(self, text: str, confidence: float = 0.5) -> int:
        self.hypotheses.append({
            "text": text, "confidence": confidence,
            "status": "unverified", "evidence": [],
        })
        return len(self.hypotheses) - 1

    def get_context_summary(self) -> str:
        parts = []
        if self.primary_goal:
            parts.append(f"🎯 ЦЕЛЬ: {self.primary_goal}")
        if self.plan:
            plan_lines = []
            for i, s in enumerate(self.plan):
                icon = {"pending": "⏳", "completed": "✅", "failed": "❌"
                        }.get(s["status"], "?")
                plan_lines.append(f"  {icon} {i+1}. {s['step']}")
                if s["result"]:
                    plan_lines.append(f"     → {str(s['result'])[:80]}")
            parts.append("ПЛАН:\n" + "\n".join(plan_lines))
        if self.tool_results:
            recent = self.tool_results[-3:]
            tl = [
                f"  {'✅' if t['success'] else '❌'} {t['tool']}: "
                f"{t['result'][:60]}"
                for t in recent
            ]
            parts.append("ПОСЛЕДНИЕ ДЕЙСТВИЯ:\n" + "\n".join(tl))
        if self.scratchpad:
            parts.append(
                "ЗАМЕТКИ:\n" +
                "\n".join(f"  • {n}" for n in self.scratchpad[-5:])
            )
        return "\n\n".join(parts) if parts else ""

    def reset(self) -> None:
        self.__init__(self.chat_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SKILL — reusable successful strategy
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Skill:
    """A learned reusable strategy."""
    id: str = ""
    name: str = ""
    description: str = ""
    pattern: str = ""                   # Regex for activation
    strategy: str = ""                  # How to solve
    tools_used: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def matches(self, text: str) -> bool:
        if not self.pattern:
            return False
        try:
            return bool(re.search(self.pattern, text.lower()))
        except re.error:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pattern": self.pattern,
            "strategy": self.strategy,
            "tools_used": self.tools_used,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "last_used": self.last_used,
            "tags": self.tags,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SEMANTIC INDEX — hybrid search (embedding + TF-IDF)
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticIndex:
    """Hybrid search: sentence-transformers (optional) + TF-IDF fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model: Any = None
        self._model_name = model_name
        self._embed_cache: dict[str, list[float]] = {}
        self._doc_freq: Counter = Counter()
        self._total_docs: int = 0

        if _HAS_SBERT:
            try:
                self._model = SentenceTransformer(model_name)
                logger.info(f"✅ SentenceTransformer loaded: {model_name}")
            except Exception as e:
                logger.warning(f"SentenceTransformer load failed: {e}")

    @property
    def has_embeddings(self) -> bool:
        return self._model is not None

    def compute_embedding(self, text: str) -> list[float] | None:
        """Compute embedding (returns None if no model)."""
        if not self._model:
            return None
        if text in self._embed_cache:
            return self._embed_cache[text]
        try:
            vec = self._model.encode(text, convert_to_numpy=True).tolist()
            self._embed_cache[text] = vec
            # Limit cache size
            if len(self._embed_cache) > 5000:
                # Remove oldest half
                keys = list(self._embed_cache.keys())
                for k in keys[:2500]:
                    del self._embed_cache[k]
            return vec
        except Exception:
            return None

    def update_idf(self, entries: list[MemoryEntry]) -> None:
        """Rebuild IDF index from all entries."""
        self._doc_freq.clear()
        self._total_docs = len(entries)
        for entry in entries:
            unique_tokens = entry._keywords | {t.lower() for t in entry.tags}
            for token in unique_tokens:
                self._doc_freq[token] += 1

    def search(
        self,
        query: str,
        candidates: list[MemoryEntry],
        limit: int = 10,
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Hybrid ranked search.

        Score = α·semantic_sim + β·keyword_overlap + γ·recency + δ·importance
        Weights: α=0.45, β=0.25, γ=0.15, δ=0.15
        """
        if not candidates:
            return []

        query_embed = self.compute_embedding(query)
        q_keywords = MemoryEntry._extract_keywords(query)
        q_bigrams = MemoryEntry._extract_bigrams(query)

        results: list[tuple[MemoryEntry, float]] = []

        for mem in candidates:
            if mem.is_expired:
                continue

            # (a) Semantic similarity
            sem_score = 0.0
            if query_embed is not None:
                if mem.embedding is None:
                    mem.embedding = self.compute_embedding(mem.content)
                if mem.embedding is not None:
                    sem_score = self._cosine(query_embed, mem.embedding)

            # (b) Keyword + bigram overlap (TF-IDF weighted)
            kw_score = 0.0
            if q_keywords:
                overlap = q_keywords & mem._keywords
                for token in overlap:
                    tf = 1.0  # binary TF
                    df = self._doc_freq.get(token, 1)
                    idf = math.log(
                        max(1, self._total_docs) / max(1, df)
                    )
                    kw_score += tf * idf
                # Normalize
                max_possible = len(q_keywords) * 3.0
                kw_score = min(1.0, kw_score / max(max_possible, 1.0))

            bg_overlap = len(q_bigrams & mem._bigrams)
            kw_score += min(0.3, bg_overlap * 0.1)

            # (c) Recency (exponential decay, 14-day half-life)
            recency = 0.5 ** (mem.age_days / 14)

            # (d) Effective importance
            eff_imp = mem.effective_importance()

            # ─── Weighted combination ─────────────
            if self.has_embeddings:
                total = (
                    sem_score * 0.45 +
                    kw_score * 0.25 +
                    recency * 0.15 +
                    eff_imp * 0.15
                )
            else:
                # No embeddings → keyword-heavy
                total = (
                    kw_score * 0.50 +
                    recency * 0.25 +
                    eff_imp * 0.25
                )

            if total > 0.05:
                results.append((mem, total))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FAILURE LEARNING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

_ERROR_PATTERNS: dict[str, str] = {
    r"timeout|timed out": "timeout",
    r"not found|404|не найден": "not_found",
    r"permission|403|запрещен": "permission",
    r"rate.?limit|429|слишком.?часто": "rate_limit",
    r"parse|json|syntax": "parse_error",
    r"network|connection|connect": "network",
    r"invalid|validation|невалидн": "validation",
}


def classify_error(message: str) -> str:
    lower = message.lower()
    for pattern, etype in _ERROR_PATTERNS.items():
        if re.search(pattern, lower):
            return etype
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. UNIFIED MEMORY MANAGER — the only manager you need
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedMemory:
    """
    World-class unified memory manager.

    Single source of truth for ALL memory operations.
    Replaces: MemoryManager, AdvancedMemoryManager, MemoryV2Engine.

    Usage:
        memory = UnifiedMemory()
        memory.add("user prefers short answers", MemoryType.PREFERENCE)
        results = memory.search("how does user like answers?")
        context = memory.get_context("what format?", chat_id=123)
    """

    # Auto-consolidation every N adds
    CONSOLIDATION_INTERVAL = 100
    # Max memories before pruning
    MAX_MEMORIES = 3000
    # Prune threshold (effective_importance below this)
    PRUNE_THRESHOLD = 0.03
    # Short-term TTL (24 hours)
    SHORT_TERM_TTL = 86400

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(DATA_DIR / "unified_memory.db")
        self._memories: dict[int, MemoryEntry] = {}
        self._by_chat: dict[int, list[int]] = defaultdict(list)
        self._next_id = 1
        self._add_counter = 0

        # Working memories (per-chat, in-RAM)
        self._working: dict[int, WorkingMemory] = {}

        # Skills
        self._skills: dict[str, Skill] = {}
        self._skill_counter = 0

        # Semantic index
        self._index = SemanticIndex()
        self._index_dirty = True

        # Init DB
        self._init_db()

        logger.info("UnifiedMemory initialized")

    # ─── DB ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    content   TEXT NOT NULL,
                    mem_type  TEXT NOT NULL,
                    layer     TEXT NOT NULL DEFAULT 'long_term',
                    importance REAL DEFAULT 0.5,
                    confidence REAL DEFAULT 0.8,
                    decay_rate REAL DEFAULT 0.1,
                    tags      TEXT DEFAULT '[]',
                    source    TEXT DEFAULT 'agent',
                    metadata  TEXT DEFAULT '{}',
                    chat_id   INTEGER,
                    created_at   REAL,
                    last_accessed REAL,
                    expires_at   REAL,
                    access_count  INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    embedding    BLOB,
                    error_context TEXT DEFAULT '',
                    correction    TEXT DEFAULT '',
                    severity      TEXT DEFAULT '',
                    content_hash  TEXT DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_type "
                "ON memories(mem_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_chat "
                "ON memories(chat_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_hash "
                "ON memories(content_hash)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id        TEXT PRIMARY KEY,
                    name      TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    pattern   TEXT DEFAULT '',
                    strategy  TEXT DEFAULT '',
                    tools     TEXT DEFAULT '[]',
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used REAL,
                    created_at REAL,
                    tags      TEXT DEFAULT '[]'
                )
            """)
            conn.commit()

    # ─── Core API ────────────────────────────────────────────────────────

    def add(
        self,
        content: str,
        memory_type: MemoryType | str = MemoryType.EPISODIC,
        importance: float = 0.5,
        confidence: float = 0.8,
        tags: list[str] | None = None,
        source: str = "agent",
        metadata: dict | None = None,
        chat_id: int | None = None,
        layer: MemoryLayer = MemoryLayer.LONG_TERM,
        ttl_seconds: int | None = None,
        # Failure-specific
        error_context: str = "",
        correction: str = "",
        severity: str = "",
    ) -> MemoryEntry:
        """
        Add a memory entry. The ONE method to store anything.

        Args:
            content: What to remember
            memory_type: Category of memory
            importance: 0.0-1.0
            confidence: 0.0-1.0
            tags: Searchable tags
            chat_id: User/chat this belongs to (None=global)
            layer: Storage layer
            ttl_seconds: Auto-expire after N seconds
            error_context: (failure only) What went wrong
            correction: (failure only) The right approach
            severity: (failure only) low/medium/high/critical
        """
        if isinstance(memory_type, str):
            try:
                memory_type = MemoryType(memory_type)
            except ValueError:
                memory_type = MemoryType.FACT

        # Deduplicate: skip if identical content exists
        content_hash = hashlib.md5(
            content.lower().strip().encode()
        ).hexdigest()[:16]

        for existing in self._memories.values():
            if existing._content_hash == content_hash and (
                existing.chat_id == chat_id
            ):
                # Update importance if new is higher
                if importance > existing.importance:
                    existing.importance = importance
                existing.touch()
                return existing

        expires_at = None
        if ttl_seconds:
            expires_at = time.time() + ttl_seconds
        elif layer == MemoryLayer.SHORT_TERM:
            expires_at = time.time() + self.SHORT_TERM_TTL

        entry = MemoryEntry(
            content=content,
            memory_type=memory_type,
            layer=layer,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
            source=source,
            metadata=metadata or {},
            chat_id=chat_id,
            expires_at=expires_at,
            error_context=error_context,
            correction=correction,
            severity=severity,
        )

        # Failure type auto-config
        if memory_type == MemoryType.FAILURE:
            entry.decay_rate = 0.01  # Failures don't decay fast
            if not severity:
                entry.severity = "medium"

        # Save to DB
        db_id = self._db_insert(entry)
        entry.db_id = db_id
        self._memories[db_id] = entry

        if chat_id is not None:
            self._by_chat[chat_id].append(db_id)

        self._index_dirty = True
        self._add_counter += 1

        # Auto-consolidation
        if self._add_counter >= self.CONSOLIDATION_INTERVAL:
            self._consolidate()
            self._add_counter = 0

        return entry

    def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: MemoryType | str | None = None,
        chat_id: int | None = None,
        min_importance: float = 0.0,
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """
        Semantic + keyword hybrid search.

        Returns most relevant memories sorted by relevance.
        """
        # Rebuild IDF if dirty
        if self._index_dirty:
            self._index.update_idf(list(self._memories.values()))
            self._index_dirty = False

        # Filter candidates
        candidates = list(self._memories.values())

        if memory_type:
            mt = memory_type if isinstance(
                memory_type, str) else memory_type.value
            candidates = [m for m in candidates if m.memory_type.value == mt]
        if chat_id is not None:
            # Include global (None) + chat-specific
            candidates = [
                m for m in candidates
                if m.chat_id is None or m.chat_id == chat_id
            ]
        if not include_expired:
            candidates = [m for m in candidates if not m.is_expired]
        if min_importance > 0:
            candidates = [
                m for m in candidates
                if m.effective_importance() >= min_importance
            ]

        # Search
        results = self._index.search(query, candidates, limit)

        # Touch accessed
        for mem, _ in results:
            mem.touch()

        return [m for m, _ in results]

    def recall(
        self,
        query: str,
        chat_id: int | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """
        High-level recall: combines search + recent + failures.
        Best method for agent context building.
        """
        # Semantic search
        search_results = self.search(
            query, limit=limit, chat_id=chat_id
        )

        # Also get recent failures for this chat (prevent repeating mistakes)
        failures = [
            m for m in self._memories.values()
            if m.memory_type == MemoryType.FAILURE
            and (m.chat_id is None or m.chat_id == chat_id)
            and not m.is_expired
            and m.relevance_to(query) > 0.1
        ]
        failures.sort(key=lambda m: m.relevance_to(query), reverse=True)

        # Merge, deduplicate
        seen_ids = {m.db_id for m in search_results}
        combined = list(search_results)
        for f in failures[:2]:
            if f.db_id not in seen_ids:
                combined.append(f)
                seen_ids.add(f.db_id)

        return combined[:limit + 2]  # Allow a bit extra for failures

    def get_context(
        self,
        query: str,
        chat_id: int | None = None,
        limit: int = 5,
    ) -> str:
        """
        Build memory context string for LLM prompt.
        The main method used by Agent.
        """
        memories = self.recall(query, chat_id=chat_id, limit=limit)
        if not memories:
            return ""

        # Build context
        type_emoji = {
            MemoryType.EPISODIC: "📝",
            MemoryType.SEMANTIC: "📚",
            MemoryType.PROCEDURAL: "🔧",
            MemoryType.STRATEGIC: "🎯",
            MemoryType.FAILURE: "⚠️",
            MemoryType.FACT: "💡",
            MemoryType.PREFERENCE: "⭐",
            MemoryType.RULE: "📋",
        }

        lines = ["🧠 ПАМЯТЬ (релевантное к запросу):"]
        for m in memories:
            emoji = type_emoji.get(m.memory_type, "•")
            imp = f"[{m.effective_importance():.0%}]"
            lines.append(f"  {emoji} {imp} {m.content[:150]}")
            if m.memory_type == MemoryType.FAILURE and m.correction:
                lines.append(f"    → Правильно: {m.correction[:100]}")

        # Skills context
        skills_ctx = self.get_skills_context(query)
        if skills_ctx:
            lines.append("")
            lines.append(skills_ctx)

        return "\n".join(lines)

    # ─── Failure Learning ────────────────────────────────────────────────

    def record_failure(
        self,
        query: str,
        error: str,
        tool: str = "",
        correction: str = "",
        severity: str = "medium",
        chat_id: int | None = None,
    ) -> MemoryEntry:
        """Record a failure for learning."""
        error_type = classify_error(error)
        content = f"[{error_type}] {error[:200]}"
        if tool:
            content = f"[{error_type}:{tool}] {error[:200]}"

        return self.add(
            content=content,
            memory_type=MemoryType.FAILURE,
            importance=0.8,
            confidence=0.9,
            tags=["failure", error_type, tool] if tool else [
                "failure", error_type],
            source="failure_learning",
            chat_id=chat_id,
            error_context=query[:500],
            correction=correction,
            severity=severity,
        )

    def get_failure_lessons(
        self,
        query: str,
        tool: str = "",
        limit: int = 3,
    ) -> list[MemoryEntry]:
        """Get relevant failure lessons."""
        failures = [
            m for m in self._memories.values()
            if m.memory_type == MemoryType.FAILURE and not m.is_expired
        ]
        if tool:
            # Prioritize same-tool failures
            tool_failures = [f for f in failures if tool in (f.tags or [])]
            other_failures = [
                f for f in failures if tool not in (f.tags or [])]
            failures = tool_failures + other_failures

        # Score by relevance
        scored = []
        for f in failures:
            score = f.relevance_to(query)
            if f.correction:
                score += 0.2  # Bonus for having a correction
            if score > 0.05:
                scored.append((f, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in scored[:limit]]

    def get_failure_context(
        self, query: str, tool: str = ""
    ) -> str:
        """Get failure lessons as context string."""
        lessons = self.get_failure_lessons(query, tool)
        if not lessons:
            return ""
        lines = ["⚠️ УРОКИ ПРОШЛЫХ ОШИБОК (не повторяй):"]
        for l in lessons:
            lines.append(f"  • {l.content[:120]}")
            if l.correction:
                lines.append(f"    → {l.correction[:100]}")
        return "\n".join(lines)

    # ─── Skills ──────────────────────────────────────────────────────────

    def add_skill(
        self,
        name: str,
        pattern: str,
        strategy: str,
        tools: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Skill:
        """Add a reusable skill."""
        self._skill_counter += 1
        sid = f"skill_{self._skill_counter}"
        skill = Skill(
            id=sid, name=name, pattern=pattern,
            strategy=strategy, tools_used=tools or [],
            tags=tags or [],
        )
        self._skills[sid] = skill
        self._db_save_skill(skill)
        return skill

    def find_skills(
        self, text: str, min_success_rate: float = 0.3
    ) -> list[Skill]:
        """Find matching skills for a query."""
        matches = [
            s for s in self._skills.values()
            if s.matches(text) and s.success_rate >= min_success_rate
        ]
        return sorted(matches, key=lambda s: s.success_rate, reverse=True)

    def record_skill_usage(self, skill_id: str, success: bool) -> None:
        skill = self._skills.get(skill_id)
        if not skill:
            return
        if success:
            skill.success_count += 1
        else:
            skill.failure_count += 1
        skill.last_used = time.time()
        self._db_save_skill(skill)

    def get_skills_context(self, query: str, limit: int = 3) -> str:
        matching = self.find_skills(query)[:limit]
        if not matching:
            return ""
        lines = ["🎓 НАВЫКИ (используй если подходит):"]
        for s in matching:
            lines.append(
                f"  • {s.name} ({s.success_rate:.0%} успех): {s.strategy}"
            )
        return "\n".join(lines)

    # ─── Working Memory ──────────────────────────────────────────────────

    def get_working(self, chat_id: int) -> WorkingMemory:
        if chat_id not in self._working:
            self._working[chat_id] = WorkingMemory(chat_id)
        return self._working[chat_id]

    def reset_working(self, chat_id: int) -> None:
        if chat_id in self._working:
            self._working[chat_id].reset()

    # ─── Persistence ─────────────────────────────────────────────────────

    def save_to_db(self, session=None) -> int:
        """
        Save all in-memory entries to SQLite.
        Also compatible with SQLAlchemy session for backward compat.
        """
        saved = 0
        with sqlite3.connect(self._db_path) as conn:
            for mem in self._memories.values():
                if mem.db_id:
                    conn.execute("""
                        UPDATE memories SET
                            importance=?, confidence=?, tags=?,
                            metadata=?, last_accessed=?,
                            access_count=?, success_count=?,
                            failure_count=?, layer=?
                        WHERE id=?
                    """, (
                        mem.importance, mem.confidence,
                        json.dumps(mem.tags),
                        json.dumps(mem.metadata),
                        mem.last_accessed,
                        mem.access_count, mem.success_count,
                        mem.failure_count, mem.layer.value,
                        mem.db_id,
                    ))
                    saved += 1
            conn.commit()
        return saved

    def load_from_db(self, session=None) -> int:
        """Load all memories from SQLite into RAM."""
        loaded = 0
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC"
            ).fetchall()

            for row in rows:
                try:
                    mem_type = MemoryType(row["mem_type"])
                except ValueError:
                    mem_type = MemoryType.FACT

                try:
                    layer = MemoryLayer(row["layer"])
                except (ValueError, KeyError):
                    layer = MemoryLayer.LONG_TERM

                entry = MemoryEntry(
                    content=row["content"],
                    memory_type=mem_type,
                    layer=layer,
                    importance=row["importance"] or 0.5,
                    confidence=row["confidence"] or 0.8,
                    decay_rate=row["decay_rate"] or 0.1,
                    tags=json.loads(row["tags"] or "[]"),
                    source=row["source"] or "agent",
                    metadata=json.loads(row["metadata"] or "{}"),
                    chat_id=row["chat_id"],
                    created_at=row["created_at"] or time.time(),
                    last_accessed=row["last_accessed"] or time.time(),
                    expires_at=row["expires_at"],
                    access_count=row["access_count"] or 0,
                    success_count=row["success_count"] or 0,
                    failure_count=row["failure_count"] or 0,
                    error_context=row["error_context"] or "",
                    correction=row["correction"] or "",
                    severity=row["severity"] or "",
                )

                # Load embedding
                if row["embedding"]:
                    try:
                        entry.embedding = json.loads(row["embedding"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                entry.db_id = row["id"]
                self._memories[entry.db_id] = entry

                if entry.chat_id is not None:
                    self._by_chat[entry.chat_id].append(entry.db_id)

                if entry.db_id >= self._next_id:
                    self._next_id = entry.db_id + 1

                loaded += 1

            # Load skills
            try:
                skill_rows = conn.execute("SELECT * FROM skills").fetchall()
                for sr in skill_rows:
                    skill = Skill(
                        id=sr["id"],
                        name=sr["name"],
                        description=sr["description"] or "",
                        pattern=sr["pattern"] or "",
                        strategy=sr["strategy"] or "",
                        tools_used=json.loads(sr["tools"] or "[]"),
                        success_count=sr["success_count"] or 0,
                        failure_count=sr["failure_count"] or 0,
                        last_used=sr["last_used"] or time.time(),
                        created_at=sr["created_at"] or time.time(),
                        tags=json.loads(sr["tags"] or "[]"),
                    )
                    self._skills[skill.id] = skill
                    # Update counter
                    try:
                        num = int(skill.id.split("_")[1])
                        if num >= self._skill_counter:
                            self._skill_counter = num + 1
                    except (IndexError, ValueError):
                        pass
            except sqlite3.OperationalError:
                pass  # Skills table may not exist in old DBs

        self._index_dirty = True
        logger.info(
            f"Loaded {loaded} memories + {len(self._skills)} skills from DB"
        )
        return loaded

    def prune(self) -> int:
        """Remove expired and low-importance memories."""
        to_remove = []
        for db_id, mem in self._memories.items():
            if mem.is_expired:
                to_remove.append(db_id)
            elif mem.effective_importance() < self.PRUNE_THRESHOLD:
                to_remove.append(db_id)

        for db_id in to_remove:
            self._remove(db_id)

        if to_remove:
            logger.info(f"Pruned {len(to_remove)} memories")
        return len(to_remove)

    # ─── Stats ───────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = defaultdict(int)
        by_layer: dict[str, int] = defaultdict(int)
        for m in self._memories.values():
            by_type[m.memory_type.value] += 1
            by_layer[m.layer.value] += 1

        total = len(self._memories)
        avg_imp = (
            sum(m.importance for m in self._memories.values()) / max(total, 1)
        )
        avg_conf = (
            sum(m.confidence for m in self._memories.values()) / max(total, 1)
        )
        failures_count = by_type.get("failure", 0)

        return {
            "total": total,
            "by_type": dict(by_type),
            "by_layer": dict(by_layer),
            "avg_importance": round(avg_imp, 3),
            "avg_confidence": round(avg_conf, 3),
            "failures_stored": failures_count,
            "skills": len(self._skills),
            "working_sessions": len(self._working),
            "semantic_search": self._index.has_embeddings,
        }

    # ─── Internal ────────────────────────────────────────────────────────

    def _db_insert(self, mem: MemoryEntry) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO memories (
                    content, mem_type, layer, importance, confidence,
                    decay_rate, tags, source, metadata, chat_id,
                    created_at, last_accessed, expires_at,
                    access_count, success_count, failure_count,
                    embedding, error_context, correction, severity,
                    content_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                mem.content,
                mem.memory_type.value,
                mem.layer.value,
                mem.importance,
                mem.confidence,
                mem.decay_rate,
                json.dumps(mem.tags),
                mem.source,
                json.dumps(mem.metadata),
                mem.chat_id,
                mem.created_at,
                mem.last_accessed,
                mem.expires_at,
                mem.access_count,
                mem.success_count,
                mem.failure_count,
                json.dumps(mem.embedding) if mem.embedding else None,
                mem.error_context,
                mem.correction,
                mem.severity,
                mem._content_hash,
            ))
            conn.commit()
            return cursor.lastrowid

    def _db_save_skill(self, skill: Skill) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skills
                    (id, name, description, pattern, strategy, tools,
                     success_count, failure_count, last_used, created_at, tags)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                skill.id, skill.name, skill.description,
                skill.pattern, skill.strategy,
                json.dumps(skill.tools_used),
                skill.success_count, skill.failure_count,
                skill.last_used, skill.created_at,
                json.dumps(skill.tags),
            ))
            conn.commit()

    def _remove(self, db_id: int) -> None:
        mem = self._memories.pop(db_id, None)
        if not mem:
            return
        if mem.chat_id is not None and db_id in self._by_chat.get(mem.chat_id, []):
            self._by_chat[mem.chat_id].remove(db_id)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM memories WHERE id=?", (db_id,))
            conn.commit()

    def _consolidate(self) -> None:
        """Remove duplicates, prune expired."""
        seen: set[str] = set()
        to_remove: list[int] = []
        for db_id, mem in self._memories.items():
            if mem.is_expired:
                to_remove.append(db_id)
                continue
            if mem._content_hash in seen:
                to_remove.append(db_id)
            else:
                seen.add(mem._content_hash)

        for db_id in to_remove:
            self._remove(db_id)

        # Prune if over max
        if len(self._memories) > self.MAX_MEMORIES:
            # Remove lowest effective_importance
            sorted_mems = sorted(
                self._memories.items(),
                key=lambda x: x[1].effective_importance(),
            )
            excess = len(self._memories) - self.MAX_MEMORIES
            for db_id, _ in sorted_mems[:excess]:
                self._remove(db_id)

        if to_remove:
            logger.info(
                f"Consolidation: removed {len(to_remove)}, "
                f"remaining={len(self._memories)}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. GLOBAL INSTANCE + BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

# The ONE instance
unified_memory = UnifiedMemory()

# Backward-compatible aliases (so old imports still work)
memory_manager = unified_memory


def get_memory_manager() -> UnifiedMemory:
    """Get the unified memory manager."""
    return unified_memory
