"""
PDS-Ultimate System Tools
==========================
Системные инструменты: память, напоминания, календарь.

ФУНКЦИИ:
- Сохранение в память (semantic memory)
- Поиск по памяти
- Создание напоминаний
- Получение расписания
- Добавление событий в календарь

ARCHITECTURE:
- Интеграция с Memory System v3.0
- Интеграция с Scheduler (APScheduler)
- Интеграция с Calendar APIs
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pds_ultimate.config import logger
from pds_ultimate.core.tools import Tool, ToolParameter, ToolRegistry, ToolResult

# ─── System Tools ───────────────────────────────────────────────────────────


async def tool_save_memory(
    content: str,
    memory_type: str = "fact",
    importance: float = 0.5,
    tags: Optional[str] = None,
) -> ToolResult:
    """
    Сохранить информацию в долговременную память.

    Типы памяти:
    - fact: факты, информация
    - preference: предпочтения пользователя
    - rule: бизнес-правила
    - episodic: события
    - procedural: как делать задачи
    """
    try:
        from pds_ultimate.core.unified_memory import MemoryType
        from pds_ultimate.core.unified_memory import unified_memory as memory_manager

        # Map string type to enum
        type_map = {
            "fact": MemoryType.FACT,
            "preference": MemoryType.PREFERENCE,
            "rule": MemoryType.RULE,
            "episodic": MemoryType.EPISODIC,
            "procedural": MemoryType.PROCEDURAL,
            "semantic": MemoryType.SEMANTIC,
        }

        mem_type = type_map.get(memory_type.lower(), MemoryType.FACT)
        tag_list = [t.strip() for t in tags.split(",")] if tags else []

        entry = memory_manager.add(
            content=content[:2000],  # Limit length
            memory_type=mem_type,
            importance=importance,
            tags=tag_list,
        )

        return ToolResult(
            "save_memory",
            True,
            f"✅ Сохранено в память (id={entry.db_id}, тип={memory_type})",
            data={"memory_id": entry.db_id, "type": memory_type},
        )

    except Exception as e:
        logger.error(f"tool_save_memory failed: {e}")
        return ToolResult("save_memory", False, "", error=str(e))


async def tool_search_memory(
    query: str,
    limit: int = 5,
    memory_type: Optional[str] = None,
) -> ToolResult:
    """
    Поиск по долговременной памяти (semantic search).

    Используется sentence-transformers для semantic search
    или keyword fallback если ML не доступен.
    """
    try:
        from pds_ultimate.core.unified_memory import unified_memory as memory_manager

        memories = memory_manager.search(
            query=query,
            limit=limit,
            memory_type=memory_type,
        )

        if not memories:
            return ToolResult(
                "search_memory",
                False,
                f"Ничего не найдено по запросу '{query}'",
            )

        results = []
        for mem in memories:
            results.append(
                f"• [{mem.memory_type}] {mem.content[:150]} "
                f"(важность={mem.importance:.1f}, уверенность={mem.confidence:.1f})"
            )

        return ToolResult(
            "search_memory",
            True,
            f"Найдено воспоминаний: {len(memories)}\n\n" + "\n".join(results),
            data={
                "memories": [
                    {"content": m.content, "type": m.memory_type,
                        "importance": m.importance}
                    for m in memories
                ]
            },
        )

    except Exception as e:
        logger.error(f"tool_search_memory failed: {e}")
        return ToolResult("search_memory", False, "", error=str(e))


async def tool_create_reminder(
    message: str,
    delay_hours: int = 1,
) -> ToolResult:
    """
    Создать напоминание через указанное время.

    Используется APScheduler для отложенных задач.
    """
    try:
        from pds_ultimate.core.scheduler import scheduler

        reminder_time = datetime.utcnow() + timedelta(hours=delay_hours)

        # Schedule reminder
        job = scheduler.add_job(
            lambda: logger.info(f"REMINDER: {message}"),
            trigger="date",
            run_date=reminder_time,
            args=[],
            name=f"reminder_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )

        return ToolResult(
            "create_reminder",
            True,
            f"✅ Напоминание создано на {reminder_time.strftime('%Y-%m-%d %H:%M')}:\n{message}",
            data={"job_id": job.id, "time": reminder_time.isoformat()},
        )

    except Exception as e:
        logger.error(f"tool_create_reminder failed: {e}")
        return ToolResult("create_reminder", False, "", error=str(e))


async def tool_get_schedule(
    date_str: Optional[str] = None,
) -> ToolResult:
    """
    Получить расписание на день.

    Интеграция с Google Calendar или локальным календарём.
    """
    try:
        from pds_ultimate.core.scheduler import scheduler

        # Get scheduled jobs
        jobs = scheduler.get_jobs()

        if not jobs:
            return ToolResult(
                "get_schedule",
                True,
                "📅 Нет запланированных событий",
            )

        schedule = "📅 Расписание:\n\n"
        for job in jobs[:20]:  # Limit to 20
            next_run = job.next_run_time
            if next_run:
                schedule += f"• {next_run.strftime('%Y-%m-%d %H:%M')}: {job.name}\n"

        return ToolResult(
            "get_schedule",
            True,
            schedule + f"\n(всего: {len(jobs)} событий)",
            data={"events": [{"name": j.name, "time": str(
                j.next_run_time)} for j in jobs]},
        )

    except Exception as e:
        logger.error(f"tool_get_schedule failed: {e}")
        return ToolResult("get_schedule", False, "", error=str(e))


async def tool_add_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
) -> ToolResult:
    """
    Добавить событие в календарь.

    Формат времени: YYYY-MM-DD HH:MM или через N часов/дней.
    """
    try:
        from pds_ultimate.core.scheduler import scheduler

        # Parse start time
        if start_time.startswith("+"):
            # Relative time (e.g., "+2 hours", "+3 days")
            parts = start_time[1:].split()
            value = int(parts[0])
            unit = parts[1] if len(parts) > 1 else "hours"

            if "day" in unit:
                start = datetime.utcnow() + timedelta(days=value)
            elif "hour" in unit:
                start = datetime.utcnow() + timedelta(hours=value)
            else:
                start = datetime.utcnow() + timedelta(hours=value)
        else:
            # Absolute time
            try:
                start = datetime.fromisoformat(start_time)
            except ValueError:
                return ToolResult(
                    "add_event",
                    False,
                    "Неверный формат времени. Используйте YYYY-MM-DD HH:MM или +N hours/days",
                )

        # Parse end time
        if end_time:
            if end_time.startswith("+"):
                parts = end_time[1:].split()
                value = int(parts[0])
                unit = parts[1] if len(parts) > 1 else "hours"
                if "day" in unit:
                    end = datetime.utcnow() + timedelta(days=value)
                else:
                    end = datetime.utcnow() + timedelta(hours=value)
            else:
                end = datetime.fromisoformat(end_time)
        else:
            end = start + timedelta(hours=1)  # Default 1 hour

        # Schedule event
        job = scheduler.add_job(
            lambda: logger.info(f"EVENT: {title}"),
            trigger="date",
            run_date=start,
            name=f"event: {title}",
        )

        return ToolResult(
            "add_event",
            True,
            f"✅ Событие добавлено:\n"
            f"📌 {title}\n"
            f"🕐 {start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')}" +
            (f"\n📝 {description}" if description else ""),
            data={"job_id": job.id, "start": start.isoformat(),
                  "end": end.isoformat()},
        )

    except Exception as e:
        logger.error(f"tool_add_event failed: {e}")
        return ToolResult("add_event", False, "", error=str(e))


# ─── Tool Registration ───────────────────────────────────────────────────────

def register_system_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать system инструменты."""

    registry.register(
        Tool(
            name="save_memory",
            description="Сохранить информацию в долговременную память",
            parameters=[
                ToolParameter("content", "string",
                              "Содержимое для запоминания"),
                ToolParameter(
                    "memory_type", "string", "Тип (fact/preference/rule/episodic/procedural)", default="fact", required=False),
                ToolParameter("importance", "number",
                              "Важность (0.0-1.0)", default=0.5, required=False),
                ToolParameter("tags", "string",
                              "Теги через запятую", required=False),
            ],
            handler=tool_save_memory,
            category="system",
        )
    )

    registry.register(
        Tool(
            name="search_memory",
            description="Поиск по долговременной памяти (semantic search)",
            parameters=[
                ToolParameter("query", "string", "Поисковый запрос"),
                ToolParameter(
                    "limit", "number", "Максимум результатов", default=5, required=False),
                ToolParameter("memory_type", "string",
                              "Фильтр по типу", required=False),
            ],
            handler=tool_search_memory,
            category="system",
        )
    )

    registry.register(
        Tool(
            name="create_reminder",
            description="Создать напоминание через указанное время",
            parameters=[
                ToolParameter("message", "string", "Текст напоминания"),
                ToolParameter("delay_hours", "number",
                              "Задержка в часах", default=1, required=False),
            ],
            handler=tool_create_reminder,
            category="system",
        )
    )

    registry.register(
        Tool(
            name="get_schedule",
            description="Получить расписание на день",
            parameters=[
                ToolParameter(
                    "date_str", "string", "Дата (YYYY-MM-DD), сегодня если не указано", required=False),
            ],
            handler=tool_get_schedule,
            category="system",
        )
    )

    registry.register(
        Tool(
            name="add_event",
            description="Добавить событие в календарь",
            parameters=[
                ToolParameter("title", "string", "Название события"),
                ToolParameter("start_time", "string",
                              "Время начала (YYYY-MM-DD HH:MM или +N hours)"),
                ToolParameter("end_time", "string",
                              "Время окончания", required=False),
                ToolParameter("description", "string",
                              "Описание", required=False),
            ],
            handler=tool_add_event,
            category="system",
        )
    )


__all__ = [
    "tool_save_memory",
    "tool_search_memory",
    "tool_create_reminder",
    "tool_get_schedule",
    "tool_add_event",
    "register_system_tools",
]
