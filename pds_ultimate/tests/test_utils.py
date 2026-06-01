"""
Тесты Utils — formatters, validators, helpers
"""

import os
import tempfile
from datetime import date, datetime, timedelta

# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatters:
    """Тесты модуля formatters."""

    def test_import(self):
        """formatters импортируется."""
        from pds_ultimate.utils.formatters import (
            format_header,
        )
        assert callable(format_header)

    def test_format_header(self):
        """format_header."""
        from pds_ultimate.utils.formatters import format_header

        result = format_header("тест", "🔥")
        assert "🔥" in result
        assert "ТЕСТ" in result

    def test_format_section(self):
        """format_section."""
        from pds_ultimate.utils.formatters import format_section

        result = format_section("Заголовок", "Содержимое")
        assert "Заголовок" in result
        assert "Содержимое" in result

    def test_format_status(self):
        """format_status с эмодзи."""
        from pds_ultimate.utils.formatters import format_status

        result = format_status("success", "Готово")
        assert "✅" in result
        assert "Готово" in result

    def test_format_success(self):
        """format_success."""
        from pds_ultimate.utils.formatters import format_success

        assert "✅" in format_success("OK")

    def test_format_error(self):
        """format_error."""
        from pds_ultimate.utils.formatters import format_error

        assert "❌" in format_error("Ошибка")

    def test_format_warning(self):
        """format_warning."""
        from pds_ultimate.utils.formatters import format_warning

        assert "⚠️" in format_warning("Внимание")


class TestMoneyFormatters:
    """Тесты форматирования денег."""

    def test_format_money_usd(self):
        """format_money: USD."""
        from pds_ultimate.utils.formatters import format_money

        result = format_money(1500.5, "USD")
        assert "$" in result
        assert "1,500.50" in result

    def test_format_money_cny(self):
        """format_money: CNY."""
        from pds_ultimate.utils.formatters import format_money

        result = format_money(1500, "CNY")
        assert "¥" in result

    def test_format_money_sign_positive(self):
        """format_money: +."""
        from pds_ultimate.utils.formatters import format_money

        result = format_money(100, show_sign=True)
        assert "+" in result

    def test_format_money_negative(self):
        """format_money: отрицательная."""
        from pds_ultimate.utils.formatters import format_money

        result = format_money(-100)
        assert "-" in result

    def test_format_profit(self):
        """format_profit."""
        from pds_ultimate.utils.formatters import format_profit

        result = format_profit(1000, 600)
        assert "Доход" in result
        assert "Расходы" in result
        assert "Прибыль" in result

    def test_format_percentage(self):
        """format_percentage."""
        from pds_ultimate.utils.formatters import format_percentage

        result = format_percentage(50, 200, "Progress")
        assert "25.0%" in result
        assert "Progress" in result

    def test_format_percentage_zero(self):
        """format_percentage: деление на 0."""
        from pds_ultimate.utils.formatters import format_percentage

        result = format_percentage(50, 0)
        assert "0.0%" in result


class TestDateFormatters:
    """Тесты форматирования дат."""

    def test_format_date_datetime(self):
        """format_date: datetime."""
        from pds_ultimate.utils.formatters import format_date

        dt = datetime(2025, 12, 25, 14, 30)
        result = format_date(dt)
        assert "25.12.2025" in result
        assert "14:30" in result

    def test_format_date_no_time(self):
        """format_date: без времени."""
        from pds_ultimate.utils.formatters import format_date

        dt = datetime(2025, 12, 25, 14, 30)
        result = format_date(dt, include_time=False)
        assert "25.12.2025" in result
        assert "14:30" not in result

    def test_format_date_date_object(self):
        """format_date: date."""
        from pds_ultimate.utils.formatters import format_date

        d = date(2025, 6, 15)
        result = format_date(d)
        assert "15.06.2025" in result

    def test_format_relative_today(self):
        """format_relative_date: сегодня."""
        from pds_ultimate.utils.formatters import format_relative_date

        result = format_relative_date(date.today())
        assert result == "сегодня"

    def test_format_relative_yesterday(self):
        """format_relative_date: вчера."""
        from pds_ultimate.utils.formatters import format_relative_date

        result = format_relative_date(date.today() - timedelta(days=1))
        assert result == "вчера"

    def test_format_relative_tomorrow(self):
        """format_relative_date: завтра."""
        from pds_ultimate.utils.formatters import format_relative_date

        result = format_relative_date(date.today() + timedelta(days=1))
        assert result == "завтра"

    def test_format_relative_days(self):
        """format_relative_date: дни назад."""
        from pds_ultimate.utils.formatters import format_relative_date

        result = format_relative_date(date.today() - timedelta(days=3))
        assert "назад" in result

    def test_format_duration_ms(self):
        """format_duration: миллисекунды."""
        from pds_ultimate.utils.formatters import format_duration

        result = format_duration(0.5)
        assert "мс" in result

    def test_format_duration_seconds(self):
        """format_duration: секунды."""
        from pds_ultimate.utils.formatters import format_duration

        result = format_duration(45)
        assert "сек" in result

    def test_format_duration_minutes(self):
        """format_duration: минуты."""
        from pds_ultimate.utils.formatters import format_duration

        result = format_duration(125)
        assert "мин" in result

    def test_format_duration_hours(self):
        """format_duration: часы."""
        from pds_ultimate.utils.formatters import format_duration

        result = format_duration(3700)
        assert "ч" in result


class TestTableFormatters:
    """Тесты таблиц."""

    def test_format_table_basic(self):
        """format_table: базовая."""
        from pds_ultimate.utils.formatters import format_table

        result = format_table(
            ["A", "B", "C"],
            [["1", "2", "3"], ["4", "5", "6"]],
        )
        assert "A" in result
        assert "1" in result
        assert "|" in result

    def test_format_table_empty(self):
        """format_table: пустая."""
        from pds_ultimate.utils.formatters import format_table

        result = format_table([], [])
        assert result == ""

    def test_format_list_bullets(self):
        """format_list: маркеры."""
        from pds_ultimate.utils.formatters import format_list

        result = format_list(["Первый", "Второй", "Третий"])
        assert "•" in result
        assert "Первый" in result

    def test_format_list_numbered(self):
        """format_list: нумерованный."""
        from pds_ultimate.utils.formatters import format_list

        result = format_list(["A", "B", "C"], numbered=True)
        assert "1." in result
        assert "2." in result

    def test_format_key_value(self):
        """format_key_value."""
        from pds_ultimate.utils.formatters import format_key_value

        result = format_key_value({"Имя": "Тест", "Статус": "OK"})
        assert "Имя" in result
        assert "Тест" in result


class TestCompositeFormatters:
    """Тесты составных форматтеров."""

    def test_format_order_summary(self):
        """format_order_summary."""
        from pds_ultimate.utils.formatters import format_order_summary

        result = format_order_summary("ORD-0001", "confirmed", 5, 1500.0)
        assert "ORD-0001" in result
        assert "$" in result

    def test_format_brief(self):
        """format_brief."""
        from pds_ultimate.utils.formatters import format_brief

        result = format_brief("ТЕСТ", {
            "📦 Заказы": "5",
            "💰 Баланс": "$1000",
        }, footer="Готово!")
        assert "ТЕСТ" in result
        assert "Заказы" in result
        assert "Готово!" in result

    def test_truncate(self):
        """truncate."""
        from pds_ultimate.utils.formatters import truncate

        text = "a" * 300
        result = truncate(text, 50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_truncate_short(self):
        """truncate: короткий текст."""
        from pds_ultimate.utils.formatters import truncate

        assert truncate("hello", 50) == "hello"

    def test_escape_markdown(self):
        """escape_markdown."""
        from pds_ultimate.utils.formatters import escape_markdown

        result = escape_markdown("*bold* _italic_")
        assert "\\*" in result
        assert "\\_" in result


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPhoneValidators:
    """Тесты валидации телефонов."""

    def test_valid_tm_phone(self):
        """Валидный ТМ номер."""
        from pds_ultimate.utils.validators import is_valid_phone

        assert is_valid_phone("+99365123456") is True

    def test_valid_cn_phone(self):
        """Валидный CN номер."""
        from pds_ultimate.utils.validators import is_valid_phone

        assert is_valid_phone("+8613912345678") is True

    def test_valid_ru_phone(self):
        """Валидный RU номер."""
        from pds_ultimate.utils.validators import is_valid_phone

        assert is_valid_phone("+79161234567") is True

    def test_invalid_phone(self):
        """Невалидный номер."""
        from pds_ultimate.utils.validators import is_valid_phone

        assert is_valid_phone("123") is False

    def test_normalize_phone_ru(self):
        """normalize_phone: 8xxx → +7xxx."""
        from pds_ultimate.utils.validators import normalize_phone

        result = normalize_phone("89161234567")
        assert result == "+79161234567"


class TestEmailValidators:
    """Тесты валидации email."""

    def test_valid_email(self):
        """Валидный email."""
        from pds_ultimate.utils.validators import is_valid_email

        assert is_valid_email("test@example.com") is True

    def test_invalid_email(self):
        """Невалидный email."""
        from pds_ultimate.utils.validators import is_valid_email

        assert is_valid_email("not-an-email") is False

    def test_invalid_email_no_domain(self):
        """Email без домена."""
        from pds_ultimate.utils.validators import is_valid_email

        assert is_valid_email("user@") is False


class TestCurrencyValidators:
    """Тесты валидации валют."""

    def test_valid_usd(self):
        """USD — валидный."""
        from pds_ultimate.utils.validators import is_valid_currency

        assert is_valid_currency("USD") is True

    def test_valid_cny(self):
        """CNY — валидный."""
        from pds_ultimate.utils.validators import is_valid_currency

        assert is_valid_currency("CNY") is True

    def test_invalid_currency(self):
        """XYZ — невалидный."""
        from pds_ultimate.utils.validators import is_valid_currency

        assert is_valid_currency("XYZ") is False

    def test_valid_amount(self):
        """is_valid_amount: числа."""
        from pds_ultimate.utils.validators import is_valid_amount

        assert is_valid_amount(100) is True
        assert is_valid_amount(0) is False
        assert is_valid_amount(-5) is False

    def test_valid_amount_string(self):
        """is_valid_amount: строка."""
        from pds_ultimate.utils.validators import is_valid_amount

        assert is_valid_amount("$1,500") is True

    def test_parse_amount(self):
        """parse_amount."""
        from pds_ultimate.utils.validators import parse_amount

        assert parse_amount("$1,500.50") == 1500.50
        assert parse_amount("1500") == 1500.0
        assert parse_amount("broken") is None


class TestDateValidators:
    """Тесты валидации дат."""

    def test_valid_date_iso(self):
        """ISO формат."""
        from pds_ultimate.utils.validators import is_valid_date

        assert is_valid_date("2025-06-15") is True

    def test_valid_date_ru(self):
        """Русский формат."""
        from pds_ultimate.utils.validators import is_valid_date

        assert is_valid_date("15.06.2025") is True

    def test_valid_date_with_time(self):
        """Дата с временем."""
        from pds_ultimate.utils.validators import is_valid_date

        assert is_valid_date("2025-06-15 14:30") is True

    def test_invalid_date(self):
        """Невалидная дата."""
        from pds_ultimate.utils.validators import is_valid_date

        assert is_valid_date("not-a-date") is False

    def test_parse_date(self):
        """parse_date."""
        from pds_ultimate.utils.validators import parse_date

        dt = parse_date("25.12.2025")
        assert dt is not None
        assert dt.day == 25
        assert dt.month == 12

    def test_is_future_date(self):
        """is_future_date."""
        from pds_ultimate.utils.validators import is_future_date

        assert is_future_date(date.today() + timedelta(days=1)) is True
        assert is_future_date(date.today() - timedelta(days=1)) is False


class TestTrackingValidators:
    """Тесты валидации трекинг-номеров."""

    def test_sf_express(self):
        """SF Express."""
        from pds_ultimate.utils.validators import detect_carrier, is_valid_tracking

        assert is_valid_tracking("SF1234567890123") is True
        assert detect_carrier("SF1234567890123") == "sf_express"

    def test_china_post(self):
        """China Post."""
        from pds_ultimate.utils.validators import is_valid_tracking

        assert is_valid_tracking("EA123456789CN") is True

    def test_invalid_tracking(self):
        """Невалидный трекинг."""
        from pds_ultimate.utils.validators import is_valid_tracking

        assert is_valid_tracking("ABC") is False


class TestFileValidators:
    """Тесты валидации файлов."""

    def test_is_document(self):
        """is_document."""
        from pds_ultimate.utils.validators import is_document

        assert is_document("report.xlsx") is True
        assert is_document("photo.jpg") is False

    def test_is_image(self):
        """is_image."""
        from pds_ultimate.utils.validators import is_image

        assert is_image("photo.jpg") is True
        assert is_image("report.xlsx") is False

    def test_is_voice(self):
        """is_voice."""
        from pds_ultimate.utils.validators import is_voice

        assert is_voice("message.ogg") is True
        assert is_voice("report.pdf") is False

    def test_validate_file_size(self):
        """validate_file_size."""
        from pds_ultimate.utils.validators import validate_file_size

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            path = f.name

        try:
            valid, msg = validate_file_size(path)
            assert valid is True
        finally:
            os.unlink(path)

    def test_validate_file_size_missing(self):
        """validate_file_size: нет файла."""
        from pds_ultimate.utils.validators import validate_file_size

        valid, msg = validate_file_size("/nonexistent/file")
        assert valid is False

    def test_is_safe_filename(self):
        """is_safe_filename."""
        from pds_ultimate.utils.validators import is_safe_filename

        assert is_safe_filename("report.pdf") is True
        assert is_safe_filename("../hack.sh") is False
        assert is_safe_filename("/etc/passwd") is False
        assert is_safe_filename("") is False


class TestTextValidators:
    """Тесты валидации текста."""

    def test_is_not_empty(self):
        """is_not_empty."""
        from pds_ultimate.utils.validators import is_not_empty

        assert is_not_empty("hello") is True
        assert is_not_empty("") is False
        assert is_not_empty(None) is False
        assert is_not_empty("   ") is False

    def test_validate_text_length(self):
        """validate_text_length."""
        from pds_ultimate.utils.validators import validate_text_length

        valid, _ = validate_text_length("hello", 1, 100)
        assert valid is True

        valid, _ = validate_text_length("", 1, 100)
        assert valid is False

    def test_is_valid_order_number(self):
        """is_valid_order_number."""
        from pds_ultimate.utils.validators import is_valid_order_number

        assert is_valid_order_number("ORD-0001") is True
        assert is_valid_order_number("ORD-12345") is True
        assert is_valid_order_number("RANDOM") is False


class TestValidationResult:
    """Тесты ValidationResult."""

    def test_creation(self):
        """ValidationResult создаётся."""
        from pds_ultimate.utils.validators import ValidationResult

        vr = ValidationResult()
        assert vr.is_valid is True

    def test_add_error(self):
        """add_error делает невалидным."""
        from pds_ultimate.utils.validators import ValidationResult

        vr = ValidationResult()
        vr.add_error("Ошибка")
        assert vr.is_valid is False

    def test_add_warning(self):
        """add_warning не делает невалидным."""
        from pds_ultimate.utils.validators import ValidationResult

        vr = ValidationResult()
        vr.add_warning("Внимание")
        assert vr.is_valid is True
        assert len(vr.warnings) == 1

    def test_to_dict(self):
        """to_dict."""
        from pds_ultimate.utils.validators import ValidationResult

        vr = ValidationResult()
        d = vr.to_dict()
        assert d["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


class TestIDGeneration:
    """Тесты генерации ID."""

    def test_generate_id(self):
        """generate_id."""
        from pds_ultimate.utils.helpers import generate_id

        uid = generate_id("test")
        assert uid.startswith("test_")
        assert len(uid) > 5

    def test_generate_id_no_prefix(self):
        """generate_id без префикса."""
        from pds_ultimate.utils.helpers import generate_id

        uid = generate_id()
        assert len(uid) == 12

    def test_generate_short_id(self):
        """generate_short_id."""
        from pds_ultimate.utils.helpers import generate_short_id

        uid = generate_short_id(6)
        assert len(uid) == 6

    def test_ids_unique(self):
        """Уникальность ID."""
        from pds_ultimate.utils.helpers import generate_id

        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100


class TestHashing:
    """Тесты хеширования."""

    def test_hash_text(self):
        """hash_text — SHA256."""
        from pds_ultimate.utils.helpers import hash_text

        h = hash_text("hello")
        assert len(h) == 64  # SHA256

    def test_hash_text_deterministic(self):
        """hash_text детерминирован."""
        from pds_ultimate.utils.helpers import hash_text

        assert hash_text("test") == hash_text("test")

    def test_quick_hash(self):
        """quick_hash — короткий."""
        from pds_ultimate.utils.helpers import quick_hash

        h = quick_hash("hello", 8)
        assert len(h) == 8


class TestFileSize:
    """Тесты размера файлов."""

    def test_format_file_size_bytes(self):
        """Байты."""
        from pds_ultimate.utils.helpers import format_file_size

        assert "Б" in format_file_size(500)

    def test_format_file_size_kb(self):
        """Килобайты."""
        from pds_ultimate.utils.helpers import format_file_size

        assert "КБ" in format_file_size(1536)

    def test_format_file_size_mb(self):
        """Мегабайты."""
        from pds_ultimate.utils.helpers import format_file_size

        assert "МБ" in format_file_size(1048576)


class TestChunks:
    """Тесты чанков."""

    def test_chunks_basic(self):
        """chunks: базовый."""
        from pds_ultimate.utils.helpers import chunks

        result = chunks([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunks_exact(self):
        """chunks: точное деление."""
        from pds_ultimate.utils.helpers import chunks

        result = chunks([1, 2, 3, 4], 2)
        assert result == [[1, 2], [3, 4]]

    def test_chunks_empty(self):
        """chunks: пустой."""
        from pds_ultimate.utils.helpers import chunks

        result = chunks([], 5)
        assert result == []


class TestSafeJSON:
    """Тесты безопасного JSON."""

    def test_safe_json_loads(self):
        """safe_json_loads: валидный."""
        from pds_ultimate.utils.helpers import safe_json_loads

        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_safe_json_loads_invalid(self):
        """safe_json_loads: невалидный."""
        from pds_ultimate.utils.helpers import safe_json_loads

        assert safe_json_loads("broken") is None

    def test_safe_json_loads_default(self):
        """safe_json_loads: с default."""
        from pds_ultimate.utils.helpers import safe_json_loads

        assert safe_json_loads("broken", default={}) == {}

    def test_safe_json_dumps(self):
        """safe_json_dumps: обычный."""
        from pds_ultimate.utils.helpers import safe_json_dumps

        result = safe_json_dumps({"a": 1})
        assert '"a"' in result

    def test_safe_json_dumps_datetime(self):
        """safe_json_dumps: с datetime (default=str)."""
        from pds_ultimate.utils.helpers import safe_json_dumps

        result = safe_json_dumps({"dt": datetime.now()})
        assert isinstance(result, str)


class TestTimer:
    """Тесты Timer."""

    def test_timer(self):
        """Timer: базовый."""
        from pds_ultimate.utils.helpers import Timer

        with Timer("test") as t:
            pass
        assert t.elapsed >= 0
        assert t.elapsed_ms >= 0

    def test_timer_label(self):
        """Timer: с label."""
        from pds_ultimate.utils.helpers import Timer

        t = Timer("operation")
        assert t.label == "operation"


class TestMisc:
    """Тесты misc-хелперов."""

    def test_clamp(self):
        """clamp."""
        from pds_ultimate.utils.helpers import clamp

        assert clamp(5, 0, 10) == 5
        assert clamp(-1, 0, 10) == 0
        assert clamp(15, 0, 10) == 10

    def test_first_non_none(self):
        """first_non_none."""
        from pds_ultimate.utils.helpers import first_non_none

        assert first_non_none(None, None, 3) == 3
        assert first_non_none(1, 2, 3) == 1
        assert first_non_none(None) is None

    def test_now_iso(self):
        """now_iso."""
        from pds_ultimate.utils.helpers import now_iso

        result = now_iso()
        assert "T" in result  # ISO format

    def test_safe_int(self):
        """safe_int."""
        from pds_ultimate.utils.helpers import safe_int

        assert safe_int("123") == 123
        assert safe_int("bad") == 0
        assert safe_int(None) == 0

    def test_safe_float(self):
        """safe_float."""
        from pds_ultimate.utils.helpers import safe_float

        assert safe_float("1.5") == 1.5
        assert safe_float("bad") == 0.0

    def test_flatten(self):
        """flatten."""
        from pds_ultimate.utils.helpers import flatten

        assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]
        assert flatten([]) == []

    def test_deduplicate(self):
        """deduplicate."""
        from pds_ultimate.utils.helpers import deduplicate

        assert deduplicate([1, 2, 2, 3, 3, 1]) == [1, 2, 3]

    def test_deduplicate_preserves_order(self):
        """deduplicate сохраняет порядок."""
        from pds_ultimate.utils.helpers import deduplicate

        assert deduplicate([3, 1, 2, 1, 3]) == [3, 1, 2]


class TestUtilsInit:
    """Тесты __init__.py — всё экспортируется."""

    def test_formatters_exported(self):
        """Formatters экспортируются из utils."""
        from pds_ultimate.utils import (
            format_header,
        )
        assert callable(format_header)

    def test_validators_exported(self):
        """Validators экспортируются."""
        from pds_ultimate.utils import (
            is_valid_phone,
        )
        assert callable(is_valid_phone)

    def test_helpers_exported(self):
        """Helpers экспортируются."""
        from pds_ultimate.utils import (
            generate_id,
        )
        assert callable(generate_id)
