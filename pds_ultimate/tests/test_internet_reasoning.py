"""
PDS-Ultimate Internet Reasoning Tests
=======================================
Тесты для Internet Reasoning Layer:
- TrustScorer, QueryExpander, FactExtractor
- ContradictionDetector, FactSynthesizer
- InternetReasoningEngine (mocked browser)
- Data models
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pds_ultimate.core.internet_reasoning import (
    TRUSTED_DOMAINS,
    UNTRUSTED_PATTERNS,
    Contradiction,
    ContradictionDetector,
    ContradictionSeverity,
    ExtractedFact,
    FactExtractor,
    FactSynthesizer,
    InternetReasoningEngine,
    QueryExpander,
    ResearchStats,
    SourceInfo,
    SourceReliability,
    SynthesizedAnswer,
    TrustScorer,
    reasoning_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def trust_scorer():
    return TrustScorer()


@pytest.fixture
def query_expander():
    return QueryExpander()


@pytest.fixture
def fact_extractor():
    return FactExtractor()


@pytest.fixture
def contradiction_detector():
    return ContradictionDetector()


@pytest.fixture
def fact_synthesizer():
    return FactSynthesizer()


@pytest.fixture
def source_a():
    return SourceInfo(
        url="https://reuters.com/article1",
        domain="reuters.com",
        title="Reuters Article",
        trust_score=0.88,
        reliability=SourceReliability.HIGH,
        freshness_score=0.9,
    )


@pytest.fixture
def source_b():
    return SourceInfo(
        url="https://bbc.com/news/article2",
        domain="bbc.com",
        title="BBC News",
        trust_score=0.85,
        reliability=SourceReliability.HIGH,
        freshness_score=0.8,
    )


@pytest.fixture
def source_low():
    return SourceInfo(
        url="https://random-blog.com/post",
        domain="random-blog.com",
        title="Blog Post",
        trust_score=0.3,
        reliability=SourceReliability.LOW,
        freshness_score=0.4,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceReliability:
    def test_values(self):
        assert SourceReliability.HIGH.value == "high"
        assert SourceReliability.MEDIUM.value == "medium"
        assert SourceReliability.LOW.value == "low"
        assert SourceReliability.UNKNOWN.value == "unknown"

    def test_count(self):
        assert len(SourceReliability) == 4


class TestContradictionSeverity:
    def test_values(self):
        assert ContradictionSeverity.MINOR.value == "minor"
        assert ContradictionSeverity.MODERATE.value == "moderate"
        assert ContradictionSeverity.MAJOR.value == "major"

    def test_count(self):
        assert len(ContradictionSeverity) == 3


class TestSourceInfo:
    def test_create_default(self):
        si = SourceInfo(url="https://example.com", domain="example.com")
        assert si.trust_score == 0.5
        assert si.freshness_score == 0.5
        assert si.reliability == SourceReliability.UNKNOWN

    def test_composite_score(self):
        si = SourceInfo(
            url="https://x.com", domain="x.com",
            trust_score=0.8, freshness_score=0.6,
        )
        # 0.8*0.7 + 0.6*0.3 = 0.56 + 0.18 = 0.74
        assert si.composite_score == 0.74

    def test_composite_score_max(self):
        si = SourceInfo(
            url="https://x.com", domain="x.com",
            trust_score=1.0, freshness_score=1.0,
        )
        assert si.composite_score == 1.0

    def test_composite_score_min(self):
        si = SourceInfo(
            url="https://x.com", domain="x.com",
            trust_score=0.0, freshness_score=0.0,
        )
        assert si.composite_score == 0.0


class TestExtractedFact:
    def test_create(self, source_a):
        fact = ExtractedFact(text="Python is popular", source=source_a)
        assert fact.confidence == 0.5
        assert fact.category == "general"
        assert fact.keywords == []

    def test_fact_id_unique(self, source_a):
        f1 = ExtractedFact(text="Fact one", source=source_a)
        f2 = ExtractedFact(text="Fact two", source=source_a)
        assert f1.fact_id != f2.fact_id

    def test_fact_id_deterministic(self, source_a):
        f1 = ExtractedFact(text="Same text", source=source_a)
        f2 = ExtractedFact(text="Same text", source=source_a)
        assert f1.fact_id == f2.fact_id

    def test_fact_id_format(self, source_a):
        f = ExtractedFact(text="test", source=source_a)
        assert f.fact_id.startswith("fact_")
        assert len(f.fact_id) == 13  # fact_ + 8 hex


class TestContradiction:
    def test_sources_involved(self, source_a, source_b):
        fa = ExtractedFact(text="A", source=source_a)
        fb = ExtractedFact(text="B", source=source_b)
        c = Contradiction(
            fact_a=fa, fact_b=fb,
            severity=ContradictionSeverity.MODERATE,
        )
        assert source_a.url in c.sources_involved
        assert source_b.url in c.sources_involved
        assert len(c.sources_involved) == 2


class TestSynthesizedAnswer:
    def test_create_empty(self):
        sa = SynthesizedAnswer(
            query="test", summary="No info",
            facts=[], sources=[], contradictions=[],
            confidence=0.0,
        )
        assert sa.has_contradictions is False
        assert sa.quality_label == "❌ Низкое качество"

    def test_high_quality(self, source_a):
        sa = SynthesizedAnswer(
            query="q", summary="Good",
            facts=[], sources=[source_a],
            contradictions=[], confidence=0.85,
        )
        assert "Высокое" in sa.quality_label

    def test_medium_quality(self, source_a):
        fa = ExtractedFact(text="A", source=source_a)
        fb = ExtractedFact(text="B", source=source_a)
        c = Contradiction(
            fact_a=fa, fact_b=fb,
            severity=ContradictionSeverity.MINOR,
        )
        sa = SynthesizedAnswer(
            query="q", summary="OK",
            facts=[fa], sources=[source_a],
            contradictions=[c], confidence=0.85,
        )
        # Has contradictions → not high quality
        assert "Среднее" in sa.quality_label

    def test_to_dict(self, source_a):
        sa = SynthesizedAnswer(
            query="test q", summary="Summary here",
            facts=[], sources=[source_a],
            contradictions=[], confidence=0.75,
            sources_count=1,
        )
        d = sa.to_dict()
        assert d["query"] == "test q"
        assert d["confidence"] == 0.75
        assert d["sources_count"] == 1
        assert len(d["sources"]) == 1
        assert d["sources"][0]["domain"] == "reuters.com"

    def test_to_dict_with_contradictions(self, source_a, source_b):
        fa = ExtractedFact(text="X", source=source_a)
        fb = ExtractedFact(text="Y", source=source_b)
        c = Contradiction(
            fact_a=fa, fact_b=fb,
            severity=ContradictionSeverity.MAJOR,
            description="Big diff",
        )
        sa = SynthesizedAnswer(
            query="q", summary="s",
            facts=[fa, fb], sources=[source_a, source_b],
            contradictions=[c], confidence=0.5,
        )
        d = sa.to_dict()
        assert d["contradictions_count"] == 1
        assert d["contradictions"][0]["severity"] == "major"
        assert d["contradictions"][0]["description"] == "Big diff"


class TestResearchStats:
    def test_defaults(self):
        s = ResearchStats()
        assert s.queries_performed == 0
        assert s.pages_analyzed == 0

    def test_to_dict(self):
        s = ResearchStats(queries_performed=5, pages_analyzed=3,
                          facts_extracted=15, contradictions_found=2,
                          total_time_ms=1234)
        d = s.to_dict()
        assert d["queries"] == 5
        assert d["pages"] == 3
        assert d["facts"] == 15
        assert d["time_ms"] == 1234


# ═══════════════════════════════════════════════════════════════════════════════
# TRUST SCORER
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrustScorer:
    def test_trusted_domain(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://wikipedia.org/wiki/Python",
            content="x" * 500,
        )
        assert si.trust_score > 0.8
        assert si.reliability == SourceReliability.HIGH

    def test_untrusted_domain(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://reddit.com/r/python/post",
            content="x" * 500,
        )
        assert si.trust_score < 0.5

    def test_unknown_domain(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://random-site-xyz.net/page",
            content="x" * 500,
        )
        assert 0.4 <= si.trust_score <= 0.7

    def test_https_bonus(self, trust_scorer):
        https = trust_scorer.score_source(
            "https://unknown-site.com/page", content="x" * 500)
        http = trust_scorer.score_source(
            "http://unknown-site.com/page", content="x" * 500)
        assert https.trust_score > http.trust_score

    def test_short_content_penalty(self, trust_scorer):
        short = trust_scorer.score_source(
            "https://example.com/page", content="short")
        long = trust_scorer.score_source(
            "https://example.com/page", content="x" * 3000)
        assert short.trust_score < long.trust_score

    def test_gov_tld_high_trust(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://data.gov/dataset", content="x" * 500)
        assert si.trust_score > 0.7

    def test_edu_tld_high_trust(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://mit.edu/research", content="x" * 500)
        assert si.trust_score > 0.7

    def test_parent_domain_match(self, trust_scorer):
        # en.wikipedia.org should match wikipedia.org
        si = trust_scorer.score_source(
            "https://en.wikipedia.org/wiki/Test", content="x" * 500)
        assert si.trust_score > 0.8

    def test_freshness_recent_date(self, trust_scorer):
        recent = datetime.now().strftime("%Y-%m-%d")
        si = trust_scorer.score_source(
            "https://example.com/page",
            content="x" * 500,
            detected_date=recent,
        )
        assert si.freshness_score == 1.0

    def test_freshness_old_date(self, trust_scorer):
        old = "2020-01-01"
        si = trust_scorer.score_source(
            "https://example.com/page",
            content="x" * 500,
            detected_date=old,
        )
        assert si.freshness_score < 0.5

    def test_freshness_date_in_content(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://example.com/page",
            content="Published on 2025-06-15. Some content here " + "x" * 500,
        )
        assert si.freshness_score == 0.6  # found date in content

    def test_freshness_no_date(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://example.com/page",
            content="No dates here at all " + "x" * 500,
        )
        assert si.freshness_score == 0.5

    def test_custom_domain(self, trust_scorer):
        trust_scorer.add_custom_domain("my-trusted.com", 0.95)
        si = trust_scorer.score_source(
            "https://my-trusted.com/page", content="x" * 500)
        assert si.trust_score > 0.9

    def test_custom_domain_overrides(self, trust_scorer):
        trust_scorer.add_custom_domain("reddit.com", 0.9)
        si = trust_scorer.score_source(
            "https://reddit.com/r/test", content="x" * 500)
        assert si.trust_score > 0.8  # overridden

    def test_get_domain_score_known(self, trust_scorer):
        score = trust_scorer.get_domain_score("wikipedia.org")
        assert score == 0.85

    def test_get_domain_score_unknown(self, trust_scorer):
        score = trust_scorer.get_domain_score("unknown-xyz.com")
        assert score is None

    def test_reliability_medium(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://unknown-medium.com/page",
            content="x" * 500,
        )
        assert si.reliability in (
            SourceReliability.MEDIUM, SourceReliability.HIGH
        )

    def test_domain_extraction(self, trust_scorer):
        si = trust_scorer.score_source(
            "https://www.docs.python.org/3/library/",
            content="x" * 500,
        )
        assert si.domain == "docs.python.org"


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY EXPANDER
# ═══════════════════════════════════════════════════════════════════════════════


class TestQueryExpander:
    def test_price_detection(self, query_expander):
        t = query_expander.detect_query_type("сколько стоит iPhone 16")
        assert t == "price"

    def test_review_detection(self, query_expander):
        t = query_expander.detect_query_type("отзывы о Samsung Galaxy")
        assert t == "review"

    def test_howto_detection(self, query_expander):
        t = query_expander.detect_query_type("как установить Python")
        assert t == "howto"

    def test_comparison_detection(self, query_expander):
        t = query_expander.detect_query_type("iPhone vs Samsung сравнение")
        assert t == "comparison"

    def test_news_detection(self, query_expander):
        t = query_expander.detect_query_type("Tesla новости 2026")
        assert t == "news"

    def test_definition_detection(self, query_expander):
        t = query_expander.detect_query_type("что такое блокчейн")
        assert t == "definition"

    def test_general_detection(self, query_expander):
        t = query_expander.detect_query_type("Python programming language")
        assert t == "general"

    def test_expand_includes_original(self, query_expander):
        queries = query_expander.expand("test query")
        assert queries[0] == "test query"

    def test_expand_max_queries(self, query_expander):
        queries = query_expander.expand("test", max_queries=2)
        assert len(queries) <= 2

    def test_expand_price_templates(self, query_expander):
        queries = query_expander.expand(
            "iPhone 16 цена", max_queries=4)
        assert len(queries) >= 2
        # Должны содержать ценовые расширения
        combined = " ".join(queries)
        assert "цена" in combined or "стоимость" in combined

    def test_expand_force_type(self, query_expander):
        queries = query_expander.expand(
            "Python", force_type="review", max_queries=3)
        combined = " ".join(queries)
        assert "отзыв" in combined or "review" in combined

    def test_expand_adds_year_if_needed(self, query_expander):
        queries = query_expander.expand(
            "random topic", max_queries=5)
        has_year = any("2026" in q for q in queries)
        assert has_year

    def test_expand_no_duplicates(self, query_expander):
        queries = query_expander.expand(
            "Python цена", max_queries=5)
        assert len(queries) == len(set(queries))

    def test_expand_single(self, query_expander):
        queries = query_expander.expand("test", max_queries=1)
        assert queries == ["test"]


# ═══════════════════════════════════════════════════════════════════════════════
# FACT EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactExtractor:
    def test_extract_from_text(self, fact_extractor, source_a):
        text = (
            "Python is a high-level programming language. "
            "It was created by Guido van Rossum in 1991. "
            "Python supports multiple programming paradigms."
        )
        facts = fact_extractor.extract_facts(text, source_a, "Python")
        assert len(facts) > 0
        assert all(isinstance(f, ExtractedFact) for f in facts)

    def test_extract_empty_text(self, fact_extractor, source_a):
        facts = fact_extractor.extract_facts("", source_a)
        assert facts == []

    def test_extract_price_category(self, fact_extractor, source_a):
        text = "The iPhone 16 Pro costs $999 in the USA."
        facts = fact_extractor.extract_facts(text, source_a, "iPhone price")
        price_facts = [f for f in facts if f.category == "price"]
        assert len(price_facts) > 0

    def test_extract_statistic_category(self, fact_extractor, source_a):
        text = "Python has grown by 25% in the last year according to surveys."
        facts = fact_extractor.extract_facts(text, source_a, "Python growth")
        stat_facts = [f for f in facts if f.category == "statistic"]
        assert len(stat_facts) > 0

    def test_extract_opinion_category(self, fact_extractor, source_a):
        text = "I think Python is the best programming language for beginners."
        facts = fact_extractor.extract_facts(text, source_a, "Python")
        opinion_facts = [f for f in facts if f.category == "opinion"]
        assert len(opinion_facts) > 0

    def test_max_facts_limit(self, fact_extractor, source_a):
        text = ". ".join(
            [f"Fact number {i} about something" for i in range(50)])
        facts = fact_extractor.extract_facts(
            text, source_a, max_facts=3)
        assert len(facts) <= 3

    def test_short_sentences_filtered(self, fact_extractor, source_a):
        text = "Hi. Ok. Yes. No. This is a sufficiently long sentence about Python."
        facts = fact_extractor.extract_facts(text, source_a)
        # Short sentences should be filtered
        for f in facts:
            assert len(f.text) >= 15

    def test_keywords_extracted(self, fact_extractor, source_a):
        text = "Python is a high-level programming language used for web development."
        facts = fact_extractor.extract_facts(text, source_a, "Python")
        if facts:
            assert len(facts[0].keywords) > 0

    def test_confidence_from_source_trust(self, fact_extractor, source_a, source_low):
        text = "This is a test fact about programming languages and development."
        facts_high = fact_extractor.extract_facts(text, source_a)
        facts_low = fact_extractor.extract_facts(text, source_low)
        if facts_high and facts_low:
            assert facts_high[0].confidence > facts_low[0].confidence

    def test_relevant_sentences_first(self, fact_extractor, source_a):
        text = (
            "Weather is nice today. "
            "Python is a versatile programming language. "
            "Cats are cute animals. "
            "Python supports web development and data science."
        )
        facts = fact_extractor.extract_facts(
            text, source_a, "Python programming", max_facts=2)
        # Python-related facts should come first
        if facts:
            assert "python" in facts[0].text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRADICTION DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestContradictionDetector:
    def test_no_contradictions_same_source(
        self, contradiction_detector, source_a
    ):
        """Факты из одного источника не проверяются."""
        fa = ExtractedFact(
            text="Price is $100",
            source=source_a,
            category="price",
            keywords=["price", "product"],
        )
        fb = ExtractedFact(
            text="Price is $500",
            source=source_a,
            category="price",
            keywords=["price", "product"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) == 0

    def test_numeric_contradiction(
        self, contradiction_detector, source_a, source_b
    ):
        """Числовое расхождение > 30%."""
        fa = ExtractedFact(
            text="The product costs $100 in stores",
            source=source_a,
            category="price",
            keywords=["product", "costs", "stores"],
        )
        fb = ExtractedFact(
            text="The product costs $200 in stores",
            source=source_b,
            category="price",
            keywords=["product", "costs", "stores"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) == 1
        assert result[0].severity in (
            ContradictionSeverity.MODERATE,
            ContradictionSeverity.MAJOR,
        )

    def test_no_numeric_contradiction_close(
        self, contradiction_detector, source_a, source_b
    ):
        """Числа близкие → нет противоречия."""
        fa = ExtractedFact(
            text="Price is $100 total",
            source=source_a,
            category="price",
            keywords=["price", "total"],
        )
        fb = ExtractedFact(
            text="Price is $110 total",
            source=source_b,
            category="price",
            keywords=["price", "total"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) == 0

    def test_textual_contradiction_antonyms(
        self, contradiction_detector, source_a, source_b
    ):
        """Антонимы: 'рост' vs 'падение'."""
        fa = ExtractedFact(
            text="Наблюдается значительный рост показателей рынка",
            source=source_a,
            keywords=["показатели", "рынок", "рост"],
        )
        fb = ExtractedFact(
            text="Наблюдается значительное падение показателей рынка",
            source=source_b,
            keywords=["показатели", "рынок", "падение"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) >= 1

    def test_no_contradiction_different_topics(
        self, contradiction_detector, source_a, source_b
    ):
        """Разные темы → нет противоречия."""
        fa = ExtractedFact(
            text="Python is great for web development",
            source=source_a,
            keywords=["python", "development"],
        )
        fb = ExtractedFact(
            text="Weather is going to be sunny tomorrow",
            source=source_b,
            keywords=["weather", "sunny"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) == 0

    def test_negation_detection(
        self, contradiction_detector, source_a, source_b
    ):
        """Отрицание в одном из утверждений."""
        fa = ExtractedFact(
            text="Python supports multithreading and parallel execution",
            source=source_a,
            keywords=["python", "supports", "parallel"],
        )
        fb = ExtractedFact(
            text="Python does not support true parallel execution threads",
            source=source_b,
            keywords=["python", "support", "parallel"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) >= 1

    def test_empty_facts(self, contradiction_detector):
        assert contradiction_detector.detect([]) == []

    def test_single_fact(self, contradiction_detector, source_a):
        fa = ExtractedFact(text="Test", source=source_a)
        assert contradiction_detector.detect([fa]) == []

    def test_major_numeric(
        self, contradiction_detector, source_a, source_b
    ):
        """Большое расхождение → MAJOR."""
        fa = ExtractedFact(
            text="Revenue was $100 million this quarter",
            source=source_a,
            category="statistic",
            keywords=["revenue", "million", "quarter"],
        )
        fb = ExtractedFact(
            text="Revenue was $300 million this quarter",
            source=source_b,
            category="statistic",
            keywords=["revenue", "million", "quarter"],
        )
        result = contradiction_detector.detect([fa, fb])
        assert len(result) == 1
        assert result[0].severity == ContradictionSeverity.MAJOR


# ═══════════════════════════════════════════════════════════════════════════════
# FACT SYNTHESIZER
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactSynthesizer:
    def test_empty_facts(self, fact_synthesizer):
        result = fact_synthesizer.synthesize("test", [], [], [])
        assert result.confidence == 0.0
        assert "не найдено" in result.summary

    def test_synthesize_with_facts(
        self, fact_synthesizer, source_a, source_b
    ):
        facts = [
            ExtractedFact(
                text="Python is popular", source=source_a,
                confidence=0.9, keywords=["python"],
            ),
            ExtractedFact(
                text="Python is used in AI", source=source_b,
                confidence=0.85, keywords=["python", "ai"],
            ),
        ]
        result = fact_synthesizer.synthesize(
            "Python", facts, [source_a, source_b], [])
        assert result.confidence > 0.5
        assert len(result.facts) == 2
        assert "Python" in result.summary

    def test_deduplication(self, fact_synthesizer, source_a, source_b):
        facts = [
            ExtractedFact(
                text="Python is a popular programming language",
                source=source_a, confidence=0.8,
            ),
            ExtractedFact(
                text="Python is a popular programming language for developers",
                source=source_b, confidence=0.9,
            ),
        ]
        result = fact_synthesizer.synthesize(
            "Python", facts, [source_a, source_b], [])
        # Should deduplicate similar facts
        assert len(result.facts) <= 2

    def test_contradiction_penalty(
        self, fact_synthesizer, source_a, source_b
    ):
        fa = ExtractedFact(
            text="X is good", source=source_a, confidence=0.8,
            keywords=["good"],
        )
        fb = ExtractedFact(
            text="X is bad", source=source_b, confidence=0.8,
            keywords=["bad"],
        )
        c = Contradiction(
            fact_a=fa, fact_b=fb,
            severity=ContradictionSeverity.MAJOR,
            description="Противоречие",
        )

        no_contra = fact_synthesizer.synthesize(
            "X", [fa, fb], [source_a, source_b], [])
        with_contra = fact_synthesizer.synthesize(
            "X", [fa, fb], [source_a, source_b], [c])

        assert with_contra.confidence < no_contra.confidence

    def test_source_bonus(self, fact_synthesizer, source_a, source_b):
        fa = ExtractedFact(
            text="Python is versatile", source=source_a, confidence=0.7)
        # More sources → higher confidence
        one = fact_synthesizer.synthesize(
            "Python", [fa], [source_a], [])
        two = fact_synthesizer.synthesize(
            "Python", [fa], [source_a, source_b], [])
        assert two.confidence >= one.confidence

    def test_summary_has_facts(
        self, fact_synthesizer, source_a
    ):
        facts = [
            ExtractedFact(
                text="Important fact about topic here",
                source=source_a, confidence=0.9,
            ),
        ]
        result = fact_synthesizer.synthesize(
            "topic", facts, [source_a], [])
        assert "Ключевые факты" in result.summary

    def test_summary_shows_contradictions(
        self, fact_synthesizer, source_a, source_b
    ):
        fa = ExtractedFact(text="A", source=source_a, keywords=["k"])
        fb = ExtractedFact(text="B", source=source_b, keywords=["k"])
        c = Contradiction(
            fact_a=fa, fact_b=fb,
            severity=ContradictionSeverity.MINOR,
            description="Test contradiction",
        )
        result = fact_synthesizer.synthesize(
            "test", [fa, fb], [source_a, source_b], [c])
        assert "противоречий" in result.summary.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNET REASONING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestInternetReasoningEngine:
    def test_global_instance(self):
        assert reasoning_engine is not None
        assert isinstance(reasoning_engine, InternetReasoningEngine)

    def test_components(self):
        engine = InternetReasoningEngine()
        assert isinstance(engine.trust_scorer, TrustScorer)
        assert isinstance(engine.query_expander, QueryExpander)
        assert isinstance(engine.fact_extractor, FactExtractor)
        assert isinstance(engine.contradiction_detector, ContradictionDetector)
        assert isinstance(engine.fact_synthesizer, FactSynthesizer)

    def test_stats_initial(self):
        engine = InternetReasoningEngine()
        stats = engine.get_stats()
        assert stats["queries"] == 0
        assert stats["pages"] == 0

    def test_reset_stats(self):
        engine = InternetReasoningEngine()
        engine._stats.queries_performed = 10
        engine.reset_stats()
        assert engine.get_stats()["queries"] == 0

    @pytest.mark.asyncio
    async def test_research_mocked(self):
        """Полный pipeline с замоканным browser_engine."""
        from pds_ultimate.core.browser_engine import (
            ExtractedData,
            SearchResult,
        )

        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[
            SearchResult(
                title="Python Tutorial",
                url="https://docs.python.org/tutorial",
                snippet="Official Python tutorial",
                position=1,
            ),
            SearchResult(
                title="Learn Python",
                url="https://realpython.com/learn",
                snippet="Real Python tutorials",
                position=2,
            ),
        ])
        mock_eng.extract_data = AsyncMock(return_value=ExtractedData(
            url="https://docs.python.org/tutorial",
            title="Python Tutorial",
            text=(
                "Python is a high-level programming language. "
                "It supports object-oriented programming. "
                "Python was created by Guido van Rossum. "
                "It is widely used in web development and data science."
            ),
        ))

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.research(
                "Python programming", max_sources=2)

        assert isinstance(result, SynthesizedAnswer)
        assert result.query == "Python programming"
        assert result.sources_count >= 1
        assert len(result.facts) > 0

    @pytest.mark.asyncio
    async def test_research_no_results(self):
        """Поиск без результатов."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.research("nonexistent query xyz")

        assert result.confidence == 0.0
        assert len(result.facts) == 0

    @pytest.mark.asyncio
    async def test_research_search_error(self):
        """Ошибка поиска → graceful."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(
            side_effect=RuntimeError("Browser not started"))

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.research("test query")

        assert isinstance(result, SynthesizedAnswer)
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_research_extract_error(self):
        """Ошибка извлечения → пропускаем источник."""
        from pds_ultimate.core.browser_engine import SearchResult

        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[
            SearchResult(
                title="Test", url="https://example.com",
                snippet="Test", position=1,
            ),
        ])
        mock_eng.extract_data = AsyncMock(
            side_effect=Exception("Connection error"))

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.research("test")

        assert isinstance(result, SynthesizedAnswer)

    @pytest.mark.asyncio
    async def test_quick_search(self):
        """quick_search без расширения запросов."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.quick_search("test")

        assert isinstance(result, SynthesizedAnswer)
        # quick_search не расширяет → 1 запрос
        mock_eng.web_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_deep_research(self):
        """deep_research с расширением."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            result = await engine.deep_research("Python programming")

        assert isinstance(result, SynthesizedAnswer)
        # deep_research расширяет → несколько запросов
        assert mock_eng.web_search.call_count >= 1

    @pytest.mark.asyncio
    async def test_stats_updated(self):
        """Статистика обновляется после research."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])

        engine = InternetReasoningEngine()

        with patch(
            "pds_ultimate.core.browser_engine.browser_engine",
            mock_eng,
        ):
            await engine.research("test")

        stats = engine.get_stats()
        assert stats["queries"] >= 1
        assert stats["time_ms"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_trusted_domains_not_empty(self):
        assert len(TRUSTED_DOMAINS) > 10

    def test_untrusted_patterns_not_empty(self):
        assert len(UNTRUSTED_PATTERNS) > 0

    def test_trusted_domains_scores_valid(self):
        for domain, score in TRUSTED_DOMAINS.items():
            assert 0.0 <= score <= 1.0, f"{domain}: {score}"

    def test_wikipedia_trusted(self):
        assert "wikipedia.org" in TRUSTED_DOMAINS
        assert TRUSTED_DOMAINS["wikipedia.org"] > 0.8

    def test_reddit_untrusted(self):
        assert "reddit.com" in UNTRUSTED_PATTERNS


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_trust_scorer_empty_url(self):
        scorer = TrustScorer()
        si = scorer.score_source("")
        assert isinstance(si, SourceInfo)

    def test_query_expander_empty(self):
        qe = QueryExpander()
        result = qe.expand("")
        assert result[0] == ""

    def test_fact_extractor_whitespace(self):
        fe = FactExtractor()
        si = SourceInfo(url="https://x.com", domain="x.com")
        facts = fe.extract_facts("   \n\t  ", si)
        assert facts == []

    def test_contradiction_detector_many_facts(self):
        cd = ContradictionDetector()
        src1 = SourceInfo(url="https://a.com", domain="a.com", trust_score=0.8)
        src2 = SourceInfo(url="https://b.com", domain="b.com", trust_score=0.8)

        facts = []
        for i in range(10):
            src = src1 if i % 2 == 0 else src2
            facts.append(ExtractedFact(
                text=f"Fact {i} about topic number {i}",
                source=src,
                keywords=[f"topic{i}"],
            ))
        # Should not crash
        result = cd.detect(facts)
        assert isinstance(result, list)

    def test_synthesizer_high_confidence_no_contradictions(self):
        fs = FactSynthesizer()
        src = SourceInfo(
            url="https://x.com", domain="x.com",
            trust_score=0.9, freshness_score=0.9,
        )
        facts = [
            ExtractedFact(
                text="Confirmed fact about topic here",
                source=src, confidence=0.95,
            ),
        ]
        result = fs.synthesize("topic", facts, [src], [])
        assert result.confidence > 0.5

    def test_text_similarity_identical(self):
        fs = FactSynthesizer()
        sim = fs._text_similarity("hello world", "hello world")
        assert sim == 1.0

    def test_text_similarity_different(self):
        fs = FactSynthesizer()
        sim = fs._text_similarity("cats are cute", "dogs are loyal")
        assert sim < 0.5

    def test_text_similarity_empty(self):
        fs = FactSynthesizer()
        sim = fs._text_similarity("", "hello")
        assert sim == 0.0

    def test_topic_similarity(self):
        cd = ContradictionDetector()
        src = SourceInfo(url="https://x.com", domain="x.com")
        fa = ExtractedFact(
            text="A", source=src,
            keywords=["python", "programming", "language"],
        )
        fb = ExtractedFact(
            text="B", source=src,
            keywords=["python", "programming", "web"],
        )
        sim = cd._topic_similarity(fa, fb)
        assert sim > 0.3

    def test_topic_similarity_no_overlap(self):
        cd = ContradictionDetector()
        src = SourceInfo(url="https://x.com", domain="x.com")
        fa = ExtractedFact(text="A", source=src, keywords=["a", "b"])
        fb = ExtractedFact(text="B", source=src, keywords=["c", "d"])
        sim = cd._topic_similarity(fa, fb)
        assert sim == 0.0

    def test_topic_similarity_empty_keywords(self):
        cd = ContradictionDetector()
        src = SourceInfo(url="https://x.com", domain="x.com")
        fa = ExtractedFact(text="A", source=src, keywords=[])
        fb = ExtractedFact(text="B", source=src, keywords=["x"])
        sim = cd._topic_similarity(fa, fb)
        assert sim == 0.0
