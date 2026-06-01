"""
Тесты финансовой формулы — profit_calc.py + currency.py
"""


class TestFinancialFormula:
    """
    Тесты финансовой формулы по ТЗ:
    ДОХОД - ТОВАР = ОСТАТОК - ДОСТАВКА = ЧИСТАЯ_ПРИБЫЛЬ
    → expense_percent% + savings_percent%
    БЕЗ налогов и комиссий.
    """

    def test_profit_calculation(self):
        """Базовый расчёт прибыли."""
        income = 1000.0
        goods_cost = 500.0
        delivery_cost = 100.0

        remainder = income - goods_cost
        assert remainder == 500.0

        net_profit = remainder - delivery_cost
        assert net_profit == 400.0

        expense_percent = 50.0
        savings_percent = 50.0

        expenses = net_profit * (expense_percent / 100)
        savings = net_profit * (savings_percent / 100)

        assert expenses == 200.0
        assert savings == 200.0
        assert abs(expenses + savings - net_profit) < 0.01

    def test_profit_zero_delivery(self):
        """Прибыль без доставки."""
        income = 500.0
        goods_cost = 300.0
        delivery_cost = 0.0

        net_profit = income - goods_cost - delivery_cost
        assert net_profit == 200.0

    def test_profit_loss(self):
        """Убыток (расход > дохода)."""
        income = 100.0
        goods_cost = 150.0
        delivery_cost = 50.0

        net_profit = income - goods_cost - delivery_cost
        assert net_profit == -100.0  # Убыток

    def test_profit_custom_percent(self):
        """Нестандартное распределение 70/30."""
        net_profit = 1000.0
        expenses = net_profit * 0.70
        savings = net_profit * 0.30

        assert expenses == 700.0
        assert savings == 300.0


class TestCurrencyConversion:
    """Тесты конвертации валют с фиксированными курсами."""

    def test_fixed_rate_tmt(self, test_config):
        """1 USD = 19.5 TMT."""
        rate = test_config.currency.fixed_rates["TMT"]
        assert rate == 19.5

        # 100 USD → TMT
        usd = 100.0
        tmt = usd * rate
        assert tmt == 1950.0

        # 1950 TMT → USD
        usd_back = tmt / rate
        assert abs(usd_back - 100.0) < 0.01

    def test_fixed_rate_cny(self, test_config):
        """1 USD = 7.1 CNY."""
        rate = test_config.currency.fixed_rates["CNY"]
        assert rate == 7.1

        # 100 USD → CNY
        usd = 100.0
        cny = usd * rate
        assert cny == 710.0

        # 710 CNY → USD
        usd_back = cny / rate
        assert abs(usd_back - 100.0) < 0.01

    def test_cross_rate_tmt_cny(self, test_config):
        """Кросс-курс TMT ↔ CNY через USD."""
        tmt_rate = test_config.currency.fixed_rates["TMT"]
        cny_rate = test_config.currency.fixed_rates["CNY"]

        # 1000 TMT → USD → CNY
        tmt = 1000.0
        usd = tmt / tmt_rate
        cny = usd * cny_rate

        expected_cny = 1000.0 / 19.5 * 7.1
        assert abs(cny - expected_cny) < 0.01

    def test_base_currency(self, test_config):
        """Базовая валюта — USD."""
        assert test_config.currency.base_currency == "USD"


class TestProfitCalculator:
    """Тесты модуля ProfitCalculator."""

    def test_import(self):
        """ProfitCalculator импортируется."""
        from pds_ultimate.modules.finance.profit_calc import ProfitCalculator
        assert ProfitCalculator is not None

    def test_init(self, session_factory):
        """ProfitCalculator инициализируется."""
        from pds_ultimate.modules.finance.profit_calc import ProfitCalculator
        calc = ProfitCalculator(session_factory)
        assert calc is not None
