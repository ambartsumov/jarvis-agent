"""WhatsApp MCP — Green-API (уже подключён к PDS)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PDS_ROOT = Path(os.environ.get("PDS_ULTIMATE_DIR", Path(__file__).resolve().parents[2]))
AGENT_ROOT = PDS_ROOT.parent
for p in (str(AGENT_ROOT), str(PDS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from bridge.async_loop import run_coroutine

mcp = FastMCP("pds-whatsapp")


def _run(coro):
    return run_coroutine(coro, timeout=120)


@mcp.tool()
def whatsapp_status() -> str:
    """Статус WhatsApp Green-API (авторизован ли аккаунт владельца)."""
    async def _go():
        from pds_ultimate.core.tools.channels import _ensure_whatsapp

        client = await _ensure_whatsapp()
        ok = getattr(client, "_started", False)
        authorized = False
        if ok:
            try:
                authorized = await client.is_logged_in()
            except Exception:
                authorized = ok
        return json.dumps(
            {
                "ok": ok and authorized,
                "authorized": authorized,
                "hint": "" if authorized else "Проверь WA_GREEN_API_* в .env и QR в console.green-api.com",
            },
            ensure_ascii=False,
        )

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def whatsapp_read(chat: str, limit: int = 50) -> str:
    """Прочитать WhatsApp-переписку (телефон, имя из контактов или chat_id)."""
    async def _go():
        from pds_ultimate.core.tools.channels import _wa_read

        res = await _wa_read(chat, limit=min(max(limit, 1), 200))
        return json.dumps(
            {"ok": res.success, "messages": res.output, "error": res.error or ""},
            ensure_ascii=False,
        )

    try:
        return _run(_go())
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def whatsapp_send(chat: str, text: str, reply_to: str = "") -> str:
    """Отправить WhatsApp-сообщение от лица владельца (Green-API)."""
    async def _go():
        from pds_ultimate.core.tools.channels import _wa_send

        res = await _wa_send(chat, text, reply_to=reply_to or None)
        return json.dumps(
            {"ok": res.success, "result": res.output, "error": res.error or ""},
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
