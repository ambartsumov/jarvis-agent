"""
Тесты Reasoning v2 (Part 8)
================================
TrustScorerV2, ContradictionDetector, QueryExpander,
HypothesisTester, ContextCompressor, ConfidenceEngine,
StalenessDetector, ReasoningLayerV2.
~65 тестов.
"""

from datetime import datetime, timedelta

from pds_ultimate.core.reasoning_v2 import (
    ConfidenceAssessment,
    ConfidenceEngine,
    ContextCompressor,
    Contradiction,
    ContradictionDetector,
    FactClaim,
    Hypothesis,
    HypothesisTester,
    QueryExpander,
    ReasoningLayerV2,
    ReasoningResult,
    StalenessDetector,
    TrustScorerV2,
    reasoning_v2,
)

# ═══════════════════════════════════════════════════════════════════════════════
# TrustScorerV2
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrustScorerV2:
    """TrustScorerV2 — оценка достоверности."""

    def test_wikipedia_high_trust(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://en.wikipedia.org/wiki/Python")
        assert score >= 0.85

    def test_reddit_low_trust(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://www.reddit.com/r/python")
        assert score < 0.5

    def test_stackoverflow_medium_trust(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://stackoverflow.com/questions/123")
        assert 0.7 <= score <= 0.9

    def test_gov_domain(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://data.gov")
        assert score >= 0.85

    def test_edu_domain(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://mit.edu/research")
        assert score >= 0.80

    def test_unknown_domain(self):
        ts = TrustScorerV2()
        score = ts.score_domain("https://randomsite12345.xyz")
        assert score == 0.50

    def test_score_content_fresh(self):
        ts = TrustScorerV2()
        score = ts.score_content(
            "A long enough text with proper content about the topic at hand " * 5,
            url="https://wikipedia.org/wiki/Test",
            publish_date=datetime.utcnow(),
        )
        assert score >= 0.7

    def test_score_content_old(self):
        ts = TrustScorerV2()
        old = datetime.utcnow() - timedelta(days=365 * 4)
        score = ts.score_content(
            "Some content about things that happened long ago",
            url="https://wikipedia.org/wiki/Test",
            publish_date=old,
        )
        # Old content gets penalty
        assert score < 0.90

    def test_score_content_short(self):
        ts = TrustScorerV2()
        score = ts.score_content("Short", url="https://wikipedia.org")
        assert score < 0.85  # Penalty for short content

    def test_score_content_with_citations(self):
        ts = TrustScorerV2()
        text = (
            "According to [source] the research shows [1] that "
            "according to experts [2] the data suggests [3] results"
        )
        score = ts.score_content(text, url="https://test.com")
        # Citations boost
        assert score > 0.45

    def test_update_history(self):
        ts = TrustScorerV2()
        ts.update_history("https://example.com", 0.9)
        ts.update_history("https://example.com", 0.8)
        score = ts.score_domain("https://example.com")
        assert 0.8 <= score <= 0.9

    def test_set_custom_score(self):
        ts = TrustScorerV2()
        ts.set_custom_score("mysite.com", 0.99)
        score = ts.score_domain("https://mysite.com")
        assert score == 0.99

    def test_custom_score_clamped(self):
        ts = TrustScorerV2()
        ts.set_custom_score("test.com", 1.5)
        assert ts._custom_scores["test.com"] == 1.0

    def test_extract_domain(self):
        assert TrustScorerV2._extract_domain(
            "https://www.example.com/path?q=1"
        ) == "example.com"

    def test_extract_domain_no_protocol(self):
        assert TrustScorerV2._extract_domain("example.com") == "example.com"


# ═══════════════════════════════════════════════════════════════════════════════
# FactClaim dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactClaim:
    """FactClaim — факт/утверждение."""

    def test_to_dict(self):
        fc = FactClaim(
            text="Python 3.12 released",
            source_url="https://python.org",
            trust_score=0.95,
        )
        d = fc.to_dict()
        assert d["text"] == "Python 3.12 released"
        assert d["trust"] == 0.95


# ═══════════════════════════════════════════════════════════════════════════════
# ContradictionDetector
# ═══════════════════════════════════════════════════════════════════════════════


class TestContradictionDetector:
    """ContradictionDetector — выявление расхождений."""

    def test_no_contradiction_same_source(self):
        cd = ContradictionDetector()
        facts = [
            FactClaim(text="The price is 100", source_url="https://a.com"),
            FactClaim(text="The price is 200", source_url="https://a.com"),
        ]
        contradictions = cd.detect(facts)
        assert len(contradictions) == 0  # Same source

    def test_numeric_contradiction(self):
        cd = ContradictionDetector()
        facts = [
            FactClaim(
                text="The population of the city is 500000",
                source_url="https://a.com",
                trust_score=0.9,
            ),
            FactClaim(
                text="The population of the city is 300000",
                source_url="https://b.com",
                trust_score=0.5,
            ),
        ]
        contradictions = cd.detect(facts)
        assert len(contradictions) >= 1
        assert "расхождение" in contradictions[0].description.lower() or \
               "разница" in contradictions[0].description.lower()

    def test_negation_contradiction(self):
        cd = ContradictionDetector()
        facts = [
            FactClaim(
                text="The results support the hypothesis clearly",
                source_url="https://a.com",
                source_name="Source A",
            ),
            FactClaim(
                text="The results oppose the hypothesis clearly",
                source_url="https://b.com",
                source_name="Source B",
            ),
        ]
        contradictions = cd.detect(facts)
        assert len(contradictions) >= 1

    def test_no_contradiction_different_topics(self):
        cd = ContradictionDetector()
        facts = [
            FactClaim(text="Python is a language", source_url="https://a.com"),
            FactClaim(text="Cats are animals", source_url="https://b.com"),
        ]
        contradictions = cd.detect(facts)
        assert len(contradictions) == 0

    def test_extract_numbers(self):
        nums = ContradictionDetector._extract_numbers(
            "The price is 42.5 dollars")
        assert 42.5 in nums

    def test_text_similarity_identical(self):
        sim = ContradictionDetector._text_similarity(
            "hello world", "hello world")
        assert sim == 1.0

    def test_text_similarity_different(self):
        sim = ContradictionDetector._text_similarity(
            "cats are cute animals",
            "python programming language",
        )
        assert sim < 0.1

    def test_text_similarity_partial(self):
        sim = ContradictionDetector._text_similarity(
            "the quick brown fox",
            "the quick red fox",
        )
        assert 0.3 < sim < 1.0

    def test_contradiction_has_resolution(self):
        cd = ContradictionDetector()
        facts = [
            FactClaim(
                text="Sales increased to 1000 units in region",
                source_url="https://reuters.com",
                trust_score=0.9,
            ),
            FactClaim(
                text="Sales decreased to 500 units in region",
                source_url="https://blog.random.com",
                trust_score=0.3,
            ),
        ]
        contradictions = cd.detect(facts)
        if contradictions:
            assert contradictions[0].resolution != ""


# ═══════════════════════════════════════════════════════════════════════════════
# QueryExpander
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryExpander:
    """QueryExpander — расширение запросов."""

    def test_expand_basic(self):
        qe = QueryExpander()
        queries = qe.expand("Python tutorial")
        assert len(queries) >= 1
        assert "Python tutorial" in queries

    def test_expand_price(self):
        qe = QueryExpander()
        queries = qe.expand("iPhone цена")
        assert len(queries) >= 2

    def test_expand_how_to(self):
        qe = QueryExpander()
        queries = qe.expand("как установить Python")
        assert len(queries) >= 2

    def test_expand_max_queries(self):
        qe = QueryExpander()
        queries = qe.expand("лучший ноутбук 2026", max_queries=2)
        assert len(queries) <= 2

    def test_expand_adds_year(self):
        qe = QueryExpander()
        queries = qe.expand("Python news")
        has_year = any("2026" in q for q in queries)
        assert has_year

    def test_refine_from_results(self):
        qe = QueryExpander()
        refined = qe.refine_from_results(
            "Python tutorial",
            results_summary="Django Flask frameworks",
            gaps=["web development"],
        )
        assert len(refined) >= 1

    def test_refine_empty_results(self):
        qe = QueryExpander()
        refined = qe.refine_from_results("test", "", [])
        assert len(refined) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# HypothesisTester
# ═══════════════════════════════════════════════════════════════════════════════


class TestHypothesisTester:
    """HypothesisTester — проверка гипотез."""

    def test_generate_binary(self):
        ht = HypothesisTester()
        hypotheses = ht.generate_hypotheses("Можно ли пить кофе на ночь?")
        assert len(hypotheses) >= 2  # ДА и НЕТ

    def test_generate_comparison(self):
        ht = HypothesisTester()
        hypotheses = ht.generate_hypotheses("Python или JavaScript?")
        assert len(hypotheses) >= 2

    def test_generate_general(self):
        ht = HypothesisTester()
        hypotheses = ht.generate_hypotheses("Что такое квантовые компьютеры?")
        assert len(hypotheses) >= 1

    def test_hypothesis_net_evidence(self):
        h = Hypothesis(
            evidence_for=[FactClaim(text="supports", trust_score=0.9)],
            evidence_against=[FactClaim(text="opposes", trust_score=0.3)],
        )
        assert h.net_evidence > 0

    def test_hypothesis_to_dict(self):
        h = Hypothesis(statement="Test", confidence=0.7, status="confirmed")
        d = h.to_dict()
        assert d["statement"] == "Test"
        assert d["confidence"] == 0.7
        assert d["status"] == "confirmed"

    def test_evaluate_hypothesis(self):
        ht = HypothesisTester()
        h = Hypothesis(statement="Python is popular programming language")
        facts = [
            FactClaim(text="Python is the most popular programming language in 2026",
                      trust_score=0.9),
        ]
        result = ht.evaluate_hypothesis(h, facts)
        assert result.confidence >= 0.5  # Should be confirmed-ish

    def test_evaluate_hypothesis_negative(self):
        ht = HypothesisTester()
        h = Hypothesis(statement="This claim is correct true")
        facts = [
            FactClaim(text="This claim is not correct false wrong",
                      trust_score=0.8),
        ]
        result = ht.evaluate_hypothesis(h, facts)
        assert result.status in ("uncertain", "rejected")


# ═══════════════════════════════════════════════════════════════════════════════
# ContextCompressor
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextCompressor:
    """ContextCompressor — сжатие контекста."""

    def test_short_text_unchanged(self):
        cc = ContextCompressor()
        text = "Short text."
        assert cc.compress(text, max_length=1000) == text

    def test_truncate_strategy(self):
        cc = ContextCompressor()
        text = "A" * 500
        result = cc.compress(text, max_length=100, strategy="truncate")
        assert len(result) <= 104  # 100 + "..."

    def test_extractive_strategy(self):
        cc = ContextCompressor()
        text = (
            "This is an important sentence about results. "
            "Another sentence here. "
            "The key finding is that Python is popular. "
            "Some filler text that is not very important. "
            "In conclusion, the data shows significant growth."
        )
        result = cc.compress(text, max_length=200, strategy="extractive")
        assert len(result) <= 200

    def test_deduplicate(self):
        cc = ContextCompressor()
        texts = [
            "Python is a great programming language",
            "Python is a great programming language",  # exact dup
            "JavaScript is used for web development",
        ]
        unique = cc.deduplicate(texts)
        assert len(unique) == 2

    def test_deduplicate_similar(self):
        cc = ContextCompressor()
        texts = [
            "Python is a great programming language for data science",
            "Python is a great programming language for data analysis",
            "JavaScript is used for web development",
        ]
        unique = cc.deduplicate(texts)
        # The two Python sentences are very similar
        assert len(unique) <= 2

    def test_deduplicate_empty(self):
        cc = ContextCompressor()
        assert cc.deduplicate([]) == []

    def test_chunk(self):
        cc = ContextCompressor()
        text = "A " * 500  # 1000 chars
        chunks = cc.chunk(text, chunk_size=300, overlap=50)
        assert len(chunks) >= 3

    def test_chunk_short(self):
        cc = ContextCompressor()
        text = "Short text"
        chunks = cc.chunk(text, chunk_size=1000)
        assert len(chunks) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# ConfidenceEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceEngine:
    """ConfidenceEngine — оценка уверенности."""

    def test_no_facts(self):
        ce = ConfidenceEngine()
        assessment = ce.assess([])
        assert assessment.overall < 0.2
        assert assessment.needs_more_data is True

    def test_single_high_trust(self):
        ce = ConfidenceEngine()
        facts = [FactClaim(text="Test fact", trust_score=0.9)]
        assessment = ce.assess(facts)
        assert assessment.overall > 0.3

    def test_multiple_facts_good(self):
        ce = ConfidenceEngine()
        facts = [
            FactClaim(text="Fact 1", trust_score=0.9),
            FactClaim(text="Fact 2", trust_score=0.85),
            FactClaim(text="Fact 3", trust_score=0.8),
        ]
        assessment = ce.assess(facts)
        assert assessment.overall > 0.6

    def test_with_contradictions(self):
        ce = ConfidenceEngine()
        facts = [
            FactClaim(text="A", trust_score=0.8),
            FactClaim(text="B", trust_score=0.8),
        ]
        contradictions = [
            Contradiction(
                claim_a=facts[0], claim_b=facts[1], description="test"
            )
        ]
        assessment = ce.assess(facts, contradictions)
        # Contradictions lower consensus
        assert assessment.consensus < 1.0

    def test_confidence_label_high(self):
        a = ConfidenceAssessment(overall=0.9)
        assert "🟢" in a.label

    def test_confidence_label_low(self):
        a = ConfidenceAssessment(overall=0.45)
        assert "🟠" in a.label

    def test_confidence_to_dict(self):
        a = ConfidenceAssessment(overall=0.75, gaps=["Missing data"])
        d = a.to_dict()
        assert d["overall"] == 0.75
        assert "Missing data" in d["gaps"]


# ═══════════════════════════════════════════════════════════════════════════════
# StalenessDetector
# ═══════════════════════════════════════════════════════════════════════════════


class TestStalenessDetector:
    """StalenessDetector — определение устаревших данных."""

    def test_detect_category_news(self):
        sd = StalenessDetector()
        assert sd.detect_category("последние новости") == "news"

    def test_detect_category_prices(self):
        sd = StalenessDetector()
        assert sd.detect_category("цена айфона") == "prices"

    def test_detect_category_technology(self):
        sd = StalenessDetector()
        assert sd.detect_category("new AI technology") == "technology"

    def test_detect_category_general(self):
        sd = StalenessDetector()
        assert sd.detect_category("something random") == "general"

    def test_is_stale_old_news(self):
        sd = StalenessDetector()
        old = datetime.utcnow() - timedelta(days=30)
        stale, reason = sd.is_stale(old, "news")
        assert stale is True
        assert "устарели" in reason

    def test_is_stale_fresh_news(self):
        sd = StalenessDetector()
        fresh = datetime.utcnow() - timedelta(hours=2)
        stale, _ = sd.is_stale(fresh, "news")
        assert stale is False

    def test_is_stale_old_prices(self):
        sd = StalenessDetector()
        old = datetime.utcnow() - timedelta(days=3)
        stale, _ = sd.is_stale(old, "prices")
        assert stale is True

    def test_filter_fresh(self):
        sd = StalenessDetector()
        now = datetime.utcnow()
        facts = [
            FactClaim(text="Fresh", timestamp=now),
            FactClaim(text="Old", timestamp=now - timedelta(days=400)),
        ]
        fresh = sd.filter_fresh(facts, "general")
        assert len(fresh) == 1
        assert fresh[0].text == "Fresh"


# ═══════════════════════════════════════════════════════════════════════════════
# ReasoningResult dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestReasoningResult:
    """ReasoningResult — результат reasoning."""

    def test_to_dict(self):
        r = ReasoningResult(answer="Test answer", sources_used=3)
        d = r.to_dict()
        assert d["answer"] == "Test answer"
        assert d["sources_used"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# ReasoningLayerV2
# ═══════════════════════════════════════════════════════════════════════════════


class TestReasoningLayerV2:
    """ReasoningLayerV2 — объединяющий движок."""

    def test_init_components(self):
        rl = ReasoningLayerV2()
        assert rl.trust_scorer is not None
        assert rl.contradiction_detector is not None
        assert rl.query_expander is not None
        assert rl.compressor is not None
        assert rl.confidence_engine is not None

    def test_expand_query(self):
        rl = ReasoningLayerV2()
        queries = rl.expand_query("Python tutorial")
        assert len(queries) >= 1

    def test_score_facts(self):
        rl = ReasoningLayerV2()
        facts = [
            FactClaim(text="Long enough text about Python programming language",
                      source_url="https://wikipedia.org/wiki/Python"),
        ]
        scored = rl.score_facts(facts)
        assert scored[0].trust_score > 0.5

    def test_find_contradictions(self):
        rl = ReasoningLayerV2()
        facts = [
            FactClaim(text="A", source_url="https://a.com"),
            FactClaim(text="B", source_url="https://b.com"),
        ]
        contradictions = rl.find_contradictions(facts)
        assert isinstance(contradictions, list)

    def test_compress_context(self):
        rl = ReasoningLayerV2()
        text = "X " * 2000
        compressed = rl.compress_context(text, max_length=100)
        assert len(compressed) <= 104

    def test_generate_hypotheses(self):
        rl = ReasoningLayerV2()
        hypotheses = rl.generate_hypotheses("Is Python good?")
        assert len(hypotheses) >= 1

    def test_get_stats(self):
        rl = ReasoningLayerV2()
        stats = rl.get_stats()
        assert "trust_domains_tracked" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# Global instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestReasoningV2Global:
    """Глобальный экземпляр."""

    def test_global_exists(self):
        assert reasoning_v2 is not None
        assert isinstance(reasoning_v2, ReasoningLayerV2)
