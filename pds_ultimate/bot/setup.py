"""
PDS-Ultimate Bot Setup
=========================
Фабричная функция создания бота.
Единая точка сборки: Bot + Dispatcher + роутеры + мидлвари.

Архитектура:
- Bot — экземпляр aiogram.Bot
- Dispatcher — обработка апдейтов
- Роутеры: universal (текст), voice (голос), files (документы/фото)
- Мидлвари: Auth → Logging → Database (в порядке применения)
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from sqlalchemy.orm import sessionmaker

from pds_ultimate.bot.handlers import files, inline, universal, voice
from pds_ultimate.bot.handlers import settings as settings_handlers
from pds_ultimate.bot.middlewares import (
    AuthMiddleware,
    DatabaseMiddleware,
    LoggingMiddleware,
)
from pds_ultimate.config import AGENT_DISPLAY, BASE_DIR, config, logger


async def create_bot(
    session_factory: sessionmaker,
) -> tuple[Bot, Dispatcher]:
    """
    Создать и настроить бота.

    Args:
        session_factory: SQLAlchemy sessionmaker (из init_database)

    Returns:
        (Bot, Dispatcher) — готовые к polling.
    """
    logger.info("🤖 Создание Telegram бота...")

    # ─── 1. Bot instance ─────────────────────────────────────────────
    # Прокси для обхода блокировок Telegram API
    session = None
    from pds_ultimate.config import proxy_if_available

    proxy = proxy_if_available(config.telegram.proxy)
    if proxy:
        session = AiohttpSession(proxy=proxy)
        logger.info(f"  🌐 Telegram proxy: {proxy}")
    elif config.telegram.proxy:
        logger.warning(
            f"  🌐 Прокси {config.telegram.proxy} недоступен — подключаюсь к Telegram напрямую"
        )

    bot = Bot(
        token=config.telegram.token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    # ─── 2. Dispatcher ───────────────────────────────────────────────
    dp = Dispatcher()

    # ─── 3. Регистрация мидлварей (порядок важен!) ───────────────────
    # Database → инжектирует db_session (нужна для Auth проверки регистрации)
    dp.message.middleware(DatabaseMiddleware(session_factory))

    # Auth → проверяет регистрацию пользователя (использует db_session)
    dp.message.outer_middleware(AuthMiddleware())

    # Logging → логируем все входящие
    dp.message.outer_middleware(LoggingMiddleware())

    logger.info("  ✓ Мидлвари зарегистрированы (DB → Auth → Log)")

    # ─── 4. Регистрация роутеров (порядок важен!) ────────────────────
    # voice и files — ПЕРЕД universal, т.к. universal ловит F.text
    dp.include_router(voice.router)     # F.voice, F.video_note
    dp.include_router(files.router)     # F.document, F.photo
    # /settings, /brief, /backup, /report, /autoreply
    dp.include_router(settings_handlers.router)
    dp.include_router(universal.router)  # CommandStart + F.text
    dp.include_router(inline.router)      # @bot <query> inline mode

    logger.info(
        "  ✓ Роутеры зарегистрированы (voice → files → settings → universal → inline)")

    # ─── 5. Startup/shutdown хуки ────────────────────────────────────
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    # ─── 6. Предзагрузка Vosk модели (мгновенное STT с первого голосового) ──
    try:
        import asyncio

        from pds_ultimate.core.speech_engine import speech_engine
        asyncio.get_event_loop().run_in_executor(None, speech_engine.preload)
        logger.info("  ⚙ Vosk модель предзагружается в фоне...")
    except Exception as _e:
        logger.debug(f"  Vosk preload skip: {_e}")

    logger.info("🤖 Бот создан и готов к работе")
    return bot, dp


async def _on_startup(bot: Bot) -> None:
    """Действия при запуске бота."""
    try:
        me = await bot.get_me()
        logger.info(f"🚀 Бот запущен: @{me.username} (id: {me.id})")
    except Exception as e:
        logger.warning(f"⚠ get_me() не удался при старте: {e}")

    # Уведомляем владельца (не чаще раза в 10 мин — иначе дубли при перезапусках)
    try:
        import time

        stamp_file = BASE_DIR / "data" / ".last_startup_notify"
        now = time.time()
        if stamp_file.exists():
            try:
                if now - float(stamp_file.read_text().strip()) < 600:
                    return
            except ValueError:
                pass
        await bot.send_message(
            config.telegram.owner_id,
            f"🟢 {AGENT_DISPLAY} запущен и готов к работе!\n"
            "Пиши текстом или голосом — я пойму.",
        )
        stamp_file.parent.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(str(now))
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление владельцу: {e}")


async def _on_shutdown(bot: Bot) -> None:
    """Действия при остановке бота."""
    logger.info("🔴 Бот останавливается...")

    try:
        await bot.send_message(
            config.telegram.owner_id,
            f"🔴 {AGENT_DISPLAY} остановлен.",
        )
    except Exception:
        pass

    # Закрываем сессию бота
    await bot.session.close()
    logger.info("🔴 Бот остановлен")


async def start_polling(bot: Bot, dp: Dispatcher) -> None:
    """
    Запустить long polling с автоматическим перезапуском при сетевых ошибках.
    """
    import asyncio

    from aiogram.exceptions import TelegramNetworkError

    retry_delay = 5
    max_retry_delay = 60

    while True:
        logger.info("📡 Запуск polling...")
        try:
            await dp.start_polling(
                bot,
                allowed_updates=[
                    "message",
                    "callback_query",
                ],
                drop_pending_updates=True,
            )
            break  # нормальный выход (Ctrl+C / shutdown)
        except TelegramNetworkError as e:
            logger.warning(
                f"⚠ Сетевая ошибка Telegram: {e}. "
                f"Повтор через {retry_delay}с..."
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
        except Exception:
            raise  # прочие ошибки — пробрасываем наверх
