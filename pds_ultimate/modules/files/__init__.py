"""
Files Module
- FileManager: Создание/редактирование файлов (Excel, PDF, DOCX)
- ExcelEngine: Профессиональные Excel-отчёты (standalone)
- PDFEngine: Генерация PDF-инвойсов (standalone)
- OCREngine: Распознавание текста (EasyOCR + Tesseract)
- FileConverter: Конвертация форматов (Word↔PDF, Excel↔CSV, etc.)
"""

from pds_ultimate.modules.files.converter import FileConverter, file_converter
from pds_ultimate.modules.files.excel_engine import ExcelEngine, excel_engine
from pds_ultimate.modules.files.file_manager import FileManager
from pds_ultimate.modules.files.ocr_engine import OCREngine, ocr_engine
from pds_ultimate.modules.files.pdf_engine import PDFEngine, pdf_engine

__all__ = [
    "FileManager",
    "ExcelEngine",
    "excel_engine",
    "PDFEngine",
    "pdf_engine",
    "OCREngine",
    "ocr_engine",
    "FileConverter",
    "file_converter",
]
