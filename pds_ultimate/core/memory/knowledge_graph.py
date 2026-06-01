"""
Knowledge Graph — entity-relationship memory for the AI agent.

Stores: People, Places, Projects, Topics as nodes.
Stores: relationships (knows, works_at, related_to, mentioned_with, etc.) as edges.
Backed by SQLite (same DB as MemoryStore) for zero extra deps.

Used by the agent to:
- Recall everything known about a person ("tell me about Slava")
- Discover relationship paths ("how is X connected to project Y")
- Auto-extract entities from conversation and link them
- Build contact/project intelligence over time
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

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


class _KGBase(DeclarativeBase):
    pass


class KGNode(_KGBase):
    """Entity node: person, place, project, concept."""
    __tablename__ = "kg_nodes"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True, default="entity")
    # kind: person | place | project | topic | company | event
    attributes: Mapped[str] = mapped_column(Text, default="{}")  # JSON dict
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class KGEdge(_KGBase):
    """Directional relationship between two entity nodes."""
    __tablename__ = "kg_edges"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    from_id: Mapped[int] = mapped_column(Integer, index=True)
    to_id: Mapped[int] = mapped_column(Integer, index=True)
    relation: Mapped[str] = mapped_column(String(128))
    # relation examples: knows, works_at, manages, related_to, mentioned_with,
    #                    member_of, owns, located_in, scheduled_for
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    context: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class KnowledgeGraph:
    """
    Entity-relationship graph for agent long-term intelligence.
    Thread-safe writes via SQLAlchemy session.
    """

    def __init__(self) -> None:
        self.engine = create_engine(
            f"sqlite:///{DATABASE_PATH}",
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _record) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        _KGBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    # ── Node operations ──────────────────────────────────────────────────────

    def upsert_entity(
        self,
        user_id: int,
        name: str,
        kind: str = "entity",
        attributes: dict | None = None,
        importance: float = 0.5,
    ) -> int:
        """Create or update an entity node. Returns node id."""
        name_low = name.strip()
        with self.Session() as session:
            existing = session.scalar(
                select(KGNode).where(
                    KGNode.user_id == user_id,
                    KGNode.name == name_low,
                )
            )
            now = datetime.now(timezone.utc)
            if existing:
                existing.mention_count += 1
                existing.importance = min(1.0, existing.importance + 0.03)
                existing.updated_at = now
                if attributes:
                    current = json.loads(existing.attributes or "{}")
                    current.update(attributes)
                    existing.attributes = json.dumps(
                        current, ensure_ascii=False)
                session.commit()
                return existing.id

            node = KGNode(
                user_id=user_id,
                name=name_low,
                kind=kind,
                attributes=json.dumps(attributes or {}, ensure_ascii=False),
                importance=importance,
            )
            session.add(node)
            session.commit()
            session.refresh(node)
            logger.debug(f"KG: new entity [{kind}] '{name_low}' id={node.id}")
            return node.id

    def add_relation(
        self,
        user_id: int,
        from_name: str,
        to_name: str,
        relation: str,
        context: str = "",
        weight: float = 1.0,
        from_kind: str = "entity",
        to_kind: str = "entity",
    ) -> None:
        """Add a directed relationship. Auto-creates entities if missing."""
        from_id = self.upsert_entity(user_id, from_name, kind=from_kind)
        to_id = self.upsert_entity(user_id, to_name, kind=to_kind)
        with self.Session() as session:
            # Upsert edge: if same relation exists, increase weight
            existing = session.scalar(
                select(KGEdge).where(
                    KGEdge.user_id == user_id,
                    KGEdge.from_id == from_id,
                    KGEdge.to_id == to_id,
                    KGEdge.relation == relation,
                )
            )
            if existing:
                existing.weight = min(10.0, existing.weight + weight)
                if context:
                    existing.context = context[:500]
                session.commit()
            else:
                edge = KGEdge(
                    user_id=user_id,
                    from_id=from_id,
                    to_id=to_id,
                    relation=relation,
                    weight=weight,
                    context=context[:500],
                )
                session.add(edge)
                session.commit()

    # ── Recall operations ────────────────────────────────────────────────────

    def get_entity(self, user_id: int, name: str) -> dict | None:
        with self.Session() as session:
            node = session.scalar(
                select(KGNode).where(
                    KGNode.user_id == user_id,
                    KGNode.name == name.strip(),
                )
            )
            if not node:
                return None
            return {
                "id": node.id,
                "name": node.name,
                "kind": node.kind,
                "attributes": json.loads(node.attributes or "{}"),
                "importance": node.importance,
                "mentions": node.mention_count,
                "updated": node.updated_at.isoformat()[:16],
            }

    def get_relations(self, user_id: int, entity_name: str) -> list[dict]:
        """All edges from/to this entity."""
        with self.Session() as session:
            node = session.scalar(
                select(KGNode).where(
                    KGNode.user_id == user_id,
                    KGNode.name == entity_name.strip(),
                )
            )
            if not node:
                return []

            out_edges = session.scalars(
                select(KGEdge).where(
                    KGEdge.user_id == user_id,
                    KGEdge.from_id == node.id,
                )
            ).all()
            in_edges = session.scalars(
                select(KGEdge).where(
                    KGEdge.user_id == user_id,
                    KGEdge.to_id == node.id,
                )
            ).all()

            # Resolve target names
            all_ids = {e.to_id for e in out_edges} | {
                e.from_id for e in in_edges}
            id_to_name: dict[int, str] = {}
            if all_ids:
                nodes = session.scalars(
                    select(KGNode).where(KGNode.id.in_(all_ids))
                ).all()
                id_to_name = {n.id: n.name for n in nodes}

            results = []
            for e in out_edges:
                results.append({
                    "direction": "→",
                    "from": entity_name,
                    "relation": e.relation,
                    "to": id_to_name.get(e.to_id, str(e.to_id)),
                    "weight": e.weight,
                    "context": e.context[:200],
                })
            for e in in_edges:
                results.append({
                    "direction": "←",
                    "from": id_to_name.get(e.from_id, str(e.from_id)),
                    "relation": e.relation,
                    "to": entity_name,
                    "weight": e.weight,
                    "context": e.context[:200],
                })
            return sorted(results, key=lambda x: -x["weight"])

    def search_entities(self, user_id: int, query: str, limit: int = 10) -> list[dict]:
        """Fuzzy search entities by name (substring)."""
        q_low = query.strip().lower()
        with self.Session() as session:
            rows = session.scalars(
                select(KGNode)
                .where(KGNode.user_id == user_id)
                .order_by(KGNode.importance.desc(), KGNode.mention_count.desc())
            ).all()
            matches = [
                r for r in rows if q_low in r.name.lower()
            ][:limit]
            return [
                {
                    "name": r.name,
                    "kind": r.kind,
                    "mentions": r.mention_count,
                    "importance": round(r.importance, 2),
                    "attributes": json.loads(r.attributes or "{}"),
                }
                for r in matches
            ]

    def full_profile(self, user_id: int, entity_name: str) -> str:
        """Return a formatted text profile: entity + all relations + attributes."""
        entity = self.get_entity(user_id, entity_name)
        if not entity:
            return f"Entity '{entity_name}' not found in knowledge graph."
        relations = self.get_relations(user_id, entity_name)
        lines = [
            f"[{entity['kind'].upper()}] {entity['name']}",
            f"  importance={entity['importance']:.2f}, mentions={entity['mentions']}",
        ]
        if entity["attributes"]:
            for k, v in entity["attributes"].items():
                lines.append(f"  {k}: {v}")
        if relations:
            lines.append("  Связи:")
            for r in relations[:20]:
                arrow = r["direction"]
                if arrow == "→":
                    lines.append(
                        f"    {entity_name} —[{r['relation']}]→ {r['to']}")
                else:
                    lines.append(
                        f"    {r['from']} —[{r['relation']}]→ {entity_name}")
        return "\n".join(lines)

    def auto_extract_and_link(
        self,
        user_id: int,
        text: str,
        source_entity: str | None = None,
    ) -> list[str]:
        """
        Heuristic entity extraction from text.
        Finds: @usernames, capitalized words (names), URLs, phone numbers.
        Returns list of extracted entity names.
        """
        found: list[str] = []

        # Telegram usernames
        for m in re.findall(r"@[\w]{3,}", text):
            self.upsert_entity(user_id, m, kind="person")
            found.append(m)

        # URLs → domain as entity
        for m in re.findall(r"https?://([^/\s]+)", text):
            self.upsert_entity(user_id, m, kind="place")
            found.append(m)

        # Capitalised Russian words (likely proper nouns)
        for m in re.findall(r"[А-ЯЁ][а-яё]{2,}", text):
            if len(m) > 3:
                self.upsert_entity(user_id, m, kind="entity", importance=0.3)
                found.append(m)

        # If source entity, link all found to it
        if source_entity and found:
            for target in found[:10]:
                self.add_relation(user_id, source_entity,
                                  target, "mentioned_with", context=text[:200])

        return found

    def list_important(self, user_id: int, limit: int = 20) -> list[dict]:
        """Top entities by importance × mention_count."""
        with self.Session() as session:
            rows = session.scalars(
                select(KGNode)
                .where(KGNode.user_id == user_id)
                .order_by((KGNode.importance * KGNode.mention_count).desc())
                .limit(limit)
            ).all()
            return [
                {
                    "name": r.name,
                    "kind": r.kind,
                    "mentions": r.mention_count,
                    "importance": round(r.importance, 2),
                }
                for r in rows
            ]


# ── Singleton ──────────────────────────────────────────────────────────────
knowledge_graph = KnowledgeGraph()
