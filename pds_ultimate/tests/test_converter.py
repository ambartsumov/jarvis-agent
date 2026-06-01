"""
Тесты File Converter — modules/files/converter.py
"""

import os
import tempfile

import pytest


class TestConversionResult:
    """Тесты ConversionResult."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.files.converter import (
            FileConverter,
            file_converter,
        )
        assert FileConverter is not None
        assert file_converter is not None

    def test_result_success(self):
        """ConversionResult success."""
        from pds_ultimate.modules.files.converter import ConversionResult

        result = ConversionResult(
            success=True,
            source_path="/src.xlsx",
            target_path="/dst.csv",
            source_format="xlsx",
            target_format="csv",
        )
        assert result.success is True
        assert result.source_format == "xlsx"

    def test_result_error(self):
        """ConversionResult error."""
        from pds_ultimate.modules.files.converter import ConversionResult

        result = ConversionResult(
            success=False,
            source_path="/bad",
            error="File not found",
        )
        assert result.success is False
        assert result.error == "File not found"

    def test_result_to_dict(self):
        """ConversionResult сериализуется."""
        from pds_ultimate.modules.files.converter import ConversionResult

        result = ConversionResult(
            source_path="/a",
            target_path="/b",
            source_format="xlsx",
            target_format="csv",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["from"] == "xlsx"
        assert d["to"] == "csv"


class TestSupportedConversions:
    """Тесты матрицы конвертаций."""

    def test_xlsx_conversions(self):
        """xlsx: минимум 3 формата."""
        from pds_ultimate.modules.files.converter import SUPPORTED_CONVERSIONS

        assert "csv" in SUPPORTED_CONVERSIONS["xlsx"]
        assert "pdf" in SUPPORTED_CONVERSIONS["xlsx"]

    def test_csv_conversions(self):
        """csv: есть xlsx."""
        from pds_ultimate.modules.files.converter import SUPPORTED_CONVERSIONS

        assert "xlsx" in SUPPORTED_CONVERSIONS["csv"]

    def test_docx_conversions(self):
        """docx → pdf, txt."""
        from pds_ultimate.modules.files.converter import SUPPORTED_CONVERSIONS

        assert "pdf" in SUPPORTED_CONVERSIONS["docx"]
        assert "txt" in SUPPORTED_CONVERSIONS["docx"]

    def test_pdf_conversions(self):
        """pdf → txt."""
        from pds_ultimate.modules.files.converter import SUPPORTED_CONVERSIONS

        assert "txt" in SUPPORTED_CONVERSIONS["pdf"]

    def test_json_conversions(self):
        """json → csv."""
        from pds_ultimate.modules.files.converter import SUPPORTED_CONVERSIONS

        assert "csv" in SUPPORTED_CONVERSIONS["json"]


class TestFileConverter:
    """Тесты конвертера."""

    def test_creation(self):
        """FileConverter создаётся."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter is not None

    def test_can_convert_xlsx_csv(self):
        """can_convert: xlsx → csv."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert("xlsx", "csv") is True

    def test_can_convert_csv_xlsx(self):
        """can_convert: csv → xlsx."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert("csv", "xlsx") is True

    def test_can_convert_docx_pdf(self):
        """can_convert: docx → pdf."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert("docx", "pdf") is True

    def test_cannot_convert_pdf_xlsx(self):
        """can_convert: pdf → xlsx — нет."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert("pdf", "xlsx") is False

    def test_cannot_convert_unknown(self):
        """can_convert: неизвестный формат."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert("xyz", "abc") is False

    def test_can_convert_with_dots(self):
        """can_convert с точкой: .xlsx → .csv."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        assert converter.can_convert(".xlsx", ".csv") is True

    def test_get_supported_formats_xlsx(self):
        """get_supported_formats: xlsx."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        formats = converter.get_supported_formats("xlsx")
        assert "csv" in formats

    def test_get_supported_formats_unknown(self):
        """get_supported_formats: неизвестный — пусто."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        formats = converter.get_supported_formats("xyz")
        assert formats == []

    @pytest.mark.asyncio
    async def test_convert_nonexistent_file(self):
        """convert: несуществующий файл."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        result = await converter.convert("/nonexistent/file.xlsx", "csv")
        assert result.success is False
        assert "не найден" in result.error

    @pytest.mark.asyncio
    async def test_convert_unsupported(self):
        """convert: неподдерживаемая конвертация."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            path = f.name
            f.write(b"test")

        try:
            result = await converter.convert(path, "abc")
            assert result.success is False
            assert "не поддерживается" in result.error
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_convert_json_to_csv(self):
        """convert: json → csv."""
        import json

        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump([
                {"name": "Item1", "price": 100},
                {"name": "Item2", "price": 200},
            ], f)
            src_path = f.name

        try:
            result = await converter.convert(src_path, "csv")
            assert result.success is True
            assert os.path.exists(result.target_path)

            # Проверяем содержимое CSV
            import csv
            with open(result.target_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)
            assert len(rows) == 3  # header + 2 rows
            assert "name" in rows[0]
        finally:
            os.unlink(src_path)
            if result.success and os.path.exists(result.target_path):
                os.unlink(result.target_path)

    @pytest.mark.asyncio
    async def test_convert_batch(self):
        """convert_batch: пакетная конвертация."""
        import json

        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()

        paths = []
        try:
            for i in range(2):
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, mode="w"
                ) as f:
                    json.dump([{"val": i}], f)
                    paths.append(f.name)

            results = await converter.convert_batch(paths, "csv")
            assert len(results) == 2
            for r in results:
                assert r.success is True
                if os.path.exists(r.target_path):
                    os.unlink(r.target_path)
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.unlink(p)

    def test_format_result_success(self):
        """format_result: успех."""
        from pds_ultimate.modules.files.converter import (
            ConversionResult,
            FileConverter,
        )

        converter = FileConverter()
        result = ConversionResult(
            success=True,
            source_path="/a.xlsx",
            target_path="/a.csv",
            source_format="xlsx",
            target_format="csv",
        )
        text = converter.format_result(result)
        assert "✅" in text
        assert "XLSX" in text
        assert "CSV" in text

    def test_format_result_error(self):
        """format_result: ошибка."""
        from pds_ultimate.modules.files.converter import (
            ConversionResult,
            FileConverter,
        )

        converter = FileConverter()
        result = ConversionResult(
            success=False,
            source_path="/a.xyz",
            error="Не поддерживается",
        )
        text = converter.format_result(result)
        assert "❌" in text

    def test_format_supported(self):
        """format_supported."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        text = converter.format_supported("xlsx")
        assert "XLSX" in text
        assert "CSV" in text

    def test_format_supported_unknown(self):
        """format_supported: неизвестный."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        text = converter.format_supported("xyz")
        assert "не поддерживается" in text

    def test_get_stats(self):
        """get_stats."""
        from pds_ultimate.modules.files.converter import FileConverter

        converter = FileConverter()
        stats = converter.get_stats()
        assert "total_conversions" in stats
        assert "supported_formats" in stats

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.files.converter import file_converter

        assert file_converter is not None
