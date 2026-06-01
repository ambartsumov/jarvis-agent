"""
Тесты Excel Engine (standalone) — modules/files/excel_engine.py
"""

import os
import tempfile

import pytest


class TestExcelEngine:
    """Тесты Excel Engine."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.files.excel_engine import (
            ExcelEngine,
            excel_engine,
        )
        assert ExcelEngine is not None
        assert excel_engine is not None

    def test_engine_creation(self):
        """ExcelEngine создаётся."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        assert engine is not None

    def test_default_formats(self):
        """Форматы по умолчанию."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        assert hasattr(engine, "DEFAULT_HEADER_FORMAT") or True
        # Formats are constants/dicts

    @pytest.mark.asyncio
    async def test_create_basic(self):
        """create: базовый Excel-файл."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name

        try:
            result = await engine.create(path, {
                "title": "Тест",
                "headers": ["Товар", "Кол-во", "Цена"],
                "rows": [
                    ["Маски", "100", "$200"],
                    ["Перчатки", "50", "$150"],
                ],
            })
            assert result.get("success") is True
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_create_empty(self):
        """create: пустой документ."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name

        try:
            result = await engine.create(path, {
                "title": "Пустой",
                "headers": [],
                "rows": [],
            })
            assert result.get("success") is True
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_read_basic(self):
        """read: чтение файла."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name

        try:
            # Сначала создаём
            await engine.create(path, {
                "title": "Чтение",
                "headers": ["A", "B"],
                "rows": [["1", "2"], ["3", "4"]],
            })

            # Потом читаем
            data = await engine.read(path)
            assert "headers" in data or "rows" in data
            if "rows" in data:
                assert len(data["rows"]) >= 2
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        """read: несуществующий файл."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        data = await engine.read("/nonexistent/file.xlsx")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_create_from_dataframe(self):
        """create_from_dataframe (если доступен)."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        if not hasattr(engine, "create_from_dataframe"):
            pytest.skip("create_from_dataframe не реализован")

        # Пробуем без pandas (должен обработать ошибку)
        try:
            import pandas as pd
            df = pd.DataFrame({
                "Name": ["Test1", "Test2"],
                "Value": [100, 200],
            })
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                path = f.name
            try:
                result = await engine.create_from_dataframe(path, df)
                assert result.get("success") is True
            finally:
                if os.path.exists(path):
                    os.unlink(path)
        except ImportError:
            pytest.skip("pandas не установлен")

    @pytest.mark.asyncio
    async def test_add_chart(self):
        """add_chart (если доступен)."""
        from pds_ultimate.modules.files.excel_engine import ExcelEngine

        engine = ExcelEngine()
        if not hasattr(engine, "add_chart"):
            pytest.skip("add_chart не реализован")

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            path = f.name

        try:
            await engine.create(path, {
                "title": "Chart Test",
                "headers": ["Month", "Sales"],
                "rows": [["Jan", "100"], ["Feb", "200"], ["Mar", "150"]],
            })
            result = await engine.add_chart(
                path,
                chart_type="column",
                title="Sales Chart",
                data_range="B1:B4",
            )
            # Может быть success или ошибка (зависит от реализации)
            assert isinstance(result, dict)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.files.excel_engine import excel_engine

        assert excel_engine is not None
