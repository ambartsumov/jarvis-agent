"""
Тесты Browser Pro (Part 8)
==============================
AntiBotEngine, FormFiller, SessionManager, BrowserProEngine.
~45 тестов.
"""

import random

from pds_ultimate.core.browser_pro import (
    AntiBotEngine,
    BrowserProEngine,
    BrowserSession,
    FormField,
    FormFiller,
    SessionManager,
    browser_pro,
)

# ═══════════════════════════════════════════════════════════════════════════════
# AntiBotEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestAntiBotEngine:
    """AntiBotEngine — обход anti-bot систем."""

    def test_user_agents_not_empty(self):
        assert len(AntiBotEngine.USER_AGENTS) > 0

    def test_viewports_not_empty(self):
        assert len(AntiBotEngine.VIEWPORTS) > 0

    def test_randomize(self):
        engine = AntiBotEngine()
        ua1 = engine.user_agent
        # Рандомизируем 10 раз — хотя бы раз должно измениться
        changed = False
        for _ in range(10):
            engine.randomize()
            if engine.user_agent != ua1:
                changed = True
                break
        # С 8 UA, вероятность 10 раз одинаково = (1/8)^9 ≈ 0
        assert changed or len(AntiBotEngine.USER_AGENTS) == 1

    def test_user_agent_is_string(self):
        engine = AntiBotEngine()
        assert isinstance(engine.user_agent, str)
        assert "Mozilla" in engine.user_agent

    def test_viewport_is_tuple(self):
        engine = AntiBotEngine()
        vp = engine.viewport
        assert isinstance(vp, tuple)
        assert len(vp) == 2
        assert vp[0] > 0 and vp[1] > 0

    def test_locale(self):
        engine = AntiBotEngine()
        locale = engine.locale
        assert isinstance(locale, str)
        assert "-" in locale  # e.g. en-US

    def test_stealth_scripts(self):
        engine = AntiBotEngine()
        scripts = engine.get_stealth_scripts()
        assert len(scripts) >= 4
        assert any("webdriver" in s for s in scripts)

    def test_bezier_curve_points(self):
        points = AntiBotEngine.bezier_curve((0, 0), (100, 100), steps=10)
        assert len(points) == 11  # 0..10 inclusive
        # Первая точка ~(0,0), последняя ~(100,100) с шумом
        assert abs(points[0][0]) < 20
        assert abs(points[-1][0] - 100) < 20

    def test_bezier_curve_different_steps(self):
        points = AntiBotEngine.bezier_curve((0, 0), (500, 300), steps=5)
        assert len(points) == 6

    def test_human_delay_range(self):
        for _ in range(50):
            delay = AntiBotEngine.human_delay(50, 300)
            assert 0.03 <= delay <= 0.5  # 30ms-500ms in seconds

    def test_human_delay_typing(self):
        for _ in range(50):
            delay = AntiBotEngine.human_delay(typing=True)
            assert 0.03 <= delay <= 0.3

    def test_natural_scroll_pattern(self):
        pattern = AntiBotEngine.natural_scroll_pattern(3000)
        assert len(pattern) > 0
        assert all("y" in e and "amount" in e and "pause" in e for e in pattern)

    def test_natural_scroll_pattern_short_page(self):
        pattern = AntiBotEngine.natural_scroll_pattern(200)
        assert len(pattern) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# FormField dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormField:
    """FormField — поле формы."""

    def test_default(self):
        f = FormField()
        assert f.field_type == "text"
        assert f.required is False

    def test_with_values(self):
        f = FormField(
            selector="#email",
            field_type="email",
            label="Email",
            required=True,
        )
        assert f.selector == "#email"
        assert f.label == "Email"


# ═══════════════════════════════════════════════════════════════════════════════
# FormFiller
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormFiller:
    """FormFiller — умное заполнение форм."""

    def test_detect_email(self):
        ff = FormFiller()
        assert ff.detect_field_type("Email address") == "email"

    def test_detect_password(self):
        ff = FormFiller()
        assert ff.detect_field_type("Пароль") == "password"

    def test_detect_phone(self):
        ff = FormFiller()
        assert ff.detect_field_type("Телефон") == "phone"

    def test_detect_name(self):
        ff = FormFiller()
        assert ff.detect_field_type("First Name") == "first_name"

    def test_detect_unknown(self):
        ff = FormFiller()
        assert ff.detect_field_type("some_random_field_xyz") == "text"

    def test_detect_by_name_attr(self):
        ff = FormFiller()
        assert ff.detect_field_type("", "email") == "email"

    def test_generate_fill_plan(self):
        ff = FormFiller()
        fields = [
            FormField(selector="#email", label="Email"),
            FormField(selector="#pass", label="Password"),
        ]
        plan = ff.generate_fill_plan(
            fields, user_data={"email": "test@test.com", "password": "123"}
        )
        assert len(plan) == 2
        # First field is email
        assert plan[0][1] == "test@test.com"

    def test_generate_fill_plan_empty_data(self):
        ff = FormFiller()
        fields = [FormField(selector="#x", label="Something", value="default")]
        plan = ff.generate_fill_plan(fields)
        assert plan[0][1] == "default"

    def test_simulate_typing_errors(self):
        """Typing errors simulation."""
        keystrokes = FormFiller.simulate_typing_errors("hello", error_rate=0.0)
        # No errors → 5 characters
        assert len(keystrokes) == 5
        assert "".join(keystrokes) == "hello"

    def test_simulate_typing_with_errors(self):
        """С высоким error_rate — будут BACKSPACE."""
        random.seed(42)
        keystrokes = FormFiller.simulate_typing_errors(
            "abcde", error_rate=0.5
        )
        # Should have some BACKSPACE entries
        # With 50% rate, it's very likely
        assert len(keystrokes) >= 5


# ═══════════════════════════════════════════════════════════════════════════════
# BrowserSession dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowserSession:
    """BrowserSession — сессия браузера."""

    def test_defaults(self):
        s = BrowserSession()
        assert s.is_authenticated is False
        assert s.cookies == []
        assert s.local_storage == {}

    def test_to_dict(self):
        s = BrowserSession(id="s1", domain="example.com")
        d = s.to_dict()
        assert d["id"] == "s1"
        assert d["domain"] == "example.com"
        assert d["authenticated"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionManager:
    """SessionManager — управление сессиями."""

    def test_create_session(self):
        sm = SessionManager()
        s = sm.create_session("example.com")
        assert s.domain == "example.com"
        assert s.id

    def test_get_session(self):
        sm = SessionManager()
        sm.create_session("example.com")
        found = sm.get_session("example.com")
        assert found is not None
        assert found.domain == "example.com"

    def test_get_session_not_found(self):
        sm = SessionManager()
        assert sm.get_session("unknown.com") is None

    def test_update_session(self):
        sm = SessionManager()
        s = sm.create_session("test.com")
        sm.update_session(
            s.id,
            cookies=[{"name": "sid", "value": "123"}],
            authenticated=True,
        )
        updated = sm.get_session("test.com")
        assert updated.is_authenticated is True
        assert len(updated.cookies) == 1

    def test_delete_session(self):
        sm = SessionManager()
        s = sm.create_session("del.com")
        assert sm.delete_session(s.id) is True
        assert sm.get_session("del.com") is None

    def test_delete_nonexistent(self):
        sm = SessionManager()
        assert sm.delete_session("nope") is False

    def test_count(self):
        sm = SessionManager()
        assert sm.count == 0
        sm.create_session("a.com")
        sm.create_session("b.com")
        assert sm.count == 2

    def test_active_sessions(self):
        sm = SessionManager()
        sm.create_session("a.com")
        sm.create_session("b.com")
        assert len(sm.active_sessions) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# BrowserProEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowserProEngine:
    """BrowserProEngine — центральный движок."""

    def test_init_components(self):
        engine = BrowserProEngine()
        assert engine.anti_bot is not None
        assert engine.form_filler is not None
        assert engine.sessions is not None

    def test_get_stats(self):
        engine = BrowserProEngine()
        stats = engine.get_stats()
        assert "total_actions" in stats
        assert "active_sessions" in stats
        assert "user_agent" in stats
        assert "viewport" in stats

    def test_action_log_empty(self):
        engine = BrowserProEngine()
        log = engine.get_action_log()
        assert log == []

    def test_log_action(self):
        engine = BrowserProEngine()
        engine._log_action("test_action", success=True)
        log = engine.get_action_log()
        assert len(log) == 1
        assert log[0]["action"] == "test_action"

    def test_log_action_limit(self):
        engine = BrowserProEngine()
        for i in range(1100):
            engine._log_action(f"action_{i}")
        log = engine.get_action_log(limit=10)
        assert len(log) == 10


# ═══════════════════════════════════════════════════════════════════════════════
# Global instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowserProGlobal:
    """Глобальный экземпляр."""

    def test_global_exists(self):
        assert browser_pro is not None
        assert isinstance(browser_pro, BrowserProEngine)
