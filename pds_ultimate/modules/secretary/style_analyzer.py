"""
PDS-Ultimate Style Analyzer
===============================
Модуль мимикрии — анализ стиля общения владельца.

По ТЗ:
- Telegram: 7 последних активных чатов (через Telethon)
- WhatsApp: 3 последних активных чата (через Playwright)
- DeepSeek анализирует: длину сообщений, сленг, эмодзи, официальность
- Формирует «Communication Style Guide» — профиль стиля
- Все исходящие сообщения генерируются в этом стиле
- Пересканирование раз в неделю
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from pds_ultimate.config import config, logger
from pds_ultimate.core.database import CommunicationStyle
from pds_ultimate.core.llm_engine import llm_engine

# ═══════════════════════════════════════════════════════════════════════════════
# Промпт для анализа стиля
# ═══════════════════════════════════════════════════════════════════════════════

STYLE_ANALYSIS_PROMPT = """Проанализируй сообщения владельца и создай подробный профиль стиля общения.

Верни JSON:
{
  "summary": "краткое описание стиля (1-2 предложения)",
  "avg_message_length": "short/medium/long",
  "formality": "informal/semi-formal/formal",
  "uses_emoji": true/false,
  "emoji_frequency": "never/rare/often/always",
  "common_emoji": ["😊", "👍"],
  "greeting_style": "как обычно здоровается",
  "farewell_style": "как обычно прощается",
  "punctuation": "как использует знаки препинания",
  "capitalization": "как использует заглавные буквы",
  "slang_words": ["список характерных слов/выражений"],
  "sentence_structure": "короткие рубленые / длинные развёрнутые",
  "humor_level": "none/light/moderate/heavy",
  "language_mix": "моно / переключается между языками",
  "typical_phrases": ["характерные фразы и выражения"],
  "response_speed_style": "мгновенно в 1-2 слова / развёрнуто",
  "tone": "дружеский/деловой/нейтральный/резкий"
}

Анализируй ТОЛЬКО исходящие сообщения (от владельца).
"""

STYLE_SYSTEM_PROMPT_TEMPLATE = """При ответах от имени владельца используй следующий стиль:

Общий стиль: {summary}
Длина сообщений: {avg_message_length}
Формальность: {formality}
Тон: {tone}
Эмодзи: {emoji_desc}
Типичные фразы: {typical_phrases}
Приветствие: {greeting_style}
Прощание: {farewell_style}
Сленг: {slang_words}
Структура предложений: {sentence_structure}

ВАЖНО: Пиши ИМЕННО так, как писал бы владелец — с его манерой, его словами, его стилем.
Не делай текст более формальным или литературным чем у него.
"""


class StyleAnalyzer:
    """
    Анализатор стиля общения.
    Сканирует чаты → DeepSeek анализирует → формирует профиль → сохраняет в БД.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Основные методы
    # ═══════════════════════════════════════════════════════════════════════

    async def full_scan(self) -> dict:
        """
        Полное сканирование: Telegram (7 чатов) + WhatsApp (3 чата).
        Возвращает профиль стиля.
        """
        logger.info("🔍 Запуск полного сканирования стиля общения...")

        all_messages: list[str] = []

        # ─── Telegram (Telethon) ─────────────────────────────────────
        tg_messages = await self._scan_telegram()
        all_messages.extend(tg_messages)
        tg_count = len(tg_messages)
        logger.info(f"  TG: собрано {tg_count} исходящих сообщений")

        # ─── WhatsApp (Playwright) ───────────────────────────────────
        wa_messages: list[str] = []
        if config.whatsapp.enabled:
            wa_messages = await self._scan_whatsapp()
            all_messages.extend(wa_messages)
            logger.info(
                f"  WA: собрано {len(wa_messages)} исходящих сообщений")
        else:
            logger.info("  WA: отключён, пропускаем")

        # ─── Проверка минимума ───────────────────────────────────────
        if len(all_messages) < config.style.min_messages_for_profile:
            logger.warning(
                f"Мало сообщений для профиля: {len(all_messages)} "
                f"(мин. {config.style.min_messages_for_profile})"
            )

        if not all_messages:
            logger.error("Нет сообщений для анализа стиля")
            return {}

        # ─── Анализ через DeepSeek ───────────────────────────────────
        profile = await self._analyze_messages(all_messages)

        # ─── Генерация system prompt ─────────────────────────────────
        system_prompt = self._generate_system_prompt(profile)

        # ─── Сохранение в БД ─────────────────────────────────────────
        with self._session_factory() as session:
            self._save_profile(
                session=session,
                profile=profile,
                system_prompt=system_prompt,
                tg_chats=config.telethon.style_analysis_chat_count,
                wa_chats=len(
                    wa_messages) > 0 and config.whatsapp.style_analysis_chat_count or 0,
                total_messages=len(all_messages),
            )

        # ─── Применяем стиль к LLM Engine ────────────────────────────
        llm_engine.set_style_guide(system_prompt)

        logger.info(f"✅ Профиль стиля создан из {len(all_messages)} сообщений")
        return profile

    async def load_existing_profile(self) -> bool:
        """
        Загрузить существующий профиль из БД (при старте системы).
        Возвращает True если профиль загружен.
        """
        with self._session_factory() as session:
            style = session.query(CommunicationStyle).filter_by(
                is_active=True
            ).order_by(CommunicationStyle.id.desc()).first()

            if not style or not style.system_prompt:
                logger.info("Профиль стиля не найден — нужно сканирование")
                return False

            llm_engine.set_style_guide(style.system_prompt)
            logger.info(
                f"Профиль стиля загружен (ID={style.id}, "
                f"сообщений={style.total_messages_analyzed})"
            )
            return True

    def needs_rescan(self) -> bool:
        """Проверить нужно ли пересканирование стиля."""
        with self._session_factory() as session:
            style = session.query(CommunicationStyle).filter_by(
                is_active=True
            ).order_by(CommunicationStyle.id.desc()).first()

            if not style or not style.last_scan_date:
                return True

            days_since = (datetime.utcnow() - style.last_scan_date).days
            return days_since >= config.style.rescan_interval_days

    # ═══════════════════════════════════════════════════════════════════════
    # Сканирование Telegram
    # ═══════════════════════════════════════════════════════════════════════

    async def _scan_telegram(self) -> list[str]:
        """Сканирование исходящих сообщений из Telegram чатов через общий Telethon клиент."""
        messages: list[str] = []

        try:
            from telethon.tl.types import User

            from pds_ultimate.integrations.telethon_client import telethon_client

            if not telethon_client._started or not telethon_client._client:
                logger.warning("Telethon не запущен — TG анализ пропущен")
                return messages

            client = telethon_client._client

            # Получаем последние активные диалоги
            dialogs = await client.get_dialogs(
                limit=config.telethon.style_analysis_chat_count * 2
            )

            # Фильтруем только личные чаты
            personal_dialogs = [
                d for d in dialogs
                if isinstance(d.entity, User) and not d.entity.bot
            ][:config.telethon.style_analysis_chat_count]

            logger.info(f"  TG: найдено {len(personal_dialogs)} личных чатов")

            # Загружаем persona_engine для per-contact обучения
            try:
                from pds_ultimate.core.persona_engine import persona_engine as _pe
            except Exception:
                _pe = None

            try:
                from pds_ultimate.core.contacts.book import contact_book as _cb
            except Exception:
                _cb = None

            for dialog in personal_dialogs:
                contact_id = dialog.entity.id
                uname = getattr(dialog.entity, "username", None) or ""
                if _cb is not None and dialog.name:
                    try:
                        _cb.save(dialog.name, telegram=uname, notes="из TG scan")
                    except Exception:
                        pass
                chat_messages = []
                async for msg in client.iter_messages(
                    dialog.entity,
                    limit=config.telethon.messages_per_chat,
                    from_user="me",
                ):
                    if msg.text and len(msg.text.strip()) > 2:
                        text = msg.text.strip()
                        chat_messages.append(text)
                        # Храним стиль общения с каждым контактом отдельно
                        # contact_id = с кем переписывался; тексты = как владелец пишет ЭТОМУ человеку
                        if _pe is not None:
                            try:
                                _pe.learn_outbound(
                                    "telegram", contact_id, text,
                                    display_name=dialog.name or "",
                                )
                            except Exception:
                                pass

                messages.extend(chat_messages)
                logger.debug(
                    f"    Чат '{dialog.name}' (id={contact_id}): {len(chat_messages)} сообщений"
                )

        except ImportError:
            logger.warning("Telethon не установлен — TG анализ пропущен")
        except Exception as e:
            logger.error(f"Ошибка сканирования TG: {e}", exc_info=True)

        return messages

    # ═══════════════════════════════════════════════════════════════════════
    # Сканирование WhatsApp
    # ═══════════════════════════════════════════════════════════════════════

    async def _scan_whatsapp(self) -> list[str]:
        """Сканирование исходящих сообщений из WhatsApp чатов."""
        messages: list[str] = []

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch_persistent_context(
                    user_data_dir=str(config.whatsapp.browser_data_dir),
                    headless=config.whatsapp.headless,
                )

                page = browser.pages[0] if browser.pages else await browser.new_page()
                await page.goto("https://web.whatsapp.com", wait_until="networkidle")

                # Ждём загрузки WhatsApp Web
                try:
                    await page.wait_for_selector(
                        '[data-testid="chat-list"]', timeout=60000
                    )
                except Exception:
                    logger.warning("WA Web не загружен — нужна авторизация QR")
                    await browser.close()
                    return messages

                # Находим последние чаты
                chat_elements = await page.query_selector_all(
                    '[data-testid="cell-frame-container"]'
                )
                chat_count = min(
                    len(chat_elements),
                    config.whatsapp.style_analysis_chat_count,
                )

                for i in range(chat_count):
                    try:
                        # Кликаем на чат
                        chat_elements = await page.query_selector_all(
                            '[data-testid="cell-frame-container"]'
                        )
                        if i >= len(chat_elements):
                            break

                        await chat_elements[i].click()
                        await page.wait_for_timeout(2000)

                        # Собираем исходящие сообщения
                        outgoing = await page.query_selector_all(
                            '.message-out .copyable-text'
                        )

                        for msg_el in outgoing[-config.whatsapp.messages_per_chat:]:
                            text = await msg_el.inner_text()
                            if text and len(text.strip()) > 2:
                                messages.append(text.strip())

                    except Exception as e:
                        logger.debug(f"  WA чат #{i}: ошибка — {e}")
                        continue

                await browser.close()

        except ImportError:
            logger.warning("Playwright не установлен — WA анализ пропущен")
        except Exception as e:
            logger.error(f"Ошибка сканирования WA: {e}", exc_info=True)

        return messages

    # ═══════════════════════════════════════════════════════════════════════
    # Анализ сообщений через DeepSeek
    # ═══════════════════════════════════════════════════════════════════════

    async def _analyze_messages(self, messages: list[str]) -> dict:
        """Отправить сообщения в DeepSeek для анализа стиля."""
        # Ограничиваем объём (чтобы не превысить контекст)
        sample = messages[:500]

        # Форматируем для анализа
        messages_text = "\n---\n".join(sample)

        response = await llm_engine.chat(
            message=f"Вот исходящие сообщения владельца ({len(sample)} шт.):\n\n{messages_text}",
            system_prompt=STYLE_ANALYSIS_PROMPT,
            task_type="analyze_style",
            temperature=0.3,
            json_mode=True,
        )

        try:
            profile = json.loads(response)
            logger.info(f"  Стиль: {profile.get('summary', 'N/A')}")
            return profile
        except json.JSONDecodeError:
            logger.error("Не удалось распарсить профиль стиля")
            return {
                "summary": "Стандартный стиль",
                "avg_message_length": "medium",
                "formality": "semi-formal",
                "tone": "дружеский",
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Генерация и сохранение
    # ═══════════════════════════════════════════════════════════════════════

    def _generate_system_prompt(self, profile: dict) -> str:
        """Генерация system prompt из профиля стиля."""
        emoji_desc = "не использует"
        if profile.get("uses_emoji"):
            freq = profile.get("emoji_frequency", "sometimes")
            common = ", ".join(profile.get("common_emoji", []))
            emoji_desc = f"использует ({freq}): {common}" if common else f"использует ({freq})"

        typical = ", ".join(profile.get("typical_phrases", [])[:10])
        slang = ", ".join(profile.get("slang_words", [])[:10])

        return STYLE_SYSTEM_PROMPT_TEMPLATE.format(
            summary=profile.get("summary", "стандартный"),
            avg_message_length=profile.get("avg_message_length", "medium"),
            formality=profile.get("formality", "semi-formal"),
            tone=profile.get("tone", "нейтральный"),
            emoji_desc=emoji_desc,
            typical_phrases=typical or "нет данных",
            greeting_style=profile.get("greeting_style", "стандартное"),
            farewell_style=profile.get("farewell_style", "стандартное"),
            slang_words=slang or "нет",
            sentence_structure=profile.get("sentence_structure", "средние"),
        )

    def _save_profile(
        self,
        session: Session,
        profile: dict,
        system_prompt: str,
        tg_chats: int,
        wa_chats: int,
        total_messages: int,
    ) -> None:
        """Сохранить профиль стиля в БД."""
        # Деактивируем старые профили
        session.query(CommunicationStyle).filter_by(
            is_active=True
        ).update({"is_active": False})

        # Создаём новый
        style = CommunicationStyle(
            style_profile=json.dumps(profile, ensure_ascii=False),
            tg_chats_analyzed=tg_chats,
            wa_chats_analyzed=wa_chats,
            total_messages_analyzed=total_messages,
            system_prompt=system_prompt,
            is_active=True,
            last_scan_date=datetime.utcnow(),
        )
        session.add(style)
        session.commit()
        logger.info(f"Профиль стиля сохранён в БД (ID={style.id})")
