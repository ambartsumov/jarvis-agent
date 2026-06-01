"""Permission engine — multi-level tool access control (OpenManus-Max style).

Modes:
- YOLO     : full access, no interception (owner default)
- STANDARD : high-risk tools blocked for non-owner, medium allowed
- STRICT   : only low-risk tools, everything else needs explicit allow
- SANDBOX  : high-risk routed through Docker isolation (if available)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pds_ultimate.config import config, logger


class PermissionMode(str, Enum):
    YOLO = "yolo"
    STANDARD = "standard"
    STRICT = "strict"
    SANDBOX = "sandbox"


@dataclass
class PermissionDecision:
    allowed: bool
    sandboxed: bool = False
    reason: str = ""


# Risk level → which modes permit it directly
_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


class PermissionEngine:
    """Decide whether a given user may run a given tool."""

    def __init__(self) -> None:
        # Per-user mode override; default derived from owner status
        self._modes: dict[int, PermissionMode] = {}
        self._owner_id = config.telegram.owner_id

    def mode_for(self, user_id: int) -> PermissionMode:
        if user_id in self._modes:
            return self._modes[user_id]
        if user_id == self._owner_id:
            return PermissionMode.YOLO
        return PermissionMode.STRICT

    def set_mode(self, user_id: int, mode: PermissionMode) -> None:
        self._modes[user_id] = mode
        logger.info(f"Permission mode for {user_id} → {mode.value}")

    def check(self, user_id: int, tool_name: str, risk: str) -> PermissionDecision:
        mode = self.mode_for(user_id)
        risk_rank = _RISK_RANK.get(risk, 2)

        if mode == PermissionMode.YOLO:
            return PermissionDecision(allowed=True, reason="yolo")

        if mode == PermissionMode.SANDBOX:
            # low/medium run directly, high-risk goes through sandbox
            if risk_rank >= _RISK_RANK["high"]:
                return PermissionDecision(allowed=True, sandboxed=True, reason="sandboxed high-risk")
            return PermissionDecision(allowed=True, reason="sandbox low/medium")

        if mode == PermissionMode.STANDARD:
            if risk_rank >= _RISK_RANK["high"]:
                return PermissionDecision(
                    allowed=False,
                    reason=f"high-risk tool '{tool_name}' blocked in STANDARD mode",
                )
            return PermissionDecision(allowed=True, reason="standard")

        # STRICT — only low-risk
        if risk_rank <= _RISK_RANK["low"]:
            return PermissionDecision(allowed=True, reason="strict low-risk")
        return PermissionDecision(
            allowed=False,
            reason=f"tool '{tool_name}' (risk={risk}) denied in STRICT mode",
        )

    def is_owner(self, user_id: int) -> bool:
        return user_id == self._owner_id


permission_engine = PermissionEngine()
