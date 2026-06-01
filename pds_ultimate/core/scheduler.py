"""
PDS-Ultimate Scheduler
========================
Планировщик задач на базе APScheduler.

Отказоустойчивость по ТЗ:
- Задачи хранятся в SQLite (выживают при перезагрузке)
- Ни одно напоминание не будет пропущено
- Поддержка: cron, interval, date триггеров

Встроенные задачи:
- Утренний брифинг (08:30) — план на день + «что добавить/убрать?»
- Проверка напоминаний за 30 минут (каждую минуту)
- Отчёт каждые 3 дня (09:00)
- Ежесуточный бэкап (03:00)
- Проверка статусов позиций (T+4, каждый вторник)
- Пересканирование стиля (раз в неделю)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    JobEvent,
    JobExecutionEvent,
)
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pds_ultimate.config import DATABASE_PATH, config, logger


class TaskScheduler:
    """
    Центральный планировщик задач.

    Lifecycle:
        1. __init__() — создаёт APScheduler
        2. set_dependencies() — получает модули и Bot из main.py
        3. start() — запускает планировщик, регистрирует builtin-задачи

    Использование:
        scheduler = TaskScheduler()
        scheduler.set_dependencies(session_factory=..., bot=..., ...)
        await scheduler.start()
    """

    def __init__(self):
        # Хранилище задач в SQLite (отказоустойчивость) для пользовательских задач
        # Memory jobstore для builtin задач (bound methods не сериализуются)
        jobstores = {
            "default": SQLAlchemyJobStore(
                url=f"sqlite:///{DATABASE_PATH}",
                tablename="apscheduler_jobs",
            ),
            "builtin": MemoryJobStore(),
        }

        # Исполнители
        executors = {
            "default": AsyncIOExecutor(),
            # Для CPU-bound задач (OCR, Excel генерация)
            "threadpool": ThreadPoolExecutor(
                max_workers=config.scheduler.max_workers
            ),
        }

        # Настройки
        job_defaults = {
            "coalesce": True,     # Объединять пропущенные запуски в один
            "max_instances": 3,   # Макс параллельных экземпляров одной задачи
            "misfire_grace_time": 3600,  # 1 час допуска для пропущенных задач
        }

        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        # Обработчики событий
        self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)
        self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)

        self._started = False

        # Зависимости — инжектятся через set_dependencies()
        self._bot: Any = None
        self._session_factory: Any = None
        self._morning_brief: Any = None
        self._calendar_mgr: Any = None
        self._backup_mgr: Any = None

        logger.info("TaskScheduler инициализирован")

    # ─── Dependency Injection ────────────────────────────────────────────

    def set_dependencies(
        self,
        session_factory: Any,
        bot: Any,
        morning_brief: Any,
        calendar_mgr: Any,
        backup_mgr: Any,
    ) -> None:
        """
        Установить зависимости из main.py.
        Вызывается ДО start().
        """
        self._session_factory = session_factory
        self._bot = bot
        self._morning_brief = morning_brief
        self._calendar_mgr = calendar_mgr
        self._backup_mgr = backup_mgr
        logger.info("TaskScheduler: зависимости установлены")

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Запустить планировщик."""
        if self._started:
            return

        self._scheduler.start()
        self._started = True

        # Зарегистрировать встроенные задачи
        await self._register_builtin_jobs()

        job_count = len(self._scheduler.get_jobs())
        logger.info(f"TaskScheduler запущен, активных задач: {job_count}")

    async def stop(self) -> None:
        """Остановить планировщик (задачи сохраняются в БД)."""
        if self._started:
            self._scheduler.shutdown(wait=True)
            self._started = False
            logger.info("TaskScheduler остановлен (задачи сохранены)")

    # ─── Добавление задач ────────────────────────────────────────────────

    def add_once(
        self,
        func: Callable,
        run_at: datetime,
        job_id: str,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        replace: bool = True,
    ) -> None:
        """
        Добавить разовую задачу.

        Args:
            func: Функция для выполнения
            run_at: Когда выполнить
            job_id: Уникальный ID задачи
            args: Позиционные аргументы
            kwargs: Именованные аргументы
            replace: Заменить если задача с таким ID уже есть
        """
        if replace:
            self.remove(job_id)

        self._scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace,
            name=job_id,
        )
        logger.debug(f"Задача добавлена: {job_id} → {run_at}")

    def add_cron(
        self,
        func: Callable,
        job_id: str,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        replace: bool = True,
        jobstore: str = "default",
        **cron_kwargs,
    ) -> None:
        """
        Добавить задачу по расписанию (cron).

        Примеры cron_kwargs:
            hour=8, minute=30              → каждый день в 08:30
            day_of_week='tue', hour=9      → каждый вторник в 09:00
            day='*/3', hour=9              → каждые 3 дня в 09:00
        """
        if replace:
            self.remove(job_id)

        self._scheduler.add_job(
            func,
            trigger=CronTrigger(**cron_kwargs),
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace,
            name=job_id,
            jobstore=jobstore,
        )
        logger.debug(f"Cron-задача добавлена: {job_id} → {cron_kwargs}")

    def add_interval(
        self,
        func: Callable,
        job_id: str,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        replace: bool = True,
        jobstore: str = "default",
        **interval_kwargs,
    ) -> None:
        """
        Добавить задачу с интервалом.

        Примеры interval_kwargs:
            hours=2       → каждые 2 часа
            minutes=30    → каждые 30 минут
            days=1        → раз в сутки
        """
        if replace:
            self.remove(job_id)

        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(**interval_kwargs),
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace,
            name=job_id,
            jobstore=jobstore,
        )
        logger.debug(
            f"Interval-задача добавлена: {job_id} → {interval_kwargs}")

    # ─── Управление задачами ─────────────────────────────────────────────

    def remove(self, job_id: str) -> bool:
        """Удалить задачу по ID. Возвращает True если задача существовала."""
        try:
            self._scheduler.remove_job(job_id)
            logger.debug(f"Задача удалена: {job_id}")
            return True
        except Exception:
            return False

    def pause(self, job_id: str) -> None:
        """Приостановить задачу."""
        try:
            self._scheduler.pause_job(job_id)
            logger.debug(f"Задача приостановлена: {job_id}")
        except Exception as e:
            logger.warning(f"Не удалось приостановить задачу {job_id}: {e}")

    def resume(self, job_id: str) -> None:
        """Возобновить задачу."""
        try:
            self._scheduler.resume_job(job_id)
            logger.debug(f"Задача возобновлена: {job_id}")
        except Exception as e:
            logger.warning(f"Не удалось возобновить задачу {job_id}: {e}")

    def reschedule(self, job_id: str, run_at: datetime) -> None:
        """Перенести задачу на другое время."""
        try:
            self._scheduler.reschedule_job(
                job_id, trigger=DateTrigger(run_date=run_at)
            )
            logger.debug(f"Задача перенесена: {job_id} → {run_at}")
        except Exception as e:
            logger.warning(f"Не удалось перенести задачу {job_id}: {e}")

    def get_all_jobs(self) -> list[dict]:
        """Получить все активные задачи."""
        jobs = self._scheduler.get_jobs()
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in jobs
        ]

    def job_exists(self, job_id: str) -> bool:
        """Проверить существование задачи."""
        return self._scheduler.get_job(job_id) is not None

    # ─── Встроенные задачи ───────────────────────────────────────────────

    async def _register_builtin_jobs(self) -> None:
        """
        Регистрация встроенных задач. Времена читаются из DB (если есть),
        иначе — из переменных окружения / значений по умолчанию.
        """
        sc = config.scheduler
        _js = "builtin"  # Memory jobstore — bound methods не сериализуются

        # Читаем динамические настройки из DB
        brief_h = int(await self._get_setting("morning_brief_hour", str(sc.morning_brief_hour)))
        brief_m = int(await self._get_setting("morning_brief_minute", str(sc.morning_brief_minute)))
        report_days = int(await self._get_setting("report_interval_days", str(sc.report_interval_days)))
        report_h = int(await self._get_setting("report_hour", str(sc.report_hour)))
        report_m = int(await self._get_setting("report_minute", str(sc.report_minute)))
        backup_h = int(await self._get_setting("backup_hour", str(sc.backup_hour)))
        backup_m = int(await self._get_setting("backup_minute", str(sc.backup_minute)))

        # 1. Утренний брифинг
        self.add_cron(
            func=self._job_morning_brief,
            job_id="builtin_morning_brief",
            jobstore=_js,
            hour=brief_h,
            minute=brief_m,
        )

        # 2. Проверка напоминаний за 30 минут (каждую минуту)
        self.add_interval(
            func=self._job_check_calendar_reminders,
            job_id="builtin_calendar_reminder_check",
            jobstore=_js,
            minutes=1,
        )

        # 3. Отчёт каждые N дней
        self.add_cron(
            func=self._job_3day_report,
            job_id="builtin_3day_report",
            jobstore=_js,
            day=f"*/{report_days}",
            hour=report_h,
            minute=report_m,
        )

        # 4. Ежесуточный бэкап
        if config.security.auto_backup:
            self.add_cron(
                func=self._job_daily_backup,
                job_id="builtin_daily_backup",
                jobstore=_js,
                hour=backup_h,
                minute=backup_m,
            )

        # 5. Проверка пропущенных напоминаний (каждый час)
        self.add_interval(
            func=self._job_check_reminders,
            job_id="builtin_reminder_check",
            jobstore=_js,
            hours=1,
        )

        logger.info(
            f"Встроенные задачи зарегистрированы: брифинг {brief_h:02d}:{brief_m:02d}, "
            f"отчёт каждые {report_days}д в {report_h:02d}:{report_m:02d}, "
            f"бэкап {backup_h:02d}:{backup_m:02d}"
        )

    async def _get_setting(self, key: str, default: str) -> str:
        """Read a scheduler setting from DB, falling back to default."""
        if not self._session_factory:
            return default
        try:
            from pds_ultimate.core.database import UserSetting
            with self._session_factory() as session:
                row = session.get(UserSetting, key)
                return row.value if row else default
        except Exception:
            return default

    async def reschedule_morning_brief(self, hour: int, minute: int) -> None:
        """Re-register morning brief job with new time and persist to DB."""
        await self._save_setting("morning_brief_hour", str(hour))
        await self._save_setting("morning_brief_minute", str(minute))
        self.add_cron(
            func=self._job_morning_brief,
            job_id="builtin_morning_brief",
            jobstore="builtin",
            hour=hour,
            minute=minute,
        )
        logger.info(f"Брифинг переназначен на {hour:02d}:{minute:02d}")

    async def reschedule_backup(self, hour: int, minute: int) -> None:
        """Re-register backup job with new time and persist to DB."""
        await self._save_setting("backup_hour", str(hour))
        await self._save_setting("backup_minute", str(minute))
        self.add_cron(
            func=self._job_daily_backup,
            job_id="builtin_daily_backup",
            jobstore="builtin",
            hour=hour,
            minute=minute,
        )
        logger.info(f"Бэкап переназначен на {hour:02d}:{minute:02d}")

    async def reschedule_report(self, interval_days: int, hour: int, minute: int) -> None:
        """Re-register 3-day report with new settings and persist to DB."""
        await self._save_setting("report_interval_days", str(interval_days))
        await self._save_setting("report_hour", str(hour))
        await self._save_setting("report_minute", str(minute))
        self.add_cron(
            func=self._job_3day_report,
            job_id="builtin_3day_report",
            jobstore="builtin",
            day=f"*/{interval_days}",
            hour=hour,
            minute=minute,
        )
        logger.info(f"Отчёт переназначен: каждые {interval_days}д в {hour:02d}:{minute:02d}")

    async def _save_setting(self, key: str, value: str) -> None:
        """Persist a scheduler setting to DB."""
        if not self._session_factory:
            return
        try:
            from pds_ultimate.core.database import UserSetting
            with self._session_factory() as session:
                row = session.get(UserSetting, key)
                if row:
                    row.value = value
                else:
                    session.add(UserSetting(key=key, value=value))
                session.commit()
        except Exception as e:
            logger.warning(f"Не удалось сохранить настройку {key}: {e}")

    # ─── Реальные job-функции ────────────────────────────────────────────

    async def _job_morning_brief(self) -> None:
        """
        Утренний брифинг → отправить владельцу в TG.
        Включает план на день + вопрос «что добавить/убрать?»
        """
        if not self._morning_brief or not self._bot:
            logger.warning(
                "[SCHEDULER] Утренний брифинг — модуль не подключён")
            return

        try:
            brief_text = await self._morning_brief.generate()
            await self._bot.send_message(
                config.telegram.owner_id,
                brief_text,
            )
            logger.info("Утренний брифинг отправлен")
        except Exception as e:
            logger.error(f"Ошибка утреннего брифинга: {e}", exc_info=True)

    async def _job_check_calendar_reminders(self) -> None:
        """
        Проверка событий за 30 минут → отправить предупреждение.
        Запускается каждую минуту.
        """
        if not self._calendar_mgr or not self._bot:
            return

        try:
            reminders = await self._calendar_mgr.get_upcoming_reminders()
            for reminder in reminders:
                text = self._calendar_mgr.format_reminder(reminder)
                await self._bot.send_message(
                    config.telegram.owner_id,
                    text,
                )
                # Помечаем чтобы не дублировать
                await self._calendar_mgr.mark_reminded(reminder["id"])
                logger.info(
                    f"Напоминание отправлено: событие #{reminder['id']} "
                    f"'{reminder['title']}' через {reminder['minutes_until']} мин"
                )
        except Exception as e:
            logger.error(f"Ошибка проверки напоминаний: {e}", exc_info=True)

    async def _job_3day_report(self) -> None:
        """3-дневный отчёт → отправить владельцу."""
        if not self._morning_brief or not self._bot:
            logger.warning("[SCHEDULER] 3-дневный отчёт — модуль не подключён")
            return

        try:
            report = await self._morning_brief.generate_3day_report()
            await self._bot.send_message(
                config.telegram.owner_id,
                report,
            )
            logger.info("3-дневный отчёт отправлен")
        except Exception as e:
            logger.error(f"Ошибка 3-дневного отчёта: {e}", exc_info=True)

    async def _job_daily_backup(self) -> None:
        """Ежесуточный бэкап."""
        if not self._backup_mgr:
            logger.warning("[SCHEDULER] Бэкап — модуль не подключён")
            return

        try:
            result = await self._backup_mgr.create_backup()
            logger.info(f"Ежесуточный бэкап выполнен: {result}")
        except Exception as e:
            logger.error(f"Ошибка бэкапа: {e}", exc_info=True)

    async def _job_check_reminders(self) -> None:
        """Проверка пропущенных напоминаний (каждый час)."""
        if not self._session_factory or not self._bot:
            return

        try:
            from pds_ultimate.core.database import Reminder, ReminderStatus

            with self._session_factory() as session:
                pending = (
                    session.query(Reminder)
                    .filter(
                        Reminder.status == ReminderStatus.PENDING,
                        Reminder.scheduled_at <= datetime.now(),
                    )
                    .all()
                )

                for rem in pending:
                    try:
                        await self._bot.send_message(
                            config.telegram.owner_id,
                            f"🔔 Напоминание:\n{rem.message}",
                        )
                        rem.status = ReminderStatus.SENT
                        rem.sent_at = datetime.now()
                    except Exception as e:
                        logger.warning(
                            f"Не удалось отправить напоминание #{rem.id}: {e}")

                session.commit()

        except Exception as e:
            logger.error(
                f"Ошибка проверки напоминаний: {e}", exc_info=True)

    # ─── Обработчики событий ─────────────────────────────────────────────

    @staticmethod
    def _on_job_error(event: JobExecutionEvent) -> None:
        logger.error(
            f"Ошибка задачи '{event.job_id}': {event.exception}",
            exc_info=event.traceback,
        )

    @staticmethod
    def _on_job_missed(event: JobEvent) -> None:
        logger.warning(f"Пропущенная задача: '{event.job_id}'")

    @staticmethod
    def _on_job_executed(event: JobExecutionEvent) -> None:
        logger.debug(f"Задача выполнена: '{event.job_id}'")


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

scheduler = TaskScheduler()
