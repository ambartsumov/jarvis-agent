"""
Тесты для Performance Engine.
================================
Покрывает: ResultCache, RequestDeduplicator,
BatchAPIProcessor, PerformanceMonitor, PerformanceEngine.
"""

import time

import pytest

from pds_ultimate.core.performance_engine import (
    BatchAPIProcessor,
    CacheEntry,
    CacheStats,
    PerformanceEngine,
    PerformanceMetrics,
    PerformanceMonitor,
    RequestDeduplicator,
    ResultCache,
    performance_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# CACHE ENTRY
# ═══════════════════════════════════════════════════════════════════════════════


class TestCacheEntry:
    def test_not_expired(self):
        entry = CacheEntry(
            key="k", value="v",
            created_at=time.time(),
            expires_at=time.time() + 100,
        )
        assert entry.is_expired is False

    def test_expired(self):
        entry = CacheEntry(
            key="k", value="v",
            created_at=time.time() - 200,
            expires_at=time.time() - 100,
        )
        assert entry.is_expired is True

    def test_age(self):
        entry = CacheEntry(
            key="k", value="v",
            created_at=time.time() - 10,
            expires_at=time.time() + 100,
        )
        assert entry.age >= 10


class TestCacheStats:
    def test_hit_rate_zero(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_100(self):
        s = CacheStats(hits=10, misses=0)
        assert s.hit_rate == 1.0

    def test_hit_rate_50(self):
        s = CacheStats(hits=5, misses=5)
        assert s.hit_rate == 0.5

    def test_to_dict(self):
        s = CacheStats(hits=3, misses=7, evictions=1, size=10, max_size=100)
        d = s.to_dict()
        assert d["hits"] == 3
        assert d["misses"] == 7
        assert "hit_rate" in d


# ═══════════════════════════════════════════════════════════════════════════════
# RESULT CACHE
# ═══════════════════════════════════════════════════════════════════════════════


class TestResultCache:
    """Тесты ResultCache — TTL + LRU кэш."""

    def setup_method(self):
        self.cache = ResultCache(max_size=10, default_ttl=300)

    # ─── Базовые операции ────────────────────────────────────────────

    def test_put_get(self):
        self.cache.put("key1", "value1")
        assert self.cache.get("key1") == "value1"

    def test_get_miss(self):
        assert self.cache.get("nonexistent") is None

    def test_expired_entry(self):
        self.cache.put("key1", "value1", ttl=0.001)
        time.sleep(0.01)
        assert self.cache.get("key1") is None

    def test_overwrite(self):
        self.cache.put("key1", "v1")
        self.cache.put("key1", "v2")
        assert self.cache.get("key1") == "v2"

    # ─── LRU Eviction ───────────────────────────────────────────────

    def test_lru_eviction(self):
        cache = ResultCache(max_size=3, default_ttl=300)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        cache.put("k4", "v4")  # Вытеснит k1
        assert cache.get("k1") is None
        assert cache.get("k4") == "v4"

    def test_lru_access_refreshes(self):
        cache = ResultCache(max_size=3, default_ttl=300)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        cache.get("k1")  # Обновляем k1 (двигаем в конец)
        cache.put("k4", "v4")  # Вытеснит k2 (самый старый)
        assert cache.get("k1") == "v1"  # k1 выжил
        assert cache.get("k2") is None  # k2 вытеснен

    # ─── Invalidation ───────────────────────────────────────────────

    def test_invalidate(self):
        self.cache.put("key1", "value1")
        assert self.cache.invalidate("key1") is True
        assert self.cache.get("key1") is None

    def test_invalidate_missing(self):
        assert self.cache.invalidate("nonexistent") is False

    def test_invalidate_pattern(self):
        self.cache.put("tool:weather:moscow", "sunny")
        self.cache.put("tool:weather:london", "rainy")
        self.cache.put("llm:chat:123", "hello")
        count = self.cache.invalidate_pattern("tool:weather:")
        assert count == 2
        assert self.cache.get("llm:chat:123") == "hello"

    def test_invalidate_category(self):
        self.cache.put("k1", "v1", category="tool")
        self.cache.put("k2", "v2", category="tool")
        self.cache.put("k3", "v3", category="llm")
        count = self.cache.invalidate_category("tool")
        assert count == 2
        assert self.cache.get("k3") == "v3"

    def test_clear(self):
        self.cache.put("k1", "v1")
        self.cache.put("k2", "v2")
        self.cache.clear()
        assert self.cache.size == 0

    def test_cleanup_expired(self):
        self.cache.put("k1", "v1", ttl=0.001)
        self.cache.put("k2", "v2", ttl=300)
        time.sleep(0.01)
        count = self.cache.cleanup_expired()
        assert count == 1
        assert self.cache.get("k2") == "v2"

    # ─── Category TTL ───────────────────────────────────────────────

    def test_category_ttl(self):
        self.cache.put("t1", "v1", category="translation")
        entry = self.cache._cache["t1"]
        # Translation TTL = 3600s
        assert entry.expires_at - \
            entry.created_at == pytest.approx(3600, abs=1)

    # ─── Decorator ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cached_decorator(self):
        call_count = 0

        @self.cache.cached(ttl=60, category="test")
        async def expensive(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        r1 = await expensive(5)
        r2 = await expensive(5)
        assert r1 == 10
        assert r2 == 10
        assert call_count == 1  # Второй вызов из кэша

    @pytest.mark.asyncio
    async def test_cached_different_args(self):
        call_count = 0

        @self.cache.cached(ttl=60)
        async def func(x):
            nonlocal call_count
            call_count += 1
            return x

        await func(1)
        await func(2)
        assert call_count == 2  # Разные аргументы

    # ─── Stats ───────────────────────────────────────────────────────

    def test_stats_tracking(self):
        self.cache.put("k1", "v1")
        self.cache.get("k1")  # hit
        self.cache.get("k2")  # miss
        assert self.cache.stats.hits == 1
        assert self.cache.stats.misses == 1

    def test_get_stats(self):
        self.cache.put("k1", "v1", category="tool")
        stats = self.cache.get_stats()
        assert "categories" in stats
        assert "tool" in stats["categories"]


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST DEDUPLICATOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestDeduplicator:
    """Тесты RequestDeduplicator."""

    @pytest.mark.asyncio
    async def test_single_request(self):
        dedup = RequestDeduplicator()

        async def fetch():
            return 42

        result = await dedup.deduplicate("key1", fetch)
        assert result == 42

    @pytest.mark.asyncio
    async def test_dedup_count(self):
        dedup = RequestDeduplicator()
        assert dedup.dedup_count == 0

    @pytest.mark.asyncio
    async def test_error_propagation(self):
        dedup = RequestDeduplicator()

        async def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await dedup.deduplicate("key1", failing)

    @pytest.mark.asyncio
    async def test_inflight_count(self):
        dedup = RequestDeduplicator()
        assert dedup.inflight_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH API PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchAPIProcessor:
    """Тесты BatchAPIProcessor."""

    @pytest.mark.asyncio
    async def test_submit_and_process(self):
        results = []

        async def mock_llm(message, **kwargs):
            results.append(message)
            return f"reply: {message}"

        batch = BatchAPIProcessor(llm_call=mock_llm, window_ms=50)
        await batch.start()

        try:
            result = await batch.submit("hello")
            assert result == "reply: hello"
        finally:
            await batch.stop()

    @pytest.mark.asyncio
    async def test_batch_count(self):
        async def mock_llm(message, **kwargs):
            return "ok"

        batch = BatchAPIProcessor(llm_call=mock_llm, window_ms=50)
        await batch.start()
        try:
            await batch.submit("test")
            assert batch.batch_count >= 1
        finally:
            await batch.stop()

    @pytest.mark.asyncio
    async def test_queue_size(self):
        batch = BatchAPIProcessor(window_ms=5000)
        assert batch.queue_size == 0

    def test_get_stats(self):
        batch = BatchAPIProcessor()
        stats = batch.get_stats()
        assert "batch_count" in stats
        assert "queue_size" in stats
        assert "running" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE MONITOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerformanceMonitor:
    def test_record_request(self):
        mon = PerformanceMonitor()
        mon.record_request(10.0, cached=True)
        mon.record_request(50.0, cached=False)
        assert mon._metrics.total_requests == 2
        assert mon._metrics.cache_hits == 1

    def test_throughput(self):
        mon = PerformanceMonitor()
        mon.record_request(10.0)
        assert mon.throughput > 0

    def test_uptime(self):
        mon = PerformanceMonitor()
        assert mon.uptime >= 0

    def test_get_report(self):
        mon = PerformanceMonitor()
        mon.record_request(10.0)
        report = mon.get_report()
        assert "uptime_sec" in report
        assert "throughput_rps" in report


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE METRICS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerformanceMetrics:
    def test_record_latency(self):
        m = PerformanceMetrics()
        m.record_latency(10.0)
        m.record_latency(20.0)
        assert m.avg_latency_ms == 15.0

    def test_to_dict(self):
        m = PerformanceMetrics()
        m.total_requests = 5
        d = m.to_dict()
        assert d["total_requests"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE ENGINE (orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerformanceEngine:
    """Тесты PerformanceEngine — главный оркестратор."""

    @pytest.mark.asyncio
    async def test_cached_call_miss(self):
        engine = PerformanceEngine()
        call_count = 0

        async def fetch():
            nonlocal call_count
            call_count += 1
            return "data"

        result = await engine.cached_call("key1", fetch)
        assert result == "data"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_cached_call_hit(self):
        engine = PerformanceEngine()

        async def fetch():
            return "data"

        r1 = await engine.cached_call("key1", fetch, category="tool")
        r2 = await engine.cached_call("key1", fetch, category="tool")
        assert r1 == r2

    @pytest.mark.asyncio
    async def test_start_stop(self):
        engine = PerformanceEngine()
        await engine.start()
        await engine.stop()

    def test_get_stats(self):
        engine = PerformanceEngine()
        stats = engine.get_stats()
        assert "cache" in stats
        assert "dedup" in stats
        assert "batch" in stats
        assert "performance" in stats

    def test_properties(self):
        engine = PerformanceEngine()
        assert isinstance(engine.cache, ResultCache)
        assert isinstance(engine.dedup, RequestDeduplicator)
        assert isinstance(engine.batch, BatchAPIProcessor)
        assert isinstance(engine.monitor, PerformanceMonitor)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalPerformanceEngine:
    def test_exists(self):
        assert performance_engine is not None
        assert isinstance(performance_engine, PerformanceEngine)
