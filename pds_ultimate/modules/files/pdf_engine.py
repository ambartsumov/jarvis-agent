"""
PDS-Ultimate PDF Engine (Standalone)
=======================================
Выделенный движок работы с PDF: генерация, чтение, инвойсы.

Расширения:
- Создание из structure dict
- Создание инвойсов (ТЗ §7.3)
- Чтение PDF → текст
- Merge/Split PDF
- Watermark

Зависимости: reportlab, PyPDF2
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class PDFEngine:
    """
    Продвинутый PDF-движок.

    Возможности:
    - create(): PDF из structure dict
    - create_invoice(): Профессиональный инвойс
    - read(): Извлечение текста
    - merge(): Объединение PDF
    - split(): Разделение PDF
    - add_watermark(): Водяной знак
    """

    # ═══════════════════════════════════════════════════════════════════════
    # Create
    # ═══════════════════════════════════════════════════════════════════════

    async def create(
        self,
        filepath: str,
        structure: dict,
    ) -> dict:
        """
        Создать PDF из structure dict.

        Structure:
        {
            "title": "Document Title",
            "content": "Text content...",
            "headers": ["Col1", "Col2"],
            "rows": [["v1", "v2"], ...],
        }
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()
            elements = []

            # Заголовок
            title = structure.get("title", "Документ")
            elements.append(Paragraph(title, styles["Title"]))
            elements.append(Spacer(1, 12))

            # Текст
            content = structure.get("content", "")
            if content:
                for line in content.split("\n"):
                    if line.strip():
                        elements.append(Paragraph(line, styles["Normal"]))
                        elements.append(Spacer(1, 6))

            # Таблица
            headers = structure.get("headers", [])
            rows = structure.get("rows", [])

            if headers:
                table_data = [headers]
                for row in rows:
                    table_data.append([str(v or "") for v in row])

                t = Table(table_data)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0),
                     colors.HexColor("#4472C4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#D9E2F3")]),
                ]))
                elements.append(t)

            doc.build(elements)
            size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

            return {
                "success": True,
                "path": filepath,
                "format": "pdf",
                "size_bytes": size,
            }

        except ImportError:
            return {"error": "reportlab не установлен"}
        except Exception as e:
            return {"error": f"PDF creation failed: {e}"}

    async def create_invoice(
        self,
        filepath: str,
        order_data: dict,
    ) -> dict:
        """
        Создать профессиональный PDF-инвойс.

        order_data:
        {
            "order_number": "ORD-001",
            "supplier": "Supplier Co.",
            "client": "Client Co.",
            "items": [
                {"name": "Item 1", "quantity": 10, "unit_price": 50, "unit": "шт"},
            ],
            "currency": "USD",
            "notes": "Payment terms: 30 days",
        }
        """
        items = order_data.get("items", [])
        currency = order_data.get("currency", "USD")
        symbol = {"USD": "$", "EUR": "€", "CNY": "¥",
                  "TMT": "TMT", "RUB": "₽"}.get(currency, currency)

        headers = ["#", "Наименование", "Кол-во", "Ед.", "Цена", "Сумма"]

        rows = []
        total = 0.0
        for i, item in enumerate(items, 1):
            qty = item.get("quantity", 0)
            price = item.get("unit_price", 0) or 0
            subtotal = qty * price
            total += subtotal

            rows.append([
                str(i),
                item.get("name", ""),
                str(qty),
                item.get("unit", "шт"),
                f"{symbol}{price:,.2f}",
                f"{symbol}{subtotal:,.2f}",
            ])

        rows.append(["", "", "", "", "ИТОГО:", f"{symbol}{total:,.2f}"])

        structure = {
            "title": (
                f"ИНВОЙС — Заказ "
                f"#{order_data.get('order_number', '?')}"
            ),
            "headers": headers,
            "rows": rows,
            "content": (
                f"Дата: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"Поставщик: {order_data.get('supplier', '—')}\n"
                f"Клиент: {order_data.get('client', '—')}\n"
                + (f"Примечание: {order_data.get('notes', '')}\n"
                   if order_data.get('notes') else "")
            ),
        }

        return await self.create(filepath, structure)

    # ═══════════════════════════════════════════════════════════════════════
    # Read
    # ═══════════════════════════════════════════════════════════════════════

    async def read(self, filepath: str) -> dict:
        """Извлечь текст из PDF."""
        try:
            import PyPDF2

            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n"

            return {
                "content": text.strip(),
                "format": "pdf",
                "pages": len(reader.pages),
            }

        except ImportError:
            return {"error": "PyPDF2 не установлен"}
        except Exception as e:
            return {"error": f"PDF read failed: {e}"}

    # ═══════════════════════════════════════════════════════════════════════
    # Merge / Split
    # ═══════════════════════════════════════════════════════════════════════

    async def merge(
        self,
        filepaths: list[str],
        output_path: str,
    ) -> dict:
        """Объединить несколько PDF в один."""
        try:
            import PyPDF2

            merger = PyPDF2.PdfMerger()

            for fp in filepaths:
                if os.path.exists(fp):
                    merger.append(fp)

            merger.write(output_path)
            merger.close()

            return {
                "success": True,
                "path": output_path,
                "merged_count": len(filepaths),
            }

        except Exception as e:
            return {"error": f"PDF merge failed: {e}"}

    async def split(
        self,
        filepath: str,
        output_dir: str,
        pages: Optional[list[int]] = None,
    ) -> dict:
        """
        Разделить PDF на отдельные страницы.
        pages: list of page numbers (1-based) or None for all.
        """
        try:
            import PyPDF2

            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                total_pages = len(reader.pages)

                if pages is None:
                    pages = list(range(1, total_pages + 1))

                results = []
                stem = Path(filepath).stem

                for page_num in pages:
                    if page_num < 1 or page_num > total_pages:
                        continue

                    writer = PyPDF2.PdfWriter()
                    writer.add_page(reader.pages[page_num - 1])

                    out_path = os.path.join(
                        output_dir, f"{stem}_page_{page_num}.pdf"
                    )
                    os.makedirs(output_dir, exist_ok=True)

                    with open(out_path, "wb") as out_f:
                        writer.write(out_f)

                    results.append(out_path)

            return {
                "success": True,
                "pages_split": len(results),
                "files": results,
            }

        except Exception as e:
            return {"error": f"PDF split failed: {e}"}

    async def add_watermark(
        self,
        filepath: str,
        watermark_text: str,
        output_path: Optional[str] = None,
    ) -> dict:
        """Добавить текстовый водяной знак (простая реализация)."""
        try:
            import io

            import PyPDF2
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            # Создаём PDF с водяным знаком
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=A4)
            c.setFont("Helvetica", 40)
            c.setFillAlpha(0.2)
            c.saveState()
            c.translate(300, 400)
            c.rotate(45)
            c.drawCentredString(0, 0, watermark_text)
            c.restoreState()
            c.save()
            packet.seek(0)

            watermark_pdf = PyPDF2.PdfReader(packet)
            watermark_page = watermark_pdf.pages[0]

            # Применяем ко всем страницам
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                writer = PyPDF2.PdfWriter()

                for page in reader.pages:
                    page.merge_page(watermark_page)
                    writer.add_page(page)

                out = output_path or filepath
                with open(out, "wb") as out_f:
                    writer.write(out_f)

            return {"success": True, "path": out}

        except Exception as e:
            return {"error": f"Watermark failed: {e}"}

    def get_stats(self) -> dict:
        return {"engine": "pdf", "backends": ["reportlab", "PyPDF2"]}


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

pdf_engine = PDFEngine()
