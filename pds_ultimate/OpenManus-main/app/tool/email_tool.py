"""Gmail tool — send/read/search/reply (Manus orchestration)."""

from __future__ import annotations

from app.integrations.gmail_client import gmail
from app.tool.base import BaseTool, ToolResult

_EMAIL_DESC = """Gmail for the owner (OAuth2). For Telegram/WhatsApp use OpenClaw channels — not this tool.

Actions:
- unread: list unread emails (max_results=5)
- inbox: list inbox emails, newest first (max_results=10)
- search: search with Gmail query — from:, subject:, after:2024/1/1, etc. (query=..., max_results=10)
- read: read full email body by id (message_id=...)
- thread: read full email thread/chain by thread_id (thread_id=...)
- send: send new email (to=..., subject=..., body=...)
- reply: reply to email (message_id=..., thread_id=..., to=..., subject=..., body=...)
- mark_read: mark email as read (message_id=...)
- check: verify Gmail OAuth is ready
"""


class EmailTool(BaseTool):
    name: str = "email"
    description: str = _EMAIL_DESC
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "reply", "unread", "inbox", "search", "read", "thread", "mark_read", "check"],
            },
            "to": {"type": "string", "description": "Recipient email"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "query": {"type": "string", "description": "Gmail search query"},
            "message_id": {"type": "string", "description": "Gmail message id"},
            "thread_id": {"type": "string", "description": "Gmail thread id"},
            "max_results": {"type": "integer", "default": 10},
        },
        "required": ["action"],
    }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        action = action.lower().strip()

        if action == "check":
            result = await gmail.list_unread(max_results=1)
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response("OK: Gmail ready")

        if action == "send":
            to = kwargs.get("to", "").strip()
            body = kwargs.get("body", "").strip()
            if not to or not body:
                return self.fail_response("to and body required")
            result = await gmail.send(to, kwargs.get("subject") or "(no subject)", body)
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "reply":
            message_id = kwargs.get("message_id", "").strip()
            to = kwargs.get("to", "").strip()
            body = kwargs.get("body", "").strip()
            if not message_id or not to or not body:
                return self.fail_response("message_id, to, and body required")
            result = await gmail.reply(
                message_id, to,
                kwargs.get("subject") or "",
                body,
                thread_id=kwargs.get("thread_id") or "",
            )
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "unread":
            result = await gmail.list_unread(max_results=int(kwargs.get("max_results") or 5))
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "inbox":
            result = await gmail.list_inbox(max_results=int(kwargs.get("max_results") or 10))
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "search":
            query = kwargs.get("query", "").strip()
            if not query:
                return self.fail_response("query required for search")
            result = await gmail.search(query, max_results=int(kwargs.get("max_results") or 10))
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "read":
            mid = kwargs.get("message_id", "").strip()
            if not mid:
                return self.fail_response("message_id required")
            result = await gmail.read(mid)
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "thread":
            tid = kwargs.get("thread_id", "").strip()
            if not tid:
                return self.fail_response("thread_id required")
            result = await gmail.read_thread(tid)
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        if action == "mark_read":
            mid = kwargs.get("message_id", "").strip()
            if not mid:
                return self.fail_response("message_id required")
            result = await gmail.mark_read(mid)
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        return self.fail_response(f"unknown action: {action}")
