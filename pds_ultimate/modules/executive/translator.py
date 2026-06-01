"""
PDS-Ultimate Translator (Language Bridge)
=============================================
Языковой мост: авто-определение языка, перевод в реальном времени,
пакетный перевод для WhatsApp-сообщений.

По ТЗ §7.2:
- Авто-перевод WhatsApp: Китайский ↔ Русский ↔ Английский ↔ Туркменский
- Определение языка сообщения
- Пакетный перевод (список сообщений)
- Кэширование переводов
- Словарь бизнес-терминов (логистика, торговля)

Поддерживаемые языки:
    ru (Русский), en (English), zh (中文),
    tk (Türkmen), tr (Türkçe), ar (العربية)
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from pds_ultimate.config import logger

# ─── Data Models ─────────────────────────────────────────────────────────────

LANGUAGE_NAMES = {
    "ru": "Русский",
    "en": "English",
    "zh": "中文",
    "tk": "Türkmen",
    "tr": "Türkçe",
    "ar": "العربية",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "pt": "Português",
    "ja": "日本語",
    "ko": "한국어",
}


@dataclass
class TranslationResult:
    """Результат перевода."""
    original: str
    translated: str
    source_lang: str
    target_lang: str
    detected_lang: Optional[str] = None
    confidence: float = 0.0
    cached: bool = False
    translation_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "translated": self.translated,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "detected_lang": self.detected_lang,
            "confidence": round(self.confidence, 3),
            "cached": self.cached,
            "time_ms": round(self.translation_time_ms, 1),
        }


@dataclass
class BatchTranslation:
    """Результат пакетного перевода."""
    results: list[TranslationResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    from_cache: int = 0
    from_api: int = 0

    @property
    def success_count(self) -> int:
        return len([r for r in self.results if r.translated])

    def to_dict(self) -> dict:
        return {
            "count": len(self.results),
            "success": self.success_count,
            "from_cache": self.from_cache,
            "from_api": self.from_api,
            "total_time_ms": round(self.total_time_ms, 1),
        }


# ─── Language Detection ──────────────────────────────────────────────────────

# Unicode ranges for language detection
LANG_RANGES = {
    "zh": [
        (0x4E00, 0x9FFF),   # CJK Unified Ideographs
        (0x3400, 0x4DBF),   # CJK Extension A
        (0xF900, 0xFAFF),   # CJK Compatibility
    ],
    "ru": [
        (0x0400, 0x04FF),   # Cyrillic
        (0x0500, 0x052F),   # Cyrillic Supplement
    ],
    "ar": [
        (0x0600, 0x06FF),   # Arabic
        (0x0750, 0x077F),   # Arabic Supplement
    ],
    "ja": [
        (0x3040, 0x309F),   # Hiragana
        (0x30A0, 0x30FF),   # Katakana
    ],
    "ko": [
        (0xAC00, 0xD7AF),   # Hangul Syllables
    ],
}

# Turkmen-specific characters (Latin with diacritics)
TURKMEN_CHARS = set("ÄäÇçŇňÖöŞşÜüÝýŽž")


class LanguageDetector:
    """
    Определение языка текста по Unicode-диапазонам и характерным паттернам.

    Быстрый offline-детектор без API:
    - Анализ Unicode-символов
    - Характерные буквы для туркменского/турецкого
    - Статистический подсчёт
    """

    def detect(self, text: str) -> tuple[str, float]:
        """
        Определить язык текста.
        Returns: (language_code, confidence)
        """
        if not text or not text.strip():
            return ("en", 0.0)

        # Подсчёт символов по диапазонам
        scores: dict[str, int] = {}
        total_alpha = 0

        for char in text:
            cp = ord(char)

            if not char.isalpha() and not (0x4E00 <= cp <= 0x9FFF):
                continue

            total_alpha += 1

            for lang, ranges in LANG_RANGES.items():
                for start, end in ranges:
                    if start <= cp <= end:
                        scores[lang] = scores.get(lang, 0) + 1
                        break

            # Latin characters
            if char.isascii() and char.isalpha():
                scores.setdefault("latin", 0)
                scores["latin"] = scores.get("latin", 0) + 1

        if total_alpha == 0:
            return ("en", 0.0)

        # Проверяем туркменский (latin + специфические символы)
        if "latin" in scores and scores["latin"] > total_alpha * 0.5:
            turkmen_count = sum(1 for c in text if c in TURKMEN_CHARS)
            if turkmen_count >= 2:
                confidence = min(
                    turkmen_count / max(total_alpha, 1) * 10, 0.95)
                return ("tk", confidence)

            # Турецкий (similar to Turkmen but with İ, ı, ğ)
            turkish_chars = set("İıĞğ")
            turkish_count = sum(1 for c in text if c in turkish_chars)
            if turkish_count >= 2:
                confidence = min(turkish_count / max(total_alpha, 1) * 10, 0.9)
                return ("tr", confidence)

        # Выбираем язык с наибольшим score
        if scores:
            # Убираем "latin" — это fallback
            lang_scores = {k: v for k, v in scores.items() if k != "latin"}

            if lang_scores:
                best_lang = max(lang_scores, key=lang_scores.get)
                confidence = lang_scores[best_lang] / total_alpha
                return (best_lang, min(confidence, 0.99))

            # Только latin → English по умолчанию
            if "latin" in scores:
                return ("en", scores["latin"] / total_alpha)

        return ("en", 0.3)


# ─── Business Glossary ───────────────────────────────────────────────────────

BUSINESS_GLOSSARY: dict[str, dict[str, str]] = {
    # RU → ZH
    "поставщик": {"zh": "供应商", "en": "supplier"},
    "заказ": {"zh": "订单", "en": "order"},
    "доставка": {"zh": "发货", "en": "delivery"},
    "оплата": {"zh": "付款", "en": "payment"},
    "цена": {"zh": "价格", "en": "price"},
    "товар": {"zh": "商品", "en": "goods"},
    "склад": {"zh": "仓库", "en": "warehouse"},
    "контейнер": {"zh": "集装箱", "en": "container"},
    "накладная": {"zh": "运单", "en": "waybill"},
    "таможня": {"zh": "海关", "en": "customs"},
    "трек-номер": {"zh": "快递单号", "en": "tracking number"},
    "образец": {"zh": "样品", "en": "sample"},
    "качество": {"zh": "质量", "en": "quality"},
    "количество": {"zh": "数量", "en": "quantity"},
    "вес": {"zh": "重量", "en": "weight"},
    "объём": {"zh": "体积", "en": "volume"},
    "упаковка": {"zh": "包装", "en": "packaging"},
    "фабрика": {"zh": "工厂", "en": "factory"},
    "торговля": {"zh": "贸易", "en": "trade"},
    "прибыль": {"zh": "利润", "en": "profit"},
}


# ─── Translation Cache ──────────────────────────────────────────────────────

class TranslationCache:
    """LRU-кэш переводов."""

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, TranslationResult] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def _key(self, text: str, source: str, target: str) -> str:
        h = hashlib.md5(text.encode()).hexdigest()[:12]
        return f"{source}:{target}:{h}"

    def get(
        self, text: str, source: str, target: str,
    ) -> Optional[TranslationResult]:
        key = self._key(text, source, target)
        if key in self._cache:
            self._hits += 1
            self._cache.move_to_end(key)
            result = self._cache[key]
            result.cached = True
            return result
        self._misses += 1
        return None

    def put(self, result: TranslationResult) -> None:
        key = self._key(result.original, result.source_lang,
                        result.target_lang)
        self._cache[key] = result
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (
                round(self._hits / total, 3) if total > 0 else 0
            ),
        }


# ─── Translator Service ─────────────────────────────────────────────────────

class TranslatorService:
    """
    Языковой мост: перевод, определение языка, бизнес-глоссарий.

    Архитектура:
    - LanguageDetector: offline определение языка
    - DeepSeek LLM: основной движок перевода
    - TranslationCache: LRU-кэш результатов
    - Business Glossary: словарь торговых терминов
    - Batch API: пакетный перевод

    Использование:
        result = await translator.translate("Привет", target_lang="en")
        lang, conf = translator.detect_language("你好")
        batch = await translator.translate_batch(messages, target_lang="ru")
    """

    def __init__(self, cache_size: int = 1000):
        self._detector = LanguageDetector()
        self._cache = TranslationCache(max_size=cache_size)
        self._glossary = BUSINESS_GLOSSARY
        self._translation_count = 0
        self._total_chars = 0

    # ═══════════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════════

    def detect_language(self, text: str) -> tuple[str, float]:
        """Определить язык текста."""
        return self._detector.detect(text)

    def get_language_name(self, code: str) -> str:
        """Получить название языка по коду."""
        return LANGUAGE_NAMES.get(code, code)

    async def translate(
        self,
        text: str,
        target_lang: str = "ru",
        source_lang: Optional[str] = None,
    ) -> TranslationResult:
        """
        Перевести текст.

        Args:
            text: Исходный текст
            target_lang: Целевой язык (ru, en, zh, tk, tr, ar)
            source_lang: Исходный язык (auto-detect если None)
        """
        start = time.monotonic()

        if not text or not text.strip():
            return TranslationResult(
                original=text,
                translated=text,
                source_lang=source_lang or "?",
                target_lang=target_lang,
            )

        # Определяем язык если не указан
        detected = None
        if not source_lang:
            source_lang, det_conf = self.detect_language(text)
            detected = source_lang

        # Одинаковый язык — возврат
        if source_lang == target_lang:
            return TranslationResult(
                original=text,
                translated=text,
                source_lang=source_lang,
                target_lang=target_lang,
                detected_lang=detected,
                confidence=1.0,
            )

        # Кэш
        cached = self._cache.get(text, source_lang, target_lang)
        if cached:
            cached.translation_time_ms = (
                time.monotonic() - start
            ) * 1000
            return cached

        # Перевод через LLM
        translated = await self._translate_llm(
            text, source_lang, target_lang
        )

        elapsed = (time.monotonic() - start) * 1000
        self._translation_count += 1
        self._total_chars += len(text)

        result = TranslationResult(
            original=text,
            translated=translated,
            source_lang=source_lang,
            target_lang=target_lang,
            detected_lang=detected,
            confidence=0.9 if translated else 0.0,
            translation_time_ms=elapsed,
        )

        # Кэшировать
        if translated:
            self._cache.put(result)

        return result

    async def translate_batch(
        self,
        texts: list[str],
        target_lang: str = "ru",
        source_lang: Optional[str] = None,
    ) -> BatchTranslation:
        """
        Пакетный перевод списка текстов.
        Оптимизирует: кэш + объединение для одного LLM-запроса.
        """
        start = time.monotonic()
        results = []
        from_cache = 0
        from_api = 0
        to_translate = []

        # Проверяем кэш для каждого
        for text in texts:
            src = source_lang
            if not src:
                src, _ = self.detect_language(text)

            cached = self._cache.get(text, src, target_lang)
            if cached:
                results.append(cached)
                from_cache += 1
            else:
                to_translate.append((text, src))
                results.append(None)  # placeholder

        # Переводим оставшиеся
        if to_translate:
            # Объединяем для одного LLM-запроса (если < 10)
            if len(to_translate) <= 10:
                translations = await self._translate_batch_llm(
                    to_translate, target_lang
                )
            else:
                # По одному для больших пакетов
                translations = []
                for text, src in to_translate:
                    t = await self._translate_llm(text, src, target_lang)
                    translations.append(t)

            # Заполняем placeholders
            t_idx = 0
            for i, r in enumerate(results):
                if r is None:
                    text, src = to_translate[t_idx]
                    translated = (
                        translations[t_idx]
                        if t_idx < len(translations) else ""
                    )
                    result = TranslationResult(
                        original=text,
                        translated=translated,
                        source_lang=src,
                        target_lang=target_lang,
                        confidence=0.9 if translated else 0.0,
                    )
                    if translated:
                        self._cache.put(result)
                    results[i] = result
                    from_api += 1
                    t_idx += 1

        elapsed = (time.monotonic() - start) * 1000

        return BatchTranslation(
            results=results,
            total_time_ms=elapsed,
            from_cache=from_cache,
            from_api=from_api,
        )

    def lookup_glossary(
        self,
        term: str,
        target_lang: str = "zh",
    ) -> Optional[str]:
        """Найти бизнес-термин в глоссарии."""
        term_lower = term.lower().strip()
        entry = self._glossary.get(term_lower)
        if entry:
            return entry.get(target_lang)
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Formatting
    # ═══════════════════════════════════════════════════════════════════════

    def format_translation(self, result: TranslationResult) -> str:
        """Форматировать результат для бота."""
        src_name = self.get_language_name(result.source_lang)
        tgt_name = self.get_language_name(result.target_lang)

        lines = [f"🌐 Перевод ({src_name} → {tgt_name}):\n"]
        lines.append(f"  📝 {result.translated}")

        if result.detected_lang:
            det_name = self.get_language_name(result.detected_lang)
            lines.append(f"\n  🔍 Определён язык: {det_name}")

        if result.cached:
            lines.append("  ⚡ Из кэша")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Статистика переводчика."""
        return {
            "translations_total": self._translation_count,
            "total_chars": self._total_chars,
            "cache": self._cache.stats,
            "supported_languages": list(LANGUAGE_NAMES.keys()),
            "glossary_size": len(self._glossary),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Internal: LLM Translation
    # ═══════════════════════════════════════════════════════════════════════

    async def _translate_llm(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Перевод через DeepSeek LLM."""
        try:
            from pds_ultimate.core.llm_engine import llm_engine

            src_name = self.get_language_name(source_lang)
            tgt_name = self.get_language_name(target_lang)

            prompt = (
                f"Переведи следующий текст с {src_name} на {tgt_name}. "
                f"Верни ТОЛЬКО перевод, без объяснений и комментариев.\n\n"
                f"Текст: {text}"
            )

            result = await llm_engine.chat(
                message=prompt,
                task_type="translate",
                temperature=0.1,
            )

            return result.strip() if result else ""

        except Exception as e:
            logger.warning(f"[Translator] LLM translation failed: {e}")
            return ""

    async def _translate_batch_llm(
        self,
        texts_with_langs: list[tuple[str, str]],
        target_lang: str,
    ) -> list[str]:
        """Пакетный перевод через один LLM-запрос."""
        try:
            from pds_ultimate.core.llm_engine import llm_engine

            tgt_name = self.get_language_name(target_lang)

            numbered = []
            for i, (text, src) in enumerate(texts_with_langs, 1):
                src_name = self.get_language_name(src)
                numbered.append(f"{i}. [{src_name}] {text}")

            prompt = (
                f"Переведи каждое сообщение на {tgt_name}. "
                f"Верни ТОЛЬКО переводы, по одному на строку, "
                f"с номерами:\n\n" + "\n".join(numbered)
            )

            result = await llm_engine.chat(
                message=prompt,
                task_type="translate",
                temperature=0.1,
            )

            if not result:
                return [""] * len(texts_with_langs)

            # Парсим нумерованный список
            lines = result.strip().split("\n")
            translations = []

            for line in lines:
                # Remove leading number: "1. text" → "text"
                cleaned = re.sub(r'^\d+[.)]\s*', '', line.strip())
                if cleaned:
                    translations.append(cleaned)

            # Дополняем если не хватает
            while len(translations) < len(texts_with_langs):
                translations.append("")

            return translations[:len(texts_with_langs)]

        except Exception as e:
            logger.warning(f"[Translator] Batch LLM failed: {e}")
            return [""] * len(texts_with_langs)


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

translator = TranslatorService()
