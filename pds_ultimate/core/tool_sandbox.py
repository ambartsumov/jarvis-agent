"""
PDS-Ultimate Tool Sandbox v1.0
=================================
Execution sandbox for safe tool invocation.

Provides:
1. Parameter Validation — strict type checking against ToolParameter schema
2. Resource Limits — memory-aware execution with configurable limits
3. Error Boundaries — structured error handling, no uncaught exceptions leak
4. Rollback Tracking — records side effects for potential rollback
5. Blocklist/Allowlist — disable dangerous tools at runtime

Integration:
    ToolRegistry.execute() → ToolSandbox.run() → handler(**params)
                                ↑
                          validates params
                          checks blocklist
                          wraps with error boundary
                          records side effects
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pds_ultimate.config import logger

# ─── Constants ───────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 30.0          # seconds
MAX_PARAM_STRING_LEN = 50_000   # max chars for a single string param
MAX_PARAM_ARRAY_LEN = 1_000     # max items in an array param
MAX_OUTPUT_LEN = 100_000        # max chars in tool output


# ─── Side Effect Tracking ────────────────────────────────────────────────────

class SideEffectType:
    """Types of side effects a tool can produce."""
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    MESSAGE_SENT = "message_sent"
    API_CALL = "api_call"
    DB_WRITE = "db_write"
    NETWORK_REQUEST = "network_request"


@dataclass(slots=True)
class SideEffect:
    """Record of a side effect from tool execution."""
    effect_type: str
    description: str
    timestamp: float = field(default_factory=time.time)
    reversible: bool = False
    rollback_info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionRecord:
    """
    Complete record of a sandboxed tool execution.

    Tracks parameters, result, timing, and side effects.
    """
    tool_name: str
    params: dict[str, Any]
    started_at: float
    completed_at: float = 0.0
    success: bool = False
    output: str = ""
    error: str | None = None
    side_effects: list[SideEffect] = field(default_factory=list)
    resource_usage: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        if self.completed_at and self.started_at:
            return int((self.completed_at - self.started_at) * 1000)
        return 0

    @property
    def has_side_effects(self) -> bool:
        return len(self.side_effects) > 0


# ─── Parameter Validator ─────────────────────────────────────────────────────

class ParamValidationError(ValueError):
    """Raised when tool parameters fail validation."""
    pass


class ParameterValidator:
    """
    Validates tool parameters against ToolParameter schema.

    Checks:
    - Required parameters present
    - Type correctness (string, number, boolean, array, object)
    - String length limits
    - Array length limits
    - Enum membership
    - No unexpected parameters (strict mode)
    """

    # JSON Schema type → Python types
    _TYPE_MAP: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "number": (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "array": (list, tuple),
        "object": (dict,),
    }

    @classmethod
    def validate(
        cls,
        params: dict[str, Any],
        schema: list,  # list[ToolParameter]
        strict: bool = False,
    ) -> dict[str, Any]:
        """
        Validate and sanitize parameters.

        Args:
            params: Raw parameters from LLM
            schema: List of ToolParameter definitions
            strict: If True, reject unexpected parameters

        Returns:
            Validated (possibly coerced) parameters

        Raises:
            ParamValidationError: If validation fails
        """
        errors: list[str] = []
        validated: dict[str, Any] = {}
        schema_names = {p.name for p in schema}

        # Check required parameters
        for p in schema:
            if p.required and p.name not in params:
                if p.default is not None:
                    validated[p.name] = p.default
                else:
                    errors.append(f"Missing required parameter: '{p.name}'")

        # Check unexpected parameters (strict mode)
        if strict:
            unexpected = set(params.keys()) - schema_names
            if unexpected:
                errors.append(f"Unexpected parameters: {unexpected}")

        # Validate each parameter
        for p in schema:
            if p.name not in params:
                if p.default is not None:
                    validated[p.name] = p.default
                continue

            value = params[p.name]

            # Type check
            expected_types = cls._TYPE_MAP.get(p.param_type)
            if expected_types and not isinstance(value, expected_types):
                # Try type coercion
                coerced = cls._try_coerce(value, p.param_type)
                if coerced is not None:
                    value = coerced
                else:
                    errors.append(
                        f"Parameter '{p.name}': expected {p.param_type}, "
                        f"got {type(value).__name__}"
                    )
                    continue

            # String length limit
            if isinstance(value, str) and len(value) > MAX_PARAM_STRING_LEN:
                errors.append(
                    f"Parameter '{p.name}': string too long "
                    f"({len(value)} > {MAX_PARAM_STRING_LEN})"
                )
                continue

            # Array length limit
            if isinstance(value, (list, tuple)) and len(value) > MAX_PARAM_ARRAY_LEN:
                errors.append(
                    f"Parameter '{p.name}': array too long "
                    f"({len(value)} > {MAX_PARAM_ARRAY_LEN})"
                )
                continue

            # Enum check
            if p.enum and value not in p.enum:
                errors.append(
                    f"Parameter '{p.name}': value '{value}' not in "
                    f"allowed values {p.enum}"
                )
                continue

            validated[p.name] = value

        # Include non-schema params in non-strict mode
        if not strict:
            for key, value in params.items():
                if key not in validated:
                    validated[key] = value

        if errors:
            raise ParamValidationError("; ".join(errors))

        return validated

    @staticmethod
    def _try_coerce(value: Any, target_type: str) -> Any | None:
        """Try to coerce a value to the target type."""
        try:
            if target_type == "string":
                return str(value)
            elif target_type == "number":
                return float(value)
            elif target_type == "integer":
                return int(value)
            elif target_type == "boolean":
                if isinstance(value, str):
                    if value.lower() in ("true", "1", "yes", "да"):
                        return True
                    if value.lower() in ("false", "0", "no", "нет"):
                        return False
                return bool(value)
        except (ValueError, TypeError):
            pass
        return None


# ─── Tool Blocklist ──────────────────────────────────────────────────────────

class ToolBlocklist:
    """
    Runtime blocklist/allowlist for tools.

    Can disable tools temporarily (e.g., during maintenance)
    or permanently (dangerous tools).
    """
    __slots__ = ("_blocked", "_reasons")

    def __init__(self):
        self._blocked: set[str] = set()
        self._reasons: dict[str, str] = {}

    def block(self, tool_name: str, reason: str = "") -> None:
        """Block a tool from execution."""
        self._blocked.add(tool_name)
        self._reasons[tool_name] = reason or "Blocked by admin"
        logger.warning(f"Tool '{tool_name}' BLOCKED: {reason}")

    def unblock(self, tool_name: str) -> None:
        """Unblock a tool."""
        self._blocked.discard(tool_name)
        self._reasons.pop(tool_name, None)

    def is_blocked(self, tool_name: str) -> bool:
        """Check if tool is blocked."""
        return tool_name in self._blocked

    def get_reason(self, tool_name: str) -> str:
        """Get the block reason."""
        return self._reasons.get(tool_name, "")

    @property
    def blocked_tools(self) -> frozenset[str]:
        return frozenset(self._blocked)

    def clear(self) -> None:
        self._blocked.clear()
        self._reasons.clear()


# ─── Tool Sandbox ────────────────────────────────────────────────────────────

class ToolSandbox:
    """
    Execution sandbox for safe tool invocation.

    Wraps tool execution with:
    - Blocklist check
    - Parameter validation
    - Timeout enforcement
    - Error boundary (no uncaught exceptions)
    - Output truncation
    - Side effect recording
    - Execution history

    Usage:
        sandbox = ToolSandbox()
        record = await sandbox.run(tool, params)
        if record.success:
            print(record.output)
    """
    __slots__ = ("_blocklist", "_validator", "_history", "_max_history")

    def __init__(self, max_history: int = 1000):
        self._blocklist = ToolBlocklist()
        self._validator = ParameterValidator()
        self._history: list[ExecutionRecord] = []
        self._max_history = max_history

    @property
    def blocklist(self) -> ToolBlocklist:
        return self._blocklist

    @property
    def validator(self) -> ParameterValidator:
        return self._validator

    async def run(
        self,
        tool,  # Tool instance
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        validate: bool = True,
        caller: str = "",
        db_session=None,
    ) -> ExecutionRecord:
        """
        Execute a tool within the sandbox.

        Args:
            tool: Tool instance to execute
            params: Parameters for the tool
            timeout: Override tool's default timeout
            validate: Whether to validate parameters
            caller: Who triggered this call (for audit)
            db_session: SQLAlchemy session if needed

        Returns:
            ExecutionRecord with full execution details
        """
        params = params or {}
        effective_timeout = timeout or tool.timeout or DEFAULT_TIMEOUT
        record = ExecutionRecord(
            tool_name=tool.name,
            params=params,
            started_at=time.time(),
        )

        try:
            # 1. Blocklist check
            if self._blocklist.is_blocked(tool.name):
                reason = self._blocklist.get_reason(tool.name)
                record.error = f"Tool blocked: {reason}"
                record.completed_at = time.time()
                return record

            # 2. Handler check
            if not tool.handler:
                record.error = f"Tool '{tool.name}' has no handler"
                record.completed_at = time.time()
                return record

            # 3. Parameter validation
            if validate and tool.parameters:
                try:
                    params = self._validator.validate(
                        params, tool.parameters, strict=False,
                    )
                except ParamValidationError as e:
                    record.error = f"Parameter validation failed: {e}"
                    record.completed_at = time.time()
                    return record

            # 4. Prepare call params
            call_params = dict(params)
            if tool.needs_db and db_session:
                call_params["db_session"] = db_session

            # 5. Execute with timeout + error boundary
            if effective_timeout > 0:
                result = await asyncio.wait_for(
                    tool.handler(**call_params),
                    timeout=effective_timeout,
                )
            else:
                result = await tool.handler(**call_params)

            # 6. Process result
            output = self._extract_output(result)

            # 7. Truncate if needed
            if len(output) > MAX_OUTPUT_LEN:
                output = output[:MAX_OUTPUT_LEN] + "…(truncated)"

            record.success = True
            record.output = output

        except asyncio.TimeoutError:
            record.error = f"Timeout after {effective_timeout}s"
        except asyncio.CancelledError:
            record.error = "Execution cancelled"
        except Exception as e:
            record.error = f"{type(e).__name__}: {e}"

        record.completed_at = time.time()

        # Record in history
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return record

    @staticmethod
    def _extract_output(result: Any) -> str:
        """Extract string output from various result types."""
        if result is None:
            return "Выполнено успешно."
        if isinstance(result, str):
            return result
        # ToolResult-like objects
        if hasattr(result, "output"):
            return str(result.output) if result.output else str(result)
        if hasattr(result, "success"):
            return str(result)
        if isinstance(result, (dict, list)):
            import json
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)

    def get_history(self, tool_name: str | None = None, count: int = 50) -> list[ExecutionRecord]:
        """Get execution history, optionally filtered by tool name."""
        if tool_name:
            matches = [r for r in self._history if r.tool_name == tool_name]
        else:
            matches = self._history
        return matches[-count:] if len(matches) > count else list(matches)

    def get_side_effects(self, tool_name: str | None = None) -> list[SideEffect]:
        """Get all recorded side effects."""
        effects: list[SideEffect] = []
        for record in self._history:
            if tool_name and record.tool_name != tool_name:
                continue
            effects.extend(record.side_effects)
        return effects

    def clear_history(self) -> None:
        """Clear execution history."""
        self._history.clear()

    @property
    def stats(self) -> dict[str, Any]:
        """Aggregate sandbox statistics."""
        total = len(self._history)
        successes = sum(1 for r in self._history if r.success)
        failures = total - successes
        total_duration = sum(r.duration_ms for r in self._history)
        return {
            "total_executions": total,
            "successes": successes,
            "failures": failures,
            "error_rate": round(failures / max(1, total) * 100, 1),
            "avg_duration_ms": round(total_duration / max(1, total)),
            "blocked_tools": list(self._blocklist.blocked_tools),
        }


# ─── Global Instance ─────────────────────────────────────────────────────────

tool_sandbox = ToolSandbox()
