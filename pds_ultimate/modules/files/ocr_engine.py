"""
PDS-Ultimate OCR Engine
==========================
Выделенный модуль оптического распознавания текста.

По ТЗ §7.4 + §3.2:
- Фото чека → OCR → сумма + категория
- Фото накладной → OCR → извлечение данных
- Фото трек-номера → OCR → авто-извлечение
- Многоязычный: русский, английский, китайский
- Два бэкенда: EasyOCR (primary) и Tesseract (fallback)
- Confidence scoring для каждого блока текста

Config:
    config.ocr.engine → "easyocr" | "tesseract"
    config.ocr.languages → ["ru", "en", "ch_sim"]
    config.ocr.confidence_threshold → 0.5
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pds_ultimate.config import config, logger

# ─── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class OCRBlock:
    """Распознанный блок текста."""
    text: str
    confidence: float  # 0.0 - 1.0
    bbox: Optional[tuple] = None  # (x1, y1, x2, y2)
    line_number: int = 0

    @property
    def is_confident(self) -> bool:
        return self.confidence >= config.ocr.confidence_threshold


@dataclass
class OCRResult:
    """Результат OCR-распознавания."""
    blocks: list[OCRBlock] = field(default_factory=list)
    full_text: str = ""
    language: str = ""
    engine_used: str = ""
    processing_time_ms: float = 0.0
    image_path: str = ""
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.blocks) > 0

    @property
    def confident_text(self) -> str:
        """Только высокоуверенный текст."""
        return "\n".join(
            b.text for b in self.blocks if b.is_confident
        )

    @property
    def avg_confidence(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(b.confidence for b in self.blocks) / len(self.blocks)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "full_text": self.full_text,
            "confident_text": self.confident_text,
            "blocks_count": len(self.blocks),
            "avg_confidence": round(self.avg_confidence, 3),
            "language": self.language,
            "engine": self.engine_used,
            "processing_ms": round(self.processing_time_ms, 1),
            "error": self.error,
        }


# ─── Extraction Models ──────────────────────────────────────────────────────

@dataclass
class ExtractedAmount:
    """Извлечённая денежная сумма."""
    value: float
    currency: str = "USD"
    raw_text: str = ""
    confidence: float = 0.0


@dataclass
class ExtractedTrackingNumber:
    """Извлечённый трек-номер."""
    number: str
    carrier: str = ""  # SF, YTO, China Post, etc.
    confidence: float = 0.0


@dataclass
class ReceiptData:
    """Распознанные данные чека."""
    amounts: list[ExtractedAmount] = field(default_factory=list)
    total: Optional[ExtractedAmount] = None
    date: Optional[str] = None
    vendor: Optional[str] = None
    items: list[dict] = field(default_factory=list)
    raw_text: str = ""

    @property
    def total_amount(self) -> float:
        if self.total:
            return self.total.value
        if self.amounts:
            return max(a.value for a in self.amounts)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total_amount,
            "currency": self.total.currency if self.total else "USD",
            "date": self.date,
            "vendor": self.vendor,
            "items_count": len(self.items),
            "amounts_found": len(self.amounts),
        }


# ─── OCR Engine ──────────────────────────────────────────────────────────────

class OCREngine:
    """
    Единый OCR-движок с несколькими бэкендами.

    Архитектура:
    - EasyOCR (primary): лучше для RU/CN, GPU-ускорение
    - Tesseract (fallback): быстрый, надёжный
    - Извлечение структурированных данных: суммы, трек-номера, даты
    - Regex-пост-процессинг для повышения точности

    Использование:
        result = await ocr_engine.recognize("photo.jpg")
        receipt = ocr_engine.extract_receipt(result)
        tracking = ocr_engine.extract_tracking(result)
    """

    # Patterns для извлечения данных
    AMOUNT_PATTERNS = [
        # $100, $1,234.56
        re.compile(r'\$\s*([\d,]+\.?\d*)', re.IGNORECASE),
        # 100 USD, 1234.56 USD
        re.compile(r'([\d,]+\.?\d*)\s*(USD|EUR|RUB|TMT|CNY|GBP|TRY)',
                   re.IGNORECASE),
        # ¥1234, ¥1,234
        re.compile(r'[¥￥]\s*([\d,]+\.?\d*)'),
        # 1234 руб, 1234р
        re.compile(r'([\d,]+\.?\d*)\s*(?:руб|₽|р\.?)', re.IGNORECASE),
        # ИТОГО: 1234, Total: 1234
        re.compile(r'(?:итого|total|всего|сумма|amount)[:\s]*([\d,]+\.?\d*)',
                   re.IGNORECASE),
    ]

    TRACKING_PATTERNS = [
        # SF Express: SF + 12-15 digits
        (re.compile(r'(SF\d{12,15})', re.IGNORECASE), "SF Express"),
        # YTO Express: YT + 12-15 digits
        (re.compile(r'(YT\d{12,15})', re.IGNORECASE), "YTO Express"),
        # China Post / EMS: E[A-Z]\d{9}[A-Z]{2}
        (re.compile(r'(E[A-Z]\d{9}[A-Z]{2})', re.IGNORECASE), "EMS"),
        # General China: 7+ digits
        (re.compile(r'(?:трек|track|tracking)[:\s#]*(\d{10,20})',
                    re.IGNORECASE), "Unknown"),
        # DHL: 10-digit
        (re.compile(r'\b(\d{10})\b'), "DHL/General"),
        # General long number that looks like tracking
        (re.compile(r'\b([A-Z]{2}\d{9}[A-Z]{2})\b'), "International"),
    ]

    DATE_PATTERNS = [
        # DD.MM.YYYY, DD/MM/YYYY
        re.compile(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})'),
        # YYYY-MM-DD
        re.compile(r'(\d{4}-\d{1,2}-\d{1,2})'),
        # DD месяц YYYY (Russian)
        re.compile(
            r'(\d{1,2})\s+'
            r'(янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)\w*'
            r'\s+(\d{2,4})',
            re.IGNORECASE,
        ),
    ]

    CURRENCY_MAP = {
        "$": "USD", "usd": "USD", "доллар": "USD",
        "€": "EUR", "eur": "EUR", "евро": "EUR",
        "₽": "RUB", "руб": "RUB", "р": "RUB", "rub": "RUB",
        "¥": "CNY", "￥": "CNY", "cny": "CNY", "юань": "CNY",
        "tmt": "TMT", "манат": "TMT",
        "£": "GBP", "gbp": "GBP",
        "₺": "TRY", "try": "TRY", "лира": "TRY",
    }

    def __init__(self):
        self._easyocr_reader = None
        self._tesseract_available = False

    # ═══════════════════════════════════════════════════════════════════════
    # OCR Recognition
    # ═══════════════════════════════════════════════════════════════════════

    async def recognize(
        self,
        image_path: str,
        languages: Optional[list[str]] = None,
        engine: Optional[str] = None,
    ) -> OCRResult:
        """
        Распознать текст на изображении.

        Args:
            image_path: Путь к изображению
            languages: Языки ["ru", "en", "ch_sim"]
            engine: "easyocr" | "tesseract" (default from config)
        """
        import time as time_mod
        start = time_mod.monotonic()

        if languages is None:
            languages = list(config.ocr.languages)

        if engine is None:
            engine = config.ocr.engine

        path = Path(image_path)
        if not path.exists():
            return OCRResult(
                error=f"Файл не найден: {image_path}",
                image_path=image_path,
            )

        # Попытка EasyOCR
        if engine == "easyocr":
            result = await self._recognize_easyocr(str(path), languages)
            if result.success:
                result.processing_time_ms = (
                    time_mod.monotonic() - start
                ) * 1000
                return result
            # Fallback to tesseract
            logger.info("[OCR] EasyOCR failed, falling back to Tesseract")

        # Tesseract
        result = await self._recognize_tesseract(str(path), languages)
        result.processing_time_ms = (time_mod.monotonic() - start) * 1000
        return result

    async def recognize_bytes(
        self,
        image_bytes: bytes,
        filename: str = "ocr_temp.jpg",
        languages: Optional[list[str]] = None,
    ) -> OCRResult:
        """Распознать текст из байтов изображения."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix=Path(filename).suffix or ".jpg",
            delete=False,
        ) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            return await self.recognize(tmp_path, languages)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Data Extraction
    # ═══════════════════════════════════════════════════════════════════════

    def extract_amounts(self, ocr_result: OCRResult) -> list[ExtractedAmount]:
        """Извлечь денежные суммы из OCR-текста."""
        amounts = []
        text = ocr_result.full_text

        for pattern in self.AMOUNT_PATTERNS:
            for match in pattern.finditer(text):
                groups = match.groups()
                raw = match.group(0)

                # Первая группа — число
                num_str = groups[0].replace(",", "").replace(" ", "")
                try:
                    value = float(num_str)
                except ValueError:
                    continue

                if value <= 0:
                    continue

                # Определить валюту
                currency = "USD"
                if len(groups) > 1 and groups[1]:
                    currency = groups[1].upper()
                else:
                    currency = self._detect_currency(raw, text)

                amounts.append(ExtractedAmount(
                    value=value,
                    currency=currency,
                    raw_text=raw,
                    confidence=ocr_result.avg_confidence,
                ))

        # Дедупликация по значению
        seen = set()
        unique = []
        for a in amounts:
            key = (round(a.value, 2), a.currency)
            if key not in seen:
                seen.add(key)
                unique.append(a)

        return unique

    def extract_tracking_numbers(
        self,
        ocr_result: OCRResult,
    ) -> list[ExtractedTrackingNumber]:
        """Извлечь трек-номера из OCR-текста."""
        tracking = []
        text = ocr_result.full_text

        for pattern, carrier in self.TRACKING_PATTERNS:
            for match in pattern.finditer(text):
                number = match.group(1)
                # Фильтруем короткие числа (могут быть ценами)
                if len(number) < 8:
                    continue

                tracking.append(ExtractedTrackingNumber(
                    number=number,
                    carrier=carrier,
                    confidence=ocr_result.avg_confidence,
                ))

        # Дедупликация
        seen = set()
        unique = []
        for t in tracking:
            if t.number not in seen:
                seen.add(t.number)
                unique.append(t)

        return unique

    def extract_receipt(self, ocr_result: OCRResult) -> ReceiptData:
        """
        Извлечь данные чека: суммы, дату, продавца.
        """
        text = ocr_result.full_text
        amounts = self.extract_amounts(ocr_result)

        # Дата
        date_str = None
        for pattern in self.DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                date_str = match.group(0)
                break

        # Продавец (первая строка часто содержит название)
        vendor = None
        lines = [
            b.text.strip() for b in ocr_result.blocks
            if b.is_confident and len(b.text.strip()) > 2
        ]
        if lines:
            # Первая строка длиннее 3 символов и не число
            for line in lines[:3]:
                if not re.match(r'^[\d\s,./$€¥₽]+$', line):
                    vendor = line
                    break

        # Итого (самая большая сумма или помеченная как total)
        total = None
        total_keywords = ["итого", "total",
                          "всего", "сумма", "amount", "к оплате"]
        for a in amounts:
            raw_lower = a.raw_text.lower()
            for kw in total_keywords:
                if kw in raw_lower:
                    total = a
                    break
            if total:
                break

        if not total and amounts:
            total = max(amounts, key=lambda a: a.value)

        return ReceiptData(
            amounts=amounts,
            total=total,
            date=date_str,
            vendor=vendor,
            raw_text=text,
        )

    def extract_dates(self, ocr_result: OCRResult) -> list[str]:
        """Извлечь все даты из OCR-текста."""
        dates = []
        text = ocr_result.full_text

        for pattern in self.DATE_PATTERNS:
            for match in pattern.finditer(text):
                dates.append(match.group(0))

        return dates

    # ═══════════════════════════════════════════════════════════════════════
    # Internal: EasyOCR
    # ═══════════════════════════════════════════════════════════════════════

    async def _recognize_easyocr(
        self,
        image_path: str,
        languages: list[str],
    ) -> OCRResult:
        """Распознавание через EasyOCR."""
        try:
            import easyocr

            if self._easyocr_reader is None:
                self._easyocr_reader = easyocr.Reader(
                    languages, gpu=False, verbose=False
                )

            raw_results = self._easyocr_reader.readtext(image_path)

            blocks = []
            texts = []

            for i, (bbox, text, conf) in enumerate(raw_results):
                blocks.append(OCRBlock(
                    text=text.strip(),
                    confidence=conf,
                    bbox=tuple(bbox[0] + bbox[2]) if bbox else None,
                    line_number=i + 1,
                ))
                texts.append(text.strip())

            full_text = "\n".join(texts)

            return OCRResult(
                blocks=blocks,
                full_text=full_text,
                language=",".join(languages),
                engine_used="easyocr",
                image_path=image_path,
            )

        except ImportError:
            return OCRResult(
                error="easyocr не установлен (pip install easyocr)",
                engine_used="easyocr",
                image_path=image_path,
            )
        except Exception as e:
            return OCRResult(
                error=f"EasyOCR error: {e}",
                engine_used="easyocr",
                image_path=image_path,
            )

    async def _recognize_tesseract(
        self,
        image_path: str,
        languages: list[str],
    ) -> OCRResult:
        """Распознавание через Tesseract."""
        try:
            import pytesseract
            from PIL import Image

            # Map language codes
            lang_map = {
                "ru": "rus", "en": "eng", "ch_sim": "chi_sim",
                "ch_tra": "chi_tra", "de": "deu", "fr": "fra",
            }
            tess_langs = "+".join(
                lang_map.get(l, l) for l in languages
            )

            img = Image.open(image_path)

            # Получаем с детализацией
            data = pytesseract.image_to_data(
                img, lang=tess_langs, output_type=pytesseract.Output.DICT
            )

            blocks = []
            texts = []
            n_boxes = len(data["text"])

            for i in range(n_boxes):
                text = data["text"][i].strip()
                conf = int(data["conf"][i])

                if text and conf > 0:
                    blocks.append(OCRBlock(
                        text=text,
                        confidence=conf / 100.0,
                        bbox=(
                            data["left"][i],
                            data["top"][i],
                            data["left"][i] + data["width"][i],
                            data["top"][i] + data["height"][i],
                        ),
                        line_number=data["line_num"][i],
                    ))
                    texts.append(text)

            full_text = " ".join(texts)

            return OCRResult(
                blocks=blocks,
                full_text=full_text,
                language=tess_langs,
                engine_used="tesseract",
                image_path=image_path,
            )

        except ImportError:
            return OCRResult(
                error="pytesseract не установлен",
                engine_used="tesseract",
                image_path=image_path,
            )
        except Exception as e:
            return OCRResult(
                error=f"Tesseract error: {e}",
                engine_used="tesseract",
                image_path=image_path,
            )

    def _detect_currency(self, raw: str, context: str) -> str:
        """Определить валюту из контекста."""
        raw_lower = raw.lower()
        context_lower = context.lower()

        for key, currency in self.CURRENCY_MAP.items():
            if key in raw_lower:
                return currency

        # Контекст (в пределах ±50 символов)
        idx = context_lower.find(raw_lower[:10])
        if idx >= 0:
            window = context_lower[max(0, idx - 50):idx + len(raw) + 50]
            for key, currency in self.CURRENCY_MAP.items():
                if key in window:
                    return currency

        return "USD"


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

ocr_engine = OCREngine()
