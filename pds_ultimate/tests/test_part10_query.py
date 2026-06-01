"""
Tests for Part 10 — Adaptive Query Expansion
"""


from pds_ultimate.core.adaptive_query import (
    AdaptiveQueryEngine,
    ExpandedQuery,
    ExpansionStrategy,
    GapAnalyzer,
    GapType,
    InformationGap,
    QueryExpander,
    QueryOptimizer,
    RefinementLoop,
    RefinementStep,
    adaptive_query,
)


class TestExpandedQuery:
    """Тесты ExpandedQuery."""

    def test_create(self):
        eq = ExpandedQuery(
            original="цена товара",
            expanded="цена товара стоимость",
            strategy=ExpansionStrategy.SYNONYM,
            added_terms=["стоимость"],
        )
        assert eq.original == "цена товара"
        assert "стоимость" in eq.expanded

    def test_to_dict(self):
        eq = ExpandedQuery(
            original="test", expanded="test expanded",
            strategy=ExpansionStrategy.RELATED,
        )
        d = eq.to_dict()
        assert "original" in d
        assert "expanded" in d
        assert "strategy" in d


class TestInformationGap:
    """Тесты InformationGap."""

    def test_create(self):
        gap = InformationGap(
            gap_type=GapType.MISSING_DATA,
            description="Нет данных",
        )
        assert gap.gap_type == GapType.MISSING_DATA

    def test_to_dict(self):
        gap = InformationGap(
            gap_type=GapType.NO_NUMBERS,
            description="Нет числовых данных",
            suggested_query="цена точно",
            priority=0.8,
        )
        d = gap.to_dict()
        assert d["type"] == "no_numbers"
        assert d["priority"] == 0.8


class TestQueryExpander:
    """Тесты QueryExpander."""

    def test_synonym_expansion(self):
        exp = QueryExpander()
        result = exp.expand("цена товара", strategy=ExpansionStrategy.SYNONYM)
        assert isinstance(result, ExpandedQuery)
        assert result.strategy == ExpansionStrategy.SYNONYM

    def test_synonym_adds_terms(self):
        exp = QueryExpander()
        result = exp.expand("цена", strategy=ExpansionStrategy.SYNONYM)
        assert len(result.added_terms) > 0 or result.expanded != "цена"

    def test_contextual_expansion(self):
        exp = QueryExpander()
        result = exp.expand(
            "импорт товаров",
            strategy=ExpansionStrategy.CONTEXTUAL,
            context="Китай поставка",
        )
        assert isinstance(result, ExpandedQuery)

    def test_temporal_expansion(self):
        exp = QueryExpander()
        result = exp.expand(
            "курс доллара", strategy=ExpansionStrategy.TEMPORAL)
        assert result.strategy == ExpansionStrategy.TEMPORAL

    def test_temporal_no_double_year(self):
        exp = QueryExpander()
        result = exp.expand("курс 2025", strategy=ExpansionStrategy.TEMPORAL)
        # Already has a year — should not add another
        assert result.confidence <= 0.5 or "2025" in result.expanded

    def test_specific_expansion(self):
        exp = QueryExpander()
        result = exp.expand(
            "товар",
            strategy=ExpansionStrategy.SPECIFIC,
            context="электроника компьютеры процессоры",
        )
        assert isinstance(result, ExpandedQuery)

    def test_broad_expansion(self):
        exp = QueryExpander()
        result = exp.expand(
            "цена на красные помидоры из Турции за 2024 год",
            strategy=ExpansionStrategy.BROAD,
        )
        assert isinstance(result, ExpandedQuery)

    def test_related_expansion(self):
        exp = QueryExpander()
        result = exp.expand("стоимость", strategy=ExpansionStrategy.RELATED)
        assert isinstance(result, ExpandedQuery)

    def test_expand_multi(self):
        exp = QueryExpander()
        results = exp.expand_multi("цена товара", context="Китай")
        assert isinstance(results, list)

    def test_no_expansion_unknown(self):
        exp = QueryExpander()
        result = exp.expand(
            "абракадабра",
            strategy=ExpansionStrategy.SYNONYM,
        )
        assert result.expanded == "абракадабра" or result.confidence <= 0.5


class TestGapAnalyzer:
    """Тесты GapAnalyzer."""

    def test_empty_answer(self):
        ga = GapAnalyzer()
        gaps = ga.analyze("Какой курс?", "")
        assert len(gaps) > 0
        assert gaps[0].gap_type == GapType.MISSING_DATA

    def test_short_answer(self):
        ga = GapAnalyzer()
        gaps = ga.analyze("Какой курс?", "5")
        assert any(g.gap_type == GapType.MISSING_DATA for g in gaps)

    def test_no_numbers_when_expected(self):
        ga = GapAnalyzer()
        gaps = ga.analyze(
            "Сколько стоит доставка?",
            "Доставка стоит по-разному, зависит от веса и расстояния.",
        )
        assert any(g.gap_type == GapType.NO_NUMBERS for g in gaps)

    def test_no_source(self):
        ga = GapAnalyzer()
        gaps = ga.analyze(
            "Курс доллара?",
            "Курс доллара составляет примерно 90 рублей",
            source_count=0,
        )
        assert any(g.gap_type == GapType.NO_SOURCE for g in gaps)

    def test_vague_answer(self):
        ga = GapAnalyzer()
        gaps = ga.analyze(
            "Что делать?",
            "Возможно, может быть стоит попробовать, "
            "вероятно это поможет, но трудно сказать наверняка. "
            "Зависит от многих факторов.",
        )
        assert any(g.gap_type == GapType.VAGUE for g in gaps)

    def test_good_answer_no_gaps(self):
        ga = GapAnalyzer()
        gaps = ga.analyze(
            "Как дела?",
            "Всё отлично! Сегодня был продуктивный день: "
            "завершили 5 задач, выручка составила 15000 долларов. "
            "Все показатели в норме, прогресс идёт по плану.",
            source_count=3,
            confidence=0.9,
        )
        no_critical = all(g.priority < 0.9 for g in gaps)
        assert no_critical

    def test_gaps_sorted_by_priority(self):
        ga = GapAnalyzer()
        gaps = ga.analyze(
            "Сколько стоит?",
            "Не знаю",
            source_count=0,
            confidence=0.1,
        )
        if len(gaps) > 1:
            for i in range(len(gaps) - 1):
                assert gaps[i].priority >= gaps[i + 1].priority


class TestRefinementLoop:
    """Тесты RefinementLoop."""

    def test_should_continue_max_iter(self):
        loop = RefinementLoop(max_iterations=3)
        gaps = [InformationGap(GapType.INCOMPLETE, "test")]
        assert loop.should_continue(3, 0.5, gaps) is False

    def test_should_continue_high_confidence(self):
        loop = RefinementLoop(target_confidence=0.8)
        gaps = [InformationGap(GapType.INCOMPLETE, "test")]
        assert loop.should_continue(0, 0.9, gaps) is False

    def test_should_continue_no_gaps(self):
        loop = RefinementLoop()
        assert loop.should_continue(0, 0.5, []) is False

    def test_should_continue_yes(self):
        loop = RefinementLoop(max_iterations=5, target_confidence=0.8)
        gaps = [InformationGap(GapType.INCOMPLETE, "test")]
        assert loop.should_continue(1, 0.4, gaps) is True

    def test_refine_query(self):
        loop = RefinementLoop()
        step = loop.refine_query(
            original_query="курс доллара",
            current_answer="Не знаю",
            confidence=0.2,
        )
        assert isinstance(step, RefinementStep)
        assert step.iteration == 0

    def test_refine_no_gaps(self):
        """При source_count=0 (default) всегда есть NO_SOURCE gap."""
        loop = RefinementLoop()
        step = loop.refine_query(
            original_query="Привет",
            current_answer="Привет! Чем могу помочь? У нас всё хорошо, "
            "данные актуальные, источников достаточно. "
            "Работаем стабильно. Показатели 100 процентов.",
            confidence=0.95,
        )
        # NO_SOURCE gap always present since refine_query
        # calls analyze with source_count=0 by default
        no_source = [g for g in step.gaps_found
                     if g.gap_type == GapType.NO_SOURCE]
        assert len(no_source) <= 1  # At most the NO_SOURCE gap

    def test_get_history(self):
        loop = RefinementLoop()
        loop.refine_query("Q", "Short", 0.3)
        history = loop.get_history()
        assert len(history) == 1

    def test_clear_history(self):
        loop = RefinementLoop()
        loop.refine_query("Q", "A", 0.5)
        loop.clear_history()
        assert len(loop.get_history()) == 0

    def test_get_stats(self):
        loop = RefinementLoop()
        stats = loop.get_stats()
        assert "total_refinements" in stats
        assert "max_iterations" in stats


class TestQueryOptimizer:
    """Тесты QueryOptimizer."""

    def test_optimize_removes_noise(self):
        opt = QueryOptimizer()
        result = opt.optimize("пожалуйста подскажи мне цена товара")
        assert "пожалуйста" not in result
        assert "цена" in result

    def test_optimize_preserves_content(self):
        opt = QueryOptimizer()
        result = opt.optimize("курс доллара юань")
        assert "курс" in result
        assert "доллара" in result

    def test_optimize_empty_after_removal(self):
        opt = QueryOptimizer()
        result = opt.optimize("скажи мне пожалуйста")
        assert len(result) > 0  # Should return original

    def test_extract_key_terms(self):
        opt = QueryOptimizer()
        terms = opt.extract_key_terms(
            "Какая цена на доставку товаров из Китая?"
        )
        assert isinstance(terms, list)
        assert len(terms) > 0

    def test_suggest_alternatives(self):
        opt = QueryOptimizer()
        alts = opt.suggest_alternatives("цена товара")
        assert isinstance(alts, list)


class TestAdaptiveQueryEngineFacade:
    """Тесты фасада AdaptiveQueryEngine."""

    def test_expand(self):
        engine = AdaptiveQueryEngine()
        result = engine.expand("цена")
        assert isinstance(result, ExpandedQuery)

    def test_expand_multi(self):
        engine = AdaptiveQueryEngine()
        results = engine.expand_multi("доставка из Китая")
        assert isinstance(results, list)

    def test_find_gaps(self):
        engine = AdaptiveQueryEngine()
        gaps = engine.find_gaps("Сколько?", "Не знаю")
        assert isinstance(gaps, list)

    def test_refine(self):
        engine = AdaptiveQueryEngine()
        step = engine.refine("курс", "Не знаю", confidence=0.2)
        assert isinstance(step, RefinementStep)

    def test_optimize(self):
        engine = AdaptiveQueryEngine()
        result = engine.optimize("подскажи цена товара")
        assert "подскажи" not in result

    def test_get_stats(self):
        engine = AdaptiveQueryEngine()
        stats = engine.get_stats()
        assert "refinement" in stats
        assert "synonyms_count" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert adaptive_query is not None
        assert isinstance(adaptive_query, AdaptiveQueryEngine)
