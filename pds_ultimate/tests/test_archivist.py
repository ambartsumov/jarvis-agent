"""
Тесты Archivist Service — modules/executive/archivist.py
"""

from datetime import date


class TestFileCategory:
    """Тесты категорий файлов."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            archivist,
        )
        assert ArchivistService is not None
        assert archivist is not None

    def test_categories_count(self):
        """Минимум 8 категорий."""
        from pds_ultimate.modules.executive.archivist import FileCategory

        # FileCategory — класс со строковыми константами
        categories = [
            v for k, v in vars(FileCategory).items()
            if not k.startswith("_") and isinstance(v, str)
        ]
        assert len(categories) >= 8

    def test_category_keywords(self):
        """CATEGORY_KEYWORDS заполнены."""
        from pds_ultimate.modules.executive.archivist import CATEGORY_KEYWORDS

        assert len(CATEGORY_KEYWORDS) >= 5

    def test_extension_categories(self):
        """EXTENSION_CATEGORIES заполнены."""
        from pds_ultimate.modules.executive.archivist import EXTENSION_CATEGORIES

        assert len(EXTENSION_CATEGORIES) >= 3


class TestFileRecord:
    """Тесты FileRecord."""

    def test_creation(self):
        """FileRecord создаётся."""
        from pds_ultimate.modules.executive.archivist import (
            FileCategory,
            FileRecord,
        )

        record = FileRecord(
            original_name="document.pdf",
            standardized_name="2025_06_15_Invoice_Payment.pdf",
            path="/tmp/2025_06_15_Invoice_Payment.pdf",
            category=FileCategory.INVOICE,
            tags=["finance", "payment"],
        )
        assert record.original_name == "document.pdf"
        assert record.category == "Инвойс"


class TestRenameResult:
    """Тесты RenameResult."""

    def test_creation(self):
        """RenameResult создаётся."""
        from pds_ultimate.modules.executive.archivist import RenameResult

        result = RenameResult(
            success=True,
            old_path="/tmp/old.pdf",
            new_path="/tmp/2025_06_15_Invoice_Payment.pdf",
            old_name="old.pdf",
            new_name="2025_06_15_Invoice_Payment.pdf",
        )
        assert result.success is True
        assert result.old_name == "old.pdf"

    def test_to_dict(self):
        """RenameResult сериализуется."""
        from pds_ultimate.modules.executive.archivist import RenameResult

        result = RenameResult(
            success=True,
            old_path="/a",
            new_path="/b",
            old_name="a",
            new_name="b",
        )
        d = result.to_dict()
        assert d["success"] is True


class TestArchivistService:
    """Тесты сервиса архивиста."""

    def test_service_creation(self):
        """ArchivistService создаётся."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        assert service is not None

    def test_standardize_basic(self):
        """standardize: базовое имя."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        result = service.standardize(
            "invoice.pdf", context="Оплата за товар")
        assert result.endswith(".pdf")
        # Содержит дату
        today = date.today().strftime("%Y_%m_%d")
        assert today in result

    def test_standardize_with_date(self):
        """standardize: имя с датой."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        result = service.standardize("report_2025.xlsx")
        assert result.endswith(".xlsx")

    def test_is_standardized_yes(self):
        """is_standardized: стандартное имя."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        assert service.is_standardized(
            "2025_06_15_Invoice_Payment.pdf") is True

    def test_is_standardized_no(self):
        """is_standardized: нестандартное имя."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        assert service.is_standardized("random_file.pdf") is False

    def test_detect_category_invoice(self):
        """detect_category: инвойс."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            FileCategory,
        )

        service = ArchivistService()
        cat = service.detect_category("invoice_payment.pdf")
        assert cat == FileCategory.INVOICE

    def test_detect_category_report(self):
        """detect_category: отчёт."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            FileCategory,
        )

        service = ArchivistService()
        cat = service.detect_category("monthly_report.xlsx")
        assert cat == FileCategory.REPORT

    def test_detect_category_photo(self):
        """detect_category: фото (по расширению)."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            FileCategory,
        )

        service = ArchivistService()
        cat = service.detect_category("IMG_20250615.jpg")
        assert cat == FileCategory.PHOTO

    def test_detect_category_unknown(self):
        """detect_category: неизвестный."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            FileCategory,
        )

        service = ArchivistService()
        cat = service.detect_category("xyz12345.dat")
        assert cat == FileCategory.OTHER

    def test_auto_tag(self):
        """auto_tag определяет теги."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        tags = service.auto_tag("invoice_delivery_china.pdf")
        assert isinstance(tags, list)
        assert len(tags) >= 1

    def test_format_rename_result(self):
        """format_rename_result."""
        from pds_ultimate.modules.executive.archivist import (
            ArchivistService,
            RenameResult,
        )

        service = ArchivistService()
        result = RenameResult(
            success=True,
            old_path="/old",
            new_path="/new",
            old_name="old.pdf",
            new_name="2025_06_15_Invoice.pdf",
        )
        text = service.format_rename_result(result)
        assert "old.pdf" in text or "2025_06_15" in text

    def test_search_empty(self):
        """search в пустом реестре."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        results = service.search("invoice")
        assert isinstance(results, list)

    def test_rename_file_nonexistent(self):
        """rename_file несуществующего файла."""
        from pds_ultimate.modules.executive.archivist import ArchivistService

        service = ArchivistService()
        result = service.rename_file("/nonexistent/file.pdf")
        assert result.success is False

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.executive.archivist import archivist

        assert archivist is not None
