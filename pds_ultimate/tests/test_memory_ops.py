"""Tests for memory pruning, forgetting, BM25 removal."""

from __future__ import annotations

import pytest

from pds_ultimate.core.memory.bm25 import BM25Index
from pds_ultimate.core.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "mem.db"
    monkeypatch.setattr("pds_ultimate.core.memory.store.DATABASE_PATH", db)
    return MemoryStore()


class TestBM25Removal:
    def test_remove_drops_doc(self):
        idx = BM25Index()
        idx.add("1", "alpha beta gamma")
        idx.add("2", "delta epsilon")
        assert idx.search("alpha")
        assert idx.remove("1")
        assert not any(d == "1" for d, _ in idx.search("alpha"))

    def test_remove_missing_returns_false(self):
        idx = BM25Index()
        idx.add("1", "alpha")
        assert not idx.remove("999")


class TestPrune:
    def test_prune_caps_facts(self, store):
        uid = 1001
        for i in range(20):
            store.remember(uid, f"fact number {i}", importance=0.1 + i * 0.01)
        removed = store.prune(uid, max_facts=10)
        assert removed == 10
        remaining = store.recall(uid, limit=100)
        assert len(remaining) == 10

    def test_prune_keeps_important(self, store):
        uid = 1002
        store.remember(uid, "low importance fact", importance=0.1)
        store.remember(uid, "critical important fact", importance=0.99)
        for i in range(15):
            store.remember(uid, f"filler {i}", importance=0.2)
        store.prune(uid, max_facts=5)
        contents = " ".join(f["content"] for f in store.recall(uid, limit=100))
        assert "critical" in contents

    def test_prune_noop_under_limit(self, store):
        uid = 1003
        store.remember(uid, "only one")
        assert store.prune(uid, max_facts=10) == 0


class TestForget:
    def test_forget_removes_matching(self, store):
        uid = 2001
        store.remember(uid, "my secret password is hunter2")
        store.remember(uid, "favorite color is blue")
        removed = store.forget(uid, "password")
        assert removed >= 1
        contents = " ".join(f["content"] for f in store.recall(uid, limit=100))
        assert "password" not in contents

    def test_forget_isolated_per_user(self, store):
        store.remember(3001, "user A confidential note")
        store.remember(3002, "user B confidential note")
        store.forget(3001, "confidential")
        assert store.recall(3002, limit=100)  # user B's memory intact

    def test_forget_empty_query(self, store):
        assert store.forget(4001, "") == 0
