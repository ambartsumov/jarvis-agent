"""
PDS-Ultimate File Handler
=============================
Обработка ЛЮБЫХ файлов:
- Документы: Excel (.xlsx/.xls), Word (.docx), PDF, CSV
- Фото: Распознавание текста (OCR), извлечение трек-номеров
- Любой файл: сохранение + контекстная обработка

Логика:
1. Скачать файл
2. Определить тип (по расширению или MIME)
3. Распарсить (Excel/Word/PDF/OCR)
4. Если есть состояние (заказ) → парсить как позиции
5. Если свободный режим → LLM решает что делать
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.orm import Session

from pds_ultimate.bot.conversation import (
    ConversationState,
    conversation_manager,
)
from pds_ultimate.bot.handlers.universal import (
    _format_items_list,
    _format_items_list_from_dicts,
    _save_to_db,
)
from pds_ultimate.config import DATA_DIR, logger
from pds_ultimate.core.llm_engine import llm_engine

router = Router(name="files")

# Папка для сохранённых файлов
FILES_DIR = DATA_DIR / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)

# Расширения документов
EXCEL_EXT = {".xlsx", ".xls"}
WORD_EXT = {".docx", ".doc"}
PDF_EXT = {".pdf"}
CSV_EXT = {".csv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
DOC_EXT = EXCEL_EXT | WORD_EXT | PDF_EXT | CSV_EXT


# ═══════════════════════════════════════════════════════════════════════════════
# Обработка ДОКУМЕНТОВ (Excel, Word, PDF, CSV и т.д.)
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(F.document)
async def handle_document(message: Message, db_session: Session) -> None:
    """Обработка любого документа."""
    chat_id = message.chat.id
    ctx = conversation_manager.get(chat_id)
    doc = message.document

    if not doc.file_name:
        await message.answer("❌ Файл без имени, не могу обработать.")
        return

    await message.bot.send_chat_action(chat_id, "typing")

    file_ext = Path(doc.file_name).suffix.lower()
    logger.info(
        f"Файл: {doc.file_name} ({doc.mime_type}), размер: {doc.file_size}")

    # Скачиваем
    tmp_dir = tempfile.mkdtemp(prefix="pds_file_")
    local_path = Path(tmp_dir) / doc.file_name

    try:
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=str(local_path))

        # ─── Обрабатываемый документ ─────────────────────────────────
        if file_ext in DOC_EXT:
            await _process_document(message, ctx, local_path, file_ext, db_session)

        # ─── Изображение как документ ────────────────────────────────
        elif file_ext in IMAGE_EXT:
            await _process_image(message, ctx, local_path, db_session)

        # ─── Неизвестный тип — сохраняем и сообщаем ──────────────────
        else:
            saved = _save_file(local_path, doc.file_name)
            caption = message.caption or ""

            response = await llm_engine.chat(
                message=(
                    f"Пользователь прислал файл: {doc.file_name} "
                    f"(тип: {doc.mime_type}, размер: {doc.file_size} байт). "
                    f"Подпись: «{caption}». "
                    f"Файл сохранён в {saved}. "
                    f"Ответь пользователю что файл сохранён и спроси что с ним сделать."
                ),
                task_type="general",
            )

            await message.answer(response)
            _save_to_db(db_session, chat_id, "assistant", response)

    except Exception as e:
        logger.error(f"Ошибка обработки файла: {e}", exc_info=True)
        await message.answer("❌ Не удалось обработать файл. Попробуй ещё раз.")

    finally:
        _cleanup_tmp(tmp_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# Обработка ФОТО
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(F.photo)
async def handle_photo(message: Message, db_session: Session) -> None:
    """
    Обработка фотографий.
    По ТЗ: фото = данные (OCR для чеков, накладных, трек-номеров).
    """
    chat_id = message.chat.id
    ctx = conversation_manager.get(chat_id)

    await message.bot.send_chat_action(chat_id, "typing")

    # Берём фото максимального качества
    photo = message.photo[-1]

    tmp_dir = tempfile.mkdtemp(prefix="pds_photo_")
    local_path = Path(tmp_dir) / f"photo_{photo.file_id[:8]}.jpg"

    try:
        file = await message.bot.get_file(photo.file_id)
        await message.bot.download_file(file.file_path, destination=str(local_path))

        logger.info(
            f"Фото: {photo.width}x{photo.height}, "
            f"размер: {photo.file_size} байт"
        )

        await _process_image(message, ctx, local_path, db_session)

    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
        await message.answer("❌ Не удалось обработать фото. Попробуй ещё раз.")

    finally:
        _cleanup_tmp(tmp_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# ВНУТРЕННЯЯ ЛОГИКА: Обработка документов
# ═══════════════════════════════════════════════════════════════════════════════

async def _process_document(
    message: Message,
    ctx,
    file_path: Path,
    ext: str,
    db_session: Session,
) -> None:
    """Обработка документа (Excel, Word, PDF, CSV)."""
    from pds_ultimate.utils.parsers import parser

    chat_id = message.chat.id
    caption = message.caption or ""

    # Парсим файл
    result = await parser.parse_file(str(file_path))

    if not result:
        await message.answer(
            f"📄 Файл получен: {file_path.name}\n"
            f"Не удалось извлечь данные. Что мне с ним сделать?"
        )
        return

    # ─── Если мы в состоянии ввода заказа → парсим как позиции ────────
    if ctx.state in (ConversationState.ORDER_INPUT, ConversationState.ORDER_CONFIRM):
        if result.items:
            existing = ctx.get_temp("parsed_items", [])
            new_items = [item.to_dict() for item in result.items]
            all_items = existing + new_items

            ctx.set_state(ConversationState.ORDER_CONFIRM,
                          parsed_items=all_items)

            items_text = _format_items_list_from_dicts(all_items)
            response = (
                f"📄 Из файла извлечено {len(new_items)} позиций:\n\n"
                f"{items_text}\n\n"
                f"Всё верно? Поправь текстом или скажи «готово»."
            )
        else:
            response = (
                f"📄 Файл прочитан, но позиции не распознаны.\n"
                f"Найден текст:\n{result.raw_text[:500]}...\n\n"
                f"Попробуй указать позиции текстом."
            )

        await message.answer(response)
        _save_to_db(db_session, chat_id, "assistant", response)
        return

    # ─── Свободный режим — LLM решает что делать ─────────────────────

    # Формируем контекст для LLM
    file_info = f"Файл: {file_path.name} (тип: {ext})\n"

    if result.items:
        items_text = _format_items_list(result.items)
        file_info += f"Распознанные позиции:\n{items_text}\n"

    if result.raw_text:
        preview = result.raw_text[:2000]
        file_info += f"Текст из файла:\n{preview}\n"

    # Подпись пользователя
    prompt = "Пользователь прислал файл"
    if caption:
        prompt += f" с подписью «{caption}»"
    prompt += f".\n\n{file_info}\n\nЧто с этим делать? Проанализируй и ответь."

    response = await llm_engine.chat(
        message=prompt,
        history=ctx.get_history_for_llm(),
        task_type="general",
    )

    # Сохраняем файл
    saved_path = _save_file(file_path, file_path.name)

    if response:
        await message.answer(response)
        ctx.add_assistant_message(response)
        _save_to_db(db_session, chat_id, "assistant", response)
    else:
        fallback = f"📄 Файл сохранён: {saved_path.name}"
        await message.answer(fallback)
        _save_to_db(db_session, chat_id, "assistant", fallback)


# ═══════════════════════════════════════════════════════════════════════════════
# ВНУТРЕННЯЯ ЛОГИКА: Обработка изображений (OCR)
# ═══════════════════════════════════════════════════════════════════════════════

async def _process_image(
    message: Message,
    ctx,
    file_path: Path,
    db_session: Session,
) -> None:
    """
    Обработка фото через OCR.
    По ТЗ: фото чека, накладной, этикетки = данные.
    """
    from pds_ultimate.utils.parsers import parser

    chat_id = message.chat.id
    caption = message.caption or ""

    # OCR + извлечение трека
    ocr_text = await parser.parse_image(str(file_path))
    tracking = await parser.extract_tracking_number(str(file_path))

    # ─── Если ожидаем трек-номер → сразу используем ──────────────────
    if ctx.state == ConversationState.AWAITING_TRACK and tracking:
        message.text = tracking
        from pds_ultimate.bot.handlers.universal import handle_text
        await handle_text(message, db_session)
        return

    # ─── Если ожидаем статус или ввод заказа ─────────────────────────
    if ctx.state in (ConversationState.ORDER_INPUT, ConversationState.ORDER_CONFIRM):
        # Парсим OCR текст как позиции
        if ocr_text:
            result = await parser.parse_text_smart(ocr_text)
            if result.items:
                existing = ctx.get_temp("parsed_items", [])
                new_items = [item.to_dict() for item in result.items]
                all_items = existing + new_items

                ctx.set_state(ConversationState.ORDER_CONFIRM,
                              parsed_items=all_items)

                items_text = _format_items_list_from_dicts(all_items)
                response = (
                    f"📸 Из фото распознано {len(new_items)} позиций:\n\n"
                    f"{items_text}\n\n"
                    f"Всё верно? Поправь текстом или скажи «готово»."
                )
                await message.answer(response)
                _save_to_db(db_session, chat_id, "assistant", response)
                return

    # ─── Свободный режим — LLM анализирует ───────────────────────────
    context_parts = []

    if tracking:
        context_parts.append(f"🔍 Обнаружен трек-номер: {tracking}")

    if ocr_text:
        context_parts.append(f"📝 Распознанный текст:\n{ocr_text[:2000]}")
    else:
        context_parts.append("Текст на фото не распознан.")

    if caption:
        context_parts.append(f"Подпись: «{caption}»")

    ocr_info = "\n".join(context_parts)

    # LLM анализирует
    response = await llm_engine.chat(
        message=(
            f"Пользователь прислал фото.\n\n{ocr_info}\n\n"
            f"Проанализируй что на фото и ответь пользователю. "
            f"Если это чек, накладная или этикетка — извлеки ключевые данные."
        ),
        history=ctx.get_history_for_llm(),
        task_type="general",
    )

    # Сохраняем фото
    _save_file(file_path, file_path.name)

    # Добавляем инфо о треке если найден
    if tracking and "трек" not in response.lower():
        response = f"🔍 Трек-номер: {tracking}\n\n{response}"

    await message.answer(response)
    ctx.add_assistant_message(response)
    _save_to_db(db_session, chat_id, "assistant", response)


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def _save_file(source: Path, filename: str) -> Path:
    """Сохранить файл в постоянное хранилище."""
    from datetime import datetime

    # Создаём подпапку по дате
    today_dir = FILES_DIR / datetime.now().strftime("%Y-%m-%d")
    today_dir.mkdir(parents=True, exist_ok=True)

    dest = today_dir / filename

    # Если файл с таким именем уже есть — добавляем суффикс
    counter = 1
    while dest.exists():
        stem = Path(filename).stem
        ext = Path(filename).suffix
        dest = today_dir / f"{stem}_{counter}{ext}"
        counter += 1

    shutil.copy2(str(source), str(dest))
    logger.info(f"Файл сохранён: {dest}")
    return dest


def _cleanup_tmp(tmp_dir: str) -> None:
    """Очистить временную папку."""
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except OSError:
        pass
