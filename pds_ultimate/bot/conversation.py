"""
PDS-Ultimate Conversation Manager
====================================
Управление контекстом разговора с пользователем.

Хранит историю сообщений для DeepSeek, управляет состояниями
диалога (свободный чат, ввод заказа, ожидание ответа и т.д.).

Нет кнопок, нет шаблонов. Только естественный язык.
Агент определяет намерение через LLM и действует.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pds_ultimate.config import logger


class ConversationState:
    """
    Возможные состояния диалога.
    Агент сам определяет и переключает состояния через LLM.
    """
    FREE = "free"                            # Свободный режим — ЛЮБАЯ задача
    AWAITING_NAME = "awaiting_name"          # Ожидание имени (onboarding)
    AWAITING_API_SETUP = "awaiting_api_setup"  # Настройка API (onboarding)
    ORDER_INPUT = "order_input"              # Ввод позиций заказа
    ORDER_CONFIRM = "order_confirm"          # Подтверждение списка позиций
    AWAITING_INCOME = "awaiting_income"      # Ожидание: сколько заплатили МНЕ
    AWAITING_EXPENSE = "awaiting_expense"    # Ожидание: сколько Я заплатил
    AWAITING_TRACK = "awaiting_track"        # Ожидание трек-номера
    AWAITING_STATUS = "awaiting_status"      # Ожидание статуса позиции
    AWAITING_DELIVERY = "awaiting_delivery"  # Ожидание стоимости доставки
    AWAITING_DELIVERY_TYPE = "awaiting_delivery_type"  # Тип ввода доставки
    FILE_OPERATION = "file_operation"         # Работа с файлами


class ConversationContext:
    """
    Контекст одного разговора (одного пользователя).
    Хранит: историю для LLM, текущее состояние, временные данные.
    """

    # Максимальное количество сообщений в контексте для LLM
    MAX_HISTORY = 40

    def __init__(self, chat_id: int):
        self.chat_id: int = chat_id
        self.state: str = ConversationState.FREE
        self.history: list[dict[str, str]] = []
        self.last_activity: datetime = datetime.utcnow()

        # Временные данные для текущей операции
        # (например, ID заказа при вводе, ожидаемая позиция и т.д.)
        self._temp_data: dict[str, Any] = {}

    # ─── История сообщений ───────────────────────────────────────────────

    def add_user_message(self, text: str) -> None:
        """Добавить сообщение пользователя в историю."""
        self.history.append({"role": "user", "content": text})
        self._trim_history()
        self.last_activity = datetime.utcnow()

    def add_assistant_message(self, text: str) -> None:
        """Добавить ответ ассистента в историю."""
        self.history.append({"role": "assistant", "content": text})
        self._trim_history()

    def get_history_for_llm(self) -> list[dict[str, str]]:
        """Получить историю для отправки в DeepSeek API.
        При >20 сообщениях автоматически сжимает старые в краткое summary.
        """
        if len(self.history) <= 20:
            return list(self.history)

        # Compress: keep last 15 messages verbatim, summarise older ones
        try:
            from pds_ultimate.core.advanced_memory_manager import ContextCompressor
            compressed = ContextCompressor.compress_history(self.history, max_messages=15)
            return compressed
        except Exception:
            return list(self.history)

    def _trim_history(self) -> None:
        """Обрезать историю до MAX_HISTORY сообщений."""
        if len(self.history) > self.MAX_HISTORY:
            # Сохраняем первые 2 сообщения (контекст) и последние MAX_HISTORY-2
            self.history = self.history[:2] + \
                self.history[-(self.MAX_HISTORY - 2):]

    def clear_history(self) -> None:
        """Очистить историю разговора."""
        self.history.clear()

    # ─── Состояние и временные данные ────────────────────────────────────

    def set_state(self, state: str, **temp_data) -> None:
        """Установить состояние и временные данные."""
        self.state = state
        if temp_data:
            self._temp_data.update(temp_data)
        logger.debug(
            f"Chat {self.chat_id}: state → {state}, data={list(temp_data.keys())}")

    def get_temp(self, key: str, default: Any = None) -> Any:
        """Получить временные данные."""
        return self._temp_data.get(key, default)

    def set_temp(self, key: str, value: Any) -> None:
        """Установить временные данные."""
        self._temp_data[key] = value

    def clear_temp(self) -> None:
        """Очистить временные данные и вернуться в свободный режим."""
        self._temp_data.clear()
        self.state = ConversationState.FREE

    def reset(self) -> None:
        """Полный сброс: история + состояние + данные."""
        self.history.clear()
        self._temp_data.clear()
        self.state = ConversationState.FREE


class ConversationManager:
    """
    Менеджер всех разговоров.

    Использование:
        manager = ConversationManager()
        ctx = manager.get(chat_id)
        ctx.add_user_message("Привет")
    """

    def __init__(self):
        self._contexts: dict[int, ConversationContext] = {}

    def get(self, chat_id: int) -> ConversationContext:
        """Получить или создать контекст для чата."""
        if chat_id not in self._contexts:
            self._contexts[chat_id] = ConversationContext(chat_id)
        return self._contexts[chat_id]

    def reset(self, chat_id: int) -> None:
        """Сбросить контекст чата."""
        if chat_id in self._contexts:
            self._contexts[chat_id].reset()

    def remove(self, chat_id: int) -> None:
        """Удалить контекст чата."""
        self._contexts.pop(chat_id, None)

    @property
    def active_count(self) -> int:
        """Количество активных разговоров."""
        return len(self._contexts)


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

conversation_manager = ConversationManager()
