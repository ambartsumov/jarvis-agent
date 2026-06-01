"""Tests for the security layer: permissions, rate limiting, sandbox."""

from __future__ import annotations

import time

import pytest

from pds_ultimate.config import config
from pds_ultimate.core.security.permissions import PermissionEngine, PermissionMode
from pds_ultimate.core.security.rate_limit import RateLimiter


@pytest.fixture
def owner_id() -> int:
    return config.telegram.owner_id


class TestPermissionEngine:
    def test_owner_yolo_allows_high_risk(self, owner_id):
        eng = PermissionEngine()
        d = eng.check(owner_id, "shell_execute", "high")
        assert d.allowed and not d.sandboxed

    def test_stranger_strict_denies_high(self):
        eng = PermissionEngine()
        d = eng.check(424242, "shell_execute", "high")
        assert not d.allowed

    def test_stranger_strict_allows_low(self):
        eng = PermissionEngine()
        d = eng.check(424242, "read_file", "low")
        assert d.allowed

    def test_standard_blocks_high_allows_medium(self):
        eng = PermissionEngine()
        eng.set_mode(424242, PermissionMode.STANDARD)
        assert not eng.check(424242, "shell_execute", "high").allowed
        assert eng.check(424242, "write_file", "medium").allowed

    def test_sandbox_routes_high(self):
        eng = PermissionEngine()
        eng.set_mode(424242, PermissionMode.SANDBOX)
        d = eng.check(424242, "shell_execute", "high")
        assert d.allowed and d.sandboxed

    def test_unknown_risk_treated_as_high(self):
        eng = PermissionEngine()
        assert not eng.check(424242, "weird", "???").allowed


class TestRateLimiter:
    def test_owner_exempt(self, owner_id):
        rl = RateLimiter()
        for _ in range(50):
            allowed, _ = rl.allow_request(owner_id)
            assert allowed

    def test_stranger_throttled_after_burst(self):
        rl = RateLimiter()
        uid = 555001
        allowed_count = 0
        for _ in range(rl.burst + 5):
            allowed, _ = rl.allow_request(uid)
            if allowed:
                allowed_count += 1
        # Should allow at most burst tokens before throttling
        assert allowed_count <= rl.burst

    def test_token_budget_enforced(self):
        rl = RateLimiter()
        rl.daily_token_budget = 100
        uid = 555002
        rl.record_tokens(uid, 150)
        ok, _ = rl.check_token_budget(uid)
        assert not ok

    def test_token_budget_resets_after_day(self):
        rl = RateLimiter()
        rl.daily_token_budget = 100
        uid = 555003
        rl.record_tokens(uid, 150)
        b = rl._bucket(uid)
        b.day_start = time.time() - 90000  # >24h ago
        ok, _ = rl.check_token_budget(uid)
        assert ok
