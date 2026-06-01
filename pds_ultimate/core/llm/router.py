"""Model routing — pick the cheapest capable model per task to save tokens."""

from __future__ import annotations

from enum import Enum

from pds_ultimate.config import config


class TaskKind(str, Enum):
    CHAT = "chat"          # light conversation
    STEP = "step"          # ReAct iteration (fast model — most calls)
    REASON = "reason"      # heavy reasoning
    PLAN = "plan"          # task decomposition
    VERIFY = "verify"      # answer verification
    SUMMARIZE = "summarize"
    PARSE = "parse"


class ModelRouter:
    """
    Cost-aware routing:
    - STEP / CHAT / SUMMARIZE / PARSE / VERIFY → fast model (deepseek-chat)
    - REASON / PLAN → reasoner model
    Most ReAct iterations are STEP, so the expensive reasoner is used sparingly.
    """

    def __init__(self) -> None:
        self._ds = config.deepseek

    def select(self, kind: TaskKind) -> tuple[str, str, str]:
        """Returns (provider, base_url, model)."""
        if kind in {TaskKind.REASON, TaskKind.PLAN}:
            return ("deepseek", self._ds.base_url, self._ds.model)
        return ("deepseek", self._ds.base_url, self._ds.fast_model)

    def api_key_for(self, provider: str) -> str:
        return self._ds.api_key if provider == "deepseek" else ""
