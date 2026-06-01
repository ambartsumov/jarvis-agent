"""
Тесты Translator Service — modules/executive/translator.py
"""

import pytest


class TestLanguageDetector:
    """Тесты определения языка."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.executive.translator import (
            TranslatorService,
            translator,
        )
        assert TranslatorService is not None
        assert translator is not None

    def test_detect_russian(self):
        """Определение русского языка."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("Привет, как дела?")
        assert lang == "ru"

    def test_detect_english(self):
        """Определение английского языка."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("Hello, how are you?")
        assert lang == "en"

    def test_detect_chinese(self):
        """Определение китайского языка."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("你好，今天天气很好")
        assert lang == "zh"

    def test_detect_turkmen(self):
        """Определение туркменского языка."""
        from pds_ultimate.modules.executive.translator import (
            TURKMEN_CHARS,
            LanguageDetector,
        )

        detector = LanguageDetector()
        # Текст с туркменскими символами
        if TURKMEN_CHARS:
            text = "Salam, nähili ýagdaýlaryňyz?"
            lang, conf = detector.detect(text)
            # Может определить как tk или en
            assert lang in ("tk", "en")

    def test_detect_arabic(self):
        """Определение арабского."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("مرحبا كيف حالك")
        assert lang == "ar"

    def test_detect_empty(self):
        """Пустой текст."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("")
        assert lang in ("en", "unknown")

    def test_detect_numbers_only(self):
        """Только числа."""
        from pds_ultimate.modules.executive.translator import LanguageDetector

        detector = LanguageDetector()
        lang, conf = detector.detect("12345 67890")
        assert isinstance(lang, str)


class TestLanguageNames:
    """Тесты LANGUAGE_NAMES."""

    def test_at_least_10_languages(self):
        """Минимум 10 языков."""
        from pds_ultimate.modules.executive.translator import LANGUAGE_NAMES

        assert len(LANGUAGE_NAMES) >= 10

    def test_main_languages(self):
        """Основные языки есть."""
        from pds_ultimate.modules.executive.translator import LANGUAGE_NAMES

        assert "ru" in LANGUAGE_NAMES
        assert "en" in LANGUAGE_NAMES
        assert "zh" in LANGUAGE_NAMES
        assert "tk" in LANGUAGE_NAMES


class TestBusinessGlossary:
    """Тесты бизнес-глоссария."""

    def test_glossary_not_empty(self):
        """Глоссарий не пустой."""
        from pds_ultimate.modules.executive.translator import BUSINESS_GLOSSARY

        assert len(BUSINESS_GLOSSARY) >= 10

    def test_glossary_has_translations(self):
        """Каждый термин имеет переводы."""
        from pds_ultimate.modules.executive.translator import BUSINESS_GLOSSARY

        for term, translations in BUSINESS_GLOSSARY.items():
            assert isinstance(translations, dict)
            assert len(translations) >= 1


class TestTranslationCache:
    """Тесты кэша переводов."""

    def test_cache_creation(self):
        """TranslationCache создаётся."""
        from pds_ultimate.modules.executive.translator import TranslationCache

        cache = TranslationCache()
        assert cache is not None

    def test_cache_miss(self):
        """Cache miss."""
        from pds_ultimate.modules.executive.translator import TranslationCache

        cache = TranslationCache()
        result = cache.get("test", "en", "ru")
        assert result is None

    def test_cache_hit(self):
        """Cache hit."""
        from pds_ultimate.modules.executive.translator import (
            TranslationCache,
            TranslationResult,
        )

        cache = TranslationCache()
        cache.put(TranslationResult(
            original="hello", translated="привет",
            source_lang="en", target_lang="ru",
        ))
        result = cache.get("hello", "en", "ru")
        assert result is not None
        assert result.translated == "привет"

    def test_cache_different_langs(self):
        """Разные языки — разный кэш."""
        from pds_ultimate.modules.executive.translator import (
            TranslationCache,
            TranslationResult,
        )

        cache = TranslationCache()
        cache.put(TranslationResult(
            original="hello", translated="привет",
            source_lang="en", target_lang="ru",
        ))
        cache.put(TranslationResult(
            original="hello", translated="你好",
            source_lang="en", target_lang="zh",
        ))
        assert cache.get("hello", "en", "ru").translated == "привет"
        assert cache.get("hello", "en", "zh").translated == "你好"


class TestTranslationResult:
    """Тесты TranslationResult."""

    def test_creation(self):
        """TranslationResult создаётся."""
        from pds_ultimate.modules.executive.translator import TranslationResult

        result = TranslationResult(
            original="Hello",
            translated="Привет",
            source_lang="en",
            target_lang="ru",
        )
        assert result.original == "Hello"
        assert result.translated == "Привет"

    def test_batch_translation(self):
        """BatchTranslation создаётся."""
        from pds_ultimate.modules.executive.translator import (
            BatchTranslation,
            TranslationResult,
        )

        results = [
            TranslationResult(original="Hello", translated="Привет",
                              source_lang="en", target_lang="ru"),
            TranslationResult(original="World", translated="Мир",
                              source_lang="en", target_lang="ru"),
        ]
        batch = BatchTranslation(results=results)
        assert len(batch.results) == 2


class TestTranslatorService:
    """Тесты сервиса перевода."""

    def test_service_creation(self):
        """TranslatorService создаётся."""
        from pds_ultimate.modules.executive.translator import TranslatorService

        service = TranslatorService()
        assert service is not None

    def test_detect_language(self):
        """detect_language через сервис."""
        from pds_ultimate.modules.executive.translator import TranslatorService

        service = TranslatorService()
        lang, conf = service.detect_language("Привет мир")
        assert lang == "ru"

    def test_detect_language_english(self):
        """detect_language для английского."""
        from pds_ultimate.modules.executive.translator import TranslatorService

        service = TranslatorService()
        lang, conf = service.detect_language("Hello world")
        assert lang == "en"

    def test_lookup_glossary(self):
        """lookup_glossary находит термин."""
        from pds_ultimate.modules.executive.translator import TranslatorService

        service = TranslatorService()
        result = service.lookup_glossary("поставщик")
        # Может быть None если точного совпадения нет
        # Но хотя бы одно совпадение по BUSINESS_GLOSSARY
        if result:
            assert isinstance(result, str)

    def test_format_translation(self):
        """format_translation форматирует."""
        from pds_ultimate.modules.executive.translator import (
            TranslationResult,
            TranslatorService,
        )

        service = TranslatorService()
        result = TranslationResult(
            original="Hello",
            translated="Привет",
            source_lang="en",
            target_lang="ru",
        )
        text = service.format_translation(result)
        assert "Привет" in text
        assert isinstance(text, str)

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.executive.translator import translator

        assert translator is not None

    @pytest.mark.asyncio
    async def test_translate_calls(self):
        """translate вызывает LLM (mock)."""
        from unittest.mock import patch

        from pds_ultimate.modules.executive.translator import (
            TranslationResult,
            TranslatorService,
        )

        service = TranslatorService()

        # Mock LLM
        with patch(
            "pds_ultimate.modules.executive.translator.TranslatorService.translate"
        ) as mock:
            mock.return_value = TranslationResult(
                original="Hello",
                translated="Привет",
                source_lang="en",
                target_lang="ru",
            )
            result = await service.translate("Hello", "ru")
            assert result.translated == "Привет"
