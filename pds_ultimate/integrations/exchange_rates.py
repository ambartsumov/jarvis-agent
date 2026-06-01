"""
PDS-Ultimate Exchange Rates Integration
==========================================
Динамические курсы валют из exchangerate-api.com.

По ТЗ §4.3:
- 1 USD = 19.5 TMT (фиксированный) — обрабатывается в CurrencyConfig
- 1 USD = 7.1 CNY (фиксированный) — обрабатывается в CurrencyConfig
- Все остальные — динамически из API (этот модуль)
- Кэш курсов: 6 часов
- Fallback: несколько API-провайдеров

Провайдеры:
1. exchangerate-api.com (primary)
2. open.er-api.com (fallback)
3. api.frankfurter.app (fallback, ECB data)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pds_ultimate.config import config, logger

# ─── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class RateInfo:
    """Информация о курсе валюты."""
    currency: str
    rate: float  # сколько единиц за 1 USD
    source: str  # откуда получен
    fetched_at: datetime = field(default_factory=datetime.now)
    is_fixed: bool = False

    @property
    def age_seconds(self) -> float:
        return (datetime.now() - self.fetched_at).total_seconds()

    @property
    def is_fresh(self) -> bool:
        """Свежий ли курс (< 6 часов)."""
        return self.age_seconds < 21600  # 6h


@dataclass
class BulkRatesResult:
    """Результат пакетного запроса курсов."""
    rates: dict[str, RateInfo] = field(default_factory=dict)
    source: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    request_ms: float = 0.0


# ─── API Providers ───────────────────────────────────────────────────────────

class RateProvider:
    """Базовый класс провайдера курсов."""

    name: str = "base"
    base_url: str = ""

    async def fetch_all(self, base: str = "USD") -> Optional[dict[str, float]]:
        """Получить все курсы относительно base. Returns {currency: rate}."""
        raise NotImplementedError

    async def fetch_one(self, currency: str, base: str = "USD") -> Optional[float]:
        """Получить один курс."""
        all_rates = await self.fetch_all(base)
        if all_rates:
            return all_rates.get(currency)
        return None


class ExchangeRateAPIProvider(RateProvider):
    """
    Primary provider: exchangerate-api.com
    URL из config.currency.exchange_api_url
    """

    name = "exchangerate-api.com"

    async def fetch_all(self, base: str = "USD") -> Optional[dict[str, float]]:
        try:
            import httpx

            url = config.currency.exchange_api_url
            if not url:
                url = f"https://open.er-api.com/v6/latest/{base}"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            # Поддержка двух форматов ответа
            rates = data.get("rates", {})
            if not rates:
                rates = data.get("conversion_rates", {})

            if rates:
                logger.debug(
                    f"[ExchangeRates] {self.name}: {len(rates)} currencies")
                return {k: float(v) for k, v in rates.items()}

        except Exception as e:
            logger.warning(f"[ExchangeRates] {self.name} failed: {e}")

        return None


class OpenERAPIProvider(RateProvider):
    """Fallback provider: open.er-api.com."""

    name = "open.er-api.com"

    async def fetch_all(self, base: str = "USD") -> Optional[dict[str, float]]:
        try:
            import httpx

            url = f"https://open.er-api.com/v6/latest/{base}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            rates = data.get("rates", {})
            if rates:
                logger.debug(
                    f"[ExchangeRates] {self.name}: {len(rates)} currencies")
                return {k: float(v) for k, v in rates.items()}

        except Exception as e:
            logger.warning(f"[ExchangeRates] {self.name} failed: {e}")

        return None


class FrankfurterProvider(RateProvider):
    """Fallback provider: api.frankfurter.app (ECB data, no USD/TMT)."""

    name = "frankfurter.app"

    async def fetch_all(self, base: str = "USD") -> Optional[dict[str, float]]:
        try:
            import httpx

            url = f"https://api.frankfurter.app/latest?from={base}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            rates = data.get("rates", {})
            if rates:
                # Frankfurter не включает base в rates
                rates[base] = 1.0
                logger.debug(
                    f"[ExchangeRates] {self.name}: {len(rates)} currencies"
                )
                return {k: float(v) for k, v in rates.items()}

        except Exception as e:
            logger.warning(f"[ExchangeRates] {self.name} failed: {e}")

        return None


# ─── Main Service ────────────────────────────────────────────────────────────

class ExchangeRateService:
    """
    Сервис динамических курсов валют.

    Архитектура:
    - Несколько провайдеров с fallback
    - In-memory кэш с TTL
    - Фиксированные курсы из config (TMT, CNY)
    - Пакетное обновление для планировщика

    Использование:
        rate = await exchange_service.get_rate("EUR")
        rates = await exchange_service.get_all_rates()
        result = await exchange_service.convert(100, "EUR", "TMT")
    """

    def __init__(
        self,
        cache_ttl: int = 21600,  # 6 hours
        providers: Optional[list[RateProvider]] = None,
    ):
        self._cache: dict[str, RateInfo] = {}
        self._cache_ttl = cache_ttl
        self._providers = providers or [
            ExchangeRateAPIProvider(),
            OpenERAPIProvider(),
            FrankfurterProvider(),
        ]
        self._last_bulk_fetch: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._error_count = 0

        # Предзаполнить фиксированные курсы
        for currency, rate in config.currency.fixed_rates.items():
            self._cache[currency] = RateInfo(
                currency=currency,
                rate=rate,
                source="fixed",
                is_fixed=True,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════════

    async def get_rate(self, currency: str) -> Optional[float]:
        """
        Получить курс валюты к USD.
        Returns: сколько единиц currency за 1 USD (или None).
        """
        currency = currency.upper()

        if currency == "USD":
            return 1.0

        # 1. Фиксированные
        fixed = config.currency.fixed_rates.get(currency)
        if fixed is not None:
            return fixed

        # 2. Кэш (если свежий)
        cached = self._cache.get(currency)
        if cached and cached.is_fresh:
            return cached.rate

        # 3. Fetch from API
        rate = await self._fetch_rate(currency)
        return rate

    async def get_all_rates(
        self,
        currencies: Optional[list[str]] = None,
    ) -> dict[str, RateInfo]:
        """
        Получить все курсы. Если currencies=None, возвращает все из кэша.
        """
        if currencies:
            result = {}
            for cur in currencies:
                rate = await self.get_rate(cur)
                if rate is not None:
                    cached = self._cache.get(cur.upper())
                    if cached:
                        result[cur.upper()] = cached
                    else:
                        result[cur.upper()] = RateInfo(
                            currency=cur.upper(),
                            rate=rate,
                            source="computed",
                        )
            return result

        # Если кэш пуст или устарел — обновить
        if not self._last_bulk_fetch or not self._is_cache_fresh():
            await self.refresh_all()

        return dict(self._cache)

    async def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> dict:
        """
        Конвертировать сумму.
        Returns dict с полями: amount, from, to, result, rate, source.
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if from_currency == to_currency:
            return {
                "amount": amount,
                "from": from_currency,
                "to": to_currency,
                "result": amount,
                "rate": 1.0,
                "source": "identity",
            }

        rate_from = await self.get_rate(from_currency)
        rate_to = await self.get_rate(to_currency)

        if rate_from is None:
            return {"error": f"Курс не найден: {from_currency}"}
        if rate_to is None:
            return {"error": f"Курс не найден: {to_currency}"}

        # from_currency → USD → to_currency
        usd_amount = amount / rate_from if from_currency != "USD" else amount
        result = usd_amount * rate_to if to_currency != "USD" else usd_amount
        cross_rate = rate_to / rate_from if rate_from > 0 else 0

        # Determine source
        from_info = self._cache.get(from_currency)
        to_info = self._cache.get(to_currency)
        sources = set()
        if from_info:
            sources.add(from_info.source)
        if to_info:
            sources.add(to_info.source)

        return {
            "amount": amount,
            "from": from_currency,
            "to": to_currency,
            "result": round(result, 2),
            "rate": round(cross_rate, 6),
            "usd_equivalent": round(usd_amount, 2),
            "source": ", ".join(sorted(sources)) or "unknown",
        }

    async def refresh_all(self) -> BulkRatesResult:
        """
        Пакетное обновление всех курсов из API.
        Используется планировщиком каждые 6 часов.
        """
        async with self._lock:
            start = time.monotonic()
            self._request_count += 1

            for provider in self._providers:
                try:
                    rates = await provider.fetch_all("USD")
                    if rates:
                        updated = 0
                        for currency, rate in rates.items():
                            # Не перезаписываем фиксированные
                            if currency in config.currency.fixed_rates:
                                continue
                            if currency == "USD":
                                continue

                            self._cache[currency] = RateInfo(
                                currency=currency,
                                rate=rate,
                                source=provider.name,
                            )
                            updated += 1

                        elapsed = (time.monotonic() - start) * 1000
                        self._last_bulk_fetch = datetime.now()

                        logger.info(
                            f"[ExchangeRates] Refreshed {updated} rates "
                            f"from {provider.name} in {elapsed:.0f}ms"
                        )

                        return BulkRatesResult(
                            rates=dict(self._cache),
                            source=provider.name,
                            request_ms=elapsed,
                        )

                except Exception as e:
                    self._error_count += 1
                    logger.warning(
                        f"[ExchangeRates] {provider.name} bulk fetch failed: {e}"
                    )
                    continue

            elapsed = (time.monotonic() - start) * 1000
            return BulkRatesResult(
                error="Все провайдеры недоступны",
                request_ms=elapsed,
            )

    def format_rates_table(
        self,
        currencies: Optional[list[str]] = None,
    ) -> str:
        """Форматирование таблицы курсов из кэша."""
        if currencies is None:
            currencies = ["TMT", "CNY", "EUR", "GBP", "TRY", "AED", "RUB"]

        lines = ["💱 Курсы валют (к USD):\n"]

        for cur in currencies:
            info = self._cache.get(cur)
            if info:
                mark = "📌" if info.is_fixed else "📊"
                age = ""
                if not info.is_fixed:
                    mins = int(info.age_seconds / 60)
                    if mins < 60:
                        age = f" ({mins}мин назад)"
                    else:
                        age = f" ({mins // 60}ч назад)"
                lines.append(f"  {mark} 1 USD = {info.rate:.2f} {cur}{age}")
            else:
                lines.append(f"  ❓ {cur}: нет данных")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Статистика сервиса."""
        fixed = sum(1 for r in self._cache.values() if r.is_fixed)
        dynamic = sum(1 for r in self._cache.values() if not r.is_fixed)
        fresh = sum(
            1 for r in self._cache.values()
            if not r.is_fixed and r.is_fresh
        )

        return {
            "total_cached": len(self._cache),
            "fixed_rates": fixed,
            "dynamic_rates": dynamic,
            "fresh_rates": fresh,
            "stale_rates": dynamic - fresh,
            "last_bulk_fetch": (
                self._last_bulk_fetch.isoformat()
                if self._last_bulk_fetch else None
            ),
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "providers": [p.name for p in self._providers],
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    def _is_cache_fresh(self) -> bool:
        """Проверить свежесть кэша."""
        if not self._last_bulk_fetch:
            return False
        age = (datetime.now() - self._last_bulk_fetch).total_seconds()
        return age < self._cache_ttl

    async def _fetch_rate(self, currency: str) -> Optional[float]:
        """Получить курс одной валюты через провайдеры."""
        self._request_count += 1

        for provider in self._providers:
            try:
                rate = await provider.fetch_one(currency)
                if rate is not None:
                    self._cache[currency] = RateInfo(
                        currency=currency,
                        rate=rate,
                        source=provider.name,
                    )
                    return rate
            except Exception as e:
                self._error_count += 1
                logger.warning(
                    f"[ExchangeRates] {provider.name} "
                    f"fetch {currency} failed: {e}"
                )
                continue

        return None


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

exchange_service = ExchangeRateService()
