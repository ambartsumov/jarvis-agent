"""Token-bucket rate limiter — per-user request throttling + daily token budget."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pds_ultimate.config import config, logger


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    # daily token accounting
    day_start: float = field(default_factory=time.time)
    tokens_used_today: int = 0


class RateLimiter:
    """
    Two-layer protection:
    1. Request rate (token bucket): refill `rate` req/sec, capacity `burst`.
    2. Daily LLM-token budget per user.
    Owner is exempt from request throttling but still tracked for stats.
    """

    def __init__(self) -> None:
        self._buckets: dict[int, _Bucket] = {}
        self.rate = config.limits.requests_per_second
        self.burst = config.limits.burst
        self.daily_token_budget = config.limits.daily_token_budget
        self._owner_id = config.telegram.owner_id

    def _bucket(self, user_id: int) -> _Bucket:
        if user_id not in self._buckets:
            self._buckets[user_id] = _Bucket(tokens=self.burst, last_refill=time.time())
        return self._buckets[user_id]

    def allow_request(self, user_id: int) -> tuple[bool, str]:
        if user_id == self._owner_id:
            return True, ""

        b = self._bucket(user_id)
        now = time.time()
        elapsed = now - b.last_refill
        b.tokens = min(self.burst, b.tokens + elapsed * self.rate)
        b.last_refill = now

        if b.tokens < 1.0:
            wait = (1.0 - b.tokens) / self.rate
            return False, f"Слишком часто. Подожди ~{wait:.0f}с."
        b.tokens -= 1.0
        return True, ""

    def check_token_budget(self, user_id: int) -> tuple[bool, str]:
        if user_id == self._owner_id or self.daily_token_budget <= 0:
            return True, ""
        b = self._bucket(user_id)
        now = time.time()
        if now - b.day_start > 86400:
            b.day_start = now
            b.tokens_used_today = 0
        if b.tokens_used_today >= self.daily_token_budget:
            return False, "Дневной лимит токенов исчерпан. Попробуй завтра."
        return True, ""

    def record_tokens(self, user_id: int, tokens: int) -> None:
        b = self._bucket(user_id)
        b.tokens_used_today += max(0, tokens)


rate_limiter = RateLimiter()
