"""
PDS-Ultimate Inline Mode Handler
==================================
Обрабатывает inline-запросы (@bot <текст>) в любом чате.
Позволяет использовать агента без добавления бота в группу —
достаточно набрать @botname вопрос в строке сообщения.

Если запрос пустой — возвращает подсказку.
Если запрос содержит текст — спрашивает агента и возвращает ответ.
"""

from __future__ import annotations

import uuid

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from pds_ultimate.config import logger

router = Router(name="inline")


@router.inline_query()
async def handle_inline_query(query: InlineQuery) -> None:
    """
    Обработка inline-запроса.

    Пример: @pds_bot курс доллара сегодня
    """
    text = (query.query or "").strip()

    if not text:
        # Подсказка при пустом запросе
        await query.answer(
            results=[
                InlineQueryResultArticle(
                    id="help",
                    title="Спросить агента",
                    description="Введите вопрос после @имя_бота ...",
                    input_message_content=InputTextMessageContent(
                        message_text="❓ Введите вопрос после упоминания бота."
                    ),
                )
            ],
            cache_time=1,
            is_personal=True,
        )
        return

    # Получаем ответ от агента (прямой вызов, без истории)
    response = "⚠️ Агент временно недоступен."
    try:
        from pds_ultimate.core.agent import agent

        response = await agent.direct_response(
            message=text,
            history=[],
            style_guide="",
            chat_id=0,
        )
        if not response:
            response = "🤖 Агент не смог дать ответ."
    except Exception as e:
        logger.warning(f"[INLINE] Ошибка агента: {e}")
        response = f"⚠️ Ошибка: {e}"

    # Обрезаем до лимитов Telegram inline
    title = response[:100].replace("\n", " ")
    description = response[:200].replace("\n", " ")
    # Полный текст тоже обрезаем — максимум 4096 символов в сообщении
    full_text = response[:4096]

    await query.answer(
        results=[
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🤖 {title}",
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=full_text,
                ),
            )
        ],
        cache_time=5,
        is_personal=True,
    )
    logger.info(f"[INLINE] Ответ на '{text[:50]}': {len(response)} символов")
