"""WebSocket IPC server — OpenManus agent brain for OpenClaw + PDS hybrid."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from bridge.pds_context import build_pds_context, resolve_user_id
from bridge.protocol import done, error_msg, event
from bridge.streaming_manus import StreamingManus

_active: dict[str, asyncio.Task] = {}
_session_active: dict[str, str] = {}
_agent: StreamingManus | None = None
_agent_lock = asyncio.Lock()

# ── Conversational shortcut ──────────────────────────────────────────────────
_TASK_KEYWORDS = re.compile(
    r"\b(создай|сделай|напиши|найди|покажи|отправь|напомни|помоги|открой|"
    r"проверь|скачай|загрузи|запусти|переведи|составь|позвони|сохрани|"
    r"удали|измени|добавь|вычисли|посчитай|включи|выключи|установи|"
    r"create|make|write|find|show|send|remind|open|check|download|"
    r"upload|run|translate|compose|save|delete|change|add|calculate|"
    r"забронируй|купи|продай|закажи|зарегистрируй|распознай|прочитай)\b",
    re.IGNORECASE,
)

_SMALLTALK_PATTERN = re.compile(
    r"^(привет|здаров|здравствуй(те)?|хай|hello|hi|hey|добр(ое|ый)\b.*|"
    r"спасибо|благодарю|thanks|thank\s+you|ок(ей)?|ok|okay|угу|ага|"
    r"пока|бай|bye|споки|спокойной\s+ночи|как\s+дела|что\s+делаешь|"
    r"как\s+ты|кто\s+ты|что\s+ты\s+умеешь|что\s+ты\s+можешь|"
    r"что\s+умеешь|расскажи\s+о\s+себе|ты\s+кто|представься)[\s.,!?]*$",
    re.IGNORECASE,
)


def _is_chat_only(text: str) -> bool:
    """Return True if message is small-talk/greeting that needs no tool calls."""
    t = text.strip()
    if not t:
        return False
    if _SMALLTALK_PATTERN.match(t):
        return True
    # Short message with no task keywords → conversational
    if len(t) <= 80 and not _TASK_KEYWORDS.search(t) and len(t.split()) <= 10:
        return True
    return False


async def _direct_chat_response(message: str, system_extra: str = "") -> str:
    """Call LLM directly for conversational messages — no tool loop."""
    try:
        from app.llm import LLM
        llm = LLM()
        system = (
            "Ты Джарвис — умный живой ассистент. Отвечай на русском языке, "
            "коротко и по-человечески. Это обычный разговор — не задача. "
            "Никаких «задача выполнена», «готово» — просто живой ответ."
        )
        if system_extra:
            system = f"{system}\n\n{system_extra}"
        messages = [{"role": "user", "content": message}]
        reply = await llm.ask(messages, system_msgs=[{"role": "system", "content": system}])
        return reply.strip()
    except Exception as exc:
        logger.warning(f"_direct_chat_response failed: {exc}")
        return ""

_BRIDGE_PROMPT = """
[Личность]
- Ты Джарвис — умный живой ассистент, не бот-скрипт. Отвечай как умный собеседник: коротко, по делу, по-человечески.
- ВСЕ ответы пользователю ТОЛЬКО на русском языке. Внутренние рассуждения не показывай.
- user_id для memory-инструментов: {user_id}.
- В групповых чатах — отвечай только когда обращаются по имени «Джарвис».
- НЕ используй ask_human с stdin. Если нужно уточнение — спроси в конце ответа.

[КРИТИЧНО — Стиль ответов]
- На приветствия, вопросы о себе, smalltalk — ПРОСТО ОТВЕЧАЙ текстом, без инструментов.
- НИКОГДА не пиши «Задача выполнена», «готово», «всё сделано» — это не задачи, это разговор.
- terminate вызывай ТОЛЬКО после реальных действий (файл создан, письмо отправлено, код запущен).
- Для обычного общения — ответь текстом, и на этом всё (terminate не нужен).

[Telegram]
- Читать/писать — ТОЛЬКО MCP pds-telegram: telegram_dialogs, telegram_read, telegram_send, telegram_status.
- telegram_dialogs(limit=100) — все чаты (имя, id, @username).
- telegram_read(chat, limit=100) — история (до 500 сообщений).
- telegram_send(target, text) — отправка от лица владельца.
- НИКОГДА не используй bot API для личных сообщений — только pds-telegram userbot.

[WhatsApp — Green-API]
- WhatsApp УЖЕ подключён. НЕ открывай web.whatsapp.com, НЕ проси QR-код.
- MCP pds-whatsapp: whatsapp_status, whatsapp_read(chat, limit=50), whatsapp_send(chat, text).

[Email — Gmail OAuth]
- Инструмент email (НЕ MCP): send, reply, unread, inbox, search, read, thread, mark_read.
- email(action="inbox", max_results=10) — последние входящие.
- email(action="search", query="from:boss@company.com") — поиск по Gmail-запросу.
- email(action="read", message_id="...") — прочитать письмо полностью.
- email(action="thread", thread_id="...") — вся цепочка писем.
- email(action="reply", message_id="...", thread_id="...", to="...", body="...") — ответить.
- email(action="send", to="...", subject="...", body="...") — новое письмо.

[Google Calendar]
- Инструмент calendar: list(days=14), add(title, start_at, end_at, notes), clear_day(when), check.
- start_at / end_at: натуральное время «завтра 14:00», «2025-06-15 16:00».

[Управление компьютером Linux — ПОЛНЫЙ ДОСТУП]
Инструмент desktop — все действия. Судо-пароль встроен.

SHELL / ФАЙЛЫ:
- run(command=...) — команда в shell.
- run_root(command=...) — команда как root (sudo).
- read_file(path=...) — читать файл (sudo если защищён).
- write_file(path=..., content=...) — записать файл (sudo если нужно).
- find_files(pattern=*.py, root_dir=/home) — найти файлы.
- ports — список открытых портов.
- user_info — текущий пользователь, группы, uname.

ПРИЛОЖЕНИЯ:
- open_app(target=telegram|cursor|chromium) — открыть приложение.
- open_url(url=...) — открыть URL.
- open_file(path=...) — открыть ФАЙЛ в нужном приложении (xlsx→LibreOffice Calc, docx→Writer, pdf→Evince, и т.д.).
- where_am_i — что сейчас открыто (вызывай перед GUI-действиями).
- active_window — id/название активного окна.
- window_activate(target=...) — вывести окно на передний план.
- kill_app(target=...) — закрыть приложение.
- screenshot(path=...) — скриншот экрана.

МЫШЬ (xdotool — мгновенно):
- mouse_click(x=..., y=..., button=1) — клик (1=лев, 2=сред, 3=прав).
- double_click(x=..., y=...) — двойной клик.
- right_click(x=..., y=...) — правый клик.
- mouse_move(x=..., y=...) — переместить курсор.
- scroll(x=..., y=..., direction=down, amount=3) — прокрутка.
- drag_drop(x1=..., y1=..., x2=..., y2=...) — перетащить.
- mouse_pos — текущая позиция курсора.
- screen_size — разрешение экрана.

КЛАВИАТУРА (xdotool — мгновенно):
- type_text(text=..., delay=0) — напечатать текст (delay=0 = максимальная скорость).
- key_press(keys=ctrl+c) — нажать клавишу/комбо: ctrl+v, Return, F5, super, ctrl+shift+i.

ПАТТЕРН для работы в приложении:
1. where_am_i → 2. window_activate(target=...) → 3. mouse_click(x,y) / type_text(text) → 4. terminate.
Для браузера — ИСПОЛЬЗУЙ browser_use (более умный инструмент с DOM).

[КРИТИЧНО — ТЫ УМЕЕШЬ УПРАВЛЯТЬ КОМПЬЮТЕРОМ]
- ТЫ МОЖЕШЬ кликать мышкой, нажимать клавиши, делать скриншоты через инструмент `desktop`.
- ТЫ МОЖЕШЬ управлять браузером через `browser_use` — он открывает страницы, кликает кнопки, заполняет поля.
- НИКОГДА не говори "я не могу управлять браузером/компьютером" — ты МОЖЕШЬ.
- Если нужно найти что-то в браузере: используй browser_use(action="navigate", url="https://google.com/search?q=...") или open_url, затем browser_use для взаимодействия.
- Если нужно открыть приложение: desktop(action="open_app", target="chromium") или desktop(action="run", command="chromium &").
- Если нужно кликнуть по экрану: сначала desktop(action="screenshot") чтобы увидеть экран, потом desktop(action="mouse_click", x=..., y=...).

[Память — MCP pds-memory]
- remember(content, user_id, importance=0.8) — запомнить важный факт навсегда.
- remember_episode(summary, user_id) — сохранить итог разговора/задачи.
- recall(query, user_id, limit=8) — вспомнить релевантное (гибридный BM25×0.4 + вектор×0.3 + рейтинг).
- recall_recent(user_id, hours=24) — что было сегодня/вчера (эпизодическая память).
- recall_about(entity, user_id) — всё что известно о человеке/проекте.
- vector_search(query, user_id, limit=10) — СЕМАНТИЧЕСКИЙ поиск TF-IDF cosine; находит идеи без точных слов.
- forget(query, user_id) — забыть устаревшее.
- consolidate_memory(user_id) — убрать дубликаты, применить затухание (раз в день).
- recall_lessons(query, user_id) — уроки из прошлых задач.
- save_lesson(lesson, user_id, outcome=success|failure) — сохранить урок.

[Knowledge Graph — граф знаний о людях, проектах, местах]
MCP pds-memory: kg_add_entity, kg_add_relation, kg_profile, kg_search, kg_list_important.
- kg_add_entity(name, kind, user_id, attributes='{}') — добавить/обновить сущность.
  kind: person | place | project | topic | company | event
- kg_add_relation(from_name, to_name, relation, user_id, context) — добавить связь.
  relation: knows | works_at | manages | member_of | related_to | mentioned_with | owns | located_in
- kg_profile(entity, user_id) — полный профиль сущности: атрибуты + все связи.
- kg_search(query, user_id) — поиск сущностей по имени.
- kg_list_important(user_id) — список важнейших людей/проектов.

[OCR — компьютерное зрение]
- desktop(action="screen_ocr") — прочитать ВЕСЬ текст с экрана через Tesseract (русский+английский).
  Опционально: path="/path/to/screenshot.png"
  Используй для: чтения закрытых текстов, проверки что отображается, скопировать текст с экрана.

[Макросы — автоматизация последовательностей]
- desktop(action="macro_record", name="my_macro", steps=[...]) — сохранить последовательность действий.
  steps: [{action:mouse_click, x:100, y:200, delay_ms:500}, {action:type_text, text:"hello"}, ...]
- desktop(action="macro_replay", name="my_macro", speed=1.0) — повторить сохранённый макрос.
  speed: 1.0=нормально, 2.0=вдвое быстрее, 0.5=медленнее.

[Скорость — ОБЯЗАТЕЛЬНО]
- Проверить ответ кого-то → telegram_read или whatsapp_read с limit=50, не больше.
- Максимум 2–3 инструмента на реальную задачу.
- После реального действия — одна короткая фраза с результатом, потом terminate(status=success).
- НЕ повторяй одно и то же разными формулировками.
"""


async def _get_agent() -> StreamingManus:
    global _agent
    if _agent is None:
        _agent = await StreamingManus.create()
        logger.info("OpenManus bridge: agent warmed (MCP connected, all tools)")
    return _agent


def _cancel_session_run(session_id: str, except_req: str = "") -> None:
    old_req = _session_active.get(session_id)
    if not old_req or old_req == except_req:
        return
    task = _active.get(old_req)
    if task and not task.done():
        task.cancel()
        logger.info(
            f"OpenManus bridge: cancelled stale run session={session_id} req={old_req}")


async def _start_stt_server() -> None:
    sock = Path(os.environ.get("PDS_STT_SOCKET",
                f"{os.environ.get('PDS_ULTIMATE_DIR', '')}/data/stt.sock"))
    if sock.exists():
        return
    script = Path(__file__).resolve().parents[2] / "scripts" / "stt_server.py"
    if not script.exists():
        script = Path(os.environ.get("PDS_ULTIMATE_DIR", "")) / \
            "scripts" / "stt_server.py"
    if not script.exists():
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(30):
            if sock.exists():
                logger.info(f"OpenManus bridge: STT server ready ({sock})")
                return
            await asyncio.sleep(0.5)
        logger.warning(
            f"OpenManus bridge: STT server slow start pid={proc.pid}")
    except Exception as exc:
        logger.warning(f"OpenManus bridge: STT server not started: {exc}")


async def _prewarm_agent() -> None:
    uid = int(
        os.environ.get("PDS_DEFAULT_USER_ID")
        or os.environ.get("TG_OWNER_ID")
        or "0"
    )
    if uid > 0:
        os.environ["PDS_DEFAULT_USER_ID"] = str(uid)
    await _get_agent()
    logger.info(f"OpenManus bridge: pre-warm ok (user_id={uid})")


async def _run_manus(req_id: str, payload: dict[str, Any], send_json) -> None:
    message = (payload.get("message") or "").strip()
    session_id = str(payload.get("session_id") or "default")
    context = payload.get("context") or {}

    if not message:
        await send_json(error_msg(req_id, "Empty message"))
        return

    user_id = resolve_user_id(context, session_id)
    if user_id > 0:
        context["user_id"] = user_id
        os.environ["PDS_DEFAULT_USER_ID"] = str(user_id)

    # ── Conversational shortcut: bypass full agent for simple chat ────────────
    if _is_chat_only(message):
        logger.info(
            f"OpenManus bridge: chat-only shortcut for {message[:40]!r}")
        extra = build_pds_context(session_id, message, context)
        answer = await _direct_chat_response(message, extra)
        if answer:
            await send_json(event(req_id=req_id, kind="final", content=answer))
            return  # caller (_task_wrapper) sends done() in finally
        # If direct call failed, fall through to full agent below

    extra = build_pds_context(session_id, message, context)

    async with _agent_lock:
        agent = await _get_agent()
        agent.prepare_for_run()
        if not getattr(agent, "_base_system_prompt", ""):
            # type: ignore[attr-defined]
            agent._base_system_prompt = agent.system_prompt

        bridge_ctx = _BRIDGE_PROMPT.format(user_id=user_id or "unknown")
        agent.system_prompt = f"{agent._base_system_prompt}\n\n{bridge_ctx}"
        if extra:
            agent.system_prompt = f"{agent.system_prompt}\n\n{extra}"

        async def sink(kind: str, data: dict[str, Any]) -> None:
            await send_json(event(req_id=req_id, kind=kind, **data))

        agent.bind_stream(req_id, sink)

        try:
            await agent.run(message)
        except asyncio.CancelledError:
            await send_json(event(req_id=req_id, kind="error", message="Cancelled"))
            raise
        except Exception as exc:
            logger.exception(f"Manus run failed: {exc}")
            await send_json(event(req_id=req_id, kind="error", message=str(exc)))
        finally:
            try:
                from app.sandbox.client import SANDBOX_CLIENT

                await SANDBOX_CLIENT.cleanup()
            except Exception:
                pass
            base = getattr(agent, "_base_system_prompt", agent.system_prompt)
            agent.system_prompt = base
            # Auto-save episode: store task summary in episodic memory
            if user_id > 0 and len(message) > 15:
                try:
                    sys.path.insert(0, os.environ.get("PDS_ULTIMATE_DIR", ""))
                    from pds_ultimate.core.memory.hierarchy import hierarchical_memory
                    summary = f"Задача: {message[:300]}"
                    hierarchical_memory.store.remember(
                        user_id, summary, layer="episodic",
                        key="auto_episode", importance=0.6
                    )
                except Exception:
                    pass


async def manus_handler(websocket) -> None:
    """Handle one persistent WebSocket connection (multiplexed runs by id)."""
    peer = getattr(websocket, "remote_address", "?")
    logger.info(f"OpenManus bridge: client connected {peer}")

    async def send_json(data: dict[str, Any]) -> None:
        await websocket.send(json.dumps(data, ensure_ascii=False))

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_json(error_msg("", "Invalid JSON"))
                continue

            mtype = msg.get("type")

            if mtype == "ping":
                await send_json({"type": "pong", "id": msg.get("id", "")})
                continue

            if mtype == "cancel":
                req_id = str(msg.get("id") or "")
                task = _active.pop(req_id, None)
                if task and not task.done():
                    task.cancel()
                await send_json(done(req_id))
                continue

            if mtype != "run":
                await send_json(error_msg(str(msg.get("id") or ""), f"Unknown type: {mtype}"))
                continue

            req_id = str(msg.get("id") or uuid.uuid4())
            session_id = str(msg.get("session_id") or "default")
            _session_active[session_id] = req_id

            old = _active.pop(req_id, None)
            if old and not old.done():
                old.cancel()

            async def _task_wrapper(rid: str = req_id, body: dict = msg) -> None:
                sid = str(body.get("session_id") or "default")
                try:
                    await _run_manus(rid, body, send_json)
                finally:
                    _active.pop(rid, None)
                    if _session_active.get(sid) == rid:
                        _session_active.pop(sid, None)
                    await send_json(done(rid))

            _active[req_id] = asyncio.create_task(_task_wrapper())

    except Exception as exc:
        logger.info(f"OpenManus bridge: disconnected ({exc})")
    finally:
        for task in list(_active.values()):
            if not task.done():
                task.cancel()


async def _serve() -> None:
    import websockets
    from app.integrations.desktop_linux import bootstrap_gui_env

    bootstrap_gui_env()
    os.environ.setdefault("PDS_BRIDGE_MODE", "1")

    # Ensure MCP subprocesses and imports see venv + project roots.
    pds_root = os.environ.get("PDS_ULTIMATE_DIR", "")
    if pds_root:
        site = f"{pds_root}/.venv/lib/python3.12/site-packages"
        parts = [site, os.path.dirname(pds_root), f"{pds_root}/OpenManus-main"]
        existing = os.environ.get("PYTHONPATH", "")
        merged = ":".join(
            [p for p in parts + ([existing] if existing else []) if p])
        os.environ["PYTHONPATH"] = merged

    await _prewarm_agent()
    await _start_stt_server()

    # Start background scheduler (daily memory maintenance, morning digest)
    try:
        owner_id = int(os.environ.get("PDS_DEFAULT_USER_ID", "0") or 0)
        if owner_id:
            from bridge.scheduler import start_scheduler
            await start_scheduler(owner_id)
    except Exception as _exc:
        logger.warning(f"Scheduler startup skipped: {_exc}")

    host = os.environ.get("MANUS_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("MANUS_BRIDGE_PORT", "8765"))
    logger.info(f"OpenManus bridge WS: ws://{host}:{port}/manus")
    async with websockets.serve(
        manus_handler, host, port, ping_interval=60, ping_timeout=300
    ):
        await asyncio.Future()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
