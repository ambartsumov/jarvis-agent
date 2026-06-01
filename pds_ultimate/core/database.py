"""
PDS-Ultimate Database Models
==============================
Полная схема базы данных системы.

Модели покрывают ВСЕ аспекты ТЗ:
- Заказы и позиции (жизненный цикл)
- Финансы (доходы, расходы, прибыль, распределение)
- Контрагенты (поставщики, клиенты)
- VIP-контакты (White List)
- Коммуникации (стиль общения, карточки)
- Календарь и задачи
- Архив всех заказов
- Пользовательские файлы

SQLAlchemy ORM + SQLite.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from pds_ultimate.config import DATABASE_PATH, logger

# ─── Base ────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


# ─── Enums ───────────────────────────────────────────────────────────────────

class OrderStatus(str, enum.Enum):
    """Статус заказа (жизненный цикл)."""
    DRAFT = "draft"                  # Черновик — ввод позиций
    CONFIRMED = "confirmed"          # Подтверждён — позиции зафиксированы
    TRACKING = "tracking"            # Сопровождение — ожидание прибытия
    DELIVERY_CALC = "delivery_calc"  # Расчёт доставки
    COMPLETED = "completed"          # Закрыт — все прибыло, расчёт завершён
    ARCHIVED = "archived"            # Архивирован — данные в All_Orders_Archive


class ItemStatus(str, enum.Enum):
    """Статус отдельной позиции."""
    PENDING = "pending"          # Ожидание (ещё не пришло)
    SHIPPED = "shipped"          # Отправлено (в пути)
    ARRIVED = "arrived"          # Прибыло
    CANCELLED = "cancelled"      # Отменено
    TRACK_REQUESTED = "track_requested"  # Запрошен трек-номер


class ContactType(str, enum.Enum):
    """Тип контакта."""
    SUPPLIER = "supplier"    # Поставщик
    CLIENT = "client"        # Клиент
    PERSONAL = "personal"    # Личный контакт
    OTHER = "other"


class VIPSource(str, enum.Enum):
    """Источник VIP-контакта."""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class ReminderStatus(str, enum.Enum):
    """Статус напоминания."""
    PENDING = "pending"
    SENT = "sent"
    ANSWERED = "answered"
    ESCALATED = "escalated"


class TaskStatus(str, enum.Enum):
    """Статус задачи."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TransactionType(str, enum.Enum):
    """Тип финансовой транзакции."""
    INCOME = "income"                  # Доход (сколько заплатили МНЕ)
    # Расход на товар (сколько Я заплатил поставщику)
    EXPENSE_GOODS = "expense_goods"
    EXPENSE_DELIVERY = "expense_delivery"  # Расход на доставку
    EXPENSE_PERSONAL = "expense_personal"  # Личный расход (чеки и т.д.)
    PROFIT_EXPENSES = "profit_expenses"  # Из прибыли → на расходы
    PROFIT_SAVINGS = "profit_savings"  # Из прибыли → отложения на будущее


class CurrencyCode(str, enum.Enum):
    """Поддерживаемые валюты."""
    USD = "USD"
    TMT = "TMT"
    CNY = "CNY"
    EUR = "EUR"
    RUB = "RUB"
    GBP = "GBP"
    TRY = "TRY"


class FileFormat(str, enum.Enum):
    """Форматы файлов, с которыми работает система."""
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"
    JSON = "json"
    IMAGE = "image"
    OTHER = "other"


class MessageDirection(str, enum.Enum):
    """Направление сообщения (для анализа стиля)."""
    INCOMING = "incoming"
    OUTGOING = "outgoing"


# ─── Миксины ────────────────────────────────────────────────────────────────

class TimestampMixin:
    """Миксин для автоматических временных меток."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# ─── МОДЕЛИ: КОНТРАГЕНТЫ ────────────────────────────────────────────────────

class Contact(TimestampMixin, Base):
    """
    Контрагент (поставщик, клиент, личный контакт).
    Карточка контрагента с историей, заметками и рейтингом.
    """
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_type: Mapped[ContactType] = mapped_column(
        SAEnum(ContactType), nullable=False, default=ContactType.OTHER
    )

    # Контактные данные
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(100))
    whatsapp_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Информация
    company: Mapped[Optional[str]] = mapped_column(String(255))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[Optional[str]] = mapped_column(String(10))  # ru, en, zh

    # Заметки (умные карточки по ТЗ: "Этот поставщик жулик")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Предупреждения (выводятся при взаимодействии)
    warnings: Mapped[Optional[str]] = mapped_column(Text)

    # Метаданные
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Связи
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="supplier", foreign_keys="Order.supplier_id"
    )
    client_orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="client", foreign_keys="Order.client_id"
    )
    vip_entries: Mapped[list["VIPContact"]] = relationship(
        "VIPContact", back_populates="contact"
    )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, name='{self.name}', type={self.contact_type.value})>"


# ─── МОДЕЛИ: VIP КОНТАКТЫ ───────────────────────────────────────────────────

class VIPContact(TimestampMixin, Base):
    """
    VIP-контакт (White List).
    Сообщения от VIP → мгновенное саммари + СРОЧНО.
    """
    __tablename__ = "vip_contacts"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    source: Mapped[VIPSource] = mapped_column(
        SAEnum(VIPSource), nullable=False)
    # Идентификатор в источнике (TG ID, WA номер, email)
    source_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    # Имя для отображения
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Связи
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="vip_entries"
    )

    __table_args__ = (
        UniqueConstraint("source", "source_identifier",
                         name="uq_vip_source_id"),
    )

    def __repr__(self) -> str:
        return f"<VIPContact(id={self.id}, name='{self.display_name}', src={self.source.value})>"


# ─── МОДЕЛИ: ЗАКАЗЫ ─────────────────────────────────────────────────────────

class Order(TimestampMixin, Base):
    """
    Заказ. Жизненный цикл по ТЗ:
    DRAFT → CONFIRMED → TRACKING → DELIVERY_CALC → COMPLETED → ARCHIVED

    Финансовая логика:
      income (заплатили МНЕ) - expense_goods (Я заплатил) = remainder
      remainder - delivery_cost = net_profit
      net_profit → expense_share + savings_share
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    # Человекочитаемый номер заказа
    order_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus), nullable=False, default=OrderStatus.DRAFT
    )

    # Контрагенты
    supplier_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="SET NULL")
    )

    # ─── Финансы по ТЗ ───────────────────────────────
    # Шаг 1: Сколько заплатили МНЕ за заказ (ДОХОД)
    income: Mapped[Optional[float]] = mapped_column(Float)
    income_currency: Mapped[Optional[str]] = mapped_column(
        String(3), default="USD")

    # Шаг 2: Сколько Я заплатил поставщику за товар (РАСХОД)
    expense_goods: Mapped[Optional[float]] = mapped_column(Float)
    expense_goods_currency: Mapped[Optional[str]
                                   ] = mapped_column(String(3), default="USD")

    # Вычисляемое: ОСТАТОК = income - expense_goods
    # (в приложении, не в БД — для гибкости мультивалютности)

    # Шаг 3: Расход на доставку
    delivery_cost: Mapped[Optional[float]] = mapped_column(Float)
    delivery_currency: Mapped[Optional[str]
                              ] = mapped_column(String(3), default="USD")
    # Тип ввода доставки: per_item (по позициям) | total (общей суммой)
    delivery_input_type: Mapped[Optional[str]] = mapped_column(String(20))

    # Шаг 4: Чистая прибыль = остаток - доставка
    net_profit: Mapped[Optional[float]] = mapped_column(Float)

    # Шаг 5: Распределение чистой прибыли
    profit_to_expenses: Mapped[Optional[float]
                               ] = mapped_column(Float)  # На расходы
    profit_to_savings: Mapped[Optional[float]
                              ] = mapped_column(Float)   # Отложения

    # Проценты распределения (на момент закрытия заказа)
    expense_percent: Mapped[Optional[float]] = mapped_column(Float)
    savings_percent: Mapped[Optional[float]] = mapped_column(Float)

    # ─── Метаданные ──────────────────────────────────
    description: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Путь к временному Excel-файлу заказа
    temp_file_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Даты
    order_date: Mapped[Optional[date]] = mapped_column(Date)
    completed_date: Mapped[Optional[date]] = mapped_column(Date)
    archived_date: Mapped[Optional[date]] = mapped_column(Date)

    # Связи
    supplier: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="orders", foreign_keys=[supplier_id]
    )
    client: Mapped[Optional["Contact"]] = relationship(
        "Contact", back_populates="client_orders", foreign_keys=[client_id]
    )
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="order", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder", back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_dates", "order_date", "completed_date"),
    )

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, num='{self.order_number}', status={self.status.value})>"


# ─── МОДЕЛИ: ПОЗИЦИИ ЗАКАЗА ─────────────────────────────────────────────────

class OrderItem(TimestampMixin, Base):
    """
    Позиция заказа. Трекинг на уровне каждой позиции (Item-Level Tracking).
    По ТЗ: T+4 дня → запрос статуса → повтор каждый вторник → трек-номер.
    """
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )

    # Информация о позиции
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="шт")  # шт, кг, м

    # Цена за единицу (если известна)
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    price_currency: Mapped[Optional[str]] = mapped_column(
        String(3), default="USD")

    # Вес (для пропорционального распределения доставки)
    weight: Mapped[Optional[float]] = mapped_column(Float)  # кг
    weight_unit: Mapped[str] = mapped_column(String(10), default="кг")

    # Статус позиции
    status: Mapped[ItemStatus] = mapped_column(
        SAEnum(ItemStatus), nullable=False, default=ItemStatus.PENDING
    )

    # Трек-номер
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100))
    tracking_source: Mapped[Optional[str]] = mapped_column(
        String(50))  # "manual", "ocr"

    # Дата прибытия
    arrival_date: Mapped[Optional[date]] = mapped_column(Date)

    # Стоимость доставки этой позиции (если ввод per_item)
    delivery_cost: Mapped[Optional[float]] = mapped_column(Float)

    # Себестоимость позиции (товар + доля доставки)
    total_cost: Mapped[Optional[float]] = mapped_column(Float)

    # Следующая дата проверки статуса
    next_check_date: Mapped[Optional[date]] = mapped_column(Date, index=True)

    # Количество отправленных напоминаний
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Связь
    order: Mapped["Order"] = relationship("Order", back_populates="items")

    __table_args__ = (
        Index("ix_items_order_status", "order_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrderItem(id={self.id}, name='{self.name}', "
            f"qty={self.quantity}, status={self.status.value})>"
        )


# ─── МОДЕЛИ: АРХИВ ЗАКАЗОВ ──────────────────────────────────────────────────

class ArchivedOrderItem(TimestampMixin, Base):
    """
    Архив позиций закрытых заказов.
    По ТЗ: ВСЕ позиции ВСЕХ закрытых заказов хранятся ВЕЧНО
    в едином файле All_Orders_Archive.xlsx + в этой таблице БД.
    """
    __tablename__ = "archived_order_items"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    # Данные из оригинального заказа
    original_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_number: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True)

    # Позиция
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="шт")
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    price_currency: Mapped[Optional[str]] = mapped_column(String(3))
    weight: Mapped[Optional[float]] = mapped_column(Float)

    # Трекинг
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100))
    arrival_date: Mapped[Optional[date]] = mapped_column(Date)

    # Стоимость
    delivery_cost: Mapped[Optional[float]] = mapped_column(Float)
    total_cost: Mapped[Optional[float]] = mapped_column(Float)

    # Контрагенты
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255))
    client_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Финансы заказа (дублируются в каждой записи для полноты архива)
    order_income: Mapped[Optional[float]] = mapped_column(Float)
    order_expense_goods: Mapped[Optional[float]] = mapped_column(Float)
    order_delivery_cost: Mapped[Optional[float]] = mapped_column(Float)
    order_net_profit: Mapped[Optional[float]] = mapped_column(Float)

    # Даты
    order_date: Mapped[Optional[date]] = mapped_column(Date)
    completed_date: Mapped[Optional[date]] = mapped_column(Date)
    archived_date: Mapped[date] = mapped_column(Date, default=date.today)

    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_archive_dates", "order_date", "archived_date"),
        Index("ix_archive_supplier", "supplier_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<ArchivedItem(order='{self.order_number}', "
            f"item='{self.item_name}', qty={self.quantity})>"
        )


# ─── МОДЕЛИ: ФИНАНСОВЫЕ ТРАНЗАКЦИИ ──────────────────────────────────────────

class Transaction(TimestampMixin, Base):
    """
    Финансовая транзакция.
    Все движения средств: доходы, расходы на товар, доставку, личные,
    распределение прибыли.
    """
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="SET NULL")
    )

    transaction_type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType), nullable=False
    )

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD")

    # Конвертированная сумма в базовой валюте (USD)
    amount_usd: Mapped[Optional[float]] = mapped_column(Float)
    # Курс на момент транзакции
    exchange_rate: Mapped[Optional[float]] = mapped_column(Float)

    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))

    # Дата транзакции (может отличаться от created_at)
    transaction_date: Mapped[date] = mapped_column(
        Date, default=date.today, index=True)

    # Связь
    order: Mapped[Optional["Order"]] = relationship(
        "Order", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_type_date",
              "transaction_type", "transaction_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, type={self.transaction_type.value}, "
            f"amount={self.amount} {self.currency})>"
        )


# ─── МОДЕЛИ: БАЛАНС (МАСТЕР-ФИНАНСЫ) ────────────────────────────────────────

class FinanceSummary(TimestampMixin, Base):
    """
    Сводка финансов (Master Finance).
    Агрегированные данные для быстрого доступа.
    Пересчитывается при каждой транзакции.
    """
    __tablename__ = "finance_summary"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    # Период (месяц)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    # Суммы за период (в USD)
    total_income: Mapped[float] = mapped_column(Float, default=0.0)
    total_expense_goods: Mapped[float] = mapped_column(Float, default=0.0)
    total_expense_delivery: Mapped[float] = mapped_column(Float, default=0.0)
    total_expense_personal: Mapped[float] = mapped_column(Float, default=0.0)
    total_net_profit: Mapped[float] = mapped_column(Float, default=0.0)
    total_to_expenses: Mapped[float] = mapped_column(Float, default=0.0)
    total_to_savings: Mapped[float] = mapped_column(Float, default=0.0)

    # Количество заказов
    orders_completed: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("period_year", "period_month",
                         name="uq_finance_period"),
    )

    def __repr__(self) -> str:
        return (
            f"<FinanceSummary(period={self.period_year}-{self.period_month:02d}, "
            f"profit={self.total_net_profit})>"
        )


# ─── МОДЕЛИ: КЭШ КУРСОВ ВАЛЮТ ───────────────────────────────────────────────

class CurrencyRate(TimestampMixin, Base):
    """
    Кэш курсов валют.
    Фиксированные: USD/TMT=19.5, USD/CNY=7.1
    Динамические: из API, обновляются каждые 6 часов.
    """
    __tablename__ = "currency_rates"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD")
    target_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    # Фиксированный курс (не обновляется из API)
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Дата актуальности курса
    rate_date: Mapped[date] = mapped_column(Date, default=date.today)

    __table_args__ = (
        UniqueConstraint("base_currency", "target_currency", "rate_date",
                         name="uq_currency_rate_date"),
        Index("ix_currency_pair", "base_currency", "target_currency"),
    )

    def __repr__(self) -> str:
        return (
            f"<CurrencyRate({self.base_currency}/{self.target_currency}="
            f"{self.rate}, fixed={self.is_fixed})>"
        )


# ─── МОДЕЛИ: НАПОМИНАНИЯ ────────────────────────────────────────────────────

class Reminder(TimestampMixin, Base):
    """
    Напоминание.
    По ТЗ:
    - T+4 дня: запрос статуса позиции
    - Повтор каждый вторник
    - Антизабывание: через 2 часа, потом вечером
    """
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE")
    )
    item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("order_items.id", ondelete="CASCADE")
    )

    status: Mapped[ReminderStatus] = mapped_column(
        SAEnum(ReminderStatus), nullable=False, default=ReminderStatus.PENDING
    )

    # Когда отправить
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True)
    # Когда фактически отправлено
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Когда получен ответ
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Текст напоминания
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Ответ пользователя
    response: Mapped[Optional[str]] = mapped_column(Text)

    # Тип: status_check, track_request, delivery_cost, general
    reminder_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Количество попыток (антизабывание)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    # Связи
    order: Mapped[Optional["Order"]] = relationship(
        "Order", back_populates="reminders")

    __table_args__ = (
        Index("ix_reminders_scheduled", "status", "scheduled_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Reminder(id={self.id}, type='{self.reminder_type}', "
            f"status={self.status.value})>"
        )


# ─── МОДЕЛИ: СТИЛЬ ОБЩЕНИЯ ──────────────────────────────────────────────────

class CommunicationStyle(TimestampMixin, Base):
    """
    Профиль стиля общения владельца (Communication Style Guide).
    По ТЗ: анализ 7 чатов TG + 3 чата WA.
    """
    __tablename__ = "communication_style"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    # JSON с полным профилем стиля
    # Содержит: avg_message_length, uses_emoji, formality_level,
    # common_phrases, greeting_style, farewell_style, etc.
    style_profile: Mapped[Optional[str]] = mapped_column(JSON)

    # Источники анализа
    tg_chats_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    wa_chats_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    total_messages_analyzed: Mapped[int] = mapped_column(Integer, default=0)

    # Системный промпт для DeepSeek (сгенерированный из профиля)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)

    # Активен ли этот профиль
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Дата последнего сканирования
    last_scan_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return (
            f"<CommunicationStyle(id={self.id}, "
            f"tg={self.tg_chats_analyzed}, wa={self.wa_chats_analyzed}, "
            f"active={self.is_active})>"
        )


# ─── МОДЕЛИ: ЗАДАЧИ / СОБЫТИЯ КАЛЕНДАРЯ ─────────────────────────────────────

class CalendarEvent(TimestampMixin, Base):
    """
    Событие календаря / задача.
    Хранится в БД (в памяти системы).
    По ТЗ: конфликт-менеджер, авто-ответчик, гео-учёт.
    Утром даёт план на день, за 30 минут предупреждает.
    """
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Местоположение (для гео-учёта)
    location: Mapped[Optional[str]] = mapped_column(Text)

    # Связь с заказом (если событие связано с логистикой)
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="SET NULL")
    )

    # Связь с контактом
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="SET NULL")
    )

    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    # Напоминание за N минут до события (по ТЗ: 30 мин)
    reminder_minutes: Mapped[int] = mapped_column(Integer, default=30)

    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), nullable=False, default=TaskStatus.PENDING
    )

    def __repr__(self) -> str:
        return f"<CalendarEvent(id={self.id}, title='{self.title}', start={self.start_time})>"


# ─── МОДЕЛИ: ПОЛЬЗОВАТЕЛЬСКИЕ ФАЙЛЫ ─────────────────────────────────────────

class UserFile(TimestampMixin, Base):
    """
    Пользовательский файл.
    По ТЗ: агент создаёт/редактирует файлы любых форматов,
    ведёт произвольный учёт, добавляет столбцы и т.д.
    Архивариус: переименовывает по стандарту.
    """
    __tablename__ = "user_files"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    # Оригинальное имя файла
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Стандартизированное имя (Архивариус)
    standardized_name: Mapped[Optional[str]] = mapped_column(String(500))
    # Путь к файлу на диске
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    # Формат
    file_format: Mapped[FileFormat] = mapped_column(
        SAEnum(FileFormat), nullable=False
    )
    file_size: Mapped[Optional[int]] = mapped_column(Integer)  # байты

    # Категория / тег
    category: Mapped[Optional[str]] = mapped_column(String(100))
    tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array

    # Связь с заказом (если файл относится к заказу)
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="SET NULL")
    )

    description: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<UserFile(id={self.id}, name='{self.original_name}')>"


# ─── МОДЕЛИ: ИСТОРИЯ РАЗГОВОРОВ (для контекста LLM) ─────────────────────────

class ConversationHistory(TimestampMixin, Base):
    """
    История разговоров с ботом.
    Для поддержания контекста и выполнения ЛЮБЫХ задач.
    """
    __tablename__ = "conversation_history"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)

    # ID чата (Telegram chat_id)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True)

    role: Mapped[str] = mapped_column(
        String(20), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Метаданные
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    # Тип контента: text, voice, file, photo
    content_type: Mapped[str] = mapped_column(String(20), default="text")

    # Для ограничения контекста (хранить последние N сообщений)
    # и ротации старых записей
    __table_args__ = (
        Index("ix_conversation_chat_created", "chat_id", "created_at"),
    )

    def __repr__(self) -> str:
        preview = self.content[:50] + \
            "..." if len(self.content) > 50 else self.content
        return f"<Conversation(id={self.id}, role='{self.role}', content='{preview}')>"


# ─── МОДЕЛИ: СИСТЕМНЫЕ НАСТРОЙКИ ────────────────────────────────────────────

class SystemSetting(TimestampMixin, Base):
    """
    Системные настройки (key-value).
    Для хранения динамических параметров, которые меняет пользователь.
    """
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<SystemSetting(key='{self.key}', value='{self.value[:50]}')>"


# ─── МОДЕЛИ: ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────────────

class UserProfile(TimestampMixin, Base):
    """
    Профиль пользователя системы.

    Роли:
    - owner: Владелец (Вячеслав Амбарцумов) — полный доступ
    - user: Обычный пользователь — доступ к своим API

    При /start бот спрашивает имя.
    Если совпадает с владельцем → все предустановленные API.
    Иначе → guided onboarding с подключением своих API.
    """
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user")  # owner | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON: персональные настройки (язык, формат, предпочтения)
    settings_json: Mapped[Optional[str]] = mapped_column(Text)
    last_active: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Связи
    api_configs: Mapped[list["UserAPIConfig"]] = relationship(
        "UserAPIConfig", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<UserProfile(id={self.id}, name='{self.name}', role='{self.role}')>"


class UserAPIConfig(TimestampMixin, Base):
    """
    API конфигурация пользователя.

    Хранит зашифрованные API ключи и настройки для каждого
    подключённого сервиса. Один пользователь может подключить
    любое количество API.

    api_type: deepseek, openai, anthropic, whatsapp_green_api,
              gmail, telegram_bot, custom_api, ...
    config_data: JSON с зашифрованными ключами
    """
    __tablename__ = "user_api_configs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_profiles.chat_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    api_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_name: Mapped[str] = mapped_column(String(100), nullable=False)
    config_data: Mapped[str] = mapped_column(
        Text, nullable=False)  # Encrypted JSON
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # Связи
    user: Mapped["UserProfile"] = relationship(
        "UserProfile", back_populates="api_configs"
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "api_type", name="uq_user_api"),
        Index("ix_user_api_active", "chat_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<UserAPIConfig(chat_id={self.chat_id}, api='{self.api_type}', active={self.is_active})>"


# ─── МОДЕЛИ: AI AGENT MEMORY (долгосрочная память агента) ────────────────────

class AgentMemory(TimestampMixin, Base):
    """
    Долгосрочная память AI-агента (Advanced Memory System).

    Хранит извлечённые факты, предпочтения, правила и инсайты.
    Используется для контекстного recall при обработке запросов.

    Типы памяти (5 + backward compat):
    - episodic: Конкретные события, взаимодействия
    - semantic: Обобщённые знания, концепции
    - procedural: Как делать задачи, алгоритмы
    - strategic: Стратегические решения, приоритеты
    - failure: Ошибки и уроки (failure-driven learning)
    - fact: Конкретный факт (backward compat)
    - preference: Предпочтение пользователя
    - rule: Бизнес-правило
    """
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="fact", index=True)
    importance: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5)
    tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    source: Mapped[Optional[str]] = mapped_column(
        String(50), default="extraction")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # ─── Advanced Memory Fields (Part 2) ─────────────────────────────────
    confidence: Mapped[Optional[float]] = mapped_column(
        Float, default=0.8)
    decay_rate: Mapped[Optional[float]] = mapped_column(
        Float, default=0.1)
    source_quality: Mapped[Optional[float]] = mapped_column(
        Float, default=0.7)
    context_hash: Mapped[Optional[str]] = mapped_column(
        String(32))  # MD5 hash для дедупликации
    chat_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, index=True)  # Per-user memory isolation
    expiry: Mapped[Optional[datetime]] = mapped_column(DateTime)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_agent_memory_type_imp", "memory_type", "importance"),
        Index("ix_agent_memory_active", "is_active"),
        Index("ix_agent_memory_hash", "context_hash"),
        Index("ix_agent_memory_chat", "chat_id", "memory_type"),
    )

    def __repr__(self) -> str:
        preview = self.content[:50] + \
            "..." if len(self.content) > 50 else self.content
        return f"<AgentMemory(id={self.id}, type='{self.memory_type}', imp={self.importance:.1f}, content='{preview}')>"


class FailureLog(TimestampMixin, Base):
    """
    Лог ошибок агента (Failure-Driven Learning).

    Хранит ошибки, причины и уроки. Агент учится на своих
    неудачах и не повторяет одни и те же ошибки.
    """
    __tablename__ = "failure_log"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, index=True)
    error_content: Mapped[str] = mapped_column(Text, nullable=False)
    error_context: Mapped[Optional[str]] = mapped_column(Text)
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    correction: Mapped[Optional[str]] = mapped_column(Text)
    lesson: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(
        String(20), default="medium")  # low | medium | high | critical
    tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_failure_log_severity", "severity"),
        Index("ix_failure_log_chat", "chat_id"),
    )


class AgentThought(TimestampMixin, Base):
    """
    Лог мышления агента (для отладки и аудита).

    Сохраняет цепочку Thought → Action → Observation
    для каждого обработанного запроса.
    """
    __tablename__ = "agent_thoughts"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True)
    # Исходный запрос пользователя
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    # Количество итераций ReAct loop
    iterations: Mapped[int] = mapped_column(Integer, default=1)
    # Использованные инструменты (JSON array)
    tools_used: Mapped[Optional[str]] = mapped_column(Text)
    # Финальный ответ
    final_answer: Mapped[Optional[str]] = mapped_column(Text)
    # Время обработки (мс)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # Количество записей памяти создано
    memories_created: Mapped[int] = mapped_column(Integer, default=0)
    # Был ли использован план
    plan_used: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_agent_thoughts_chat", "chat_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentThought(id={self.id}, iters={self.iterations}, tools={self.tools_used})>"


# ─── МОДЕЛЬ: ПОЛЬЗОВАТЕЛЬСКИЕ НАСТРОЙКИ ─────────────────────────────────────

class UserSetting(Base):
    """
    Хранилище настроек пользователя типа ключ-значение.
    Используется для динамических настроек планировщика и авто-ответчика.
    """
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserSetting(key='{self.key}', value='{self.value}')>"


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE ENGINE & SESSION
# ═══════════════════════════════════════════════════════════════════════════════

def create_db_engine(db_path: str | None = None):
    """
    Создать движок БД.
    SQLite с WAL mode для конкурентного доступа (asyncio).
    """
    if db_path is None:
        db_path = str(DATABASE_PATH)

    url = f"sqlite:///{db_path}"

    engine = create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )

    # Включаем WAL mode и foreign keys при каждом подключении
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        cursor.close()

    return engine


def create_session_factory(engine) -> sessionmaker:
    """Создать фабрику сессий."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_database(db_path: str | None = None) -> tuple:
    """
    Инициализация базы данных.
    Создаёт все таблицы, инициализирует фиксированные курсы.

    Returns:
        (engine, SessionFactory)
    """
    engine = create_db_engine(db_path)
    Base.metadata.create_all(engine)

    SessionFactory = create_session_factory(engine)

    # Инициализация фиксированных курсов валют
    _init_fixed_currency_rates(SessionFactory)

    logger.info(f"База данных инициализирована: {db_path or DATABASE_PATH}")
    return engine, SessionFactory


def _init_fixed_currency_rates(SessionFactory: sessionmaker) -> None:
    """
    Инициализация фиксированных курсов валют.
    1 USD = 19.5 TMT
    1 USD = 7.1 CNY
    """
    from pds_ultimate.config import config

    with SessionFactory() as session:
        for currency, rate in config.currency.fixed_rates.items():
            existing = session.query(CurrencyRate).filter_by(
                base_currency="USD",
                target_currency=currency,
                is_fixed=True,
            ).first()

            if existing:
                existing.rate = rate
                existing.rate_date = date.today()
            else:
                session.add(CurrencyRate(
                    base_currency="USD",
                    target_currency=currency,
                    rate=rate,
                    is_fixed=True,
                    rate_date=date.today(),
                ))

        session.commit()
        logger.info("Фиксированные курсы валют инициализированы: "
                    f"USD/TMT={config.currency.fixed_rates.get('TMT')}, "
                    f"USD/CNY={config.currency.fixed_rates.get('CNY')}")
