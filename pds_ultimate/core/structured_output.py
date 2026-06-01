"""
PDS-Ultimate Structured Output
=================================
Step 13: Pydantic-validated LLM responses with retry logic.

PROBLEM:
    LLM returns invalid JSON → agent crashes with json.JSONDecodeError.
    Current fix: catch exception → return fallback. This loses data.

SOLUTION:
    1. Define expected response as Pydantic model
    2. Ask LLM with JSON mode
    3. Parse response into Pydantic model
    4. On validation error → re-prompt with error details
    5. On max retries → return fallback with error info

USAGE:
    schema = ResponseSchema(
        name="plan",
        fields={"steps": "list of step descriptions", "confidence": "0.0-1.0"},
        required=["steps"],
    )
    result = await structured_llm.generate(prompt, schema)
    # result.success → True/False
    # result.data → validated dict
    # result.raw → original LLM response
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FieldSpec:
    """Specification for a single field in the response."""
    name: str
    type: str = "string"          # string, number, boolean, array, object
    description: str = ""
    required: bool = True
    default: Any = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema property."""
        type_map = {
            "string": "string",
            "str": "string",
            "number": "number",
            "int": "integer",
            "integer": "integer",
            "float": "number",
            "bool": "boolean",
            "boolean": "boolean",
            "array": "array",
            "list": "array",
            "object": "object",
            "dict": "object",
        }
        schema: dict[str, Any] = {
            "type": type_map.get(self.type, "string"),
        }
        if self.description:
            schema["description"] = self.description
        return schema


@dataclass
class ResponseSchema:
    """
    Schema for expected LLM response.

    Defines the structure of the JSON that LLM should return.
    """
    name: str
    fields: dict[str, str | FieldSpec] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self):
        # Normalize string fields to FieldSpec
        normalized: dict[str, FieldSpec] = {}
        for key, value in self.fields.items():
            if isinstance(value, str):
                normalized[key] = FieldSpec(
                    name=key,
                    description=value,
                )
            else:
                normalized[key] = value
        self.fields = normalized

        # If no required specified, all fields are required
        if not self.required:
            self.required = list(self.fields.keys())

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema for LLM prompt."""
        properties = {
            name: spec.to_json_schema()
            for name, spec in self.fields.items()
        }
        return {
            "type": "object",
            "required": self.required,
            "properties": properties,
        }

    def to_prompt(self) -> str:
        """Generate a prompt instruction for the LLM."""
        schema = self.to_json_schema()
        schema_str = json.dumps(schema, indent=2, ensure_ascii=False)
        return (
            f"Верни ответ СТРОГО в JSON формате по этой схеме:\n"
            f"```json\n{schema_str}\n```\n"
            f"Никакого текста до или после JSON."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION RESULT
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ParseResult:
    """Result of parsing and validating LLM response."""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    errors: list[str] = field(default_factory=list)
    attempts: int = 1

    @property
    def is_valid(self) -> bool:
        return self.success and not self.errors

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the parsed data."""
        return self.data.get(key, default)


# ═══════════════════════════════════════════════════════════════════════════════
# JSON EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════


class JSONExtractor:
    """
    Extract JSON from LLM response text.

    Handles common LLM quirks:
    - JSON wrapped in markdown code blocks
    - Text before/after JSON
    - Trailing commas
    - Single quotes instead of double
    """

    # Pattern to find JSON in markdown code blocks
    _CODE_BLOCK_RE = re.compile(
        r"```(?:json)?\s*\n?(.*?)\n?\s*```",
        re.DOTALL,
    )

    def extract(self, text: str) -> tuple[dict[str, Any] | None, str]:
        """
        Extract and parse JSON from LLM response.

        Returns: (parsed_dict_or_None, error_message)
        """
        if not text or not text.strip():
            return None, "Empty response"

        # Strategy 1: Direct parse
        parsed = self._try_parse(text.strip())
        if parsed is not None:
            return parsed, ""

        # Strategy 2: Extract from code block
        match = self._CODE_BLOCK_RE.search(text)
        if match:
            parsed = self._try_parse(match.group(1).strip())
            if parsed is not None:
                return parsed, ""

        # Strategy 3: Find first { ... } block
        parsed = self._extract_braces(text)
        if parsed is not None:
            return parsed, ""

        # Strategy 4: Fix common issues and retry
        cleaned = self._fix_common_issues(text)
        parsed = self._try_parse(cleaned)
        if parsed is not None:
            return parsed, ""

        return None, f"Failed to extract JSON from response ({len(text)} chars)"

    def _try_parse(self, text: str) -> dict[str, Any] | None:
        """Try to parse text as JSON."""
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    def _extract_braces(self, text: str) -> dict[str, Any] | None:
        """Find and extract the first JSON object in text."""
        start = text.find("{")
        if start == -1:
            return None

        # Find matching closing brace
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    return self._try_parse(candidate)

        return None

    def _fix_common_issues(self, text: str) -> str:
        """Fix common JSON formatting issues from LLMs."""
        # Remove leading/trailing non-JSON
        text = text.strip()

        # Remove trailing commas before } or ]
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # Try to find JSON portion
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        return text


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════


class ResponseValidator:
    """Validate parsed JSON against a ResponseSchema."""

    _TYPE_CHECKS: dict[str, type] = {
        "string": str,
        "str": str,
        "number": (int, float),
        "int": int,
        "integer": int,
        "float": (int, float),
        "bool": bool,
        "boolean": bool,
        "array": list,
        "list": list,
        "object": dict,
        "dict": dict,
    }

    def validate(
        self,
        data: dict[str, Any],
        schema: ResponseSchema,
    ) -> list[str]:
        """
        Validate data against schema.

        Returns list of validation errors (empty = valid).
        """
        errors: list[str] = []

        # Check required fields
        for field_name in schema.required:
            if field_name not in data:
                errors.append(f"Missing required field: '{field_name}'")

        # Check field types
        for field_name, spec in schema.fields.items():
            if field_name not in data:
                continue

            value = data[field_name]
            expected_type = self._TYPE_CHECKS.get(spec.type)

            if expected_type and not isinstance(value, expected_type):
                errors.append(
                    f"Field '{field_name}': expected {spec.type}, "
                    f"got {type(value).__name__}"
                )

        return errors


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURED LLM
# ═══════════════════════════════════════════════════════════════════════════════


class StructuredLLM:
    """
    LLM wrapper that returns validated, structured responses.

    Usage:
        schema = ResponseSchema("plan", {"steps": "list of steps"})
        result = await structured_llm.generate("Create a plan for X", schema)
        if result.success:
            steps = result.data["steps"]
    """

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self.extractor = JSONExtractor()
        self.validator = ResponseValidator()
        self._stats: dict[str, int] = {
            "total_calls": 0,
            "first_try_success": 0,
            "retry_success": 0,
            "failures": 0,
        }

    async def generate(
        self,
        prompt: str,
        schema: ResponseSchema,
        system_prompt: str = "",
        temperature: float = 0.3,
    ) -> ParseResult:
        """
        Generate a structured response from LLM.

        1. Send prompt with schema instructions
        2. Parse and validate response
        3. On failure: retry with error feedback
        """
        from pds_ultimate.core.llm_engine import llm_engine

        self._stats["total_calls"] += 1

        full_prompt = f"{prompt}\n\n{schema.to_prompt()}"

        errors_so_far: list[str] = []

        for attempt in range(1, self.max_retries + 2):
            try:
                if attempt > 1:
                    # Re-prompt with error details
                    error_feedback = "\n".join(
                        f"- {e}" for e in errors_so_far
                    )
                    full_prompt = (
                        f"{prompt}\n\n"
                        f"ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ НЕВАЛИДНЫМ:\n{error_feedback}\n\n"
                        f"ИСПРАВЬ и верни валидный JSON:\n{schema.to_prompt()}"
                    )

                response = await llm_engine.chat(
                    message=full_prompt,
                    system_prompt=system_prompt or None,
                    task_type="structured_output",
                    temperature=temperature,
                    json_mode=True,
                )

                # Extract JSON
                data, extract_error = self.extractor.extract(response)
                if data is None:
                    errors_so_far.append(extract_error)
                    continue

                # Validate
                validation_errors = self.validator.validate(data, schema)
                if validation_errors:
                    errors_so_far.extend(validation_errors)
                    continue

                # Success!
                if attempt == 1:
                    self._stats["first_try_success"] += 1
                else:
                    self._stats["retry_success"] += 1

                return ParseResult(
                    success=True,
                    data=data,
                    raw=response,
                    attempts=attempt,
                )

            except Exception as e:
                errors_so_far.append(f"LLM error: {str(e)}")

        # All retries failed
        self._stats["failures"] += 1
        return ParseResult(
            success=False,
            raw="",
            errors=errors_so_far,
            attempts=self.max_retries + 1,
        )

    def parse_response(
        self,
        response: str,
        schema: ResponseSchema,
    ) -> ParseResult:
        """
        Parse and validate an existing response (no LLM call).

        Useful for validating responses from other sources.
        """
        data, extract_error = self.extractor.extract(response)
        if data is None:
            return ParseResult(
                success=False,
                raw=response,
                errors=[extract_error],
            )

        validation_errors = self.validator.validate(data, schema)
        if validation_errors:
            return ParseResult(
                success=False,
                data=data,
                raw=response,
                errors=validation_errors,
            )

        return ParseResult(
            success=True,
            data=data,
            raw=response,
        )

    def get_stats(self) -> dict[str, int]:
        """Return structured output statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "total_calls": 0,
            "first_try_success": 0,
            "retry_success": 0,
            "failures": 0,
        }


# ─── Global Instance ─────────────────────────────────────────────────────────

structured_llm = StructuredLLM()
