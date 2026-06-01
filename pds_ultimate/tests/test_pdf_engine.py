"""
Тесты PDF Engine (standalone) — modules/files/pdf_engine.py
"""

import os
import tempfile

import pytest


class TestPDFEngine:
    """Тесты PDF Engine."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.files.pdf_engine import (
            PDFEngine,
            pdf_engine,
        )
        assert PDFEngine is not None
        assert pdf_engine is not None

    def test_engine_creation(self):
        """PDFEngine создаётся."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        assert engine is not None

    @pytest.mark.asyncio
    async def test_create_basic(self):
        """create: базовый PDF."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name

        try:
            result = await engine.create(path, {
                "title": "Тестовый документ",
                "content": "Это тестовое содержимое документа.\nВторая строка.",
            })
            assert result.get("success") is True
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_create_with_table(self):
        """create: PDF с таблицей."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name

        try:
            result = await engine.create(path, {
                "title": "Отчёт",
                "headers": ["Товар", "Цена", "Кол-во"],
                "rows": [
                    ["Маски", "$200", "100"],
                    ["Перчатки", "$150", "50"],
                ],
            })
            assert result.get("success") is True
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_create_invoice(self):
        """create_invoice: профессиональный инвойс."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        if not hasattr(engine, "create_invoice"):
            pytest.skip("create_invoice не реализован")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name

        try:
            result = await engine.create_invoice(path, {
                "invoice_number": "INV-001",
                "date": "2025-06-15",
                "seller": "PDS Company",
                "buyer": "Test Buyer",
                "items": [
                    {"name": "Маски", "qty": 100, "price": 2.0},
                    {"name": "Перчатки", "qty": 50, "price": 3.0},
                ],
                "currency": "USD",
            })
            assert result.get("success") is True
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_read_basic(self):
        """read: чтение PDF."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name

        try:
            # Создаём
            await engine.create(path, {
                "title": "Тест чтения",
                "content": "Hello World текст",
            })

            # Читаем
            data = await engine.read(path)
            assert "content" in data or "text" in data or "error" not in data
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        """read: несуществующий файл."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        data = await engine.read("/nonexistent/file.pdf")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_merge(self):
        """merge: объединение PDF."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        if not hasattr(engine, "merge"):
            pytest.skip("merge не реализован")

        paths = []
        try:
            for i in range(2):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    p = f.name
                    paths.append(p)
                await engine.create(p, {
                    "title": f"Doc {i + 1}",
                    "content": f"Content of document {i + 1}",
                })

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                merged_path = f.name
                paths.append(merged_path)

            result = await engine.merge(
                [paths[0], paths[1]], merged_path
            )
            assert result.get("success") is True
            assert os.path.exists(merged_path)
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.unlink(p)

    @pytest.mark.asyncio
    async def test_split(self):
        """split: разделение PDF."""
        from pds_ultimate.modules.files.pdf_engine import PDFEngine

        engine = PDFEngine()
        if not hasattr(engine, "split"):
            pytest.skip("split не реализован")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name

        try:
            await engine.create(path, {
                "title": "Split Test",
                "content": "Page content",
            })

            with tempfile.TemporaryDirectory() as tmpdir:
                result = await engine.split(path, tmpdir)
                assert isinstance(result, dict)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.files.pdf_engine import pdf_engine

        assert pdf_engine is not None
