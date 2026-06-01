"""
Settings handler — динамическое управление расписанием и авто-ответом через бота.

Команды:
  /settings          — показать текущие настройки
  /brief HH:MM       — изменить время утреннего брифинга
  /backup HH:MM      — изменить время бэкапа
  /report N HH:MM    — отчёт каждые N дней в HH:MM
  /autoreply on|off  — включить/выключить авто-ответ в TG
  /autoreplystyle    — обновить стиль авто-ответа (запускает ресканирование)
"""
from __future__ import annotations

import re
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from pds_ultimate.config import config, logger

router = Router(name="settings")

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_time(text: str) -> tuple[int, int] | None:
    """Parse HH:MM -> (hour, minute) or None if invalid."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def _only_owner(message: Message) -> bool:
    return message.from_user and message.from_user.id == config.telegram.owner_id


# ─── /settings ───────────────────────────────────────────────────────────────


@router.message(Command("settings"))
async def cmd_settings(message: Message, scheduler: Any = None) -> None:
    if not _only_owner(message):
        return

    if scheduler is None:
        from pds_ultimate.core.scheduler import scheduler as _sched
        scheduler = _sched

    sc = config.scheduler
    bh = int(await scheduler._get_setting("morning_brief_hour", str(sc.morning_brief_hour)))
    bm = int(await scheduler._get_setting("morning_brief_minute", str(sc.morning_brief_minute)))
    rdays = int(await scheduler._get_setting("report_interval_days", str(sc.report_interval_days)))
    rh = int(await scheduler._get_setting("report_hour", str(sc.report_hour)))
    rm = int(await scheduler._get_setting("report_minute", str(sc.report_minute)))
    bkh = int(await scheduler._get_setting("backup_hour", str(sc.backup_hour)))
    bkm = int(await scheduler._get_setting("backup_minute", str(sc.backup_minute)))
    ar_enabled = await scheduler._get_setting("autoreply_enabled", "false")

    text = (
        "⚙️ <b>Текущие настройки</b>\n\n"
        f"🌅 Брифинг: <b>{bh:02d}:{bm:02d}</b>  — изменить: <code>/brief HH:MM</code>\n"
        f"📊 Отчёт: каждые <b>{rdays}д</b> в <b>{rh:02d}:{rm:02d}</b>  — <code>/report N HH:MM</code>\n"
        f"💾 Бэкап: <b>{bkh:02d}:{bkm:02d}</b>  — изменить: <code>/backup HH:MM</code>\n"
        f"🤖 Авто-ответ (TG): <b>{'вкл' if ar_enabled == 'true' else 'выкл'}</b>  — <code>/autoreply on|off</code>\n"
    )
    await message.answer(text, parse_mode="HTML")


# ─── /brief HH:MM ────────────────────────────────────────────────────────────


@router.message(Command("brief"))
async def cmd_brief(message: Message, scheduler: Any = None) -> None:
    if not _only_owner(message):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/brief HH:MM</code>", parse_mode="HTML")
        return

    t = _parse_time(args[1])
    if t is None:
        await message.answer("Неверный формат времени. Пример: <code>/brief 08:30</code>", parse_mode="HTML")
        return

    if scheduler is None:
        from pds_ultimate.core.scheduler import scheduler as _sched
        scheduler = _sched

    h, m = t
    await scheduler.reschedule_morning_brief(h, m)
    await message.answer(f"✅ Утренний брифинг перенесён на <b>{h:02d}:{m:02d}</b>", parse_mode="HTML")
    logger.info(f"[SETTINGS] Брифинг перенесён на {h:02d}:{m:02d} пользователем {message.from_user.id}")


# ─── /backup HH:MM ───────────────────────────────────────────────────────────


@router.message(Command("backup"))
async def cmd_backup_time(message: Message, scheduler: Any = None) -> None:
    if not _only_owner(message):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/backup HH:MM</code>", parse_mode="HTML")
        return

    t = _parse_time(args[1])
    if t is None:
        await message.answer("Неверный формат времени. Пример: <code>/backup 03:00</code>", parse_mode="HTML")
        return

    if scheduler is None:
        from pds_ultimate.core.scheduler import scheduler as _sched
        scheduler = _sched

    h, m = t
    await scheduler.reschedule_backup(h, m)
    await message.answer(f"✅ Бэкап перенесён на <b>{h:02d}:{m:02d}</b>", parse_mode="HTML")
    logger.info(f"[SETTINGS] Бэкап перенесён на {h:02d}:{m:02d}")


# ─── /report N HH:MM ─────────────────────────────────────────────────────────


@router.message(Command("report"))
async def cmd_report_schedule(message: Message, scheduler: Any = None) -> None:
    if not _only_owner(message):
        return

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "Использование: <code>/report N HH:MM</code>\nПример: <code>/report 3 09:00</code>",
            parse_mode="HTML",
        )
        return

    try:
        days = int(args[1])
        if days < 1 or days > 30:
            raise ValueError
    except ValueError:
        await message.answer("N должно быть числом от 1 до 30")
        return

    t = _parse_time(args[2])
    if t is None:
        await message.answer("Неверный формат времени. Пример: <code>/report 3 09:00</code>", parse_mode="HTML")
        return

    if scheduler is None:
        from pds_ultimate.core.scheduler import scheduler as _sched
        scheduler = _sched

    h, m = t
    await scheduler.reschedule_report(days, h, m)
    await message.answer(
        f"✅ Отчёт: каждые <b>{days}д</b> в <b>{h:02d}:{m:02d}</b>",
        parse_mode="HTML",
    )
    logger.info(f"[SETTINGS] Отчёт перенаряжён: каждые {days}д в {h:02d}:{m:02d}")


# ─── /autoreply on|off ───────────────────────────────────────────────────────


@router.message(Command("autoreply"))
async def cmd_autoreply(message: Message, scheduler: Any = None) -> None:
    if not _only_owner(message):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        await message.answer(
            "Использование: <code>/autoreply on</code> или <code>/autoreply off</code>",
            parse_mode="HTML",
        )
        return

    enabled = args[1].lower() == "on"

    if scheduler is None:
        from pds_ultimate.core.scheduler import scheduler as _sched
        scheduler = _sched

    await scheduler._save_setting("autoreply_enabled", "true" if enabled else "false")

    # Notify telethon client
    try:
        from pds_ultimate.integrations.telethon_client import telethon_client
        if enabled:
            await telethon_client.disable_auto_reply()
            await message.answer(
                "⚠️ Старый авто-ответ Telethon отключён — используется TriggerEngine (без дублей).\n"
                "Реакции на входящие идут через агента с per-contact стилем.",
                parse_mode="HTML",
            )
            logger.info("[SETTINGS] autoreply on → using TriggerEngine only")
            return
        else:
            await telethon_client.disable_auto_reply()
    except Exception as e:
        logger.warning(f"Не удалось переключить авто-ответ в Telethon: {e}")

    status = "включён" if enabled else "выключен"
    await message.answer(
        f"🤖 Авто-ответ в Telegram <b>{status}</b>",
        parse_mode="HTML",
    )
    logger.info(f"[SETTINGS] Авто-ответ TG: {status}")


# ─── /tasks [id] ─────────────────────────────────────────────────────────────


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    """
    /tasks        — список всех активных автономных задач
    /tasks <id>   — подробный статус конкретной задачи
    """
    if not _only_owner(message):
        return

    from pds_ultimate.core.autonomy_engine import autonomy_engine

    args = (message.text or "").split(maxsplit=1)
    task_id = args[1].strip() if len(args) > 1 else ""

    if task_id:
        task = autonomy_engine.get_task(task_id)
        if not task:
            await message.answer(f"❌ Задача <code>{task_id}</code> не найдена.", parse_mode="HTML")
            return
        lines = [
            f"📋 <b>Задача {task.id}</b>",
            f"🎯 {task.title}",
            f"📊 Статус: <b>{task.status.value}</b>",
            f"📈 Прогресс: {task.progress:.0%}",
            f"🔧 Шагов: {len(task.steps)}",
        ]
        if task.corrections:
            lines.append(f"🔄 Коррекций: {len(task.corrections)}")
        await message.answer("\n".join(lines), parse_mode="HTML")
    else:
        stats = autonomy_engine.get_stats()
        queue_text = autonomy_engine.format_queue()
        total = stats.get("total", 0)
        active = stats.get("active", 0)
        if total == 0:
            await message.answer("📋 Нет активных задач.", parse_mode="HTML")
            return
        text = (
            f"📋 <b>Автономные задачи</b>\n\n"
            f"{queue_text}\n\n"
            f"Всего: {total} | Активных: {active}"
        )
        await message.answer(text[:4096], parse_mode="HTML")


# ─── /help ───────────────────────────────────────────────────────────────────


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """/help — показать список доступных команд."""
    if not _only_owner(message):
        return

    text = (
        "🤖 <b>PDS-Ultimate — Команды бота</b>\n\n"
        "<b>Основное</b>\n"
        "/start — приветствие и статус\n"
        "/help — эта справка\n\n"
        "<b>Настройки расписания</b>\n"
        "/settings — текущие настройки\n"
        "/brief HH:MM — время утреннего брифинга\n"
        "/report N HH:MM — интервал отчётов\n"
        "/backup HH:MM — время резервного копирования\n\n"
        "<b>Авто-ответ</b>\n"
        "/autoreply on|off — включить/выключить авто-ответ в Telegram\n\n"
        "<b>Задачи</b>\n"
        "/tasks — список фоновых задач\n"
        "/tasks &lt;id&gt; — статус конкретной задачи\n\n"
        "<b>Память агента</b>\n"
        "/memory — обзор памяти по типам\n"
        "/memory &lt;запрос&gt; — поиск в памяти\n"
        "/memory export — скачать всю память как JSON\n\n"
        "💡 Для всего остального просто напиши что нужно — агент сам разберётся."
    )
    await message.answer(text, parse_mode="HTML")


# ─── /memory [query | export] ────────────────────────────────────────────────


@router.message(Command("memory"))
async def cmd_memory(message: Message) -> None:
    """
    /memory            — показать статистику и последние записи памяти
    /memory <запрос>   — найти в памяти по ключевым словам
    /memory export     — скачать всю память как JSON-файл
    """
    if not _only_owner(message):
        return

    from pds_ultimate.core.advanced_memory_manager import advanced_memory_manager

    args = (message.text or "").split(maxsplit=1)
    query = args[1].strip() if len(args) > 1 else ""

    if query.lower() == "export":
        # Export mode — send JSON file
        import io
        import json as _json
        all_entries = advanced_memory_manager.recall_all(top_k=10000)
        data = []
        for e in all_entries:
            data.append({
                "id": e.id,
                "type": e.memory_type.value if hasattr(e.memory_type, "value") else str(e.memory_type),
                "content": e.content,
                "importance": getattr(e, "importance", 0),
                "tags": list(getattr(e, "tags", [])),
                "created_at": str(getattr(e, "created_at", "")),
            })
        buf = io.BytesIO(_json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.name = "memory_export.json"
        buf.seek(0)
        from aiogram.types import BufferedInputFile
        await message.answer_document(
            BufferedInputFile(buf.read(), filename="memory_export.json"),
            caption=f"🧠 Экспорт памяти: {len(data)} записей"
        )
        return

    if query:
        # Search mode
        entries = advanced_memory_manager.recall(query=query, top_k=15)
        if not entries:
            await message.answer(f"🧠 По запросу «{query}» ничего не найдено в памяти.")
            return
        lines = [f"🧠 <b>Память по запросу «{query}»</b> ({len(entries)} записей):\n"]
        for e in entries[:15]:
            mtype = e.memory_type.value if hasattr(e.memory_type, "value") else str(e.memory_type)
            imp = f"⭐{e.importance:.1f}" if hasattr(e, "importance") else ""
            lines.append(f"[{mtype}] {imp} {e.content}")
        await message.answer("\n".join(lines)[:4096], parse_mode="HTML")
    else:
        # Stats mode — show all entries grouped by type
        all_entries = advanced_memory_manager.recall_all(top_k=200)
        if not all_entries:
            await message.answer("🧠 Память пустая. Агент ещё ничего не запомнил.")
            return

        # Group by type
        by_type: dict[str, list] = {}
        for e in all_entries:
            t = e.memory_type.value if hasattr(e.memory_type, "value") else str(e.memory_type)
            by_type.setdefault(t, []).append(e)

        type_icons = {
            "fact": "📌", "preference": "❤️", "rule": "📏",
            "procedural": "🔧", "strategic": "🎯", "failure": "⚠️",
        }
        lines = [f"🧠 <b>Долгосрочная память</b> ({len(all_entries)} записей)\n"]
        for t, entries in sorted(by_type.items()):
            icon = type_icons.get(t, "•")
            top = sorted(entries, key=lambda x: getattr(x, "importance", 0), reverse=True)[:5]
            lines.append(f"\n{icon} <b>{t.upper()}</b> ({len(entries)} шт.):")
            for e in top:
                lines.append(f"  • {e.content[:120]}")
        lines.append(f"\n💡 Поиск: <code>/memory ваш запрос</code> | Экспорт: <code>/memory export</code>")
        await message.answer("\n".join(lines)[:4096], parse_mode="HTML")
