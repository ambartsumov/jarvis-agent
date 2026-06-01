"""
Tests for Step 13: Structured Output (Pydantic Validation)
============================================================
Covers:
- FieldSpec: creation, types, to_json_schema
- ResponseSchema: fields normalization, required, to_json_schema, to_prompt
- ParseResult: success/failure, get(), is_valid
- JSONExtractor: direct parse, code blocks, braces extraction, fixes
- ResponseValidator: required fields, type checks
- StructuredLLM: parse_response (sync), stats
"""

from unittest.mock import AsyncMock, patch

import pytest

from pds_ultimate.core.structured_output import (
    FieldSpec,
    JSONExtractor,
    ParseResult,
    ResponseSchema,
    ResponseValidator,
    StructuredLLM,
    structured_llm,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. FIELD SPEC
# ═══════════════════════════════════════════════════════════════════════════════


class TestFieldSpec:
    def test_defaults(self):
        f = FieldSpec(name="x")
        assert f.type == "string"
        assert f.required is True
        assert f.default is None

    def test_custom_type(self):
        f = FieldSpec(name="score", type="number", description="0 to 1")
        assert f.type == "number"

    def test_to_json_schema_string(self):
        f = FieldSpec(name="name", type="string", description="User name")
        schema = f.to_json_schema()
        assert schema["type"] == "string"
        assert schema["description"] == "User name"

    def test_to_json_schema_number(self):
        f = FieldSpec(name="age", type="int")
        schema = f.to_json_schema()
        assert schema["type"] == "integer"

    def test_to_json_schema_array(self):
        f = FieldSpec(name="items", type="list")
        schema = f.to_json_schema()
        assert schema["type"] == "array"

    def test_to_json_schema_bool(self):
        f = FieldSpec(name="flag", type="bool")
        schema = f.to_json_schema()
        assert schema["type"] == "boolean"

    def test_frozen(self):
        f = FieldSpec(name="x")
        with pytest.raises(AttributeError):
            f.name = "y"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RESPONSE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseSchema:
    def test_string_fields_normalized(self):
        schema = ResponseSchema(
            name="test",
            fields={"name": "user name", "age": "user age"},
        )
        assert isinstance(schema.fields["name"], FieldSpec)
        assert schema.fields["name"].description == "user name"

    def test_fieldspec_fields_preserved(self):
        spec = FieldSpec(name="score", type="number")
        schema = ResponseSchema(
            name="test",
            fields={"score": spec},
        )
        assert schema.fields["score"].type == "number"

    def test_auto_required(self):
        schema = ResponseSchema(
            name="test",
            fields={"a": "field a", "b": "field b"},
        )
        assert "a" in schema.required
        assert "b" in schema.required

    def test_explicit_required(self):
        schema = ResponseSchema(
            name="test",
            fields={"a": "field a", "b": "field b"},
            required=["a"],
        )
        assert schema.required == ["a"]

    def test_to_json_schema(self):
        schema = ResponseSchema(
            name="plan",
            fields={"steps": "list of steps"},
            required=["steps"],
        )
        js = schema.to_json_schema()
        assert js["type"] == "object"
        assert "steps" in js["properties"]
        assert js["required"] == ["steps"]

    def test_to_prompt(self):
        schema = ResponseSchema(
            name="test",
            fields={"answer": "the answer"},
        )
        prompt = schema.to_prompt()
        assert "JSON" in prompt
        assert "answer" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PARSE RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseResult:
    def test_success(self):
        r = ParseResult(success=True, data={"answer": "42"})
        assert r.is_valid
        assert r.get("answer") == "42"

    def test_failure(self):
        r = ParseResult(success=False, errors=["missing field"])
        assert not r.is_valid
        assert len(r.errors) == 1

    def test_get_default(self):
        r = ParseResult(success=True, data={"a": 1})
        assert r.get("missing", "default") == "default"

    def test_attempts(self):
        r = ParseResult(success=True, data={}, attempts=3)
        assert r.attempts == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 4. JSON EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestJSONExtractor:
    def setup_method(self):
        self.extractor = JSONExtractor()

    def test_direct_json(self):
        data, err = self.extractor.extract('{"key": "value"}')
        assert data == {"key": "value"}
        assert err == ""

    def test_empty_string(self):
        data, err = self.extractor.extract("")
        assert data is None
        assert "Empty" in err

    def test_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        data, err = self.extractor.extract(text)
        assert data == {"key": "value"}

    def test_code_block_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        data, err = self.extractor.extract(text)
        assert data == {"key": "value"}

    def test_text_around_json(self):
        text = 'Here is the result:\n{"answer": 42}\nThat is all.'
        data, err = self.extractor.extract(text)
        assert data == {"answer": 42}

    def test_trailing_comma(self):
        text = '{"a": 1, "b": 2,}'
        data, err = self.extractor.extract(text)
        assert data is not None
        assert data["a"] == 1

    def test_not_json(self):
        data, err = self.extractor.extract("This is just plain text")
        assert data is None
        assert "Failed" in err

    def test_nested_json(self):
        text = '{"outer": {"inner": "value"}}'
        data, err = self.extractor.extract(text)
        assert data["outer"]["inner"] == "value"

    def test_array_not_dict(self):
        # We only accept dicts as top-level
        text = '[1, 2, 3]'
        data, err = self.extractor.extract(text)
        # Should fail since it's not a dict
        assert data is None

    def test_extract_braces_complex(self):
        text = 'prefix {"x": {"y": 1}} suffix'
        data, err = self.extractor.extract(text)
        assert data == {"x": {"y": 1}}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RESPONSE VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestResponseValidator:
    def setup_method(self):
        self.validator = ResponseValidator()

    def test_valid_data(self):
        schema = ResponseSchema(
            name="test",
            fields={"name": FieldSpec(name="name", type="string")},
            required=["name"],
        )
        errors = self.validator.validate({"name": "Alice"}, schema)
        assert errors == []

    def test_missing_required(self):
        schema = ResponseSchema(
            name="test",
            fields={"name": "the name"},
            required=["name"],
        )
        errors = self.validator.validate({}, schema)
        assert len(errors) == 1
        assert "Missing" in errors[0]

    def test_wrong_type(self):
        schema = ResponseSchema(
            name="test",
            fields={"score": FieldSpec(name="score", type="number")},
            required=["score"],
        )
        errors = self.validator.validate({"score": "not a number"}, schema)
        assert len(errors) == 1
        assert "expected number" in errors[0]

    def test_int_accepted_for_number(self):
        schema = ResponseSchema(
            name="test",
            fields={"score": FieldSpec(name="score", type="float")},
        )
        errors = self.validator.validate({"score": 42}, schema)
        assert errors == []  # int is valid for float/number

    def test_extra_fields_ignored(self):
        schema = ResponseSchema(
            name="test",
            fields={"name": "the name"},
            required=["name"],
        )
        errors = self.validator.validate(
            {"name": "Alice", "extra": "ignored"}, schema,
        )
        assert errors == []

    def test_optional_field_missing(self):
        schema = ResponseSchema(
            name="test",
            fields={
                "name": FieldSpec(name="name", type="string"),
                "age": FieldSpec(name="age", type="int", required=False),
            },
            required=["name"],
        )
        errors = self.validator.validate({"name": "Alice"}, schema)
        assert errors == []

    def test_array_type(self):
        schema = ResponseSchema(
            name="test",
            fields={"items": FieldSpec(name="items", type="list")},
            required=["items"],
        )
        errors = self.validator.validate({"items": [1, 2, 3]}, schema)
        assert errors == []

    def test_bool_type_wrong(self):
        schema = ResponseSchema(
            name="test",
            fields={"flag": FieldSpec(name="flag", type="bool")},
            required=["flag"],
        )
        errors = self.validator.validate({"flag": "yes"}, schema)
        assert len(errors) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. STRUCTURED LLM
# ═══════════════════════════════════════════════════════════════════════════════


class TestStructuredLLM:
    def setup_method(self):
        self.llm = StructuredLLM(max_retries=1)

    def test_parse_response_valid(self):
        schema = ResponseSchema(
            name="answer",
            fields={"text": "the answer"},
            required=["text"],
        )
        result = self.llm.parse_response(
            '{"text": "Hello"}',
            schema,
        )
        assert result.success
        assert result.data["text"] == "Hello"

    def test_parse_response_invalid_json(self):
        schema = ResponseSchema(
            name="test",
            fields={"x": "val"},
        )
        result = self.llm.parse_response("not json at all", schema)
        assert not result.success

    def test_parse_response_missing_field(self):
        schema = ResponseSchema(
            name="test",
            fields={"required_field": "must exist"},
            required=["required_field"],
        )
        result = self.llm.parse_response('{"other": 1}', schema)
        assert not result.success
        assert any("Missing" in e for e in result.errors)

    def test_parse_response_code_block(self):
        schema = ResponseSchema(
            name="test",
            fields={"answer": "the answer"},
        )
        result = self.llm.parse_response(
            '```json\n{"answer": "42"}\n```',
            schema,
        )
        assert result.success
        assert result.data["answer"] == "42"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_generate_success(self):
        schema = ResponseSchema(
            name="plan",
            fields={"steps": FieldSpec(name="steps", type="list")},
            required=["steps"],
        )

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value='{"steps": ["step1", "step2"]}')

        with patch(
            "pds_ultimate.core.llm_engine.llm_engine",
            mock_llm,
        ):
            result = await self.llm.generate("Create a plan", schema)

        assert result.success
        assert result.data["steps"] == ["step1", "step2"]
        assert result.attempts == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_generate_retry_on_invalid(self):
        schema = ResponseSchema(
            name="test",
            fields={"answer": "the answer"},
            required=["answer"],
        )

        mock_llm = AsyncMock()
        # First call: invalid, second: valid
        mock_llm.chat = AsyncMock(
            side_effect=[
                "not json",
                '{"answer": "correct"}',
            ]
        )

        with patch(
            "pds_ultimate.core.llm_engine.llm_engine",
            mock_llm,
        ):
            result = await self.llm.generate("Answer me", schema)

        assert result.success
        assert result.data["answer"] == "correct"
        assert result.attempts == 2

    @pytest.mark.asyncio(loop_scope="function")
    async def test_generate_all_retries_fail(self):
        schema = ResponseSchema(
            name="test",
            fields={"x": "val"},
        )

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="garbage")

        with patch(
            "pds_ultimate.core.llm_engine.llm_engine",
            mock_llm,
        ):
            result = await self.llm.generate("Do something", schema)

        assert not result.success
        assert len(result.errors) > 0

    def test_stats_tracking(self):
        llm = StructuredLLM()
        schema = ResponseSchema(name="t", fields={"a": "x"})
        llm.parse_response('{"a": "ok"}', schema)
        stats = llm.get_stats()
        assert "total_calls" in stats

    def test_stats_reset(self):
        llm = StructuredLLM()
        llm._stats["total_calls"] = 10
        llm.reset_stats()
        assert llm.get_stats()["total_calls"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalInstance:
    def test_structured_llm_exists(self):
        assert structured_llm is not None
        assert isinstance(structured_llm, StructuredLLM)

    def test_structured_llm_functional(self):
        schema = ResponseSchema(name="t", fields={"a": "x"})
        result = structured_llm.parse_response('{"a": "ok"}', schema)
        assert result.success
