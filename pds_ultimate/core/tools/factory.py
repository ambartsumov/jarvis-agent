"""Dynamic tool factory — the agent writes & registers its own tools at runtime (Manus-style).

If a capability is missing, the agent calls `create_tool` with Python code defining an
async `run(**kwargs)` function. The tool is compiled, registered, persisted to disk, and
immediately available. This is what makes the agent never need to refuse a task.

Security: `create_tool` and the dynamic tools it produces are risk="high", so the
permission engine restricts them to the owner (full power, no limits). Non-owners can't
create or execute them.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import Any

from pds_ultimate.config import DATA_DIR, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

DYNAMIC_DIR = DATA_DIR / "dynamic_tools"
DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)

# Broken duplicates of built-in channel tools — never load (they confuse the agent).
_DYNAMIC_BLOCKLIST = frozenset({
    "telegram_send_message",
    "send_gmail_oauth",
    "send_email_smtp",
})


def _wrap_run_result(result: Any) -> ToolResult:
    if isinstance(result, ToolResult):
        return result
    text = str(result).strip()
    low = text.lower()
    if (
        low.startswith(("❌", "ошибка", "error:", "error ", "fail"))
        or " tracebac" in low
        or "exception" in low[:80]
    ):
        return ToolResult(success=False, output="", error=text)
    return ToolResult(success=True, output=text)


def _build_namespace() -> dict[str, Any]:
    """Rich execution namespace — owner gets full power (no artificial limits)."""
    import base64
    import datetime
    import hashlib
    import math
    import os
    import random
    import re
    import subprocess
    import time
    from urllib.parse import quote_plus, urlencode

    import httpx

    ns: dict[str, Any] = {
        "__builtins__": __builtins__,
        "asyncio": asyncio,
        "httpx": httpx,
        "json": json,
        "os": os,
        "re": re,
        "math": math,
        "time": time,
        "random": random,
        "base64": base64,
        "hashlib": hashlib,
        "datetime": datetime,
        "subprocess": subprocess,
        "Path": Path,
        "quote_plus": quote_plus,
        "urlencode": urlencode,
        "ToolResult": ToolResult,
        "logger": logger,
    }
    return ns


def _compile_handler(name: str, code: str):
    """Compile user code and return its async `run` callable wrapped as a tool handler."""
    ns = _build_namespace()
    compiled = compile(textwrap.dedent(code), f"<dynamic_tool:{name}>", "exec")
    exec(compiled, ns)  # noqa: S102 — intentional: owner-authored, gated by permissions
    run_fn = ns.get("run")
    if run_fn is None:
        raise ValueError("Код должен определять функцию `async def run(**kwargs)`")

    async def handler(**params: Any) -> ToolResult:
        try:
            if asyncio.iscoroutinefunction(run_fn):
                result = await run_fn(**params)
            else:
                result = run_fn(**params)
            return _wrap_run_result(result)
        except Exception as exc:
            return ToolResult(success=False, output="", error=f"{type(exc).__name__}: {exc}")

    return handler


async def create_dynamic_tool(
    name: str,
    description: str,
    parameters: Any,
    code: str,
    *,
    persist: bool = True,
) -> ToolResult:
    name = name.strip().replace(" ", "_")
    if not name.isidentifier():
        return ToolResult(success=False, output="", error=f"Недопустимое имя инструмента: {name}")

    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters) if parameters.strip() else {}
        except json.JSONDecodeError:
            parameters = {}
    if not isinstance(parameters, dict) or "type" not in parameters:
        parameters = {"type": "object", "properties": parameters if isinstance(parameters, dict) else {}}

    try:
        handler = _compile_handler(name, code)
    except Exception as exc:
        return ToolResult(success=False, output="", error=f"Ошибка компиляции инструмента: {exc}")

    tool_registry.register(
        ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            category="dynamic",
            risk="high",
        )
    )

    if persist:
        try:
            (DYNAMIC_DIR / f"{name}.json").write_text(
                json.dumps(
                    {"name": name, "description": description, "parameters": parameters, "code": code},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Не удалось сохранить инструмент {name}: {exc}")

    logger.info(f"🛠️ Создан динамический инструмент: {name}")
    return ToolResult(
        success=True,
        output=f"Инструмент '{name}' создан и готов к вызову. Можешь сразу его использовать.",
    )


def load_dynamic_tools() -> int:
    """Re-register all persisted dynamic tools on startup."""
    count = 0
    for path in DYNAMIC_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("name", path.stem)
            if name in _DYNAMIC_BLOCKLIST:
                logger.warning(f"Пропуск сломанного dynamic tool: {name}")
                continue
            handler = _compile_handler(data["name"], data["code"])
            tool_registry.register(
                ToolSpec(
                    name=data["name"],
                    description=data["description"],
                    parameters=data["parameters"],
                    handler=handler,
                    category="dynamic",
                    risk="high",
                )
            )
            count += 1
        except Exception as exc:
            logger.warning(f"Не удалось загрузить инструмент {path.name}: {exc}")
    if count:
        logger.info(f"🛠️ Загружено {count} динамических инструментов")
    return count


def register_factory_tool() -> None:
    async def _create_tool(name: str, description: str, code: str, parameters: Any = None) -> ToolResult:
        return await create_dynamic_tool(name, description, parameters or {}, code)

    tool_registry.register(
        ToolSpec(
            name="create_tool",
            description=(
                "Создай НОВЫЙ инструмент для себя, если нужной возможности ещё нет. "
                "Передай Python-код, определяющий 'async def run(**kwargs)', который выполняет задачу "
                "и возвращает строку результата. Доступны: httpx, asyncio, os, subprocess, json, re, "
                "Path и др. После создания СРАЗУ вызови новый инструмент по его имени. "
                "Так ты можешь сделать абсолютно всё, даже если готового инструмента нет."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя инструмента (валидный идентификатор)"},
                    "description": {"type": "string", "description": "Что инструмент делает"},
                    "code": {
                        "type": "string",
                        "description": "Python-код с 'async def run(**kwargs): ... return result'",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "JSON-schema параметров инструмента (OpenAI tools формат)",
                    },
                },
                "required": ["name", "description", "code"],
            },
            handler=_create_tool,
            category="meta",
            risk="high",
        )
    )
    logger.info("🛠️ Registered meta-tool: create_tool")
