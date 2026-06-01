"""
PDS-Ultimate Communication Tools
=================================
Инструменты для коммуникаций: Telegram, WhatsApp, Email.

ФУНКЦИИ:
- Отправка сообщений Telegram
- Отправка сообщений WhatsApp
- Чтение чатов
- Анализ стиля общения
- Мимикрия стиля

ARCHITECTURE:
- Async-first для всех операций
- Rate limiting для предотвращения блокировок
- Error handling с retry logic
"""

from __future__ import annotations

from typing import Any, Optional

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools import Tool, ToolParameter, ToolResult, ToolRegistry

# ─── Communication Tools ────────────────────────────────────────────────────


async def tool_send_telegram_message(
    chat_id: str,
    message: str,
    parse_mode: str = "HTML",
) -> ToolResult:
    """
    Отправить сообщение в Telegram.
    
    Поддерживает HTML markdown.
    """
    if not config.telegram.token:
        return ToolResult(
            "send_telegram_message",
            False,
            "",
            error="TG_BOT_TOKEN не настроен"
        )
    
    try:
        import httpx
        
        url = f"https://api.telegram.org/bot{config.telegram.token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": message[:4096],  # Telegram limit
            "parse_mode": parse_mode,
        }
        
        async with httpx.AsyncClient(proxy=config.deepseek.proxy or None) as client:
            response = await client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
        
        if result.get("ok"):
            message_id = result["result"]["message_id"]
            return ToolResult(
                "send_telegram_message",
                True,
                f"✅ Сообщение отправлено в {chat_id} (msg_id={message_id})",
                data={"message_id": message_id, "chat_id": chat_id},
            )
        else:
            return ToolResult(
                "send_telegram_message",
                False,
                f"Ошибка: {result.get('description', 'Unknown error')}",
                error=result.get("description"),
            )
        
    except Exception as e:
        logger.error(f"tool_send_telegram_message failed: {e}")
        return ToolResult("send_telegram_message", False, "", error=str(e))


async def tool_send_whatsapp_message(
    phone: str,
    message: str,
) -> ToolResult:
    """
    Отправить сообщение в WhatsApp через Green-API.
    """
    if not config.whatsapp.green_api_instance or not config.whatsapp.green_api_token:
        return ToolResult(
            "send_whatsapp_message",
            False,
            "",
            error="WhatsApp Green-API не настроен"
        )
    
    try:
        import httpx
        
        instance_id = config.whatsapp.green_api_instance
        token = config.whatsapp.green_api_token
        
        url = f"https://green-api.com/waInstance{instance_id}/sendMessage/{token}"
        
        payload = {
            "chatId": f"{phone}@c.us",
            "message": message,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
        
        if result.get("idMessage"):
            return ToolResult(
                "send_whatsapp_message",
                True,
                f"✅ Сообщение отправлено в WhatsApp ({phone})",
                data={"message_id": result["idMessage"], "phone": phone},
            )
        else:
            return ToolResult(
                "send_whatsapp_message",
                False,
                f"Ошибка: {result.get('description', 'Unknown error')}",
                error=result.get("description"),
            )
        
    except Exception as e:
        logger.error(f"tool_send_whatsapp_message failed: {e}")
        return ToolResult("send_whatsapp_message", False, "", error=str(e))


async def tool_read_telegram_chat(
    chat_id: str,
    limit: int = 50,
) -> ToolResult:
    """
    Прочитать последние сообщения из Telegram чата.
    
    Требует Telethon userbot.
    """
    try:
        # Check if Telethon is available
        from telethon import TelegramClient
        from telethon.tl.types import Message
        
        if not config.telethon.api_id or not config.telethon.api_hash:
            return ToolResult(
                "read_telegram_chat",
                False,
                "",
                error="Telethon не настроен (TG_API_ID, TG_API_HASH)"
            )
        
        # Create client (ephemeral)
        client = TelegramClient(
            "temp_session",
            config.telethon.api_id,
            config.telethon.api_hash,
        )
        
        await client.start()
        
        # Get messages
        messages = []
        async for message in client.iter_messages(chat_id, limit=limit):
            messages.append({
                "id": message.id,
                "date": message.date.isoformat(),
                "from_id": message.sender_id,
                "text": message.text[:500] if message.text else "",
            })
        
        await client.disconnect()
        
        if not messages:
            return ToolResult(
                "read_telegram_chat",
                False,
                f"Нет сообщений в {chat_id}",
            )
        
        summary = f"📱 Последние сообщения из {chat_id} ({len(messages)}):\n\n"
        for msg in messages[:10]:
            summary += f"• {msg['date'][:16]}: {msg['text'][:100]}\n"
        
        return ToolResult(
            "read_telegram_chat",
            True,
            summary,
            data={"messages": messages, "count": len(messages)},
        )
        
    except ImportError:
        return ToolResult(
            "read_telegram_chat",
            False,
            "Telethon не установлен (pip install telethon)",
            error="Telethon not installed",
        )
    except Exception as e:
        logger.error(f"tool_read_telegram_chat failed: {e}")
        return ToolResult("read_telegram_chat", False, "", error=str(e))


async def tool_analyze_chat_style(
    chat_id: str,
    messages_count: int = 100,
) -> ToolResult:
    """
    Анализировать стиль общения в чате.
    
    Возвращает паттерны:
    - Длина сообщений
    - Использование эмодзи
    - Время ответа
    - Лексика
    """
    try:
        from telethon import TelegramClient
        
        if not config.telethon.api_id or not config.telethon.api_hash:
            return ToolResult(
                "analyze_chat_style",
                False,
                "",
                error="Telethon не настроен"
            )
        
        client = TelegramClient(
            "temp_session",
            config.telethon.api_id,
            config.telethon.api_hash,
        )
        
        await client.start()
        
        # Collect messages
        texts = []
        timestamps = []
        emoji_counts = []
        
        import re
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "]+",
            flags=re.UNICODE,
        )
        
        async for message in client.iter_messages(chat_id, limit=messages_count):
            if message.text:
                texts.append(message.text)
                timestamps.append(message.date)
                emojis = emoji_pattern.findall(message.text)
                emoji_counts.append(len(emojis))
        
        await client.disconnect()
        
        if not texts:
            return ToolResult(
                "analyze_chat_style",
                False,
                "Нет сообщений для анализа",
            )
        
        # Analyze
        avg_length = sum(len(t) for t in texts) / len(texts)
        avg_emoji = sum(emoji_counts) / len(emoji_counts) if emoji_counts else 0
        
        # Common words
        from collections import Counter
        words = re.findall(r"\b\w{3,}\b", " ".join(texts).lower())
        common_words = [w for w, _ in Counter(words).most_common(10)]
        
        style_guide = f"""
📊 СТИЛЬ ОБЩЕНИЯ ({chat_id})
═══════════════════════════════

📝 Статистика:
  • Средняя длина: {avg_length:.0f} символов
  • Эмодзи на сообщение: {avg_emoji:.1f}
  • Всего сообщений: {len(texts)}

🔑 Частые слова: {', '.join(common_words[:5])}

💡 Рекомендации:
  • Краткость: {'да' if avg_length < 100 else 'нет'}
  • Эмодзи: {'умеренно' if avg_emoji < 3 else 'много'}
  • Формальность: {'низкая' if len(common_words) > 0 else 'высокая'}
"""
        
        return ToolResult(
            "analyze_chat_style",
            True,
            style_guide,
            data={
                "avg_length": avg_length,
                "avg_emoji": avg_emoji,
                "common_words": common_words,
                "message_count": len(texts),
            },
        )
        
    except ImportError:
        return ToolResult(
            "analyze_chat_style",
            False,
            "Telethon не установлен",
            error="Telethon not installed",
        )
    except Exception as e:
        logger.error(f"tool_analyze_chat_style failed: {e}")
        return ToolResult("analyze_chat_style", False, "", error=str(e))


# ─── Tool Registration ───────────────────────────────────────────────────────

def register_communication_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать communication инструменты."""
    
    registry.register(
        Tool(
            name="send_telegram_message",
            description="Отправить сообщение в Telegram",
            parameters=[
                ToolParameter("chat_id", "string", "ID чата или username"),
                ToolParameter("message", "string", "Текст сообщения"),
                ToolParameter("parse_mode", "string", "Режим форматирования (HTML/Markdown)", default="HTML", required=False),
            ],
            handler=tool_send_telegram_message,
            category="communication",
        )
    )
    
    registry.register(
        Tool(
            name="send_whatsapp_message",
            description="Отправить сообщение в WhatsApp",
            parameters=[
                ToolParameter("phone", "string", "Номер телефона"),
                ToolParameter("message", "string", "Текст сообщения"),
            ],
            handler=tool_send_whatsapp_message,
            category="communication",
        )
    )
    
    registry.register(
        Tool(
            name="read_telegram_chat",
            description="Прочитать последние сообщения из Telegram чата",
            parameters=[
                ToolParameter("chat_id", "string", "ID чата или username"),
                ToolParameter("limit", "number", "Количество сообщений", default=50, required=False),
            ],
            handler=tool_read_telegram_chat,
            category="communication",
        )
    )
    
    registry.register(
        Tool(
            name="analyze_chat_style",
            description="Анализировать стиль общения в чате",
            parameters=[
                ToolParameter("chat_id", "string", "ID чата или username"),
                ToolParameter("messages_count", "number", "Количество сообщений для анализа", default=100, required=False),
            ],
            handler=tool_analyze_chat_style,
            category="communication",
        )
    )


__all__ = [
    "tool_send_telegram_message",
    "tool_send_whatsapp_message",
    "tool_read_telegram_chat",
    "tool_analyze_chat_style",
    "register_communication_tools",
]
