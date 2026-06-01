"""
PDS-Ultimate Bot Middlewares
==============================
Middleware для Aiogram:
- AuthMiddleware: Multi-user авторизация (все пользователи допускаются к /start и регистрации)
- LoggingMiddleware: Логирование всех входящих сообщений
- DatabaseMiddleware: Инъекция сессии БД в хэндлеры
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.orm import Session, sessionmaker

from pds_ultimate.config import config, logger


class AuthMiddleware(BaseMiddleware):
    """
    Multi-user авторизация.

    Логика:
    - /start — пропускаем ВСЕХ (для регистрации новых пользователей)
    - Зарегистрированные пользователи — пропускаем
    - Незарегистрированные в процессе ввода имени (AWAITING_NAME) — пропускаем
    - Остальные незарегистрированные — перенаправляем на /start
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        message: Message | None = None

        if isinstance(event, Message):
            message = event
        elif hasattr(event, "message") and isinstance(event.message, Message):
            message = event.message

        if message and message.from_user:
            # Владелец проходит ВСЕГДА, без регистрации и шаблонов
            if message.from_user.id == config.telegram.owner_id:
                return await handler(event, data)

            # /start — всегда пропускаем (точка входа регистрации)
            if message.text and message.text.strip().startswith("/start"):
                return await handler(event, data)

            # Проверяем состояние диалога — если в процессе регистрации, пропускаем
            from pds_ultimate.bot.conversation import (
                ConversationState,
                conversation_manager,
            )
            ctx = conversation_manager.get(message.chat.id)
            if ctx.state in (
                ConversationState.AWAITING_NAME,
                ConversationState.AWAITING_API_SETUP,
            ):
                return await handler(event, data)

            # Проверяем: зарегистрирован ли пользователь?
            from pds_ultimate.core.user_manager import user_manager
            db_session: Session | None = data.get("db_session")

            if db_session:
                # Если db_session уже есть (DB middleware before Auth), используем
                if user_manager.is_registered(message.chat.id, db_session):
                    return await handler(event, data)
            else:
                # Владелец всегда проходит (fallback без БД)
                if message.from_user.id == config.telegram.owner_id:
                    return await handler(event, data)
                # Без БД-сессии пропускаем (DatabaseMiddleware обеспечит позже)
                return await handler(event, data)

            # Незарегистрированный пользователь — просим /start
            logger.debug(
                f"Незарегистрированный user_id={message.from_user.id} — "
                f"перенаправляем на /start"
            )
            await message.answer(
                "👋 Привет! Для начала работы нажми /start"
            )
            return  # Блокируем

        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """
    Логирование всех входящих сообщений.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            content_type = event.content_type
            text_preview = ""
            if event.text:
                text_preview = event.text[:80] + \
                    ("..." if len(event.text) > 80 else "")
            elif event.caption:
                text_preview = f"[caption] {event.caption[:60]}"

            logger.info(
                f"📩 Входящее [{content_type}] от {event.from_user.id}: {text_preview}"
            )

        return await handler(event, data)


class DatabaseMiddleware(BaseMiddleware):
    """
    Инъекция сессии БД в каждый хэндлер.
    Хэндлер получает data["db_session"] — готовую SQLAlchemy сессию.
    Сессия автоматически закрывается после обработки.
    """

    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: Session = self._session_factory()
        data["db_session"] = session
        try:
            result = await handler(event, data)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
