"""PDS memory MCP server — world-class agent memory for OpenManus."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PDS_ROOT = Path(os.environ.get("PDS_ULTIMATE_DIR",
                Path(__file__).resolve().parents[2]))
AGENT_ROOT = PDS_ROOT.parent
for p in (str(AGENT_ROOT), str(PDS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

mcp = FastMCP("pds-memory")

_memory_inst = None
_lessons_inst = None


def _get_memory():
    global _memory_inst
    if _memory_inst is None:
        from pds_ultimate.core.memory.hierarchy import hierarchical_memory
        _memory_inst = hierarchical_memory
    return _memory_inst


def _get_store():
    return _get_memory().store


def _get_lessons():
    global _lessons_inst
    if _lessons_inst is None:
        from pds_ultimate.core.agent.lessons import lesson_book
        _lessons_inst = lesson_book
    return _lessons_inst


def _uid(user_id: int | None) -> int:
    if user_id and user_id > 0:
        return int(user_id)
    return int(os.environ.get("PDS_DEFAULT_USER_ID", "0") or 0)


# ── Core memory tools ─────────────────────────────────────────────────────────

@mcp.tool()
def remember(
    content: str,
    user_id: int = 0,
    key: str = "",
    importance: float = 0.8,
) -> str:
    """
    Save a fact to long-term semantic memory.
    Use for: preferences, instructions, people, tasks, decisions, anything worth keeping.
    importance: 0.5=normal, 0.8=important, 1.0=critical (never forget).
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    if not content.strip():
        return json.dumps({"ok": False, "error": "empty content"})
    mid = _get_memory().remember_fact(
        uid, content.strip(), key=key, importance=importance)
    return json.dumps({"ok": True, "id": mid, "user_id": uid})


@mcp.tool()
def remember_episode(
    summary: str,
    user_id: int = 0,
    importance: float = 0.7,
) -> str:
    """
    Save an episodic memory — a summary of what happened in this session/conversation.
    Use after completing a task or at end of conversation to preserve context.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    mid = _get_memory().remember_fact(
        uid, summary.strip(), key="episode", layer="episodic", importance=importance
    )
    return json.dumps({"ok": True, "id": mid, "layer": "episodic"})


@mcp.tool()
def recall(query: str = "", user_id: int = 0, limit: int = 8) -> str:
    """
    Recall relevant facts from long-term memory (BM25 + recency + importance score).
    query: what you're looking for. Leave empty to get most important recent facts.
    Returns facts ranked by relevance + recency + importance.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "facts": [], "error": "user_id required"})
    rows = _get_memory().recall(uid, query=query, limit=limit)
    return json.dumps({"ok": True, "facts": rows}, ensure_ascii=False)


@mcp.tool()
def recall_recent(user_id: int = 0, hours: int = 24, limit: int = 20) -> str:
    """
    Recall memories from the last N hours — temporal/episodic recall.
    Use for: 'что я делал сегодня', 'вчерашние задачи', recent context.
    hours: how far back to look (default 24 = today).
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "facts": [], "error": "user_id required"})
    rows = _get_store().recall_recent(uid, hours=hours, limit=limit)
    return json.dumps({"ok": True, "hours": hours, "facts": rows}, ensure_ascii=False)


@mcp.tool()
def recall_about(entity: str, user_id: int = 0, limit: int = 10) -> str:
    """
    Recall everything known about a specific person, place, or project.
    entity: name of the person/place/project (e.g. 'Слава', 'проект X', 'Google').
    Use before meetings, before contacting someone, to get full context.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "facts": [], "error": "user_id required"})
    rows = _get_store().recall_about_entity(uid, entity, limit=limit)
    return json.dumps({"ok": True, "entity": entity, "facts": rows}, ensure_ascii=False)


@mcp.tool()
def memory_search(query: str, user_id: int = 0, limit: int = 8) -> str:
    """Search semantic memory — alias for recall with a required query."""
    return recall(query=query, user_id=user_id, limit=limit)


@mcp.tool()
def forget(query: str, user_id: int = 0) -> str:
    """Forget facts matching query. Use when something is outdated or wrong."""
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "deleted": 0, "error": "user_id required"})
    n = _get_memory().forget(uid, query)
    return json.dumps({"ok": True, "deleted": n})


@mcp.tool()
def consolidate_memory(user_id: int = 0) -> str:
    """
    Run memory consolidation: remove near-duplicate facts, apply temporal decay.
    Call after long conversations or when memory feels cluttered.
    Returns how many duplicates were removed.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    store = _get_store()
    removed = store.consolidate(uid)
    store.apply_temporal_decay(uid)
    return json.dumps({"ok": True, "duplicates_removed": removed})


# ── Lesson memory ─────────────────────────────────────────────────────────────

@mcp.tool()
def recall_lessons(query: str, user_id: int = 0, limit: int = 5) -> str:
    """
    Recall past failure/success lessons relevant to the current task.
    Use before starting a complex task to learn from past mistakes.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "lessons": "", "error": "user_id required"})
    text = _get_lessons().recall(uid, query, limit=limit)
    return json.dumps({"ok": True, "lessons": text or ""}, ensure_ascii=False)


@mcp.tool()
def save_lesson(lesson: str, user_id: int = 0, outcome: str = "success") -> str:
    """
    Save a lesson learned from a task (success or failure).
    Use after completing/failing a task to improve future performance.
    outcome: 'success' or 'failure'
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    try:
        _get_lessons().add(uid, lesson.strip(), outcome=outcome)
        return json.dumps({"ok": True})
    except Exception:
        # Fallback: store as semantic memory
        mid = _get_memory().remember_fact(
            uid, f"[LESSON/{outcome.upper()}] {lesson}", key="lesson", importance=0.9
        )
        return json.dumps({"ok": True, "id": mid, "note": "stored as semantic"})


@mcp.tool()
def build_memory_context(query: str = "", user_id: int = 0) -> str:
    """Build compact memory context block for injection (working + episodic + semantic)."""
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "context": "", "error": "user_id required"})
    ctx = _get_memory().build_context(uid, query=query)
    return json.dumps({"ok": True, "context": ctx or ""}, ensure_ascii=False)


# ── Vector search ─────────────────────────────────────────────────────────────


@mcp.tool()
def vector_search(query: str, user_id: int = 0, limit: int = 10) -> str:
    """
    Semantic vector search over memory using TF-IDF cosine similarity.
    Returns memories semantically similar to the query, even without exact keyword matches.
    Use when recall() doesn't find what you need.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    try:
        from pds_ultimate.core.memory.vector_store import vector_index
        hits = vector_index.search(query, limit=limit)
        # Enrich with full content from store
        store = _get_store()
        with store.session_factory() as session:
            from pds_ultimate.core.memory.store import MemoryFact
            from sqlalchemy import select
            rows = {
                str(r.id): r
                for r in session.scalars(
                    select(MemoryFact).where(MemoryFact.user_id == uid)
                ).all()
            }
        results = []
        for doc_id, score in hits:
            row = rows.get(str(doc_id))
            if row:
                results.append({
                    "id": row.id,
                    "content": (row.compressed or row.content)[:400],
                    "layer": row.layer,
                    "score": round(score, 4),
                })
        return json.dumps({"ok": True, "results": results}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ── Knowledge Graph tools ─────────────────────────────────────────────────────


@mcp.tool()
def kg_profile(entity: str, user_id: int = 0) -> str:
    """
    Get full profile of an entity (person, project, place) from the knowledge graph.
    Returns all known attributes and relationships.
    Example: kg_profile('Иван Петров', user_id=123)
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    profile = _get_memory().kg_profile(uid, entity)
    return json.dumps({"ok": True, "profile": profile}, ensure_ascii=False)


@mcp.tool()
def kg_add_entity(name: str, kind: str = "entity", user_id: int = 0,
                  attributes: str = "{}") -> str:
    """
    Add or update an entity in the knowledge graph.
    kind: person | place | project | topic | company | event
    attributes: JSON string with any extra fields, e.g. '{"phone": "+7..."}'
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    try:
        attrs = json.loads(attributes) if attributes else {}
    except Exception:
        attrs = {}
    eid = _get_memory().kg_upsert_entity(uid, name, kind=kind, attributes=attrs)
    return json.dumps({"ok": True, "id": eid}, ensure_ascii=False)


@mcp.tool()
def kg_add_relation(from_name: str, to_name: str, relation: str,
                    user_id: int = 0, context: str = "") -> str:
    """
    Add a relationship between two entities.
    relation examples: knows, works_at, manages, member_of, related_to,
                       owns, located_in, scheduled_for, mentioned_with
    context: optional text snippet explaining the relationship.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    _get_memory().kg_add_relation(uid, from_name, to_name, relation, context=context)
    return json.dumps({"ok": True}, ensure_ascii=False)


@mcp.tool()
def kg_search(query: str, user_id: int = 0, limit: int = 10) -> str:
    """
    Search for entities in the knowledge graph by name (substring match).
    Returns entities sorted by importance × mentions.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    results = _get_memory().kg_search(uid, query, limit=limit)
    return json.dumps({"ok": True, "entities": results}, ensure_ascii=False)


@mcp.tool()
def kg_list_important(user_id: int = 0, limit: int = 20) -> str:
    """
    List the most important entities in the knowledge graph (people, projects, etc.).
    Sorted by importance score × mention count.
    """
    uid = _uid(user_id)
    if not uid:
        return json.dumps({"ok": False, "error": "user_id required"})
    results = _get_memory().kg_list_important(uid, limit=limit)
    return json.dumps({"ok": True, "entities": results}, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
