"""
Tests for Step 2: Native Function Calling
==========================================
Tests the new chat_with_tools in llm_engine and the v5 Agent
that uses native API-level tool calls instead of JSON parsing hacks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ─── Imports under test ───────────────────────────────────────────────────────
from pds_ultimate.core.agent import (
    Agent,
    AgentAction,
    AgentResponse,
    AgentStep,
    TaskVerifier,
    _sanitize_answer,
)
from pds_ultimate.core.tools import Tool, ToolParameter, ToolRegistry

# ═══════════════════════════════════════════════════════════════════════════════
# 1. _sanitize_answer tests (replaces old 5-level JSON cleaning)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSanitizeAnswer:
    """Test the lightweight answer sanitizer."""

    def test_plain_text_passes_through(self):
        assert _sanitize_answer(
            "Привет! Вот твой ответ.") == "Привет! Вот твой ответ."

    def test_empty_string(self):
        assert _sanitize_answer("") == ""

    def test_none_input(self):
        assert _sanitize_answer(None) == ""

    def test_strips_think_tags(self):
        text = "<think>reasoning here</think>Final answer text"
        assert _sanitize_answer(text) == "Final answer text"

    def test_strips_multiline_think_tags(self):
        text = "<think>\nlong\nthinking\n</think>\nОтвет"
        result = _sanitize_answer(text)
        assert "think" not in result
        assert "Ответ" in result

    def test_extracts_answer_from_json_object(self):
        text = '{"answer": "Extracted answer", "thought": "some thought"}'
        assert _sanitize_answer(text) == "Extracted answer"

    def test_extracts_response_from_json_object(self):
        text = '{"response": "Response text"}'
        assert _sanitize_answer(text) == "Response text"

    def test_extracts_result_from_json_object(self):
        text = '{"result": "Result text"}'
        assert _sanitize_answer(text) == "Result text"

    def test_returns_json_if_no_answer_key(self):
        text = '{"unknown_key": "value"}'
        assert _sanitize_answer(text) == text  # passes through

    def test_non_json_with_braces(self):
        text = "Use the {tool_name} for this."
        assert _sanitize_answer(text) == text  # not JSON, passes through

    def test_whitespace_stripped(self):
        text = "  \n  Ответ с пробелами  \n  "
        assert _sanitize_answer(text) == "Ответ с пробелами"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AgentAction / AgentStep / AgentResponse dataclass tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataclasses:
    """Test agent dataclasses."""

    def test_agent_action_defaults(self):
        action = AgentAction(action_type="tool_call", tool_name="web_search")
        assert action.action_type == "tool_call"
        assert action.tool_name == "web_search"
        assert action.tool_params is None
        assert action.thought == ""
        assert action.confidence == 0.0

    def test_agent_step_defaults(self):
        step = AgentStep(iteration=1)
        assert step.iteration == 1
        assert step.thought == ""
        assert step.action is None
        assert step.quality_score == 0.7

    def test_agent_response_defaults(self):
        resp = AgentResponse(answer="test")
        assert resp.answer == "test"
        assert resp.tools_used == []
        assert resp.total_iterations == 0
        assert resp.quality_score == 0.7
        assert resp.task_verified is False
        assert resp.files_to_send == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TaskVerifier tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskVerifier:
    """Test task verification (heuristic)."""

    def test_fast_check_good_answer(self):
        score = TaskVerifier.fast_check(
            "Какая погода?",
            "Сегодня в Ашхабаде +35°C, солнечно без осадков."
        )
        assert score >= 0.5

    def test_fast_check_empty_answer(self):
        score = TaskVerifier.fast_check("Задача", "")
        assert score == 0.1

    def test_fast_check_json_leak_penalty(self):
        score = TaskVerifier.fast_check(
            "Привет",
            '{"action": {"type": "final_answer"}, "thought": "thinking"}'
        )
        assert score < 0.5  # Penalized for JSON leak

    def test_fast_check_too_short_for_complex_task(self):
        long_task = "Проанализируй все заказы за последний месяц, сгруппируй по поставщикам, " * 5
        score = TaskVerifier.fast_check(long_task, "Ок")
        assert score < 0.7

    def test_fast_check_hallucination_penalty(self):
        score = TaskVerifier.fast_check(
            "Помоги",
            "К сожалению, я не могу выполнить эту задачу."
        )
        assert score < 0.5

    def test_fast_check_repetitive_answer(self):
        # Many duplicate sentences
        answer = "Ответ готов. " * 10
        score = TaskVerifier.fast_check("Задача", answer)
        assert score < 0.7


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Agent — text response (no tools needed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentTextResponse:
    """Test agent when LLM returns a text answer (no tool calls)."""

    @pytest.fixture
    def agent(self):
        return Agent()

    @pytest.mark.asyncio
    async def test_simple_text_response(self, agent):
        """LLM returns text → agent returns it as final answer."""
        mock_result = {
            "type": "text",
            "content": "Привет! Всё отлично.",
            "tool_calls": [],
            "thought": "Simple greeting",
            "raw": "Привет! Всё отлично.",
        }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:
            mock_llm.chat_with_tools = AsyncMock(return_value=mock_result)
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.9, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []

            response = await agent.execute("Привет!")

        assert response.answer == "Привет! Всё отлично."
        assert response.total_iterations == 1
        assert response.tools_used == []

    @pytest.mark.asyncio
    async def test_text_with_think_tags(self, agent):
        """LLM returns text with <think> — should be stripped."""
        mock_result = {
            "type": "text",
            "content": "<think>reasoning</think>Чистый ответ",
            "tool_calls": [],
            "thought": "",
            "raw": "<think>reasoning</think>Чистый ответ",
        }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:
            mock_llm.chat_with_tools = AsyncMock(return_value=mock_result)
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.9, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []

            response = await agent.execute("Вопрос")

        assert "think" not in response.answer
        assert "Чистый ответ" in response.answer


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Agent — single tool call
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentToolCall:
    """Test agent with native function calling (single tool)."""

    @pytest.fixture
    def agent(self):
        return Agent()

    @pytest.mark.asyncio
    async def test_single_tool_call_then_answer(self, agent):
        """LLM calls a tool → gets result → returns final answer."""
        # First call: LLM wants to call a tool
        tool_call_result = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "web_search",
                    "arguments": {"query": "weather"}}
            ],
            "thought": "Need to search",
            "raw": "",
        }
        # Second call: LLM returns final answer after seeing tool result
        text_result = {
            "type": "text",
            "content": "Погода сегодня: +25°C",
            "tool_calls": [],
            "thought": "Got the info",
            "raw": "Погода сегодня: +25°C",
        }

        with patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=[tool_call_result, text_result])
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.9, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = [
                {"type": "function", "function": {"name": "web_search"}}
            ]
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(return_value="Weather: 25°C, sunny")

            response = await agent.execute("Какая погода?")

        assert response.answer == "Погода сегодня: +25°C"
        assert response.total_iterations == 2
        assert "web_search" in response.tools_used
        mock_tools.execute.assert_called_once_with(
            "web_search", query="weather")

    @pytest.mark.asyncio
    async def test_tool_not_found(self, agent):
        """LLM calls a non-existent tool → error in observation."""
        tool_call_result = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "nonexistent_tool", "arguments": {}}
            ],
            "thought": "",
            "raw": "",
        }
        text_result = {
            "type": "text",
            "content": "Не удалось найти инструмент.",
            "tool_calls": [],
            "thought": "",
            "raw": "",
        }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=[tool_call_result, text_result])
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.7, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = False

            response = await agent.execute("Test")

        # The error should be in the step observation
        assert len(response.steps) >= 1
        assert "не найден" in response.steps[0].observation

    @pytest.mark.asyncio
    async def test_tool_execution_error(self, agent):
        """Tool raises exception → error recorded in step."""
        tool_call_result = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "broken_tool", "arguments": {}}
            ],
            "thought": "",
            "raw": "",
        }
        text_result = {
            "type": "text",
            "content": "Ошибка при выполнении.",
            "tool_calls": [],
            "thought": "",
            "raw": "",
        }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=[tool_call_result, text_result])
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.7, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(
                side_effect=RuntimeError("DB connection lost"))

            response = await agent.execute("Test")

        assert "Ошибка" in response.steps[0].observation


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Agent — parallel tool calls
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentParallelTools:
    """Test agent handling multiple tool calls in one response."""

    @pytest.fixture
    def agent(self):
        return Agent()

    @pytest.mark.asyncio
    async def test_parallel_tool_calls(self, agent):
        """LLM returns 2 tool_calls → both executed in parallel."""
        parallel_result = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "web_search",
                    "arguments": {"query": "weather"}},
                {"id": "call_2", "name": "web_search",
                    "arguments": {"query": "news"}},
            ],
            "thought": "Need both",
            "raw": "",
        }
        final_result = {
            "type": "text",
            "content": "Погода +25, новости хорошие.",
            "tool_calls": [],
            "thought": "",
            "raw": "",
        }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=[parallel_result, final_result])
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.9, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(
                side_effect=["Result 1", "Result 2"])

            response = await agent.execute("Погода и новости")

        assert response.answer == "Погода +25, новости хорошие."
        assert "web_search" in response.tools_used
        assert response.steps[0].action.action_type == "parallel_tools"
        assert len(response.steps[0].action.parallel_calls) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Agent — oscillation detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestOscillationDetection:
    """Test ABAB oscillation detection."""

    def test_no_oscillation_with_few_steps(self):
        agent = Agent()
        steps = [AgentStep(iteration=i+1) for i in range(2)]
        assert agent._detect_oscillation(steps) is False

    def test_oscillation_detected(self):
        agent = Agent()
        steps = []
        for i, (atype, tname) in enumerate([
            ("tool_call", "search"),
            ("tool_call", "read"),
            ("tool_call", "search"),
            ("tool_call", "read"),
        ]):
            step = AgentStep(iteration=i+1)
            step.action = AgentAction(action_type=atype, tool_name=tname)
            steps.append(step)
        assert agent._detect_oscillation(steps) is True

    def test_no_oscillation_different_tools(self):
        agent = Agent()
        steps = []
        for i, (atype, tname) in enumerate([
            ("tool_call", "search"),
            ("tool_call", "read"),
            ("tool_call", "write"),
            ("tool_call", "save"),
        ]):
            step = AgentStep(iteration=i+1)
            step.action = AgentAction(action_type=atype, tool_name=tname)
            steps.append(step)
        assert agent._detect_oscillation(steps) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Agent — max iterations / LLM error
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentEdgeCases:
    """Test agent edge cases."""

    @pytest.fixture
    def agent(self):
        return Agent()

    @pytest.mark.asyncio
    async def test_llm_error_returns_error_message(self, agent):
        """LLM raises exception → agent returns error message."""
        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=ConnectionError("API down"))
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []

            response = await agent.execute("Test")

        assert "Ошибка" in response.answer

    @pytest.mark.asyncio
    async def test_max_iterations_exhausted(self, agent):
        """Agent stops after max iterations even if no final answer."""
        # Always return tool calls, never text
        infinite_tool = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_x", "name": "search", "arguments": {"q": "x"}}
            ],
            "thought": "",
            "raw": "",
        }

        with patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(return_value=infinite_tool)
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(return_value="some result")

            response = await agent.execute("Привет")  # simple → 3 iterations

        assert response.total_iterations <= 3
        assert response.answer  # Should have some fallback answer

    def test_get_max_iterations_simple(self, agent):
        assert agent._get_max_iterations("привет") == 3

    def test_get_max_iterations_complex(self, agent):
        complex_msg = "проанализируй все данные, сравни поставщиков, создай отчёт в Excel и отправь на email"
        result = agent._get_max_iterations(complex_msg)
        assert result >= 5


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Tool JSON schema tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolJSONSchema:
    """Test that tools produce valid OpenAI function calling schemas."""

    def test_tool_json_schema_format(self):
        tool = Tool(
            name="test_tool",
            description="A test tool",
            handler=AsyncMock(),
            parameters=[
                ToolParameter(
                    name="query",
                    param_type="string",
                    description="Search query",
                    required=True,
                ),
                ToolParameter(
                    name="limit",
                    param_type="integer",
                    description="Max results",
                    required=False,
                    default=10,
                ),
            ],
        )
        schema = tool.to_json_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert schema["function"]["description"] == "A test tool"
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "limit" in params["properties"]
        assert "query" in params["required"]
        assert "limit" not in params["required"]

    def test_registry_json_schema_list(self):
        registry = ToolRegistry()
        tool1 = Tool(name="t1", description="Tool 1",
                     handler=AsyncMock(), parameters=[])
        tool2 = Tool(name="t2", description="Tool 2",
                     handler=AsyncMock(), parameters=[])
        registry.register(tool1)
        registry.register(tool2)

        schemas = registry.get_tools_json_schema()
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"t1", "t2"}

    def test_registry_has_tool(self):
        registry = ToolRegistry()
        tool = Tool(name="exists", description="",
                    handler=AsyncMock(), parameters=[])
        registry.register(tool)
        assert registry.has_tool("exists") is True
        assert registry.has_tool("not_exists") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Multi-turn conversation format
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationFormat:
    """Test that the agent builds correct multi-turn conversation."""

    @pytest.fixture
    def agent(self):
        return Agent()

    @pytest.mark.asyncio
    async def test_tool_result_added_to_conversation(self, agent):
        """After tool execution, role=tool message is added to history."""
        tool_call_result = {
            "type": "tool_calls",
            "content": "",
            "tool_calls": [
                {"id": "call_abc", "name": "calculator",
                    "arguments": {"expr": "2+2"}}
            ],
            "thought": "Calculate",
            "raw": "",
        }
        final_result = {
            "type": "text",
            "content": "Результат: 4",
            "tool_calls": [],
            "thought": "",
            "raw": "",
        }

        captured_history = []

        async def capture_chat_with_tools(message, tools, history, **kw):
            captured_history.append(list(history) if history else [])
            if len(captured_history) == 1:
                return tool_call_result
            return final_result

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:

            mock_llm.chat_with_tools = AsyncMock(
                side_effect=capture_chat_with_tools)
            mock_llm.chat = AsyncMock(
                return_value='{"score": 0.9, "issues": [], "passed": true}')
            mock_mem.get_context.return_value = ""
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(return_value="4")

            await agent.execute("Сколько будет 2+2?")

        # Second call should have history with assistant tool_call + tool result
        assert len(captured_history) == 2
        second_call_history = captured_history[1]
        # Should contain: assistant msg with tool_calls + tool result
        assert len(second_call_history) >= 2
        # Assistant message with tool_calls
        assert second_call_history[-2]["role"] == "assistant"
        assert "tool_calls" in second_call_history[-2]
        # Tool result message
        assert second_call_history[-1]["role"] == "tool"
        assert second_call_history[-1]["tool_call_id"] == "call_abc"
        assert second_call_history[-1]["content"] == "4"
