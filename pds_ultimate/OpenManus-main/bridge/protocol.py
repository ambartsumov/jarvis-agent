"""WebSocket IPC protocol between OpenClaw (TS) and OpenManus (Python)."""

from __future__ import annotations

from typing import Any, Literal

EventKind = Literal[
    "step",
    "thought",
    "tool_start",
    "tool_end",
    "final",
    "error",
    "ping",
    "pong",
]

ClientMsgType = Literal["run", "cancel", "ping"]
ServerMsgType = Literal["event", "done", "error", "pong"]


def run_request(
    *,
    req_id: str,
    message: str,
    session_id: str = "default",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "run",
        "id": req_id,
        "session_id": session_id,
        "message": message,
        "context": context or {},
    }


def event(
    *,
    req_id: str,
    kind: EventKind,
    **payload: Any,
) -> dict[str, Any]:
    return {"type": "event", "id": req_id, "event": kind, **payload}


def done(req_id: str) -> dict[str, Any]:
    return {"type": "done", "id": req_id}


def error_msg(req_id: str, message: str) -> dict[str, Any]:
    return {"type": "error", "id": req_id, "message": message}
