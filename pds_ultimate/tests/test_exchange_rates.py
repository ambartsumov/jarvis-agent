"""
Тесты Exchange Rates Service — integrations/exchange_rates.py
"""

import pytest


class TestExchangeRateService:
    """Тесты сервиса курсов валют."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.integrations.exchange_rates import (
            ExchangeRateService,
            exchange_service,
        )
        assert ExchangeRateService is not None
        assert exchange_service is not None

    def test_rate_info_creation(self):
        """RateInfo создаётся корректно."""
        from pds_ultimate.integrations.exchange_rates import RateInfo

        rate = RateInfo(
            currency="CNY",
            rate=7.1,
            source="fixed",
        )
        assert rate.currency == "CNY"
        assert rate.rate == 7.1
        assert rate.source == "fixed"

    def test_rate_info_freshness(self):
        """RateInfo age/freshness работает."""
        from pds_ultimate.integrations.exchange_rates import RateInfo

        rate = RateInfo(currency="TMT", rate=19.5, source="config")
        assert rate.is_fresh  # только что создан
        assert rate.age_seconds < 5

    def test_bulk_rates_result(self):
        """BulkRatesResult создаётся."""
        from pds_ultimate.integrations.exchange_rates import (
            BulkRatesResult,
            RateInfo,
        )

        rates = {
            "CNY": RateInfo(currency="CNY", rate=7.1, source="fixed"),
            "TMT": RateInfo(currency="TMT", rate=19.5, source="fixed"),
        }
        result = BulkRatesResult(rates=rates, source="test")
        assert len(result.rates) == 2
        assert result.source == "test"
        assert result.error is None

    def test_bulk_rates_result_with_error(self):
        """BulkRatesResult с ошибкой."""
        from pds_ultimate.integrations.exchange_rates import BulkRatesResult

        result = BulkRatesResult(error="All providers down")
        assert result.error == "All providers down"
        assert len(result.rates) == 0

    def test_service_instance(self):
        """Глобальный экземпляр создан."""
        from pds_ultimate.integrations.exchange_rates import exchange_service

        assert exchange_service is not None

    @pytest.mark.asyncio
    async def test_get_fixed_rate_cny(self):
        """Получить фиксированный курс CNY."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        rate = await service.get_rate("CNY")
        assert rate is not None
        assert rate == 7.1

    @pytest.mark.asyncio
    async def test_get_fixed_rate_tmt(self):
        """Получить фиксированный курс TMT."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        rate = await service.get_rate("TMT")
        assert rate is not None
        assert rate == 19.5

    @pytest.mark.asyncio
    async def test_get_rate_usd_identity(self):
        """Курс USD к USD = 1.0."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        rate = await service.get_rate("USD")
        assert rate == 1.0

    @pytest.mark.asyncio
    async def test_convert_basic(self):
        """Конвертация USD → CNY."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        result = await service.convert(100, "USD", "CNY")
        assert isinstance(result, dict)
        assert result.get("result") == 710.0

    @pytest.mark.asyncio
    async def test_convert_same_currency(self):
        """Конвертация USD → USD (identity)."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        result = await service.convert(100, "USD", "USD")
        assert result["result"] == 100
        assert result["rate"] == 1.0
        assert result["source"] == "identity"

    @pytest.mark.asyncio
    async def test_convert_tmt_to_usd(self):
        """Конвертация TMT → USD."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        result = await service.convert(195, "TMT", "USD")
        assert isinstance(result, dict)
        assert "result" in result
        assert abs(result["result"] - 10.0) < 0.01

    def test_format_rates_table(self):
        """Форматирование таблицы курсов."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        table = service.format_rates_table()
        assert isinstance(table, str)
        assert "Курсы валют" in table

    @pytest.mark.asyncio
    async def test_refresh_all(self):
        """refresh_all возвращает BulkRatesResult."""
        from pds_ultimate.integrations.exchange_rates import (
            BulkRatesResult,
            ExchangeRateService,
        )

        service = ExchangeRateService()
        result = await service.refresh_all()
        assert isinstance(result, BulkRatesResult)

    def test_get_stats(self):
        """get_stats возвращает статистику."""
        from pds_ultimate.integrations.exchange_rates import ExchangeRateService

        service = ExchangeRateService()
        stats = service.get_stats()
        assert isinstance(stats, dict)
        assert "total_cached" in stats
        assert "fixed_rates" in stats
        assert "providers" in stats


class TestProviders:
    """Тесты провайдеров курсов."""

    def test_exchangerate_api_provider(self):
        """ExchangeRateAPIProvider создаётся."""
        from pds_ultimate.integrations.exchange_rates import (
            ExchangeRateAPIProvider,
        )

        provider = ExchangeRateAPIProvider()
        assert provider.name == "exchangerate-api.com"

    def test_open_er_provider(self):
        """OpenERAPIProvider создаётся."""
        from pds_ultimate.integrations.exchange_rates import (
            OpenERAPIProvider,
        )

        provider = OpenERAPIProvider()
        assert provider.name == "open.er-api.com"

    def test_frankfurter_provider(self):
        """FrankfurterProvider создаётся."""
        from pds_ultimate.integrations.exchange_rates import (
            FrankfurterProvider,
        )

        provider = FrankfurterProvider()
        assert provider.name == "frankfurter.app"
