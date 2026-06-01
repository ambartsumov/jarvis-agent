"""Ethan — main ReAct agent (Manus/OpenClaw level), native function-calling."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

from pds_ultimate.config import BASE_DIR, config, logger
from pds_ultimate.core.agent.base import BaseAgent
from pds_ultimate.core.agent.control import cancellation
from pds_ultimate.core.agent.planner import Planner
from pds_ultimate.core.agent.prompts import ETHAN_SYSTEM_NATIVE
from pds_ultimate.core.agent.types import AgentResponse, AgentStep
from pds_ultimate.core.agent.verifier import Verifier
from pds_ultimate.core.llm.client import llm_client
from pds_ultimate.core.llm.router import TaskKind
from pds_ultimate.core.memory.hierarchy import hierarchical_memory
from pds_ultimate.core.security.permissions import permission_engine
from pds_ultimate.core.security.rate_limit import rate_limiter
from pds_ultimate.core.security.sandbox import run_in_sandbox
from pds_ultimate.core.tools.registry import tool_registry

# Tools whose high-risk execution can be transparently routed to the sandbox
_SANDBOXABLE = {"shell_execute", "python_execute"}

# Tasks that MUST use tools — block text-only "done" hallucinations.
_ACTION_REQUIRED = re.compile(
    r"открой|запусти|напиши|запиши|сделай|отправ|клик|найди|скачай|создай|включи|выключи",
    re.I,
)
_WRITE_TASK = re.compile(
    r"(?:текстов\w*\s+)?(?:редактор|файл)|edit_text", re.I)
_EMAIL_TASK = re.compile(
    r"email|e-?mail|@\w+\.|отправ.*(?:почт|письм|mail)|gmail", re.I)
_OPEN_TASK = re.compile(r"открой|запусти", re.I)
_CALENDAR_TASK = re.compile(
    r"календар|расписан|событ|встреч|напомин|завтра|послезавтра|сегодня|"
    r"удали\s+все|запиши|gcal_",
    re.I,
)
_MESSAGING_TASK = re.compile(
    r"напиши|ответь|отправ|скажи|перешли|telegram|whatsapp|@\w|кирил|мам|пап|"
    r"рус|милан|руст|контакт|диалог|сообщ",
    re.I,
)
_SEND_TOOLS = frozenset({"telegram_send", "whatsapp_send", "email_send"})


class EthanAgent(BaseAgent):
    """
    Native function-calling ReAct agent.

    - Think → Act → Observe via OpenAI tool-calling (robust, low hallucination)
    - Parallel tool execution (multiple tool_calls per turn)
    - Permission engine gates high-risk tools per user
    - Wall-clock timeout + cooperative cancellation (/stop)
    - Cost-aware model routing (chat model for steps)
    """

    def __init__(self) -> None:
        super().__init__(name="Итан", max_steps=config.limits.agent_max_steps)
        self.planner = Planner()
        self.verifier = Verifier()
        self._plan_used = False
        # Active-run context shared with orchestration tooling
        self._active_deadline: float = 0.0
        self._active_cancel: asyncio.Event | None = None
        self._active_user: int = 0
        self._subtask_depth: int = 0

    def _system_prompt(self, user_id: int, query: str = "") -> str:
        memory_ctx = hierarchical_memory.build_context(user_id, query=query)
        lessons = ""
        try:
            from pds_ultimate.core.agent.lessons import lesson_book
            lessons = lesson_book.recall(user_id, query)
        except Exception as exc:
            logger.debug(f"lessons recall skipped: {exc}")
        return ETHAN_SYSTEM_NATIVE.format(
            memory=memory_ctx or "Нет релевантной памяти.",
            lessons=lessons or "Пока нет накопленных уроков.",
            workspace=str(BASE_DIR.parent),
        )

    async def should_use_tools(self, text: str) -> bool:
        """Manus-режим: tool-calling агент — это путь ПО УМОЛЧАНИЮ.

        LLM сам решит, нужен ли инструмент. В чат-режим (без инструментов)
        уходят только тривиальные приветствия/благодарности/смолток, где
        инструменты заведомо не нужны — это экономит один LLM-вызов.
        """
        t = text.lower().strip()
        # Очень короткий смолток без задачи → быстрый прямой ответ.
        smalltalk = (
            r"^(привет|здаров|здравствуй(те)?|хай|hello|hi|hey|добр(ое|ый)\b.*|"
            r"спасибо|благодарю|thanks|thank you|ок(ей)?|ok|okay|угу|ага|да|нет|"
            r"пока|бай|bye|споки|спокойной ночи|как дела|что делаешь|как ты)\.?!?\??$"
        )
        if re.match(smalltalk, t):
            return False
        # Составные приветствия: "привет как дела", "привет, как ты" и т.п.
        _greeting_words = {"привет", "здаров", "хай", "hi", "hello", "hey"}
        _task_keywords = re.compile(
            r"\b(создай|сделай|напиши|найди|покажи|отправь|напомни|помоги|открой|"
            r"проверь|скачай|загрузи|запусти|переведи|составь|позвони|сохрани|"
            r"удали|измени|добавь|вычисли|посчитай|дай|включи|выключи|установи)\b"
        )
        first_word = t.split()[0].rstrip(",!?.") if t else ""
        if (
            first_word in _greeting_words
            and len(t) <= 80
            and not _task_keywords.search(t)
        ):
            return False
        # Всё остальное обрабатывает агент с инструментами.
        return True

    async def direct_response(
        self,
        message: str,
        history: list[dict] | None = None,
        style_guide: str = "",
        chat_id: int = 0,
    ) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt(chat_id, query=message)}]
        if history:
            messages.extend(history[-12:])
        messages.append({"role": "user", "content": message})
        answer = await llm_client.chat(messages, kind=TaskKind.CHAT)
        if chat_id:
            try:
                self.remember_turn(chat_id, "user", message)
                self.remember_turn(chat_id, "assistant", answer)
            except Exception:
                pass
        return answer

    async def background_extract_memories(self, dialogue: str, db_session: Any = None) -> None:
        try:
            data = await llm_client.chat_json(
                [
                    {"role": "system",
                        "content": 'Извлеки 0-3 важных факта. JSON: {"facts":["..."]}'},
                    {"role": "user", "content": dialogue[:6000]},
                ],
                kind=TaskKind.SUMMARIZE,
            )
            for fact in data.get("facts", []):
                if isinstance(fact, str) and len(fact) > 5:
                    hierarchical_memory.remember_fact(
                        config.telegram.owner_id, fact)
        except Exception as exc:
            logger.debug(f"Background memory extract: {exc}")

    async def process(
        self,
        message: str,
        chat_id: int,
        history: list[dict] | None = None,
        db_session: Any = None,
        style_guide: str = "",
        step_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentResponse:
        t0 = time.monotonic()
        reply_context = message if "[КОНТЕКСТ" in message else ""
        result = await self.run(
            chat_id, message, reply_context=reply_context,
            step_callback=step_callback, style_guide=style_guide,
        )

        files: list[dict] = []
        for art in result.artifacts:
            if art.get("type") == "file" and art.get("path"):
                path = art["path"]
                files.append({
                    "filepath": path,
                    "filename": path.split("/")[-1],
                    "caption": art.get("caption", ""),
                })

        result.total_time_ms = int((time.monotonic() - t0) * 1000)
        result.files_to_send = files
        return result

    async def run(
        self,
        user_id: int,
        message: str,
        *,
        reply_context: str = "",
        step_callback: Callable[[str], Awaitable[None]] | None = None,
        style_guide: str = "",
    ) -> AgentResponse:
        deadline = time.monotonic() + config.limits.agent_wall_clock_sec
        cancel_event = cancellation.begin(user_id)
        try:
            return await self._run_inner(
                user_id, message, reply_context, step_callback, deadline, cancel_event,
                style_guide=style_guide,
            )
        finally:
            cancellation.end(user_id)

    async def _run_inner(
        self,
        user_id: int,
        message: str,
        reply_context: str,
        step_callback: Callable[[str], Awaitable[None]] | None,
        deadline: float,
        cancel_event: asyncio.Event,
        style_guide: str = "",
    ) -> AgentResponse:
        self.reset()
        self._plan_used = False
        self._active_deadline = deadline
        self._active_cancel = cancel_event
        self._active_user = user_id
        observations: list[str] = []
        tools_used: list[str] = []
        artifacts: list[dict] = []
        memories_created = 0

        user_text = message
        if reply_context:
            user_text = f"[КОНТЕКСТ — ответ на: «{reply_context}»]\n{message}"

        # ⚡ Fast path: skip LLM for obvious single-action commands (saves 10-30s)
        from pds_ultimate.core.agent.fast_paths import try_fast_path

        fast = await try_fast_path(user_text, user_id)
        if fast is not None:
            self.remember_turn(user_id, "user", user_text)
            self.remember_turn(user_id, "assistant", fast.answer)
            logger.info(f"Agent: fast_path ({fast.tools_used})")
            return fast

        self.remember_turn(user_id, "user", user_text)

        from datetime import datetime

        speed_hint = (
            "\n\n⚡ ТЕРМИНАЛ ПЕРВЫМ: open_app/run/spawn/chrome_profile/music/shell_execute — "
            "до любого click_text/read_screen. OCR/мышь только если CLI не помог. "
            "Минимум шагов, параллельные tool_calls в одном ответе."
        )
        if _CALENDAR_TASK.search(user_text):
            now = datetime.now()
            weekdays = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
            speed_hint += (
                f"\n\n📅 Сейчас: {now.strftime('%Y-%m-%d %H:%M')} ({weekdays[now.weekday()]}). "
                "Календарь: сам пойми формулировку владельца → gcal_list при необходимости → "
                "gcal_clear_day / gcal_add. Не edit_text."
            )
        if _MESSAGING_TASK.search(user_text) and not _CALENDAR_TASK.search(user_text):
            speed_hint += (
                "\n\n💬 Сообщение: contact_find (если имя) → contact_style_get → "
                "telegram_read (контекст) → telegram_send. "
                "НЕ create_tool для TG/email — есть готовые инструменты. "
                "OK: в ответе инструмента = отправлено. ERROR: = не отправлено."
            )
        if style_guide:
            speed_hint += f"\n\n[style_guide]\n{style_guide}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(
                user_id, query=user_text) + speed_hint}
        ]
        for m in hierarchical_memory.session(user_id).as_messages(max_turns=6):
            messages.append(m)
        messages.append({"role": "user", "content": user_text})

        tools_schema = tool_registry.openai_schemas()
        from pds_ultimate.core.agent.tool_filter import select_tool_schemas

        tools_schema = select_tool_schemas(user_text, tools_schema)
        logger.debug(f"Agent tools: {len(tools_schema)} schemas (filtered)")
        final_answer = ""

        for iteration in range(1, self.max_steps + 1):
            if cancel_event.is_set():
                final_answer = "⏹ Остановлено по запросу."
                break
            if time.monotonic() > deadline:
                final_answer = (
                    "⏱ Превышен лимит времени выполнения. "
                    f"Сделано шагов: {iteration - 1}. Уточни или разбей задачу."
                )
                break

            t0 = time.monotonic()
            try:
                resp = await llm_client.complete(
                    messages, kind=TaskKind.STEP, tools=tools_schema, tool_choice="auto",
                    temperature=0.2, max_tokens=1024,
                )
            except Exception as exc:
                logger.error(f"Agent LLM error: {exc}")
                final_answer = f"Ошибка LLM: {exc}"
                break

            rate_limiter.record_tokens(user_id, resp.total_tokens)

            # ── Stuck detection (OpenManus-style): duplicate assistant messages ──
            if resp.content and not resp.tool_calls:
                recent_assistant = [
                    m["content"] for m in messages
                    if m.get("role") == "assistant" and m.get("content")
                ]
                duplicate_count = sum(
                    1 for c in recent_assistant[-6:] if c == resp.content)
                if duplicate_count >= 2:
                    logger.warning(
                        f"Agent: stuck detected (duplicate content × {duplicate_count}), injecting escape")
                    messages.append({
                        "role": "user",
                        "content": (
                            "Ты повторяешь один и тот же ответ без прогресса. "
                            "Попробуй другой подход: вызови инструмент для проверки состояния, "
                            "или признай, что задача не может быть выполнена, и объясни почему."
                        ),
                    })
                    continue

            if not resp.tool_calls:
                # Block hallucinated "done" when zero tools ran on an action task.
                if _ACTION_REQUIRED.search(user_text) and not tools_used and iteration <= 4:
                    messages.append({
                        "role": "user",
                        "content": (
                            "СТОП. Ты ответил текстом без инструментов, но задача требует ДЕЙСТВИЙ. "
                            "Вызови инструменты сейчас. Текст в редакторе → desktop(action=edit_text, content=...). "
                            "Открыть приложение → desktop(open_app). Проверка → read_file. "
                            "Не пиши «готово/открыл/написал» пока инструмент не вернул успех."
                        ),
                    })
                    continue
                final_answer = resp.content or ""
                step = AgentStep(
                    iteration=iteration, thought=resp.content[:200], action="finish",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                self.record_step(step)
                break

            # Record assistant turn with tool calls (json-safe)
            messages.append({
                "role": "assistant",
                "content": resp.content or None,
                "tool_calls": resp.tool_calls,
            })

            # Execute all tool calls (parallel)
            exec_results = await self._execute_tool_calls(resp.tool_calls, user_id, cancel_event)

            for tc, (tool_name, params, result) in zip(resp.tool_calls, exec_results):
                obs = result.to_observation()
                observations.append(f"[{tool_name}] {obs[:500]}")
                tools_used.append(tool_name)
                if result.artifacts:
                    artifacts.extend(result.artifacts)
                if tool_name == "remember" and result.success:
                    memories_created += 1

                step = AgentStep(
                    iteration=iteration,
                    thought=resp.content[:200],
                    action="tool_call",
                    tool_name=tool_name,
                    tool_input=params,
                    observation=obs[:4000],
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                self.record_step(step)
                if step_callback:
                    try:
                        await step_callback(f"{tool_name}: {obs[:100]}")
                    except Exception:
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": obs[:2000],
                })
        else:
            final_answer = "Достигнут лимит шагов. Уточни задачу или разбей на части."

        final_answer = self._reconcile_final_answer(
            user_text, final_answer, self.steps)

        # Skip verifier unless multiple failures — saves 3-8s per request
        err_count = sum(1 for o in observations if "ERROR" in o)
        needs_verify = err_count >= 2 and len(observations) >= 3
        if needs_verify:
            verified, final_answer = await self.verifier.verify(user_text, final_answer, observations)
        else:
            verified = True

        # Hard guard: writing/open/calendar tasks without proper tools = failure (no lying).
        used = set(tools_used)
        if _CALENDAR_TASK.search(user_text) and not (used & {"gcal_add", "schedule_add", "gcal_clear_day"}):
            if not final_answer.startswith(("⏱", "⏹", "Ошибка LLM", "❌")):
                final_answer = (
                    "❌ Событие в календарь не создано — нужен gcal_add или schedule_add, "
                    "не текстовый файл на компе. Повтори команду."
                )
                verified = False
        elif (
            _WRITE_TASK.search(user_text)
            and not _CALENDAR_TASK.search(user_text)
            and not _EMAIL_TASK.search(user_text)
            and not (used & {"desktop", "write_file", "read_file"})
        ):
            if not final_answer.startswith(("⏱", "⏹", "Ошибка LLM", "❌")):
                final_answer = (
                    "❌ Не написал текст — инструменты write_file/desktop(edit_text) не вызывались. "
                    "Повтори команду, выполню через редактор с проверкой."
                )
                verified = False
        elif _OPEN_TASK.search(user_text) and not (used & {"desktop", "browser", "shell_execute"}):
            if not final_answer.startswith(("⏱", "⏹", "Ошибка LLM", "❌")):
                final_answer = (
                    "❌ Не открыл — desktop/browser не вызывались. Повтори команду."
                )
                verified = False

        self.remember_turn(user_id, "assistant", final_answer)
        await hierarchical_memory.maybe_summarize_session(user_id)

        # 📚 Self-improvement: mine this run for lessons & winning recipes (zero-LLM).
        try:
            from pds_ultimate.core.agent.lessons import lesson_book
            run_ok = err_count == 0 and not final_answer.startswith(
                ("⏱", "⏹", "Ошибка LLM"))
            lesson_book.record(user_id, message, self.steps, final_ok=run_ok)
        except Exception as exc:
            logger.debug(f"lessons record skipped: {exc}")

        return AgentResponse(
            answer=final_answer,
            steps=self.steps,
            tools_used=list(dict.fromkeys(tools_used)),
            verified=verified,
            total_iterations=len(self.steps),
            memory_entries_created=memories_created,
            plan_used=self._plan_used,
            artifacts=artifacts,
        )

    @staticmethod
    def _reconcile_final_answer(user_text: str, final_answer: str, steps: list) -> str:
        """If a send tool succeeded, don't report failure to the owner."""
        if not _MESSAGING_TASK.search(user_text):
            return final_answer

        last_send: AgentStep | None = None
        for step in reversed(steps):
            if step.tool_name in _SEND_TOOLS:
                last_send = step
                break
        if not last_send:
            return final_answer

        obs = (last_send.observation or "").strip()
        if obs.upper().startswith("ERROR"):
            return final_answer

        low_obs = obs.lower()
        if not any(k in low_obs for k in ("отправлен", "ok:", "email отправлен")):
            return final_answer

        # Strip false failure language when send actually worked
        if final_answer.startswith(("❌", "Ошибка", "ERROR")) or "не удалось" in final_answer.lower():
            target = last_send.tool_input.get("target") or last_send.tool_input.get(
                "chat") or last_send.tool_input.get("to") or "?"
            text = last_send.tool_input.get(
                "text") or last_send.tool_input.get("body") or ""
            preview = text[:120] + ("…" if len(text) > 120 else "")
            channel = {
                "telegram_send": "Telegram",
                "whatsapp_send": "WhatsApp",
                "email_send": "Email",
            }.get(last_send.tool_name or "", "канал")
            return f"✅ Отправил в {channel} → {target}" + (f": «{preview}»" if preview else "")

        return final_answer

    async def _execute_tool_calls(
        self, tool_calls: list[dict], user_id: int, cancel_event: asyncio.Event
    ) -> list[tuple[str, dict, Any]]:
        async def one(tc: dict) -> tuple[str, dict, Any]:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            params = self._parse_args(fn.get("arguments"))
            params = self._inject_user_id(tool_name, params, user_id)
            result = await self._guarded_execute(tool_name, params, user_id, cancel_event)
            return tool_name, params, result

        return list(await asyncio.gather(*(one(tc) for tc in tool_calls)))

    async def _guarded_execute(
        self, tool_name: str, params: dict, user_id: int, cancel_event: asyncio.Event
    ):
        from pds_ultimate.core.tools.base import ToolResult

        if cancel_event.is_set():
            return ToolResult(success=False, output="", error="Отменено пользователем.")

        tool = tool_registry.get(tool_name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {tool_name}")

        decision = permission_engine.check(user_id, tool_name, tool.risk)
        if not decision.allowed:
            logger.warning(
                f"Permission denied: {tool_name} for {user_id} ({decision.reason})")
            return ToolResult(success=False, output="", error=f"⛔ Доступ запрещён: {decision.reason}")

        if decision.sandboxed and tool_name in _SANDBOXABLE:
            if tool_name == "python_execute":
                import shlex
                code = params.get("code", "")
                command = f"python3 -c {shlex.quote(code)}"
            else:
                command = params.get("command", "")
            ok, out = await run_in_sandbox(command)
            return ToolResult(success=ok, output=out, error="" if ok else out)

        return await tool_registry.execute(tool_name, params)

    @staticmethod
    def _parse_args(arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if not arguments:
            return {}
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}

    _USER_SCOPED = {
        "remember", "recall", "forget", "plan_and_execute",
        "contact_save", "contact_find", "contact_list",
        "directive_add", "directive_list", "directive_remove",
        "schedule_add", "schedule_list", "schedule_today", "schedule_remove",
        "gcal_sync", "gcal_list", "gcal_add", "gcal_clear_day",
    }

    @classmethod
    def _inject_user_id(cls, tool_name: str, params: dict[str, Any], user_id: int) -> dict[str, Any]:
        if tool_name in cls._USER_SCOPED and "user_id" not in params:
            params = {**params, "user_id": user_id}
        return params

    async def run_subtask(self, user_id: int, task: str, context: str = "", *, max_steps: int = 8) -> str:
        """Run a focused, bounded sub-agent for one plan step. Excludes orchestration tools."""
        deadline = self._active_deadline or (
            time.monotonic() + config.limits.agent_wall_clock_sec)
        cancel_event = self._active_cancel or asyncio.Event()

        sub_prompt = (
            "Ты — фокусированный под-агент. Выполни РОВНО эту подзадачу и верни краткий результат.\n"
            f"Подзадача: {task}\n\nКонтекст (результаты предыдущих шагов):\n{context or '—'}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(
                user_id, query=task)},
            {"role": "user", "content": sub_prompt},
        ]
        # Subset of tools without recursion into the orchestrator
        tools_schema = [
            s for s in tool_registry.openai_schemas()
            if s.get("function", {}).get("name") != "plan_and_execute"
        ]

        for _ in range(1, max_steps + 1):
            if cancel_event.is_set() or time.monotonic() > deadline:
                return "(под-агент остановлен: время/отмена)"
            try:
                resp = await llm_client.complete(
                    messages, kind=TaskKind.STEP, tools=tools_schema, tool_choice="auto",
                    temperature=0.2, max_tokens=1024,
                )
            except Exception as exc:
                return f"(ошибка под-агента: {exc})"
            rate_limiter.record_tokens(user_id, resp.total_tokens)
            if not resp.tool_calls:
                return resp.content or ""
            messages.append(
                {"role": "assistant", "content": resp.content or None, "tool_calls": resp.tool_calls})
            exec_results = await self._execute_tool_calls(resp.tool_calls, user_id, cancel_event)
            for tc, (_, _, result) in zip(resp.tool_calls, exec_results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result.to_observation()[:6000],
                })
        return "(под-агент: достигнут лимит шагов)"


agent = EthanAgent()


# ─── Orchestration tool (decompose complex goals into a DAG of sub-agents) ─────
async def _plan_and_execute(user_id: int, goal: str) -> "Any":
    from pds_ultimate.core.agent.orchestrator import dag_executor
    from pds_ultimate.core.tools.base import ToolResult

    # Guard against deep recursion
    if agent._subtask_depth >= 1:
        result = await agent.run_subtask(user_id, goal)
        return ToolResult(success=True, output=result)

    agent._subtask_depth += 1
    agent._plan_used = True
    try:
        async def sub_runner(subtask: str, context: str) -> str:
            return await agent.run_subtask(user_id, subtask, context)

        summary, _steps = await dag_executor.execute(goal, sub_runner)
        return ToolResult(success=True, output=summary)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))
    finally:
        agent._subtask_depth = max(0, agent._subtask_depth - 1)


def register_orchestration_tool() -> None:
    from pds_ultimate.core.tools.base import ToolSpec

    tool_registry.register(
        ToolSpec(
            name="plan_and_execute",
            description=(
                "Decompose a COMPLEX multi-step goal into a plan and execute it via parallel "
                "sub-agents. Use ONLY for genuinely complex tasks (research + build + verify, "
                "multi-file projects). Returns a summary of all step results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "goal": {"type": "string", "description": "The complex goal to decompose and execute"},
                },
                "required": ["user_id", "goal"],
            },
            handler=_plan_and_execute,
            category="agent",
            risk="low",
        )
    )
