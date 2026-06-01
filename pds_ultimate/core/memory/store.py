"""SQLite-backed persistent memory — BM25 + Vector TF-IDF + temporal decay + spaced repetition."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pds_ultimate.config import DATABASE_PATH, logger
from pds_ultimate.core.memory.bm25 import BM25Index

# Lazy-import vector store to avoid circular imports
_vector_store = None


def _get_vec():
    global _vector_store
    if _vector_store is None:
        try:
            from pds_ultimate.core.memory.vector_store import vector_index
            _vector_store = vector_index
        except Exception as exc:
            logger.warning(f"VectorStore unavailable: {exc}")
    return _vector_store


class _Base(DeclarativeBase):
    pass


class MemoryFact(_Base):
    __tablename__ = "agent_memory_v3"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    layer: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(256), index=True, default="")
    content: Mapped[str] = mapped_column(Text)
    compressed: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc))
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


def _recency_score(dt: datetime) -> float:
    """Ebbinghaus-inspired recency: 1.0 = just now, ~0.5 = 7 days ago, ~0.1 = 60 days ago."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - dt).total_seconds() / 86400.0)
    # Exponential decay with half-life of ~7 days
    return math.exp(-0.1 * days)


class MemoryStore:
    def __init__(self) -> None:
        self.engine = create_engine(
            f"sqlite:///{DATABASE_PATH}",
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        _Base.metadata.create_all(self.engine)
        self._migrate_schema()
        self.session_factory = sessionmaker(
            self.engine, expire_on_commit=False)
        self._bm25 = BM25Index()
        self._rebuild_index()

    def _migrate_schema(self) -> None:
        """Add new columns to existing DB without data loss."""
        import sqlite3

        conn = sqlite3.connect(str(DATABASE_PATH))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(agent_memory_v3)")
        cols = {row[1] for row in cur.fetchall()}
        if not cols:
            conn.close()
            return
        if "compressed" not in cols:
            cur.execute(
                "ALTER TABLE agent_memory_v3 ADD COLUMN compressed TEXT DEFAULT ''")
        if "token_estimate" not in cols:
            cur.execute(
                "ALTER TABLE agent_memory_v3 ADD COLUMN token_estimate INTEGER DEFAULT 0")
        if "last_accessed_at" not in cols:
            cur.execute(
                "ALTER TABLE agent_memory_v3 ADD COLUMN last_accessed_at DATETIME"
            )
        conn.commit()
        conn.close()

    def _rebuild_index(self) -> None:
        with self.session_factory() as session:
            rows = session.scalars(select(MemoryFact)).all()
        items = [(str(r.id), r.content, {
                  "layer": r.layer, "key": r.key}) for r in rows]
        self._bm25.rebuild(items)
        vec = _get_vec()
        if vec is not None:
            try:
                vec.rebuild(items)
            except Exception as exc:
                logger.warning(f"Vector rebuild failed: {exc}")

    def remember(
        self,
        user_id: int,
        content: str,
        *,
        layer: str = "semantic",
        key: str = "",
        importance: float = 0.7,
        compressed: str = "",
    ) -> int:
        token_est = max(1, len(content) // 4)
        with self.session_factory() as session:
            existing = session.scalar(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.layer == layer,
                    MemoryFact.key == key,
                    MemoryFact.content == content,
                )
            )
            if existing:
                # Spaced-repetition: seeing the same fact again boosts importance
                existing.access_count += 1
                existing.importance = min(1.0, existing.importance + 0.05)
                existing.updated_at = datetime.now(timezone.utc)
                existing.last_accessed_at = datetime.now(timezone.utc)
                session.commit()
                return existing.id

            fact = MemoryFact(
                user_id=user_id,
                layer=layer,
                key=key,
                content=content,
                compressed=compressed or content[:500],
                importance=importance,
                token_estimate=token_est,
            )
            session.add(fact)
            session.commit()
            session.refresh(fact)
            self._bm25.add(str(fact.id), fact.content, layer=layer, key=key)
            vec = _get_vec()
            if vec is not None:
                try:
                    vec.add(str(fact.id), fact.content, meta={
                            "layer": layer, "key": key})
                except Exception as exc:
                    logger.warning(f"Vector add failed: {exc}")
            return fact.id

    def recall(
        self,
        user_id: int,
        query: str = "",
        *,
        layer: str | None = None,
        limit: int = 12,
    ) -> list[dict]:
        with self.session_factory() as session:
            stmt = select(MemoryFact).where(MemoryFact.user_id == user_id)
            if layer:
                stmt = stmt.where(MemoryFact.layer == layer)

            if query:
                bm25_hits = self._bm25.search(query, limit=limit * 4)
                bm25_score = {int(h[0]): h[1] for h in bm25_hits}
                # Hybrid: merge BM25 + vector TF-IDF scores
                vec = _get_vec()
                vec_score: dict[int, float] = {}
                if vec is not None:
                    try:
                        v_hits = vec.search(query, limit=limit * 4)
                        vec_score = {int(h[0]): h[1] for h in v_hits}
                    except Exception as exc:
                        logger.warning(f"Vector search failed: {exc}")
                hit_ids = set(bm25_score) | set(vec_score)
                rows = session.scalars(stmt).all()
                rows = [r for r in rows if r.id in hit_ids]
                # Combined score: BM25×0.4 + vector×0.3 + recency×0.2 + importance×0.1
                rows.sort(
                    key=lambda r: (
                        bm25_score.get(r.id, 0) * 0.4
                        + vec_score.get(r.id, 0) * 0.3
                        + _recency_score(r.last_accessed_at) * 0.2
                        + r.importance * 0.1
                    ),
                    reverse=True,
                )
            else:
                rows = session.scalars(
                    stmt.order_by(MemoryFact.importance.desc(),
                                  MemoryFact.updated_at.desc())
                ).all()

            results = []
            now = datetime.now(timezone.utc)
            for row in rows[:limit]:
                # Boost importance on access (spaced repetition)
                row.access_count += 1
                row.importance = min(1.0, row.importance + 0.02)
                row.last_accessed_at = now
                text = row.compressed or row.content
                results.append(
                    {
                        "id": row.id,
                        "layer": row.layer,
                        "key": row.key,
                        "content": text,
                        "importance": round(row.importance, 3),
                        "tokens": row.token_estimate,
                        "days_ago": round((now - (row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at)).total_seconds() / 86400, 1),
                    }
                )

            import time

            from sqlalchemy.exc import OperationalError

            for attempt in range(5):
                try:
                    session.commit()
                    break
                except OperationalError as exc:
                    session.rollback()
                    if "locked" not in str(exc).lower() or attempt >= 4:
                        logger.warning(f"memory recall commit skipped: {exc}")
                        break
                    time.sleep(0.15 * (attempt + 1))
            return results

    def recall_recent(
        self,
        user_id: int,
        *,
        hours: int = 24,
        limit: int = 20,
    ) -> list[dict]:
        """Recall memories created or updated in the last N hours (temporal recall)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self.session_factory() as session:
            rows = session.scalars(
                select(MemoryFact)
                .where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.updated_at >= cutoff,
                )
                .order_by(MemoryFact.updated_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "layer": r.layer,
                    "key": r.key,
                    "content": r.compressed or r.content,
                    "importance": round(r.importance, 3),
                    "updated_at": r.updated_at.isoformat()[:16],
                }
                for r in rows
            ]

    def recall_about_entity(
        self,
        user_id: int,
        entity: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        """Recall all facts mentioning a specific person, place, or project."""
        hits = self._bm25.search(entity, limit=limit * 3)
        if not hits:
            return []
        hit_ids = {int(h[0]) for h in hits}
        with self.session_factory() as session:
            rows = session.scalars(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.id.in_(hit_ids),
                )
            ).all()
            # Extra filter: entity name must appear in content
            entity_low = entity.lower()
            rows = [r for r in rows if entity_low in r.content.lower()]
            rows.sort(key=lambda r: r.importance, reverse=True)
            return [
                {
                    "id": r.id,
                    "layer": r.layer,
                    "content": r.compressed or r.content,
                    "importance": round(r.importance, 3),
                    "updated_at": r.updated_at.isoformat()[:16],
                }
                for r in rows[:limit]
            ]

    def consolidate(self, user_id: int) -> int:
        """
        Memory consolidation: merge near-duplicate semantic facts.
        Keeps the one with higher importance; deletes others.
        Returns number of facts removed.
        """
        with self.session_factory() as session:
            rows = session.scalars(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.layer == "semantic",
                )
            ).all()

        seen: dict[str, int] = {}  # fingerprint → row id to keep
        to_delete: list[int] = []
        rows_by_id = {r.id: r for r in rows}

        for row in sorted(rows, key=lambda r: r.importance, reverse=True):
            # Simple fingerprint: first 80 chars lowercased, no spaces
            fp = "".join(row.content[:80].lower().split())
            if fp in seen:
                to_delete.append(row.id)
            else:
                seen[fp] = row.id

        if not to_delete:
            return 0

        with self.session_factory() as session:
            rows_to_del = session.scalars(
                select(MemoryFact).where(MemoryFact.id.in_(to_delete))
            ).all()
            for r in rows_to_del:
                session.delete(r)
            session.commit()

        for rid in to_delete:
            self._bm25.remove(str(rid))

        logger.info(
            f"Consolidated {len(to_delete)} duplicate memories for user {user_id}")
        return len(to_delete)

    def apply_temporal_decay(self, user_id: int) -> None:
        """
        Apply Ebbinghaus-inspired forgetting: reduce importance of unaccessed facts.
        Call periodically (e.g. once per day). Facts with importance < 0.1 are pruned.
        """
        now = datetime.now(timezone.utc)
        # never-accessed for 90 days → prune
        cutoff_prune = now - timedelta(days=90)

        with self.session_factory() as session:
            rows = session.scalars(
                select(MemoryFact).where(MemoryFact.user_id == user_id)
            ).all()

            to_delete = []
            for row in rows:
                la = row.last_accessed_at
                if la is None:
                    la = row.updated_at
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                days_since = (now - la).total_seconds() / 86400.0
                # Decay: importance × e^(-0.02 × days) — slow decay
                decay = math.exp(-0.02 * days_since)
                new_imp = row.importance * decay
                if new_imp < 0.05 and la < cutoff_prune:
                    to_delete.append(row.id)
                else:
                    row.importance = max(0.05, new_imp)
            session.commit()

        if to_delete:
            with self.session_factory() as session:
                old = session.scalars(
                    select(MemoryFact).where(MemoryFact.id.in_(to_delete))
                ).all()
                for r in old:
                    session.delete(r)
                session.commit()
            for rid in to_delete:
                self._bm25.remove(str(rid))
            logger.info(
                f"Temporal decay pruned {len(to_delete)} forgotten facts for user {user_id}")

    def prune(self, user_id: int, *, max_facts: int = 500) -> int:
        """Cap a user's semantic memory. Evicts least-important, least-accessed, oldest."""
        from sqlalchemy import func

        with self.session_factory() as session:
            total = session.scalar(
                select(func.count()).select_from(MemoryFact).where(
                    MemoryFact.user_id == user_id, MemoryFact.layer == "semantic"
                )
            ) or 0
            if total <= max_facts:
                return 0
            rows = session.scalars(
                select(MemoryFact)
                .where(MemoryFact.user_id == user_id, MemoryFact.layer == "semantic")
                .order_by(
                    MemoryFact.importance.asc(),
                    MemoryFact.access_count.asc(),
                    MemoryFact.updated_at.asc(),
                )
            ).all()
            to_delete = rows[: total - max_facts]
            removed_ids = [r.id for r in to_delete]
            for r in to_delete:
                session.delete(r)
            session.commit()

        for rid in removed_ids:
            self._bm25.remove(str(rid))
        logger.info(f"Pruned {len(removed_ids)} memories for user {user_id}")
        return len(removed_ids)

    def forget(self, user_id: int, query: str) -> int:
        """Delete facts matching a query (explicit user-driven forgetting)."""
        if not query.strip():
            return 0
        hits = self._bm25.search(query, limit=50)
        hit_ids = {int(h[0]) for h in hits}
        if not hit_ids:
            return 0
        with self.session_factory() as session:
            rows = session.scalars(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id, MemoryFact.id.in_(hit_ids)
                )
            ).all()
            removed_ids = [r.id for r in rows]
            for r in rows:
                session.delete(r)
            session.commit()
        for rid in removed_ids:
            self._bm25.remove(str(rid))
        return len(removed_ids)

    def format_context(self, user_id: int, query: str = "", limit: int = 8, budget_tokens: int = 800) -> str:
        facts = self.recall(user_id, query, limit=limit)
        if not facts:
            return ""
        lines = [f"- [{f['layer']}] {f['content']}" for f in facts]
        from pds_ultimate.core.memory.token_budget import trim_to_budget

        return trim_to_budget(lines, budget_tokens)
