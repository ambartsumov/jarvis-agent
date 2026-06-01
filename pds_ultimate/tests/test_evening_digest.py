"""
Тесты Evening Digest (Part 9)
===================================
DigestItem, Recommendation, DaySummary, DayRecapCollector,
RecommendationEngine, DigestFormatter, EveningDigestEngine.
~50 тестов.
"""


from pds_ultimate.core.evening_digest import (
    DayRecapCollector,
    DaySummary,
    DigestFormatter,
    DigestItem,
    DigestPriority,
    DigestSection,
    EveningDigestEngine,
    Recommendation,
    RecommendationEngine,
    RecommendationType,
    evening_digest,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnums:
    """Enum smoke tests."""

    def test_digest_section(self):
        assert DigestSection.ORDERS.value == "orders"
        assert DigestSection.FINANCE.value == "finance"
        assert DigestSection.TASKS.value == "tasks"
        assert DigestSection.ALERTS.value == "alerts"
        assert DigestSection.RECOMMENDATIONS.value == "recommendations"
        assert DigestSection.UNRESOLVED.value == "unresolved"

    def test_recommendation_type(self):
        assert RecommendationType.FOLLOWUP.value == "followup"
        assert RecommendationType.RISK.value == "risk"
        assert RecommendationType.OPTIMIZATION.value == "optimization"
        assert RecommendationType.OPPORTUNITY.value == "opportunity"
        assert RecommendationType.CELEBRATION.value == "celebration"

    def test_digest_priority(self):
        assert DigestPriority.LOW.value == "low"
        assert DigestPriority.MEDIUM.value == "medium"
        assert DigestPriority.HIGH.value == "high"


# ═══════════════════════════════════════════════════════════════════════════════
# DigestItem
# ═══════════════════════════════════════════════════════════════════════════════


class TestDigestItem:
    """DigestItem — один пункт дайджеста."""

    def test_create(self):
        item = DigestItem(
            section=DigestSection.ORDERS,
            title="Итоги дня",
            description="Всё хорошо",
        )
        assert item.title == "Итоги дня"
        assert item.section == DigestSection.ORDERS

    def test_priority_default(self):
        item = DigestItem(
            section=DigestSection.TASKS,
            title="T",
            description="C",
        )
        assert item.priority == DigestPriority.MEDIUM

    def test_to_dict(self):
        item = DigestItem(
            section=DigestSection.FINANCE,
            title="Финансы",
            description="Прибыль 100$",
            priority=DigestPriority.HIGH,
        )
        d = item.to_dict()
        assert d["title"] == "Финансы"
        assert d["priority"] == "high"

    def test_format_line(self):
        item = DigestItem(
            section=DigestSection.FINANCE,
            title="Доход",
            description="$5000",
        )
        line = item.format_line()
        assert "Доход" in line


# ═══════════════════════════════════════════════════════════════════════════════
# Recommendation
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecommendation:
    """Recommendation — рекомендация."""

    def test_create(self):
        r = Recommendation(
            rec_type=RecommendationType.FOLLOWUP,
            title="Сделать что-то",
            description="Подробнее...",
        )
        assert r.title == "Сделать что-то"
        assert r.rec_type == RecommendationType.FOLLOWUP

    def test_to_dict(self):
        r = Recommendation(
            rec_type=RecommendationType.RISK,
            title="Внимание",
            description="Описание",
            priority=DigestPriority.HIGH,
        )
        d = r.to_dict()
        assert d["type"] == "risk"
        assert d["priority"] == "high"

    def test_format_text(self):
        r = Recommendation(
            rec_type=RecommendationType.OPPORTUNITY,
            title="Возможность",
            description="Подробнее",
            action_text="Действуйте",
        )
        text = r.format_text()
        assert "Возможность" in text
        assert "Действуйте" in text


# ═══════════════════════════════════════════════════════════════════════════════
# DaySummary
# ═══════════════════════════════════════════════════════════════════════════════


class TestDaySummary:
    """DaySummary — итоги дня."""

    def test_create_default(self):
        ds = DaySummary()
        assert ds.orders_created == 0
        assert ds.revenue == 0.0
        assert ds.expenses == 0.0
        assert ds.profit == 0.0

    def test_with_values(self):
        ds = DaySummary(
            revenue=5000, expenses=3000, profit=2000,
            orders_created=10, tasks_completed=5,
        )
        assert ds.revenue == 5000
        assert ds.profit == 2000

    def test_net_profit_margin(self):
        ds = DaySummary(revenue=1000, expenses=600, profit=400)
        assert ds.net_profit_margin == 40.0

    def test_net_profit_margin_zero_revenue(self):
        ds = DaySummary(revenue=0, profit=0)
        assert ds.net_profit_margin == 0.0

    def test_to_dict(self):
        ds = DaySummary(revenue=100, expenses=50, profit=50)
        d = ds.to_dict()
        assert d["revenue"] == 100
        assert d["expenses"] == 50
        assert d["profit"] == 50
        assert "date" in d
        assert "profit_margin" in d


# ═══════════════════════════════════════════════════════════════════════════════
# DayRecapCollector
# ═══════════════════════════════════════════════════════════════════════════════


class TestDayRecapCollector:
    """DayRecapCollector — сборщик данных за день."""

    def test_record_day_and_total_days(self):
        rc = DayRecapCollector()
        ds = DaySummary(revenue=1000, profit=500)
        rc.record_day(ds)
        assert rc.total_days == 1

    def test_record_multiple(self):
        rc = DayRecapCollector()
        for i in range(5):
            rc.record_day(DaySummary(revenue=100 * i))
        assert rc.total_days == 5

    def test_compare_with_yesterday(self):
        rc = DayRecapCollector()
        # Just verify it returns a dict (no data = zeroes)
        comparison = rc.compare_with_yesterday()
        assert isinstance(comparison, dict)
        assert "revenue" in comparison

    def test_get_today_empty(self):
        rc = DayRecapCollector()
        today = rc.get_today()
        assert today.revenue == 0.0

    def test_get_last_n_days(self):
        rc = DayRecapCollector()
        rc.record_day(DaySummary(revenue=100))
        rc.record_day(DaySummary(revenue=200))
        last = rc.get_last_n_days(7)
        assert len(last) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# RecommendationEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecommendationEngine:
    """RecommendationEngine — движок рекомендаций."""

    def test_default_rules(self):
        re = RecommendationEngine()
        assert len(re._rules) >= 3

    def test_generate_for_low_margin(self):
        re = RecommendationEngine()
        ds = DaySummary(revenue=1000, expenses=900, profit=100)
        recs = re.generate(ds)
        assert isinstance(recs, list)

    def test_generate_for_good_day(self):
        re = RecommendationEngine()
        ds = DaySummary(
            revenue=10000, expenses=2000, profit=8000,
            orders_created=20, tasks_completed=15,
        )
        recs = re.generate(ds)
        assert isinstance(recs, list)

    def test_generate_empty_day(self):
        re = RecommendationEngine()
        ds = DaySummary()
        recs = re.generate(ds)
        assert isinstance(recs, list)

    def test_add_custom_rule(self):
        re = RecommendationEngine()
        initial = len(re._rules)

        def check(summary):
            return summary.revenue > 0

        def generate(summary):
            return Recommendation(
                rec_type=RecommendationType.OPTIMIZATION,
                title="Custom",
                description="Custom rule triggered",
            )

        re.add_rule("custom_rule", check, generate)
        assert len(re._rules) == initial + 1

    def test_custom_rule_fires(self):
        re = RecommendationEngine()

        def check(s):
            return s.revenue > 9000

        def gen(s):
            return Recommendation(
                rec_type=RecommendationType.CELEBRATION,
                title="Big revenue!",
                description="Over 9000",
            )

        re.add_rule("big_rev", check, gen)
        recs = re.generate(DaySummary(
            revenue=10000, profit=5000, tasks_completed=5))
        titles = [r.title for r in recs]
        assert "Big revenue!" in titles


# ═══════════════════════════════════════════════════════════════════════════════
# DigestFormatter
# ═══════════════════════════════════════════════════════════════════════════════


class TestDigestFormatter:
    """DigestFormatter — форматирование дайджеста."""

    def test_format_evening_digest(self):
        df = DigestFormatter()
        ds = DaySummary(revenue=5000, expenses=3000, profit=2000)
        text = df.format_evening_digest(ds)
        assert "5,000" in text or "5000" in text or "5 000" in text

    def test_format_evening_digest_with_recs(self):
        df = DigestFormatter()
        ds = DaySummary(revenue=5000, expenses=3000, profit=2000,
                        orders_created=5, tasks_completed=3)
        recs = [
            Recommendation(
                rec_type=RecommendationType.OPTIMIZATION,
                title="Tip",
                description="Something useful",
            ),
        ]
        text = df.format_evening_digest(ds, recommendations=recs)
        assert isinstance(text, str)
        assert len(text) > 50

    def test_format_short_digest(self):
        df = DigestFormatter()
        ds = DaySummary(revenue=3000, expenses=2000, profit=1000)
        text = df.format_short_digest(ds)
        assert isinstance(text, str)
        assert len(text) > 5

    def test_format_short_digest_empty(self):
        df = DigestFormatter()
        ds = DaySummary()
        text = df.format_short_digest(ds)
        assert isinstance(text, str)


# ═══════════════════════════════════════════════════════════════════════════════
# EveningDigestEngine (facade)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEveningDigestEngine:
    """EveningDigestEngine — главный фасад."""

    def test_record_day_summary(self):
        ed = EveningDigestEngine()
        ds = DaySummary(revenue=1000, profit=500)
        ed.record_day_summary(ds)
        assert ed.recap.total_days == 1

    def test_generate_digest(self):
        ed = EveningDigestEngine()
        ds = DaySummary(
            revenue=5000, expenses=3000, profit=2000,
            orders_created=5,
        )
        text = ed.generate_digest(ds)
        assert isinstance(text, str)
        assert len(text) > 20

    def test_generate_short_digest(self):
        ed = EveningDigestEngine()
        ds = DaySummary(
            revenue=3000, expenses=2000, profit=1000,
        )
        text = ed.generate_short_digest(ds)
        assert isinstance(text, str)
        assert len(text) > 10

    def test_generate_digest_with_history(self):
        ed = EveningDigestEngine()
        ed.record_day_summary(DaySummary(revenue=1000, profit=500))
        ed.record_day_summary(DaySummary(revenue=2000, profit=1000))
        ds = DaySummary(revenue=3000, profit=1500)
        text = ed.generate_digest(ds)
        assert isinstance(text, str)

    def test_create_summary(self):
        ed = EveningDigestEngine()
        ds = ed.create_summary(revenue=500, profit=200)
        assert ds.revenue == 500
        assert ed.recap.total_days == 1

    def test_get_stats(self):
        ed = EveningDigestEngine()
        stats = ed.get_stats()
        assert "days_recorded" in stats
        assert "rules_count" in stats

    def test_global_instance(self):
        assert evening_digest is not None
        assert isinstance(evening_digest, EveningDigestEngine)
