"""
Tests for Step 5: Token-aware Context Management
=================================================
Tests for: token_counter.py + updated conversation.py

Coverage:
- estimate_tokens — accuracy for EN, RU, mixed, edge cases
- count_message_tokens — overhead calculation
- count_messages_tokens — multi-message totals
- ContextBudget — budget math
- TokenAwareTrimmer — trim logic, summary injection
- SmartContextBuilder — full pipeline
- ConversationContext — token-aware get_history_for_llm
"""

from __future__ import annotations

from pds_ultimate.bot.conversation import (
    ConversationContext,
    ConversationManager,
    ConversationState,
)
from pds_ultimate.core.token_counter import (
    ContextBudget,
    SmartContextBuilder,
    TokenAwareTrimmer,
    count_message_tokens,
    count_messages_tokens,
    estimate_tokens,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. estimate_tokens
# ═══════════════════════════════════════════════════════════════════════════════


class TestEstimateTokens:
    """Test token estimation accuracy."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word_english(self):
        t = estimate_tokens("hello")
        assert 1 <= t <= 3

    def test_english_sentence(self):
        text = "The quick brown fox jumps over the lazy dog."
        t = estimate_tokens(text)
        # ~44 chars / 3.8 ≈ 11-12 tokens
        assert 8 <= t <= 16

    def test_cyrillic_text(self):
        text = "Привет, как дела? Всё хорошо, спасибо!"
        t = estimate_tokens(text)
        # Cyrillic chars ≈ 0.67 tokens each → more tokens per char
        assert t > 0

    def test_mixed_ru_en(self):
        text = "Привет! Hello world! Как дела?"
        t = estimate_tokens(text)
        assert t > 0

    def test_long_text(self):
        text = "word " * 1000  # 5000 chars
        t = estimate_tokens(text)
        # ~5000 / 3.8 ≈ 1316 tokens
        assert 1000 <= t <= 2000

    def test_only_spaces(self):
        t = estimate_tokens("     ")
        assert t >= 1

    def test_numbers(self):
        t = estimate_tokens("12345 67890 111 222")
        assert t >= 1

    def test_code_snippet(self):
        code = "def hello():\n    print('world')\n    return 42"
        t = estimate_tokens(code)
        assert t >= 5

    def test_unicode_emoji(self):
        text = "Hello 🌍🎉 world!"
        t = estimate_tokens(text)
        assert t >= 1

    def test_proportionality(self):
        """Longer text → more tokens."""
        short = estimate_tokens("hello")
        long_ = estimate_tokens("hello " * 100)
        assert long_ > short * 10


# ═══════════════════════════════════════════════════════════════════════════════
# 2. count_message_tokens
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountMessageTokens:
    """Test per-message token counting."""

    def test_simple_user_message(self):
        msg = {"role": "user", "content": "Hello"}
        t = count_message_tokens(msg)
        # 4 overhead + ~2 (content) + ~1 (role) = ~7
        assert t >= 5

    def test_empty_content(self):
        msg = {"role": "assistant", "content": ""}
        t = count_message_tokens(msg)
        # 4 overhead + 0 content + ~2 role
        assert t >= 4

    def test_none_content(self):
        msg = {"role": "user", "content": None}
        t = count_message_tokens(msg)
        assert t >= 4

    def test_long_content(self):
        msg = {"role": "assistant", "content": "word " * 500}
        t = count_message_tokens(msg)
        assert t > 100

    def test_system_message(self):
        msg = {"role": "system", "content": "You are a helpful assistant."}
        t = count_message_tokens(msg)
        assert t >= 5

    def test_overhead_included(self):
        """Message tokens > content tokens (overhead exists)."""
        msg = {"role": "user", "content": "Hi"}
        total = count_message_tokens(msg)
        content_only = estimate_tokens("Hi")
        assert total > content_only


# ═══════════════════════════════════════════════════════════════════════════════
# 3. count_messages_tokens
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountMessagesTokens:
    """Test multi-message token counting."""

    def test_empty_list(self):
        t = count_messages_tokens([])
        # Just the 3-token reply priming
        assert t == 3

    def test_single_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        t = count_messages_tokens(msgs)
        assert t > 3  # more than just priming

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        t = count_messages_tokens(msgs)
        assert t > count_messages_tokens(msgs[:1])

    def test_additivity(self):
        """Total ≈ sum of individual + 3."""
        msgs = [
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "B"},
        ]
        total = count_messages_tokens(msgs)
        individual_sum = sum(count_message_tokens(m) for m in msgs) + 3
        assert total == individual_sum


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ContextBudget
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextBudget:
    """Test budget calculations."""

    def test_default_budget(self):
        b = ContextBudget()
        assert b.max_context_tokens == 14000
        assert b.max_response_tokens == 4096

    def test_available_for_history(self):
        b = ContextBudget(
            max_context_tokens=10000,
            max_response_tokens=2000,
            system_prompt_tokens=500,
            reserved_tokens=100,
        )
        assert b.available_for_history == 10000 - 2000 - 500 - 100

    def test_available_adjusts_with_system_prompt(self):
        b = ContextBudget(max_context_tokens=10000, max_response_tokens=2000)
        avail1 = b.available_for_history
        b.system_prompt_tokens = 1000
        avail2 = b.available_for_history
        assert avail2 == avail1 - 1000

    def test_custom_budget(self):
        b = ContextBudget(max_context_tokens=32000, max_response_tokens=8192)
        assert b.available_for_history > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TokenAwareTrimmer
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenAwareTrimmer:
    """Test token-aware history trimming."""

    def _make_messages(self, n: int, content_len: int = 50) -> list[dict]:
        """Create n alternating user/assistant messages."""
        msgs = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"Message {i}: " + "x" * content_len
            msgs.append({"role": role, "content": content})
        return msgs

    def test_no_trim_needed(self):
        """Short history fits entirely."""
        budget = ContextBudget(max_context_tokens=50000,
                               max_response_tokens=4096)
        trimmer = TokenAwareTrimmer(budget)
        msgs = self._make_messages(5)
        result = trimmer.trim(msgs)
        assert result.trimmed_count == 0
        assert len(result.messages) == 5
        assert result.summary_injected is False

    def test_trim_old_messages(self):
        """Long history gets trimmed."""
        budget = ContextBudget(
            max_context_tokens=500,
            max_response_tokens=100,
            reserved_tokens=50,
        )
        trimmer = TokenAwareTrimmer(budget)
        msgs = self._make_messages(50, content_len=100)
        result = trimmer.trim(msgs)
        assert result.trimmed_count > 0
        assert len(result.messages) < 50

    def test_keeps_recent_messages(self):
        """Most recent messages are kept."""
        budget = ContextBudget(
            max_context_tokens=500,
            max_response_tokens=100,
            reserved_tokens=50,
        )
        trimmer = TokenAwareTrimmer(budget)
        msgs = self._make_messages(20, content_len=50)
        result = trimmer.trim(msgs)
        # Last message should always be present
        assert result.messages[-1] == msgs[-1]

    def test_summary_injection(self):
        """Summary injected when many messages trimmed."""
        budget = ContextBudget(
            max_context_tokens=1200,
            max_response_tokens=100,
            reserved_tokens=50,
        )
        trimmer = TokenAwareTrimmer(budget)
        # 80 messages x ~30 tokens each ≈ 2400 tokens → budget 1050 → ~35 kept, 45 trimmed
        msgs = self._make_messages(80, content_len=80)
        result = trimmer.trim(msgs)
        # Many messages trimmed → summary should be injected
        assert result.trimmed_count >= trimmer.SUMMARY_THRESHOLD
        assert result.summary_injected is True
        # First message should be the summary
        assert "[Сводка" in result.messages[0]["content"]

    def test_empty_history(self):
        trimmer = TokenAwareTrimmer()
        result = trimmer.trim([])
        assert result.messages == []
        assert result.trimmed_count == 0

    def test_single_message_always_kept(self):
        """Even with tiny budget, last message is kept."""
        budget = ContextBudget(
            max_context_tokens=10,
            max_response_tokens=5,
            reserved_tokens=5,
        )
        trimmer = TokenAwareTrimmer(budget)
        msgs = [{"role": "user", "content": "Important message that must be kept"}]
        result = trimmer.trim(msgs)
        assert len(result.messages) >= 1

    def test_trim_result_token_count(self):
        """TrimResult total_tokens is accurate."""
        trimmer = TokenAwareTrimmer()
        msgs = self._make_messages(5)
        result = trimmer.trim(msgs)
        expected = count_messages_tokens(result.messages) - 3  # minus priming
        # Should be reasonably close
        assert abs(result.total_tokens - expected) < 20

    def test_system_prompt_affects_budget(self):
        """System prompt reduces available budget."""
        budget = ContextBudget(
            max_context_tokens=1000,
            max_response_tokens=200,
            reserved_tokens=50,
        )
        trimmer = TokenAwareTrimmer(budget)
        msgs = self._make_messages(20, content_len=50)

        result_no_sys = trimmer.trim(msgs)
        result_with_sys = trimmer.trim(
            msgs,
            system_prompt="You are a very detailed assistant " * 20,
        )
        # With system prompt, more messages get trimmed
        assert result_with_sys.trimmed_count >= result_no_sys.trimmed_count


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SmartContextBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestSmartContextBuilder:
    """Test the full context builder pipeline."""

    def test_build_simple(self):
        builder = SmartContextBuilder(max_context_tokens=50000)
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = builder.build(history)
        assert len(result) == 2

    def test_build_with_system_prompt(self):
        builder = SmartContextBuilder(max_context_tokens=50000)
        history = [
            {"role": "user", "content": "Hi"},
        ]
        result = builder.build(history, system_prompt="You are helpful.")
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful."
        assert len(result) == 2

    def test_build_with_memories(self):
        builder = SmartContextBuilder(max_context_tokens=50000)
        history = [
            {"role": "user", "content": "What's my name?"},
        ]
        memories = ["User's name is Slavik", "User likes Python"]
        result = builder.build(
            history,
            system_prompt="You are helpful.",
            retrieved_memories=memories,
        )
        # system + memories + user = 3
        assert len(result) == 3
        assert "[Релевантные воспоминания]" in result[1]["content"]

    def test_build_trims_long_history(self):
        builder = SmartContextBuilder(
            max_context_tokens=800,
            max_response_tokens=200,
        )
        # Create a long history that needs trimming
        history = []
        for i in range(50):
            role = "user" if i % 2 == 0 else "assistant"
            history.append(
                {"role": role, "content": f"Message {i} " + "x" * 80})

        result = builder.build(history, system_prompt="System")
        # Should be shorter than original
        assert len(result) < 52  # 50 history + 1 system + possible summary

    def test_build_empty_history(self):
        builder = SmartContextBuilder()
        result = builder.build([])
        assert result == []

    def test_build_empty_history_with_system(self):
        builder = SmartContextBuilder()
        result = builder.build([], system_prompt="Be helpful.")
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_get_stats(self):
        builder = SmartContextBuilder(
            max_context_tokens=14000,
            max_response_tokens=4096,
        )
        stats = builder.get_stats()
        assert stats["max_context_tokens"] == 14000
        assert stats["max_response_tokens"] == 4096
        assert "available_for_history" in stats

    def test_memory_truncation(self):
        """Long memories get truncated."""
        builder = SmartContextBuilder(max_context_tokens=50000)
        memories = ["A" * 500]  # Very long memory
        result = builder.build(
            [{"role": "user", "content": "test"}],
            system_prompt="Be helpful.",
            retrieved_memories=memories,
        )
        # system(0) + memory(1) + user(2)
        mem_msg = result[1]["content"]
        assert "..." in mem_msg

    def test_max_five_memories(self):
        """At most 5 memories are included."""
        builder = SmartContextBuilder(max_context_tokens=50000)
        memories = [f"Memory {i}" for i in range(10)]
        result = builder.build(
            [{"role": "user", "content": "test"}],
            system_prompt="Be helpful.",
            retrieved_memories=memories,
        )
        # system(0) + memory(1) + user(2)
        mem_msg = result[1]["content"]
        # Should contain "1." through "5." but not "6."
        assert "5." in mem_msg
        assert "6." not in mem_msg


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ConversationContext — token-aware integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversationContextTokenAware:
    """Test updated ConversationContext with token awareness."""

    def test_basic_add_and_get(self):
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("Hello")
        ctx.add_assistant_message("Hi there!")
        history = ctx.get_history_for_llm()
        assert len(history) == 2

    def test_get_history_with_system_prompt(self):
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("Hello")
        history = ctx.get_history_for_llm(system_prompt="Be helpful.")
        assert history[0]["role"] == "system"
        assert len(history) == 2

    def test_get_history_with_memories(self):
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("What's my name?")
        memories = ["User name is Slavik"]
        history = ctx.get_history_for_llm(
            system_prompt="Be helpful.",
            retrieved_memories=memories,
        )
        assert len(history) == 3  # system + memories + user
        assert "[Релевантные воспоминания]" in history[1]["content"]

    def test_token_count_property(self):
        ctx = ConversationContext(chat_id=123)
        assert ctx.token_count == 3  # just priming
        ctx.add_user_message("Hello world, this is a test message.")
        assert ctx.token_count > 3

    def test_raw_history(self):
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("A")
        ctx.add_assistant_message("B")
        raw = ctx.get_raw_history()
        assert len(raw) == 2
        # Modifying raw should not affect internal
        raw.append({"role": "user", "content": "C"})
        assert len(ctx.history) == 2

    def test_hard_limit_still_works(self):
        """MAX_HISTORY hard limit as safety net."""
        ctx = ConversationContext(chat_id=123)
        for i in range(100):
            ctx.add_user_message(f"msg {i}")
        assert len(ctx.history) <= ctx.MAX_HISTORY

    def test_backward_compat_get_history_no_args(self):
        """get_history_for_llm() works without args (backward compat)."""
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("Hello")
        ctx.add_assistant_message("Hi!")
        # Should work without any args (old callers)
        history = ctx.get_history_for_llm()
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_state_management(self):
        """Existing state management still works."""
        ctx = ConversationContext(chat_id=123)
        assert ctx.state == ConversationState.FREE
        ctx.set_state(ConversationState.ORDER_INPUT, order_id=42)
        assert ctx.state == ConversationState.ORDER_INPUT
        assert ctx.get_temp("order_id") == 42

    def test_reset(self):
        ctx = ConversationContext(chat_id=123)
        ctx.add_user_message("Hello")
        ctx.set_state(ConversationState.ORDER_INPUT)
        ctx.reset()
        assert ctx.state == ConversationState.FREE
        assert len(ctx.history) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ConversationManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversationManager:
    """Test ConversationManager unchanged behavior."""

    def test_get_creates_context(self):
        mgr = ConversationManager()
        ctx = mgr.get(123)
        assert ctx.chat_id == 123

    def test_get_returns_same_context(self):
        mgr = ConversationManager()
        ctx1 = mgr.get(123)
        ctx2 = mgr.get(123)
        assert ctx1 is ctx2

    def test_active_count(self):
        mgr = ConversationManager()
        mgr.get(1)
        mgr.get(2)
        assert mgr.active_count == 2

    def test_reset(self):
        mgr = ConversationManager()
        ctx = mgr.get(123)
        ctx.add_user_message("Hello")
        mgr.reset(123)
        assert len(ctx.history) == 0

    def test_remove(self):
        mgr = ConversationManager()
        mgr.get(123)
        mgr.remove(123)
        assert mgr.active_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Edge Cases & Stress Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and stress tests."""

    def test_very_long_single_message(self):
        """Single message exceeding budget."""
        budget = ContextBudget(
            max_context_tokens=100,
            max_response_tokens=50,
        )
        trimmer = TokenAwareTrimmer(budget)
        msgs = [{"role": "user", "content": "x" * 10000}]
        result = trimmer.trim(msgs)
        # Should still return at least the message
        assert len(result.messages) >= 1

    def test_all_same_role(self):
        """All messages same role (unusual but valid)."""
        trimmer = TokenAwareTrimmer()
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        result = trimmer.trim(msgs)
        assert len(result.messages) > 0

    def test_empty_content_messages(self):
        """Messages with empty content."""
        trimmer = TokenAwareTrimmer()
        msgs = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "Hello"},
        ]
        result = trimmer.trim(msgs)
        assert len(result.messages) == 3

    def test_summary_format(self):
        """Verify summary message format."""
        trimmer = TokenAwareTrimmer()
        summary = trimmer._make_summary([
            {"role": "user", "content": "Message one about weather"},
            {"role": "assistant", "content": "It's sunny today"},
            {"role": "user", "content": "And tomorrow?"},
            {"role": "assistant", "content": "Rain expected"},
        ])
        assert summary["role"] == "system"
        assert "[Сводка" in summary["content"]
        assert "[user]" in summary["content"]
        assert "[assistant]" in summary["content"]

    def test_builder_no_memories_no_system(self):
        """Builder with just history."""
        builder = SmartContextBuilder()
        msgs = [{"role": "user", "content": "Hi"}]
        result = builder.build(msgs)
        assert len(result) == 1

    def test_estimate_tokens_deterministic(self):
        """Same input → same output."""
        text = "Test consistency check!"
        t1 = estimate_tokens(text)
        t2 = estimate_tokens(text)
        assert t1 == t2

    def test_token_count_scales_linearly(self):
        """Token count grows ~linearly with text length."""
        t1 = estimate_tokens("a" * 100)
        t2 = estimate_tokens("a" * 1000)
        ratio = t2 / t1
        # Should be roughly 10x (8x-12x acceptable)
        assert 7 < ratio < 13
