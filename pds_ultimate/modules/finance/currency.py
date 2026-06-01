"""
PDS-Ultimate Currency Manager
=================================
Мультивалютность с фиксированными и динамическими курсами.

По ТЗ:
- 1 USD = 19.5 TMT (фиксированный)
- 1 USD = 7.1 CNY (фиксированный)
- Все остальные — динамически из API (exchangerate-api.com)
- Кэш курсов: 6 часов
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pds_ultimate.config import config, logger


class CurrencyManager:
    """
    Менеджер валют: конвертация, кэш, обновление курсов.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory
        self._cache: dict[str, tuple[float, datetime]] = {}
        self._cache_ttl = config.currency.cache_ttl

    # ═══════════════════════════════════════════════════════════════════════
    # Конвертация
    # ═══════════════════════════════════════════════════════════════════════

    async def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> dict:
        """
        Конвертировать сумму из одной валюты в другую.
        Все курсы относительно USD.
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
            }

        # Получить курсы к USD
        rate_from = await self.get_rate(from_currency)
        rate_to = await self.get_rate(to_currency)

        if rate_from is None or rate_to is None:
            return {"error": f"Курс не найден: {from_currency} или {to_currency}"}

        # amount в from_currency → USD → to_currency
        # rate = сколько единиц валюты за 1 USD
        # amount_from / rate_from = USD
        # USD * rate_to = amount_to
        usd_amount = amount / rate_from if from_currency != "USD" else amount
        result = usd_amount * rate_to if to_currency != "USD" else usd_amount

        cross_rate = rate_to / rate_from if rate_from > 0 else 0

        return {
            "amount": amount,
            "from": from_currency,
            "to": to_currency,
            "result": round(result, 2),
            "rate": round(cross_rate, 6),
            "usd_equivalent": round(usd_amount, 2),
        }

    async def to_usd(self, amount: float, currency: str) -> float:
        """Быстрая конвертация в USD."""
        currency = currency.upper()
        if currency == "USD":
            return amount

        rate = await self.get_rate(currency)
        if rate and rate > 0:
            return amount / rate

        return amount

    async def from_usd(self, amount_usd: float, currency: str) -> float:
        """Конвертация из USD в другую валюту."""
        currency = currency.upper()
        if currency == "USD":
            return amount_usd

        rate = await self.get_rate(currency)
        if rate and rate > 0:
            return amount_usd * rate

        return amount_usd

    # ═══════════════════════════════════════════════════════════════════════
    # Получение курса
    # ═══════════════════════════════════════════════════════════════════════

    async def get_rate(self, currency: str) -> Optional[float]:
        """
        Получить курс валюты к USD (сколько единиц за 1 USD).
        USD → 1.0
        TMT → 19.5 (фиксированный)
        CNY → 7.1 (фиксированный)
        """
        currency = currency.upper()

        if currency == "USD":
            return 1.0

        # 1. Фиксированные курсы
        fixed = config.currency.fixed_rates.get(currency)
        if fixed is not None:
            return fixed

        # 2. Кэш в памяти
        cached = self._cache.get(currency)
        if cached:
            rate, cached_at = cached
            if (datetime.now() - cached_at).total_seconds() < self._cache_ttl:
                return rate

        # 3. Кэш в БД
        db_rate = await self._get_db_rate(currency)
        if db_rate is not None:
            self._cache[currency] = (db_rate, datetime.now())
            return db_rate

        # 4. API (если нет в кэше)
        api_rate = await self._fetch_from_api(currency)
        if api_rate is not None:
            self._cache[currency] = (api_rate, datetime.now())
            await self._save_db_rate(currency, api_rate)
            return api_rate

        return None

    async def update_dynamic_rates(self) -> dict:
        """
        Обновить все динамические курсы из API.
        Вызывается планировщиком каждые 6 часов.
        """
        try:
            import httpx

            url = config.currency.exchange_api_url
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            rates = data.get("rates", {})
            updated = 0

            for currency, rate in rates.items():
                # Пропускаем фиксированные
                if currency in config.currency.fixed_rates:
                    continue

                if currency == "USD":
                    continue

                await self._save_db_rate(currency, rate)
                self._cache[currency] = (rate, datetime.now())
                updated += 1

            logger.info(f"Dynamic rates updated: {updated} currencies")
            return {"updated": updated, "source": url}

        except Exception as e:
            logger.error(f"Failed to update rates: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_conversion(self, result: dict) -> str:
        """Форматировать результат конвертации."""
        if "error" in result:
            return f"❌ {result['error']}"

        return (
            f"💱 {result['amount']:,.2f} {result['from']} = "
            f"{result['result']:,.2f} {result['to']}\n"
            f"Курс: 1 {result['from']} = {result['rate']:.4f} {result['to']}"
        )

    async def format_rates_table(self, currencies: Optional[list[str]] = None) -> str:
        """Таблица актуальных курсов."""
        if currencies is None:
            currencies = ["TMT", "CNY", "EUR", "GBP", "TRY", "AED"]

        lines = ["💱 Курсы валют (к USD):\n"]

        for cur in currencies:
            rate = await self.get_rate(cur)
            if rate is not None:
                is_fixed = cur in config.currency.fixed_rates
                mark = "📌" if is_fixed else "📊"
                lines.append(f"  {mark} 1 USD = {rate:.2f} {cur}")
            else:
                lines.append(f"  ❓ {cur}: нет данных")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal: БД кэш
    # ═══════════════════════════════════════════════════════════════════════

    async def _get_db_rate(self, currency: str) -> Optional[float]:
        """Получить курс из БД."""
        from pds_ultimate.core.database import CurrencyRate

        with self._session_factory() as session:
            record = (
                session.query(CurrencyRate)
                .filter(
                    CurrencyRate.base_currency == "USD",
                    CurrencyRate.target_currency == currency,
                )
                .order_by(CurrencyRate.rate_date.desc())
                .first()
            )

            if record:
                # Проверить свежесть (для динамических)
                if record.is_fixed:
                    return record.rate

                age = (date.today() - record.rate_date).days
                if age <= 1:  # Актуален в пределах 1 дня
                    return record.rate

        return None

    async def _save_db_rate(self, currency: str, rate: float) -> None:
        """Сохранить курс в БД."""
        from pds_ultimate.core.database import CurrencyRate

        with self._session_factory() as session:
            existing = (
                session.query(CurrencyRate)
                .filter(
                    CurrencyRate.base_currency == "USD",
                    CurrencyRate.target_currency == currency,
                    CurrencyRate.rate_date == date.today(),
                )
                .first()
            )

            if existing:
                existing.rate = rate
            else:
                session.add(CurrencyRate(
                    base_currency="USD",
                    target_currency=currency,
                    rate=rate,
                    is_fixed=False,
                    rate_date=date.today(),
                ))

            session.commit()

    async def _fetch_from_api(self, currency: str) -> Optional[float]:
        """Получить курс из API."""
        try:
            import httpx

            url = config.currency.exchange_api_url
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            rates = data.get("rates", {})
            rate = rates.get(currency)

            if rate:
                logger.info(f"API rate fetched: 1 USD = {rate} {currency}")
                return float(rate)

        except Exception as e:
            logger.warning(f"API rate fetch failed for {currency}: {e}")

        return None
