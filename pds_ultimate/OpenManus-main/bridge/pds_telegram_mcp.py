"""Telegram userbot MCP — читать/писать чаты через Telethon (полная история, голосовые в чатах)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from bridge.async_loop import run_coroutine

PDS_ROOT = Path(os.environ.get("PDS_ULTIMATE_DIR", Path(__file__).resolve().parents[2]))
AGENT_ROOT = PDS_ROOT.parent
for p in (str(AGENT_ROOT), str(PDS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

mcp = FastMCP("pds-telegram")
_started = False


async def _ensure_telethon():
    global _started
    from pds_ultimate.integrations.telethon_client import telethon_client

    if not getattr(telethon_client, "_started", False):
        await telethon_client.start()
    _started = getattr(telethon_client, "_started", False)
    return telethon_client


def _run(coro):
    return run_coroutine(coro, timeout=120)


@mcp.tool()
def telegram_dialogs(limit: int = 100) -> str:
    """Список Telegram-диалогов (имя, id, @username) — все чаты аккаунта владельца."""
    async def _go():
        from pds_ultimate.core.tools.channels import _tg_dialogs

        res = await _tg_dialogs(limit=min(max(limit, 1), 200))
        return json.dumps({"ok": res.success, "dialogs": res.output, "error": res.error or ""}, ensure_ascii=False)

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def telegram_read(chat: str, limit: int = 200) -> str:
    """Прочитать историю Telegram-чата (@username или chat_id). До ~500 последних сообщений."""
    async def _go():
        from pds_ultimate.core.tools.channels import _tg_read

        res = await _tg_read(chat, limit=min(max(limit, 1), 500))
        return json.dumps({"ok": res.success, "messages": res.output, "error": res.error or ""}, ensure_ascii=False)

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def telegram_send(
    target: str,
    text: str,
    reply_to: int = 0,
    file_path: str = "",
) -> str:
    """Отправить сообщение в Telegram от лица владельца (@username, chat_id, телефон)."""
    async def _go():
        from pds_ultimate.core.tools.channels import _tg_send

        res = await _tg_send(
            target,
            text,
            reply_to=reply_to or None,
            file_path=file_path,
        )
        return json.dumps({"ok": res.success, "result": res.output, "error": res.error or ""}, ensure_ascii=False)

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def telegram_status() -> str:
    """Проверить, авторизован ли Telethon userbot."""
    async def _go():
        client = await _ensure_telethon()
        ok = getattr(client, "_started", False)
        return json.dumps(
            {
                "ok": ok,
                "authorized": ok,
                "hint": "" if ok else "Запустите telethon_auth.py для авторизации userbot",
            },
            ensure_ascii=False,
        )

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
