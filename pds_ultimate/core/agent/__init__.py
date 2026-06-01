from __future__ import annotations

import json
import os
import re

__all__ = ["EthanAgent", "agent", "_clean_json_from_response"]

_agent_impl = None


def _clean_json_from_response(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            action = data.get("action") or {}
            if isinstance(action, dict):
                return action.get("answer") or data.get("thought") or text
            return data.get("answer") or data.get("thought") or text
        except json.JSONDecodeError:
            pass
    match = re.search(r'"answer"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    return text


def _get_agent():
    global _agent_impl
    if _agent_impl is None:
        if os.environ.get("PDS_USE_ETHAN", "").lower() in ("1", "true", "yes"):
            from pds_ultimate.core.agent.ethan import agent as impl
        else:
            from pds_ultimate.bridge.hybrid_agent import agent as impl
        _agent_impl = impl
    return _agent_impl


class _LazyAgent:
    """Defer hybrid/ethan choice until first use (avoids circular imports)."""

    def __getattr__(self, name: str):
        return getattr(_get_agent(), name)


agent = _LazyAgent()


def __getattr__(name: str):
    if name == "EthanAgent":
        return type(_get_agent())
    raise AttributeError(name)
