"""
PDS-Ultimate Agent Tests
=========================
Тесты для AI Agent System: tools, memory, agent core.

Тестируем:
1. Tool Registry — регистрация, поиск, JSON schema
2. Memory System — store, recall, working memory
3. Business Tools — создание, исполнение
4. Agent — парсинг ответов, smart routing
5. Database — новые модели AgentMemory, AgentThought
"""

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pds_ultimate.core.database import (
    AgentMemory,
    AgentThought,
    Base,
    Contact,
    ContactType,
    Order,
    OrderStatus,
    Transaction,
    TransactionType,
)
from pds_ultimate.core.memory import MemoryEntry, MemoryManager, WorkingMemory
from pds_ultimate.core.tools import Tool, ToolParameter, ToolRegistry, ToolResult

# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db_session():
    """In-memory SQLite сессия для тестов."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_fk(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def registry():
    """Чистый реестр инструментов."""
    return ToolRegistry()


@pytest.fixture
def memory():
    """Чистый менеджер памяти."""
    return MemoryManager()


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: TOOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolRegistry:
    """Тесты реестра инструментов."""

    def test_register_tool(self, registry):
        """Регистрация инструмента."""
        tool = Tool(
            name="test_tool",
            description="Тестовый инструмент",
            category="test",
        )
        registry.register(tool)
        assert registry.count == 1
        assert registry.get("test_tool") is tool

    def test_unregister_tool(self, registry):
        """Удаление инструмента."""
        tool = Tool(name="tmp", description="tmp", category="test")
        registry.register(tool)
        assert registry.count == 1
        registry.unregister("tmp")
        assert registry.count == 0

    def test_list_tools(self, registry):
        """Список инструментов."""
        registry.register(Tool(name="a", description="A", category="cat1"))
        registry.register(Tool(name="b", description="B", category="cat2"))
        registry.register(Tool(name="c", description="C",
                          category="cat1", visible=False))

        all_visible = registry.list_tools()
        assert len(all_visible) == 2

        cat1 = registry.list_tools(category="cat1")
        assert len(cat1) == 1  # "c" is not visible
        assert cat1[0].name == "a"

    def test_list_names(self, registry):
        """Список имён."""
        registry.register(Tool(name="x", description="X"))
        registry.register(Tool(name="y", description="Y"))
        names = registry.list_names()
        assert "x" in names
        assert "y" in names

    def test_categories(self, registry):
        """Категории."""
        registry.register(Tool(name="a", description="A", category="finance"))
        registry.register(
            Tool(name="b", description="B", category="logistics"))
        cats = registry.categories
        assert "finance" in cats
        assert "logistics" in cats

    def test_tool_json_schema(self):
        """JSON Schema инструмента."""
        tool = Tool(
            name="create_order",
            description="Создать заказ",
            parameters=[
                ToolParameter("items", "string", "Список позиций", True),
                ToolParameter("note", "string", "Примечание", False, ""),
            ],
        )
        schema = tool.to_json_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "create_order"
        assert "items" in schema["function"]["parameters"]["properties"]
        assert "items" in schema["function"]["parameters"]["required"]
        assert "note" not in schema["function"]["parameters"]["required"]

    def test_tool_with_enum(self):
        """Параметр с enum."""
        tool = Tool(
            name="filter",
            description="Фильтр",
            parameters=[
                ToolParameter("status", "string", "Статус", True,
                              enum=["active", "closed"]),
            ],
        )
        schema = tool.to_json_schema()
        assert schema["function"]["parameters"]["properties"]["status"]["enum"] == [
            "active", "closed"]

    @pytest.mark.asyncio
    async def test_execute_tool(self, registry):
        """Выполнение инструмента."""
        async def handler(x: int = 0):
            return f"result={x * 2}"

        tool = Tool(name="double", description="Удвоить", handler=handler)
        registry.register(tool)

        result = await registry.execute("double", {"x": 5})
        assert result.success
        assert "10" in result.output

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry):
        """Выполнение несуществующего инструмента."""
        result = await registry.execute("nonexistent")
        assert not result.success
        assert "не найден" in result.error

    @pytest.mark.asyncio
    async def test_execute_tool_error(self, registry):
        """Обработка ошибки в инструменте."""
        async def bad_handler():
            raise ValueError("test error")

        tool = Tool(name="bad", description="Bad", handler=bad_handler)
        registry.register(tool)

        result = await registry.execute("bad")
        assert not result.success
        assert "test error" in result.error

    @pytest.mark.asyncio
    async def test_execute_returns_dict(self, registry):
        """Инструмент возвращает dict."""
        async def handler():
            return {"balance": 1000, "currency": "USD"}

        tool = Tool(name="balance", description="Баланс", handler=handler)
        registry.register(tool)

        result = await registry.execute("balance")
        assert result.success
        assert result.data == {"balance": 1000, "currency": "USD"}

    @pytest.mark.asyncio
    async def test_execute_returns_tool_result(self, registry):
        """Инструмент возвращает ToolResult напрямую."""
        async def handler():
            return ToolResult("custom", True, "OK", data=42)

        tool = Tool(name="custom", description="Custom", handler=handler)
        registry.register(tool)

        result = await registry.execute("custom")
        assert result.success
        assert result.data == 42

    def test_get_tools_prompt(self, registry):
        """Генерация описания для system prompt."""
        registry.register(Tool(
            name="get_balance",
            description="Получить баланс",
            parameters=[ToolParameter("currency", "string", "Валюта", False)],
            category="finance",
        ))
        prompt = registry.get_tools_prompt()
        assert "FINANCE" in prompt
        assert "get_balance" in prompt
        assert "Получить баланс" in prompt

    def test_get_tools_json_schema(self, registry):
        """JSON Schema для всех инструментов."""
        registry.register(Tool(name="a", description="A"))
        registry.register(Tool(name="b", description="B", visible=False))

        schemas = registry.get_tools_json_schema()
        assert len(schemas) == 1  # Only visible
        assert schemas[0]["function"]["name"] == "a"

    @pytest.mark.asyncio
    async def test_execute_with_db_session(self, registry):
        """Инструмент с db_session."""
        async def handler(db_session=None):
            return f"session={db_session is not None}"

        tool = Tool(name="db_tool", description="DB Tool",
                    handler=handler, needs_db=True)
        registry.register(tool)

        result = await registry.execute("db_tool", db_session="mock_session")
        assert result.success
        assert "True" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: TOOL RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolResult:
    """Тесты результата инструмента."""

    def test_success_result(self):
        r = ToolResult("test", True, "OK", data=42)
        assert str(r) == "OK"
        assert r.data == 42

    def test_error_result(self):
        r = ToolResult("test", False, "", error="fail")
        assert "ОШИБКА" in str(r)
        assert "fail" in str(r)


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: MEMORY SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryEntry:
    """Тесты единицы памяти."""

    def test_create_entry(self):
        entry = MemoryEntry("test fact", memory_type="fact", importance=0.7)
        assert entry.content == "test fact"
        assert entry.memory_type == "fact"
        assert entry.importance == 0.7
        assert entry.access_count == 0

    def test_touch(self):
        entry = MemoryEntry("test")
        entry.touch()
        assert entry.access_count == 1

    def test_importance_clamped(self):
        e1 = MemoryEntry("test", importance=2.0)
        assert e1.importance == 1.0
        e2 = MemoryEntry("test", importance=-0.5)
        assert e2.importance == 0.0

    def test_to_dict(self):
        entry = MemoryEntry("fact", tags=["a", "b"])
        d = entry.to_dict()
        assert d["content"] == "fact"
        assert d["tags"] == ["a", "b"]


class TestWorkingMemory:
    """Тесты рабочей памяти."""

    def test_set_goal(self):
        wm = WorkingMemory()
        wm.set_goal("Создать заказ")
        assert wm.current_goal == "Создать заказ"
        assert len(wm.plan) == 0

    def test_plan_steps(self):
        wm = WorkingMemory()
        wm.add_plan_step("Распарсить")
        wm.add_plan_step("Сохранить")
        assert len(wm.plan) == 2

        wm.complete_step(0, "Готово")
        assert wm.plan[0]["status"] == "completed"

        wm.fail_step(1, "Ошибка")
        assert wm.plan[1]["status"] == "failed"

    def test_get_current_step(self):
        wm = WorkingMemory()
        wm.add_plan_step("Step 1")
        wm.add_plan_step("Step 2")

        current = wm.get_current_step()
        assert current["step"] == "Step 1"

        wm.complete_step(0, "done")
        current = wm.get_current_step()
        assert current["step"] == "Step 2"

    def test_scratchpad(self):
        wm = WorkingMemory()
        wm.iteration = 1
        wm.add_note("Важное наблюдение")
        assert len(wm.scratchpad) == 1
        assert "Важное наблюдение" in wm.scratchpad[0]

    def test_tool_results(self):
        wm = WorkingMemory()
        wm.add_tool_result("get_balance", "$1000", True)
        assert len(wm.tool_results) == 1
        assert wm.tool_results[0]["tool"] == "get_balance"

    def test_context_summary(self):
        wm = WorkingMemory()
        wm.set_goal("Показать баланс")
        wm.add_plan_step("Запросить БД")
        summary = wm.get_context_summary()
        assert "Показать баланс" in summary
        assert "Запросить БД" in summary

    def test_reset(self):
        wm = WorkingMemory()
        wm.set_goal("Test")
        wm.add_note("note")
        wm.reset()
        assert wm.current_goal == ""
        assert len(wm.scratchpad) == 0


class TestMemoryManager:
    """Тесты менеджера памяти."""

    def test_store_and_recall(self, memory):
        memory.store_fact("Поставщик Ахмед надёжный", importance=0.8,
                          tags=["supplier", "contact"])
        results = memory.recall("Ахмед поставщик")
        assert len(results) >= 1
        assert "Ахмед" in results[0].content

    def test_store_preference(self, memory):
        entry = memory.store_preference("Босс любит краткие ответы")
        assert entry.memory_type == "preference"
        assert entry.importance == 0.7

    def test_store_rule(self, memory):
        entry = memory.store_rule("Заказы > $5000 требуют одобрения")
        assert entry.memory_type == "rule"
        assert entry.importance == 0.8

    def test_recall_by_type(self, memory):
        memory.store_fact("Факт 1", tags=["test"])
        memory.store_preference("Предпочтение 1")
        memory.store_rule("Правило 1")

        facts = memory.recall_all(memory_type="fact")
        assert len(facts) == 1
        prefs = memory.recall_all(memory_type="preference")
        assert len(prefs) == 1

    def test_recall_empty(self, memory):
        results = memory.recall("несуществующий запрос")
        assert len(results) == 0

    def test_importance_filtering(self, memory):
        memory.store_fact("Не важно", importance=0.1)
        memory.store_fact("Важно", importance=0.9)

        results = memory.recall_all(min_importance=0.5)
        assert len(results) == 1
        assert "Важно" in results[0].content

    def test_context_for_prompt(self, memory):
        memory.store_fact("USD/TMT = 19.5", importance=0.9,
                          tags=["currency", "rate"])
        # recall работает по пересечению слов — ищем по словам из контента
        ctx = memory.get_context_for_prompt("USD TMT rate currency")
        assert "19.5" in ctx

    def test_context_empty(self, memory):
        ctx = memory.get_context_for_prompt("что-то странное")
        assert ctx == ""

    def test_working_memory(self, memory):
        wm1 = memory.get_working(123)
        wm2 = memory.get_working(123)
        assert wm1 is wm2  # Same instance

        wm3 = memory.get_working(456)
        assert wm3 is not wm1

    def test_reset_working(self, memory):
        wm = memory.get_working(123)
        wm.set_goal("test")
        memory.reset_working(123)
        assert wm.current_goal == ""

    def test_enforce_limits(self, memory):
        memory.MAX_MEMORIES = 5
        for i in range(10):
            memory.store_fact(f"Fact {i}", importance=i / 10)
        assert memory.total_count == 5

    def test_stats(self, memory):
        memory.store_fact("F1")
        memory.store_preference("P1")
        stats = memory.get_stats()
        assert stats["total"] == 2
        assert "fact" in stats["by_type"]
        assert "preference" in stats["by_type"]


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: MEMORY + DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryDB:
    """Тесты сохранения/загрузки памяти в БД."""

    def test_save_to_db(self, memory, db_session):
        memory.store_fact("Test fact 1", importance=0.7)
        memory.store_preference("User likes short answers")

        count = memory.save_to_db(db_session)
        assert count == 2

        # Проверяем в БД
        entries = db_session.query(AgentMemory).all()
        assert len(entries) == 2

    def test_load_from_db(self, db_session):
        # Добавляем записи напрямую в БД
        db_session.add(AgentMemory(
            content="DB fact",
            memory_type="fact",
            importance=0.8,
            tags=json.dumps(["test"]),
            source="test",
            is_active=True,
        ))
        db_session.commit()

        # Загружаем в новый менеджер
        new_memory = MemoryManager()
        count = new_memory.load_from_db(db_session)
        assert count == 1
        assert new_memory.total_count == 1

        results = new_memory.recall("DB fact")
        assert len(results) == 1

    def test_save_and_reload(self, memory, db_session):
        memory.store_fact("Persistent fact", importance=0.9,
                          tags=["important"])
        memory.save_to_db(db_session)

        new_memory = MemoryManager()
        new_memory.load_from_db(db_session)
        results = new_memory.recall("Persistent fact")
        assert len(results) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: DATABASE MODELS (AgentMemory, AgentThought)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentDBModels:
    """Тесты новых моделей БД."""

    def test_create_agent_memory(self, db_session):
        entry = AgentMemory(
            content="Test memory",
            memory_type="fact",
            importance=0.5,
            tags=json.dumps(["test"]),
            source="test",
            is_active=True,
        )
        db_session.add(entry)
        db_session.commit()

        loaded = db_session.query(AgentMemory).first()
        assert loaded.content == "Test memory"
        assert loaded.memory_type == "fact"
        assert loaded.importance == 0.5
        assert loaded.is_active is True

    def test_create_agent_thought(self, db_session):
        thought = AgentThought(
            chat_id=123456,
            user_query="Покажи баланс",
            iterations=2,
            tools_used=json.dumps(["get_financial_summary"]),
            final_answer="Баланс: $1000",
            processing_time_ms=500,
            memories_created=1,
            plan_used=False,
        )
        db_session.add(thought)
        db_session.commit()

        loaded = db_session.query(AgentThought).first()
        assert loaded.chat_id == 123456
        assert loaded.iterations == 2
        assert "get_financial_summary" in loaded.tools_used
        assert loaded.processing_time_ms == 500


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: AGENT CORE
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentParsing:
    """Тесты парсинга ответов агента."""

    def test_import(self):
        from pds_ultimate.core.agent import Agent, AgentAction, AgentResponse
        assert Agent is not None
        assert AgentAction is not None
        assert AgentResponse is not None

    def test_parse_final_answer(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        raw = json.dumps({
            "thought": "Это простой вопрос",
            "action": {"type": "final_answer", "answer": "Привет, босс!"},
            "confidence": 0.9,
        })
        action = agent_instance._parse_response(raw)
        assert action.action_type == "final_answer"
        assert "Привет" in action.answer

    def test_parse_tool_call(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        raw = json.dumps({
            "thought": "Нужно проверить баланс",
            "action": {
                "type": "tool_call",
                "tool": "get_financial_summary",
                "params": {},
            },
            "confidence": 0.8,
        })
        action = agent_instance._parse_response(raw)
        assert action.action_type == "tool_call"
        assert action.tool_name == "get_financial_summary"

    def test_parse_ask_user(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        raw = json.dumps({
            "thought": "Нужно уточнить",
            "action": {"type": "ask_user", "answer": "Какой номер заказа?"},
            "confidence": 0.6,
        })
        action = agent_instance._parse_response(raw)
        assert action.action_type == "ask_user"
        assert "номер заказа" in action.answer

    def test_parse_non_json(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        action = agent_instance._parse_response("Просто текст без JSON")
        assert action.action_type == "final_answer"
        assert "Просто текст" in action.answer

    def test_parse_with_memory(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        raw = json.dumps({
            "thought": "Надо запомнить",
            "action": {"type": "final_answer", "answer": "OK"},
            "confidence": 0.9,
            "should_remember": "Пользователь предпочитает краткие ответы",
        })
        action = agent_instance._parse_response(raw)
        assert action._should_remember == "Пользователь предпочитает краткие ответы"


class TestAgentRouting:
    """Тесты smart routing."""

    @pytest.mark.asyncio
    async def test_simple_no_tools(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        assert not await agent_instance.should_use_tools("привет")
        assert not await agent_instance.should_use_tools("как дела")
        assert not await agent_instance.should_use_tools("спасибо")

    @pytest.mark.asyncio
    async def test_complex_needs_tools(self):
        from pds_ultimate.core.agent import Agent
        agent_instance = Agent(tool_reg=ToolRegistry(),
                               mem_mgr=MemoryManager())

        assert await agent_instance.should_use_tools("сколько прибыли")
        assert await agent_instance.should_use_tools("какой доход")
        assert await agent_instance.should_use_tools("создай файл excel")
        assert await agent_instance.should_use_tools("напомни мне завтра")
        # Числа в сообщении — tools
        assert await agent_instance.should_use_tools("позвони 12345")
        # Длинное сообщение — tools
        assert await agent_instance.should_use_tools("x " * 60)


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: BUSINESS TOOLS REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusinessTools:
    """Тесты регистрации бизнес-инструментов."""

    def test_register_all(self):
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry as global_registry

        count = register_all_tools()
        assert count >= 14  # Минимум 14 инструментов

        # Проверяем что инструменты зарегистрированы в глобальном реестре
        assert global_registry.get("create_order") is not None
        assert global_registry.get("get_orders_status") is not None
        assert global_registry.get("get_financial_summary") is not None
        assert global_registry.get("convert_currency") is not None
        assert global_registry.get("save_contact_note") is not None
        assert global_registry.get("find_contact") is not None
        assert global_registry.get("create_reminder") is not None
        assert global_registry.get("morning_brief") is not None
        assert global_registry.get("translate") is not None
        assert global_registry.get("summarize") is not None
        assert global_registry.get("remember") is not None
        assert global_registry.get("recall") is not None

    @pytest.mark.asyncio
    async def test_convert_currency_tool(self):
        from pds_ultimate.core.business_tools import tool_convert_currency

        result = await tool_convert_currency(100, "TMT", "USD")
        assert result.success
        assert "5.13" in result.output  # 100/19.5 ≈ 5.13

    @pytest.mark.asyncio
    async def test_convert_currency_cny(self):
        from pds_ultimate.core.business_tools import tool_convert_currency

        result = await tool_convert_currency(71, "CNY", "USD")
        assert result.success
        assert "10.00" in result.output  # 71/7.1 = 10.00

    @pytest.mark.asyncio
    async def test_financial_summary_no_session(self):
        from pds_ultimate.core.business_tools import tool_get_financial_summary

        result = await tool_get_financial_summary(db_session=None)
        assert not result.success
        assert "сессии" in result.error.lower() or "Нет" in result.error

    @pytest.mark.asyncio
    async def test_remember_tool(self):
        from pds_ultimate.core.business_tools import tool_remember

        result = await tool_remember("Тестовый факт", importance=0.8)
        assert result.success
        assert "Запомнил" in result.output

    @pytest.mark.asyncio
    async def test_recall_tool_empty(self):
        from pds_ultimate.core.business_tools import tool_recall

        result = await tool_recall("несуществующий_запрос_xyz")
        assert result.success
        # Может найти или нет — зависит от состояния memory_manager

    @pytest.mark.asyncio
    async def test_financial_summary_with_db(self, db_session):
        from pds_ultimate.core.business_tools import tool_get_financial_summary

        # Добавляем тестовые данные
        order = Order(
            order_number="TEST-001",
            status=OrderStatus.COMPLETED,
            order_date=date.today(),
            income=1000,
            income_currency="USD",
        )
        db_session.add(order)
        db_session.flush()

        db_session.add(Transaction(
            order_id=order.id,
            transaction_type=TransactionType.INCOME,
            amount=1000,
            currency="USD",
            amount_usd=1000,
            description="Test income",
            transaction_date=date.today(),
        ))
        db_session.commit()

        result = await tool_get_financial_summary(db_session=db_session)
        assert result.success
        assert "1000" in result.output

    @pytest.mark.asyncio
    async def test_save_contact_note_with_db(self, db_session):
        from pds_ultimate.core.business_tools import tool_save_contact_note

        result = await tool_save_contact_note(
            name="Тестовый Контакт",
            note="Надёжный поставщик",
            db_session=db_session,
        )
        assert result.success
        assert "Записал" in result.output

        # Проверяем в БД
        contact = db_session.query(Contact).first()
        assert contact is not None
        assert "Надёжный" in contact.notes

    @pytest.mark.asyncio
    async def test_find_contact_with_db(self, db_session):
        from pds_ultimate.core.business_tools import tool_find_contact

        db_session.add(
            Contact(name="Ахмед", contact_type=ContactType.SUPPLIER))
        db_session.commit()

        result = await tool_find_contact("Ахмед", db_session=db_session)
        assert result.success
        assert "Ахмед" in result.output

    @pytest.mark.asyncio
    async def test_morning_brief_with_db(self, db_session):
        from pds_ultimate.core.business_tools import tool_morning_brief

        result = await tool_morning_brief(db_session=db_session)
        assert result.success
        assert "БРИФИНГ" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТЫ: CROSS-REFERENCES (новые файлы)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentCrossRefs:
    """Кросс-тесты: все новые модули правильно связаны."""

    def test_core_imports(self):
        """Все core модули импортируются."""
        from pds_ultimate.core.agent import Agent, agent
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.memory import MemoryManager, memory_manager
        from pds_ultimate.core.tools import ToolRegistry, tool_registry
        assert Agent is not None
        assert agent is not None
        assert MemoryManager is not None
        assert memory_manager is not None
        assert ToolRegistry is not None
        assert tool_registry is not None
        assert register_all_tools is not None

    def test_db_models_import(self):
        """Новые модели БД импортируются."""
        from pds_ultimate.core.database import AgentMemory, AgentThought
        assert AgentMemory is not None
        assert AgentThought is not None

    def test_agent_has_tools_and_memory(self):
        """Агент имеет доступ к tools и memory."""
        from pds_ultimate.core.agent import Agent
        from pds_ultimate.core.memory import MemoryManager
        from pds_ultimate.core.tools import ToolRegistry

        reg = ToolRegistry()
        mem = MemoryManager()
        a = Agent(tool_reg=reg, mem_mgr=mem)
        assert a._tools is reg
        assert a._memory is mem

    def test_tool_registry_decorator(self):
        """Декоратор регистрации работает."""
        from pds_ultimate.core.tools import register_tool

        # Декоратор использует глобальный registry — просто проверяем что не падает
        @register_tool(
            name="test_decorator_tool",
            description="Test",
            category="test",
        )
        async def my_tool():
            return "ok"

        assert my_tool is not None

    def test_universal_handler_imports_agent(self):
        """Universal handler импортирует Agent."""
        from pds_ultimate.bot.handlers import universal
        assert hasattr(universal, 'agent')
