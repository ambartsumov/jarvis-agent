"""
Тесты парсеров — parsers.py
"""


class TestRegexParser:
    """Тесты RegexParser — парсинг товаров из текста."""

    def test_import(self):
        """RegexParser импортируется."""
        from pds_ultimate.utils.parsers import RegexParser
        assert RegexParser is not None

    def test_parse_items(self):
        """Парсинг позиций заказа."""
        from pds_ultimate.utils.parsers import RegexParser

        items = RegexParser.parse("Балаклавы 100 шт по 200$")
        assert len(items) >= 1
        assert items[0].name
        assert items[0].quantity > 0

    def test_parse_multiple_lines(self):
        """Парсинг нескольких строк."""
        from pds_ultimate.utils.parsers import RegexParser

        text = """Маски 50 шт по 3$
Перчатки 200 шт по 1.5$"""
        items = RegexParser.parse(text)
        assert len(items) >= 2

    def test_parse_empty(self):
        """Пустой текст — пустой результат."""
        from pds_ultimate.utils.parsers import RegexParser

        items = RegexParser.parse("")
        assert items == []

    def test_parse_currency_usd(self):
        """Распознавание валюты USD."""
        from pds_ultimate.utils.parsers import RegexParser

        items = RegexParser.parse("Товар 10 шт по 50$")
        if items:
            assert items[0].currency == "USD"

    def test_parse_currency_cny(self):
        """Распознавание валюты CNY."""
        from pds_ultimate.utils.parsers import RegexParser

        items = RegexParser.parse("Товар 10 шт по 50 юан")
        if items:
            assert items[0].currency == "CNY"

    def test_parse_currency_tmt(self):
        """Распознавание валюты TMT."""
        from pds_ultimate.utils.parsers import RegexParser

        items = RegexParser.parse("Товар 10 шт по 500 ман")
        if items:
            assert items[0].currency == "TMT"


class TestParsedItem:
    """Тесты ParsedItem dataclass."""

    def test_create_item(self):
        """Создание ParsedItem."""
        from pds_ultimate.utils.parsers import ParsedItem

        item = ParsedItem(
            name="Тестовый товар",
            quantity=10.0,
            unit="шт",
            unit_price=5.0,
            currency="USD",
        )
        assert item.name == "Тестовый товар"
        assert item.quantity == 10.0
        assert item.unit_price == 5.0
        assert item.currency == "USD"

    def test_item_no_price(self):
        """ParsedItem без цены."""
        from pds_ultimate.utils.parsers import ParsedItem

        item = ParsedItem(name="Товар", quantity=5.0)
        assert item.unit_price is None
        assert item.currency == "USD"


class TestParseResult:
    """Тесты ParseResult dataclass."""

    def test_create_result(self):
        """Создание ParseResult."""
        from pds_ultimate.utils.parsers import ParseResult

        result = ParseResult(source_type="text", raw_text="тест")
        assert result.source_type == "text"
        assert result.items == []
        assert result.errors == []


class TestUniversalParser:
    """Тесты UniversalParser."""

    def test_import(self):
        """UniversalParser импортируется."""
        from pds_ultimate.utils.parsers import UniversalParser
        parser = UniversalParser()
        assert parser is not None

    def test_parse_text(self):
        """parse_text возвращает ParseResult."""
        from pds_ultimate.utils.parsers import UniversalParser

        parser = UniversalParser()
        result = parser.parse_text("Балаклавы 100 шт по 200$")
        assert result is not None
        assert result.source_type == "text"

    def test_detect_format_xlsx(self):
        """Определение формата .xlsx."""
        from pds_ultimate.utils.parsers import UniversalParser

        parser = UniversalParser()
        assert parser.detect_format("file.xlsx") == "xlsx"

    def test_detect_format_pdf(self):
        """Определение формата .pdf."""
        from pds_ultimate.utils.parsers import UniversalParser

        parser = UniversalParser()
        assert parser.detect_format("file.pdf") == "pdf"

    def test_detect_format_voice(self):
        """Определение голосового формата."""
        from pds_ultimate.utils.parsers import UniversalParser

        parser = UniversalParser()
        assert parser.detect_format("voice.ogg") == "voice"

    def test_detect_format_unknown(self):
        """Неизвестный формат."""
        from pds_ultimate.utils.parsers import UniversalParser

        parser = UniversalParser()
        assert parser.detect_format("file.xyz") == "unknown"

    def test_global_parser_instance(self):
        """Глобальный экземпляр parser доступен."""
        from pds_ultimate.utils.parsers import parser
        assert parser is not None
