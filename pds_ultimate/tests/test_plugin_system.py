"""
Тесты Plugin System (Part 8)
=================================
Plugin Manager, API Detector, Rate Limiter, PluginConfig.
~50 тестов покрывающих основные компоненты.
"""


from pds_ultimate.core.plugin_system import (
    APIDetector,
    Plugin,
    PluginConfig,
    PluginEndpoint,
    PluginHealth,
    PluginManager,
    PluginStatus,
    PluginType,
    RateLimiter,
    plugin_manager,
)

# ═══════════════════════════════════════════════════════════════════════════════
# PluginType Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginType:
    """Enum PluginType — типы плагинов."""

    def test_rest_api_value(self):
        assert PluginType.REST_API.value == "rest_api"

    def test_llm_api_value(self):
        assert PluginType.LLM_API.value == "llm_api"

    def test_payment_api_value(self):
        assert PluginType.PAYMENT_API.value == "payment_api"

    def test_messaging_api_value(self):
        assert PluginType.MESSAGING_API.value == "messaging_api"

    def test_cloud_api_value(self):
        assert PluginType.CLOUD_API.value == "cloud_api"

    def test_webhook_value(self):
        assert PluginType.WEBHOOK.value == "webhook"

    def test_custom_func_value(self):
        assert PluginType.CUSTOM_FUNC.value == "custom_func"

    def test_database_value(self):
        assert PluginType.DATABASE.value == "database"

    def test_unknown_value(self):
        assert PluginType.UNKNOWN.value == "unknown"

    def test_total_types_count(self):
        """9 типов плагинов."""
        assert len(PluginType) == 9


# ═══════════════════════════════════════════════════════════════════════════════
# PluginStatus Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginStatus:
    """Enum PluginStatus — статусы плагинов."""

    def test_pending_value(self):
        assert PluginStatus.PENDING.value == "pending"

    def test_active_value(self):
        assert PluginStatus.ACTIVE.value == "active"

    def test_error_value(self):
        assert PluginStatus.ERROR.value == "error"

    def test_total_statuses(self):
        assert len(PluginStatus) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# PluginConfig dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginConfig:
    """PluginConfig — конфигурация плагина."""

    def test_create_minimal(self):
        cfg = PluginConfig(name="Test")
        assert cfg.name == "Test"
        assert cfg.plugin_type == PluginType.UNKNOWN

    def test_create_full(self):
        cfg = PluginConfig(
            name="MyAPI",
            plugin_type=PluginType.REST_API,
            base_url="https://api.example.com",
            api_key="key123",
            auth_type="bearer",
            rate_limit=100,
            timeout=15,
        )
        assert cfg.base_url == "https://api.example.com"
        assert cfg.api_key == "key123"
        assert cfg.rate_limit == 100
        assert cfg.timeout == 15

    def test_to_dict(self):
        cfg = PluginConfig(
            name="Test",
            plugin_type=PluginType.LLM_API,
            base_url="https://api.openai.com",
        )
        d = cfg.to_dict()
        assert d["name"] == "Test"
        assert d["plugin_type"] == "llm_api"
        assert d["base_url"] == "https://api.openai.com"

    def test_default_auth(self):
        cfg = PluginConfig(name="X")
        assert cfg.auth_type == "bearer"
        assert cfg.auth_header == "Authorization"

    def test_default_rate_limit(self):
        cfg = PluginConfig(name="X")
        assert cfg.rate_limit == 60

    def test_endpoints_default_empty(self):
        cfg = PluginConfig(name="X")
        assert cfg.endpoints == []


# ═══════════════════════════════════════════════════════════════════════════════
# PluginEndpoint dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginEndpoint:
    """PluginEndpoint — endpoint для REST API плагина."""

    def test_create_default(self):
        ep = PluginEndpoint()
        assert ep.method == "GET"
        assert ep.path == ""
        assert ep.response_format == "json"

    def test_create_post(self):
        ep = PluginEndpoint(method="POST", path="/v1/chat/completions")
        assert ep.method == "POST"
        assert ep.path == "/v1/chat/completions"


# ═══════════════════════════════════════════════════════════════════════════════
# PluginHealth dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginHealth:
    """PluginHealth — результат health check."""

    def test_healthy(self):
        h = PluginHealth(healthy=True, latency_ms=42, status_code=200)
        assert "✅" in h.status
        assert "42" in h.status

    def test_unhealthy(self):
        h = PluginHealth(healthy=False, error="Connection refused")
        assert "❌" in h.status
        assert "Connection refused" in h.status

    def test_defaults(self):
        h = PluginHealth()
        assert h.healthy is False
        assert h.latency_ms == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Plugin dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlugin:
    """Plugin — полный плагин."""

    def test_to_dict(self):
        cfg = PluginConfig(name="Test", plugin_type=PluginType.REST_API)
        p = Plugin(id="abc123", config=cfg, owner_id=42)
        d = p.to_dict()
        assert d["id"] == "abc123"
        assert d["name"] == "Test"
        assert d["type"] == "rest_api"
        assert d["owner_id"] == 42

    def test_default_status(self):
        cfg = PluginConfig(name="Test")
        p = Plugin(id="x", config=cfg)
        assert p.status == PluginStatus.PENDING

    def test_usage_count_default(self):
        cfg = PluginConfig(name="Test")
        p = Plugin(id="x", config=cfg)
        assert p.usage_count == 0
        assert p.error_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# APIDetector
# ═══════════════════════════════════════════════════════════════════════════════


class TestAPIDetector:
    """APIDetector — определение типа API из текста."""

    def test_detect_openai_key(self):
        text = "Мой ключ: sk-proj-abcdefghijklmnopqrstuvwxyz12345678901234567890"
        results = APIDetector.detect_from_text(text)
        assert len(results) >= 1
        found = [r for r in results if r.get("service") in (
            "OpenAI", "DeepSeek", "Generic API")]
        assert len(found) >= 1

    def test_detect_stripe_key(self):
        text = "sk_" + "live_" + "abcdefghijklmnopqrstuvwxyz"
        results = APIDetector.detect_from_text(text)
        stripe = [r for r in results if r["service"] == "Stripe"]
        assert len(stripe) >= 1

    def test_detect_sendgrid_key(self):
        text = "SG.abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyz12345678901ABCDE"
        results = APIDetector.detect_from_text(text)
        # SendGrid or at least generic detection
        assert len(results) >= 1

    def test_detect_google_key(self):
        text = "AIza" + "SyA1234567890abcdefghijklmnopqrstuv"
        results = APIDetector.detect_from_text(text)
        google = [r for r in results if r.get("service") == "Google"]
        assert len(google) >= 1

    def test_detect_aws_key(self):
        text = "AKIA" + "ABCDEFGHIJKLMNOP"
        results = APIDetector.detect_from_text(text)
        aws = [r for r in results if r["service"] == "AWS"]
        assert len(aws) >= 1

    def test_detect_url_openai(self):
        text = "Отправляй на https://api.openai.com/v1/chat"
        results = APIDetector.detect_from_text(text)
        oa = [r for r in results if r.get(
            "service") == "OpenAI" and "url" in r]
        assert len(oa) >= 1

    def test_detect_url_stripe(self):
        text = "https://api.stripe.com/v1/charges"
        results = APIDetector.detect_from_text(text)
        s = [r for r in results if r.get("service") == "Stripe"]
        assert len(s) >= 1

    def test_detect_empty(self):
        results = APIDetector.detect_from_text("")
        assert results == []

    def test_detect_no_keys(self):
        results = APIDetector.detect_from_text("Просто текст без ключей")
        assert len(results) == 0

    def test_detect_rest_api_url(self):
        text = "https://example.com/api/v1/users"
        results = APIDetector.detect_from_text(text)
        rest = [r for r in results if r.get("type") == PluginType.REST_API]
        assert len(rest) >= 1

    def test_get_service_info_openai(self):
        info = APIDetector.get_service_info("OpenAI")
        assert "OpenAI" in info["name"]
        assert "capabilities" in info
        assert "setup_guide" in info

    def test_get_service_info_unknown(self):
        info = APIDetector.get_service_info("UnknownService")
        assert "setup_guide" in info

    def test_get_service_info_stripe(self):
        info = APIDetector.get_service_info("Stripe")
        assert "Stripe" in info["name"]
        desc = info.get("description", "").lower()
        assert "платеж" in desc or "payment" in desc


# ═══════════════════════════════════════════════════════════════════════════════
# RateLimiter
# ═══════════════════════════════════════════════════════════════════════════════


class TestRateLimiter:
    """RateLimiter — per-plugin rate limiting."""

    def test_check_allows(self):
        rl = RateLimiter()
        assert rl.check("p1", limit=10) is True

    def test_check_blocks_after_limit(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.check("p1", limit=10)
        assert rl.check("p1", limit=10) is False

    def test_remaining_full(self):
        rl = RateLimiter()
        assert rl.remaining("p1", limit=60) == 60

    def test_remaining_decreases(self):
        rl = RateLimiter()
        rl.check("p1", limit=10)
        assert rl.remaining("p1", limit=10) == 9

    def test_reset(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.check("p1", limit=10)
        rl.reset("p1")
        assert rl.check("p1", limit=10) is True

    def test_independent_plugins(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("p1", limit=5)
        assert rl.check("p1", limit=5) is False
        assert rl.check("p2", limit=5) is True


# ═══════════════════════════════════════════════════════════════════════════════
# PluginManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginManager:
    """PluginManager — центральный менеджер плагинов."""

    def _make_manager(self) -> PluginManager:
        """Чистый менеджер для каждого теста."""
        pm = PluginManager()
        pm._plugins.clear()
        return pm

    def test_register_plugin(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="Test API", base_url="https://api.test.com")
        plugin = pm.register_plugin(cfg, owner_id=42)
        assert plugin.id
        assert plugin.config.name == "Test API"
        assert plugin.owner_id == 42
        assert plugin.status == PluginStatus.PENDING

    def test_unregister_plugin(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="ToRemove")
        plugin = pm.register_plugin(cfg)
        assert pm.unregister_plugin(plugin.id) is True
        assert pm.get_plugin(plugin.id) is None

    def test_unregister_nonexistent(self):
        pm = self._make_manager()
        assert pm.unregister_plugin("nonexistent") is False

    def test_get_plugin(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="Findme")
        plugin = pm.register_plugin(cfg)
        found = pm.get_plugin(plugin.id)
        assert found is not None
        assert found.config.name == "Findme"

    def test_get_by_name(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="MySpecialPlugin")
        pm.register_plugin(cfg)
        found = pm.get_by_name("MySpecialPlugin")
        assert found is not None

    def test_get_by_name_case_insensitive(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="TestPlugin")
        pm.register_plugin(cfg)
        found = pm.get_by_name("testplugin")
        assert found is not None

    def test_get_user_plugins(self):
        pm = self._make_manager()
        cfg1 = PluginConfig(name="P1")
        cfg2 = PluginConfig(name="P2")
        cfg3 = PluginConfig(name="P3")
        pm.register_plugin(cfg1, owner_id=1)
        pm.register_plugin(cfg2, owner_id=1)
        pm.register_plugin(cfg3, owner_id=2)
        user1 = pm.get_user_plugins(1)
        assert len(user1) == 2

    def test_count_property(self):
        pm = self._make_manager()
        assert pm.count == 0
        cfg = PluginConfig(name="X")
        pm.register_plugin(cfg)
        assert pm.count == 1

    def test_active_count(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="Active")
        plugin = pm.register_plugin(cfg)
        assert pm.active_count == 0
        plugin.status = PluginStatus.ACTIVE
        assert pm.active_count == 1

    def test_get_active_plugins(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="A")
        p = pm.register_plugin(cfg)
        p.status = PluginStatus.ACTIVE
        active = pm.get_active_plugins()
        assert len(active) == 1

    def test_detect_from_message(self):
        pm = self._make_manager()
        results = pm.detect_from_message(
            "sk_" + "live_" + "testkey123456789012345678")
        assert len(results) >= 1

    def test_get_onboarding_text_general(self):
        pm = self._make_manager()
        text = pm.get_onboarding_text()
        assert "API" in text
        assert len(text) > 100

    def test_get_onboarding_text_specific(self):
        pm = self._make_manager()
        text = pm.get_onboarding_text("OpenAI")
        assert "OpenAI" in text

    def test_make_tool_name(self):
        pm = self._make_manager()
        name = pm._make_tool_name("My Test Plugin")
        assert name.startswith("plugin_")
        assert "my" in name or "test" in name

    def test_get_stats_empty(self):
        pm = self._make_manager()
        stats = pm.get_stats()
        assert stats["total"] == 0
        assert stats["active"] == 0

    def test_get_stats_with_plugins(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="Stats", plugin_type=PluginType.REST_API)
        p = pm.register_plugin(cfg)
        p.status = PluginStatus.ACTIVE
        p.usage_count = 5
        stats = pm.get_stats()
        assert stats["total"] == 1
        assert stats["active"] == 1
        assert stats["total_usage"] == 5

    def test_build_headers_bearer(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="X", api_key="mykey", auth_type="bearer")
        headers = pm._build_headers(cfg)
        assert "Bearer mykey" in headers.get("Authorization", "")

    def test_build_headers_api_key(self):
        pm = self._make_manager()
        cfg = PluginConfig(name="X", api_key="mykey", auth_type="api_key")
        headers = pm._build_headers(cfg)
        assert headers.get("Authorization") == "mykey"

    def test_build_headers_basic(self):
        pm = self._make_manager()
        cfg = PluginConfig(
            name="X", api_key="user", api_secret="pass", auth_type="basic"
        )
        headers = pm._build_headers(cfg)
        assert headers.get("Authorization", "").startswith("Basic ")


# ═══════════════════════════════════════════════════════════════════════════════
# Global instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestPluginManagerGlobal:
    """Глобальный экземпляр plugin_manager."""

    def test_global_instance_exists(self):
        assert plugin_manager is not None
        assert isinstance(plugin_manager, PluginManager)

    def test_global_has_plugins_dir(self):
        assert plugin_manager.PLUGINS_DIR.exists()
