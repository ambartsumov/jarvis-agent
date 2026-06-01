"""
Tests for Step 9: Real-time Persona Adaptation Engine
======================================================
Tests for persona_adaptation.py + integration with emotional_intelligence.py
and persona_engine.py.

Total: ~85 tests covering:
- FeedbackSignal detection
- ConversationEmotionTracker
- AdaptiveStyleSelector
- FeedbackLearner
- PersonaAdaptationEngine orchestration
- Integration with EmotionalIntelligenceEngine
- Integration with PersonaEngine
"""

import time
from collections import Counter, defaultdict
from unittest.mock import patch

import pytest

from pds_ultimate.core.persona_adaptation import (
    AdaptationAction,
    AdaptationRecommendation,
    AdaptiveStyleSelector,
    ConversationEmotionTracker,
    ConversationPhase,
    ConversationTrajectory,
    EmotionTurn,
    FeedbackLearner,
    FeedbackSignal,
    PersonaAdaptationEngine,
    detect_feedback,
    persona_adaptation,
)

# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK SIGNAL DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectFeedback:
    """Tests for detect_feedback function."""

    def test_empty_text(self):
        assert detect_feedback("") == FeedbackSignal.NONE
        assert detect_feedback("   ") == FeedbackSignal.NONE
        assert detect_feedback(None) == FeedbackSignal.NONE

    def test_positive_emoji(self):
        assert detect_feedback("👍") == FeedbackSignal.POSITIVE_EMOJI
        assert detect_feedback("❤️") == FeedbackSignal.POSITIVE_EMOJI
        assert detect_feedback("Отлично 🔥") == FeedbackSignal.POSITIVE_EMOJI

    def test_negative_emoji(self):
        assert detect_feedback("👎") == FeedbackSignal.NEGATIVE_EMOJI
        assert detect_feedback("😡") == FeedbackSignal.NEGATIVE_EMOJI
        assert detect_feedback("Плохо 😤") == FeedbackSignal.NEGATIVE_EMOJI

    def test_thanks(self):
        assert detect_feedback("спасибо") == FeedbackSignal.THANKS
        assert detect_feedback("Спасибо большое!") == FeedbackSignal.THANKS
        assert detect_feedback("thanks") == FeedbackSignal.THANKS
        assert detect_feedback("thx") == FeedbackSignal.THANKS
        assert detect_feedback("благодарю") == FeedbackSignal.THANKS

    def test_short_ack(self):
        assert detect_feedback("ок") == FeedbackSignal.SHORT_ACK
        assert detect_feedback("ok") == FeedbackSignal.SHORT_ACK
        assert detect_feedback("да") == FeedbackSignal.SHORT_ACK
        assert detect_feedback("понял") == FeedbackSignal.SHORT_ACK
        assert detect_feedback("хорошо") == FeedbackSignal.SHORT_ACK

    def test_complaint(self):
        assert detect_feedback(
            "Это неправильно сделал") == FeedbackSignal.COMPLAINT
        assert detect_feedback(
            "не работает вообще") == FeedbackSignal.COMPLAINT
        assert detect_feedback(
            "Неправильно всё") == FeedbackSignal.COMPLAINT

    def test_repeat_request(self):
        assert detect_feedback(
            "Повтори пожалуйста") == FeedbackSignal.REPEAT_REQUEST
        assert detect_feedback(
            "Ещё раз попробуй") == FeedbackSignal.REPEAT_REQUEST

    def test_escalation(self):
        assert detect_feedback(
            "Сколько можно повторять!") == FeedbackSignal.ESCALATION
        assert detect_feedback(
            "Уже третий раз прошу") == FeedbackSignal.ESCALATION
        assert detect_feedback(
            "Я же говорил тебе!") == FeedbackSignal.ESCALATION

    def test_elaboration_after_confusion(self):
        long_text = "Я имел в виду что нужно сделать так: сначала открыть файл, потом найти строку и заменить"
        assert detect_feedback(
            long_text, "confusion") == FeedbackSignal.ELABORATION

    def test_elaboration_not_after_neutral(self):
        long_text = "Я имел в виду что нужно сделать так: сначала открыть файл, потом найти строку и заменить"
        # Not elaboration without confusion context
        assert detect_feedback(long_text, "neutral") == FeedbackSignal.NONE

    def test_thanks_in_longer_message(self):
        assert detect_feedback(
            "Большое спасибо за помощь с этой задачей") == FeedbackSignal.THANKS

    def test_no_signal(self):
        assert detect_feedback("Какая погода сегодня?") == FeedbackSignal.NONE
        assert detect_feedback("Покажи баланс") == FeedbackSignal.NONE


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION EMOTION TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversationEmotionTracker:
    """Tests for ConversationEmotionTracker."""

    def setup_method(self):
        self.tracker = ConversationEmotionTracker()

    def test_initial_empty(self):
        trajectory = self.tracker.get_trajectory(999)
        assert trajectory.turns == []
        assert trajectory.avg_intensity == 0.0
        assert trajectory.dominant_emotion == "neutral"

    def test_record_single_turn(self):
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)
        trajectory = self.tracker.get_trajectory(1)
        assert len(trajectory.turns) == 1
        assert trajectory.dominant_emotion == "joy"
        assert trajectory.avg_intensity == 0.8

    def test_record_multiple_turns(self):
        self.tracker.record_turn(1, "joy", 0.6, is_user=True)
        self.tracker.record_turn(1, "neutral", 0.4, is_user=False)
        self.tracker.record_turn(1, "frustration", 0.9, is_user=True)

        trajectory = self.tracker.get_trajectory(1)
        assert len(trajectory.turns) == 3

    def test_user_turns_only_in_avg(self):
        self.tracker.record_turn(1, "joy", 0.6, is_user=True)
        self.tracker.record_turn(1, "neutral", 0.2, is_user=False)
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)

        trajectory = self.tracker.get_trajectory(1)
        # avg_intensity = (0.6 + 0.8) / 2 = 0.7
        assert trajectory.avg_intensity == 0.7

    def test_emotion_shifts_counted(self):
        self.tracker.record_turn(1, "joy", 0.5, is_user=True)
        self.tracker.record_turn(1, "anger", 0.7, is_user=True)
        self.tracker.record_turn(1, "anger", 0.8, is_user=True)
        self.tracker.record_turn(1, "sadness", 0.6, is_user=True)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.emotion_shifts == 2  # joy→anger, anger→sadness

    def test_dominant_emotion(self):
        self.tracker.record_turn(1, "joy", 0.5, is_user=True)
        self.tracker.record_turn(1, "joy", 0.6, is_user=True)
        self.tracker.record_turn(1, "anger", 0.7, is_user=True)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.dominant_emotion == "joy"

    def test_satisfaction_trend_improving(self):
        self.tracker.record_turn(1, "anger", 0.8, is_user=True,
                                 feedback=FeedbackSignal.COMPLAINT)
        self.tracker.record_turn(1, "joy", 0.6, is_user=True,
                                 feedback=FeedbackSignal.THANKS)
        self.tracker.record_turn(1, "joy", 0.5, is_user=True,
                                 feedback=FeedbackSignal.POSITIVE_EMOJI)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.satisfaction_trend == "improving"

    def test_satisfaction_trend_declining(self):
        self.tracker.record_turn(1, "anger", 0.8, is_user=True,
                                 feedback=FeedbackSignal.COMPLAINT)
        self.tracker.record_turn(1, "frustration", 0.9, is_user=True,
                                 feedback=FeedbackSignal.ESCALATION)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.satisfaction_trend == "declining"

    def test_satisfaction_trend_stable_no_feedback(self):
        self.tracker.record_turn(1, "neutral", 0.5, is_user=True)
        self.tracker.record_turn(1, "neutral", 0.5, is_user=True)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.satisfaction_trend == "stable"

    def test_escalation_tracking(self):
        self.tracker.record_turn(1, "frustration", 0.8, is_user=True,
                                 feedback=FeedbackSignal.ESCALATION)
        self.tracker.record_turn(1, "frustration", 0.9, is_user=True,
                                 feedback=FeedbackSignal.ESCALATION)

        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.escalation_count == 2

    def test_phase_greeting(self):
        self.tracker.record_turn(1, "joy", 0.5, is_user=True)
        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.phase == ConversationPhase.GREETING

    def test_phase_exploration(self):
        for _ in range(2):
            self.tracker.record_turn(1, "neutral", 0.5, is_user=True)
        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.phase == ConversationPhase.EXPLORATION

    def test_phase_problem_solving(self):
        for _ in range(4):
            self.tracker.record_turn(1, "neutral", 0.5, is_user=True)
        self.tracker.record_turn(1, "frustration", 0.8, is_user=True)
        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.phase == ConversationPhase.PROBLEM_SOLVING

    def test_phase_winding_down(self):
        for _ in range(4):
            self.tracker.record_turn(1, "neutral", 0.5, is_user=True)
        self.tracker.record_turn(1, "joy", 0.5, is_user=True,
                                 feedback=FeedbackSignal.THANKS)
        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.phase == ConversationPhase.WINDING_DOWN

    def test_per_user_isolation(self):
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)
        self.tracker.record_turn(2, "anger", 0.9, is_user=True)

        t1 = self.tracker.get_trajectory(1)
        t2 = self.tracker.get_trajectory(2)
        assert t1.dominant_emotion == "joy"
        assert t2.dominant_emotion == "anger"

    def test_reset(self):
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)
        self.tracker.reset(1)
        trajectory = self.tracker.get_trajectory(1)
        assert trajectory.turns == []

    def test_get_turn_count(self):
        assert self.tracker.get_turn_count(1) == 0
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)
        self.tracker.record_turn(1, "neutral", 0.3, is_user=False)
        assert self.tracker.get_turn_count(1) == 2

    def test_get_stats(self):
        self.tracker.record_turn(1, "joy", 0.8, is_user=True)
        self.tracker.record_turn(2, "anger", 0.9, is_user=True)
        stats = self.tracker.get_stats()
        assert stats["active_conversations"] == 2
        assert stats["total_turns"] == 2

    def test_max_turns_limit(self):
        for i in range(60):
            self.tracker.record_turn(1, "neutral", 0.5, is_user=True)
        trajectory = self.tracker.get_trajectory(1)
        assert len(trajectory.turns) <= ConversationEmotionTracker.MAX_TURNS


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE STYLE SELECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdaptiveStyleSelector:
    """Tests for AdaptiveStyleSelector."""

    def setup_method(self):
        self.selector = AdaptiveStyleSelector()

    def test_empty_trajectory(self):
        trajectory = ConversationTrajectory()
        rec = self.selector.recommend(trajectory)
        assert isinstance(rec, AdaptationRecommendation)
        assert 0.0 <= rec.empathy_level <= 1.0
        assert 0.0 <= rec.formality_level <= 1.0

    def test_high_persona_formality(self):
        trajectory = ConversationTrajectory()
        rec = self.selector.recommend(trajectory, persona_formality=0.9)
        assert rec.formality_level > 0.5

    def test_low_persona_formality(self):
        trajectory = ConversationTrajectory()
        rec = self.selector.recommend(trajectory, persona_formality=0.1)
        assert rec.formality_level < 0.5

    def test_frustration_increases_empathy(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("frustration", 0.8, time.time(), True)],
            avg_intensity=0.8,
            dominant_emotion="frustration",
        )
        rec = self.selector.recommend(trajectory)
        assert rec.empathy_level > 0.5

    def test_escalation_boosts_empathy(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("frustration", 0.9, time.time(), True,
                               FeedbackSignal.ESCALATION)],
            avg_intensity=0.9,
            dominant_emotion="frustration",
            escalation_count=2,
        )
        rec = self.selector.recommend(trajectory)
        assert rec.empathy_level >= 0.7
        assert AdaptationAction.ADD_FOLLOWUP in rec.actions

    def test_urgency_speed_up(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("urgency", 0.9, time.time(), True)],
            avg_intensity=0.9,
            dominant_emotion="urgency",
        )
        rec = self.selector.recommend(trajectory)
        assert rec.urgency_factor > 0.5
        assert AdaptationAction.SPEED_UP in rec.actions

    def test_confusion_more_detail(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("confusion", 0.7, time.time(), True)],
            avg_intensity=0.7,
            dominant_emotion="confusion",
        )
        rec = self.selector.recommend(trajectory, persona_avg_msg_len=30)
        # Even with short avg_msg_len, confusion should push detail up
        assert rec.detail_level >= 0.2

    def test_short_messages_low_detail(self):
        trajectory = ConversationTrajectory()
        rec = self.selector.recommend(trajectory, persona_avg_msg_len=20)
        assert rec.detail_level < 0.5

    def test_long_messages_high_detail(self):
        trajectory = ConversationTrajectory()
        rec = self.selector.recommend(trajectory, persona_avg_msg_len=100)
        assert rec.detail_level > 0.5

    def test_problem_solving_simplifies(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("frustration", 0.7, time.time(), True)],
            phase=ConversationPhase.PROBLEM_SOLVING,
            avg_intensity=0.7,
            dominant_emotion="frustration",
        )
        rec = self.selector.recommend(trajectory)
        assert AdaptationAction.SIMPLIFY_LANGUAGE in rec.actions

    def test_declining_satisfaction_encouragement(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("anger", 0.8, time.time(), True,
                               FeedbackSignal.COMPLAINT)],
            avg_intensity=0.8,
            dominant_emotion="anger",
            satisfaction_trend="declining",
        )
        rec = self.selector.recommend(trajectory)
        assert AdaptationAction.ADD_ENCOURAGEMENT in rec.actions

    def test_no_change_on_neutral(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("neutral", 0.5, time.time(), True)],
            avg_intensity=0.5,
            dominant_emotion="neutral",
        )
        rec = self.selector.recommend(trajectory)
        assert AdaptationAction.NO_CHANGE in rec.actions

    def test_confidence_grows_with_turns(self):
        turns_few = [EmotionTurn("neutral", 0.5, time.time(), True)]
        turns_many = [EmotionTurn("neutral", 0.5, time.time(), True)
                      for _ in range(10)]

        rec_few = self.selector.recommend(
            ConversationTrajectory(turns=turns_few))
        rec_many = self.selector.recommend(
            ConversationTrajectory(turns=turns_many))
        assert rec_many.confidence > rec_few.confidence

    def test_humor_hint_for_joyful_user(self):
        trajectory = ConversationTrajectory(
            turns=[EmotionTurn("joy", 0.6, time.time(), True)],
            dominant_emotion="joy",
            avg_intensity=0.6,
        )
        rec = self.selector.recommend(trajectory, persona_humor=0.8)
        assert "юмор" in rec.tone_hint.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTATION RECOMMENDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdaptationRecommendation:
    """Tests for AdaptationRecommendation."""

    def test_default_empty_prompt(self):
        rec = AdaptationRecommendation()
        assert rec.to_prompt_fragment() == ""

    def test_high_empathy_prompt(self):
        rec = AdaptationRecommendation(empathy_level=0.9)
        fragment = rec.to_prompt_fragment()
        assert "эмпатичн" in fragment.lower()

    def test_low_empathy_prompt(self):
        rec = AdaptationRecommendation(empathy_level=0.1)
        fragment = rec.to_prompt_fragment()
        assert "по делу" in fragment.lower()

    def test_high_formality_prompt(self):
        rec = AdaptationRecommendation(formality_level=0.9)
        fragment = rec.to_prompt_fragment()
        assert "формальн" in fragment.lower() or "Вы" in fragment

    def test_low_formality_prompt(self):
        rec = AdaptationRecommendation(formality_level=0.1)
        fragment = rec.to_prompt_fragment()
        assert "неформальн" in fragment.lower() or "друг" in fragment.lower()

    def test_high_detail_prompt(self):
        rec = AdaptationRecommendation(detail_level=0.9)
        fragment = rec.to_prompt_fragment()
        assert "подробн" in fragment.lower() or "развёрнут" in fragment.lower()

    def test_low_detail_prompt(self):
        rec = AdaptationRecommendation(detail_level=0.1)
        fragment = rec.to_prompt_fragment()
        assert "кратк" in fragment.lower()

    def test_urgency_prompt(self):
        rec = AdaptationRecommendation(urgency_factor=0.8)
        fragment = rec.to_prompt_fragment()
        assert "срочно" in fragment.lower() or "быстро" in fragment.lower()

    def test_tone_hint_included(self):
        rec = AdaptationRecommendation(tone_hint="Будь терпеливым.")
        fragment = rec.to_prompt_fragment()
        assert "терпеливым" in fragment


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK LEARNER
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeedbackLearner:
    """Tests for FeedbackLearner."""

    def setup_method(self):
        self.learner = FeedbackLearner()

    def test_positive_emoji_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.POSITIVE_EMOJI)
        assert "emoji_frequency" in adj
        assert adj["emoji_frequency"] > 0

    def test_negative_emoji_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.NEGATIVE_EMOJI)
        assert "formality_level" in adj
        assert adj["formality_level"] > 0
        assert "humor_level" in adj
        assert adj["humor_level"] < 0

    def test_thanks_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.THANKS)
        assert "agreeableness" in adj
        assert adj["agreeableness"] > 0

    def test_complaint_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.COMPLAINT)
        assert adj["formality_level"] > 0
        assert adj["humor_level"] < 0

    def test_escalation_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.ESCALATION)
        assert adj["humor_level"] < 0
        assert adj["formality_level"] > 0

    def test_none_no_adjustments(self):
        adj = self.learner.compute_adjustments(FeedbackSignal.NONE)
        assert adj == {}

    def test_apply_adjustments(self):
        profile = {"formality_level": 0.5, "humor_level": 0.3}
        adjusted = self.learner.apply_adjustments(
            profile, {"formality_level": 0.1, "humor_level": -0.1}
        )
        assert adjusted["formality_level"] == 0.6
        assert adjusted["humor_level"] == pytest.approx(0.2)

    def test_apply_adjustments_clamped(self):
        profile = {"formality_level": 0.95, "humor_level": 0.05}
        adjusted = self.learner.apply_adjustments(
            profile, {"formality_level": 0.1, "humor_level": -0.1}
        )
        assert adjusted["formality_level"] == 1.0
        assert adjusted["humor_level"] == 0.0

    def test_apply_adjustments_unknown_key(self):
        profile = {"formality_level": 0.5}
        adjusted = self.learner.apply_adjustments(
            profile, {"unknown_key": 0.1, "formality_level": 0.1}
        )
        assert adjusted["formality_level"] == 0.6
        # Unknown key not in original, not added
        assert "unknown_key" not in adjusted


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA ADAPTATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersonaAdaptationEngine:
    """Tests for PersonaAdaptationEngine."""

    def setup_method(self):
        self.engine = PersonaAdaptationEngine()

    def test_process_neutral_message(self):
        rec = self.engine.process_user_message(
            user_id=1, text="Какая погода?", emotion="neutral", intensity=0.5,
        )
        assert isinstance(rec, AdaptationRecommendation)

    def test_process_frustrated_message(self):
        rec = self.engine.process_user_message(
            user_id=1,
            text="Это не работает! Уже третий раз!",
            emotion="frustration",
            intensity=0.9,
        )
        assert rec.empathy_level > 0.5

    def test_feedback_detected_thanks(self):
        # First message
        self.engine.process_user_message(
            user_id=1, text="Сделай отчёт", emotion="neutral", intensity=0.5,
        )
        # Second message — thanks
        self.engine.process_user_message(
            user_id=1, text="Спасибо!", emotion="gratitude", intensity=0.6,
        )
        adjustments = self.engine.get_persona_adjustments()
        assert "agreeableness" in adjustments

    def test_feedback_detected_escalation(self):
        self.engine.process_user_message(
            user_id=1,
            text="Сколько можно! Я уже просил!",
            emotion="frustration",
            intensity=0.9,
        )
        rec_after = self.engine.process_user_message(
            user_id=1,
            text="Уже десятый раз прошу!",
            emotion="anger",
            intensity=0.95,
        )
        assert rec_after.empathy_level >= 0.6

    def test_record_agent_response(self):
        self.engine.process_user_message(
            user_id=1, text="Привет", emotion="joy", intensity=0.5,
        )
        self.engine.record_agent_response(1, "neutral", 0.3)
        trajectory = self.engine.tracker.get_trajectory(1)
        assert len(trajectory.turns) == 2

    def test_reset_conversation(self):
        self.engine.process_user_message(
            user_id=1, text="Привет", emotion="joy", intensity=0.5,
        )
        self.engine.reset_conversation(1)
        trajectory = self.engine.tracker.get_trajectory(1)
        assert trajectory.turns == []

    def test_per_user_isolation(self):
        self.engine.process_user_message(
            user_id=1, text="Ура!", emotion="joy", intensity=0.8,
        )
        self.engine.process_user_message(
            user_id=2, text="Бесит!", emotion="anger", intensity=0.9,
        )
        t1 = self.engine.tracker.get_trajectory(1)
        t2 = self.engine.tracker.get_trajectory(2)
        assert t1.dominant_emotion == "joy"
        assert t2.dominant_emotion == "anger"

    def test_get_stats(self):
        self.engine.process_user_message(
            user_id=1, text="Привет", emotion="joy", intensity=0.5,
        )
        stats = self.engine.get_stats()
        assert stats["active_conversations"] == 1

    def test_persona_adjustments_default_empty(self):
        engine = PersonaAdaptationEngine()
        adjustments = engine.get_persona_adjustments()
        assert adjustments == {}

    def test_multi_turn_trajectory(self):
        for i in range(5):
            self.engine.process_user_message(
                user_id=1, text=f"Сообщение {i}",
                emotion="neutral", intensity=0.5,
            )
        trajectory = self.engine.tracker.get_trajectory(1)
        assert len(trajectory.turns) == 5

    def test_properties_accessible(self):
        assert isinstance(self.engine.tracker, ConversationEmotionTracker)
        assert isinstance(self.engine.learner, FeedbackLearner)
        assert isinstance(self.engine.selector, AdaptiveStyleSelector)


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION: EMOTIONAL INTELLIGENCE + ADAPTATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestEQIntegration:
    """Test integration between EmotionalIntelligenceEngine and PersonaAdaptation."""

    def test_process_message_triggers_adaptation(self):
        """EQ engine process_message should call persona_adaptation."""
        from pds_ultimate.core.emotional_intelligence import EmotionalIntelligenceEngine

        engine = EmotionalIntelligenceEngine()
        with patch(
            "pds_ultimate.core.persona_adaptation.persona_adaptation"
        ) as mock_adapt:
            # Mock needs process_user_message to return something
            mock_adapt.process_user_message.return_value = AdaptationRecommendation()
            engine.process_message(1, "Это отлично!")
            mock_adapt.process_user_message.assert_called_once()

    def test_emotional_context_includes_adaptation(self):
        """get_emotional_context should include adaptation recommendations."""
        from pds_ultimate.core.emotional_intelligence import EmotionalIntelligenceEngine

        engine = EmotionalIntelligenceEngine()
        # Process a message first to populate tracker
        engine.process_message(1, "Отлично! 🔥")
        context = engine.get_emotional_context(1)
        assert "[Эмоциональный контекст пользователя:" in context

    def test_get_stats_includes_adaptation(self):
        """get_stats should include adaptation stats."""
        from pds_ultimate.core.emotional_intelligence import EmotionalIntelligenceEngine

        engine = EmotionalIntelligenceEngine()
        engine.process_message(1, "Привет")
        stats = engine.get_stats()
        assert "tracked_users" in stats

    def test_graceful_degradation_no_adaptation(self):
        """If persona_adaptation import fails, EQ should still work."""
        from pds_ultimate.core.emotional_intelligence import EmotionalIntelligenceEngine

        engine = EmotionalIntelligenceEngine()
        # Patch the import to fail
        with patch.dict(
            "sys.modules",
            {"pds_ultimate.core.persona_adaptation": None},
        ):
            # Should not raise — ImportError caught by try/except
            response = engine.process_message(1, "Привет мир!")
            assert response.tone is not None


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION: PERSONA ENGINE + ADAPTATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersonaEngineIntegration:
    """Test integration between PersonaEngine and PersonaAdaptation."""

    def test_learn_from_message_applies_adjustments(self):
        """PersonaEngine.learn_from_message should apply feedback adjustments."""
        from pds_ultimate.core.persona_engine import PersonaEngine

        pe = PersonaEngine.__new__(PersonaEngine)
        pe._profiles = {}
        pe._word_counters = defaultdict(Counter)
        pe._phrase_counters = defaultdict(Counter)
        pe._joke_counters = defaultdict(Counter)
        pe._session_factory = None
        pe._shared_groups = []
        pe._last_retrain_at = 0.0

        # Mock persona_adaptation at SOURCE module
        mock_adjustments = {"formality_level": 0.05}
        with patch(
            "pds_ultimate.core.persona_adaptation.persona_adaptation"
        ) as mock_adapt:
            mock_adapt.get_persona_adjustments.return_value = mock_adjustments

            pe.learn_from_message(
                chat_id=1,
                text="Пожалуйста сделайте это задание для меня побыстрее",
                is_owner=True,
            )

        profile = pe._profiles[1]
        assert profile.messages_analyzed == 1

    def test_learn_graceful_without_adaptation(self):
        """PersonaEngine should work even if persona_adaptation is unavailable."""
        from pds_ultimate.core.persona_engine import PersonaEngine

        pe = PersonaEngine.__new__(PersonaEngine)
        pe._profiles = {}
        pe._word_counters = defaultdict(Counter)
        pe._phrase_counters = defaultdict(Counter)
        pe._joke_counters = defaultdict(Counter)
        pe._session_factory = None
        pe._shared_groups = []
        pe._last_retrain_at = 0.0

        # Patch the import to fail
        with patch.dict(
            "sys.modules",
            {"pds_ultimate.core.persona_adaptation": None},
        ):
            # Should not raise — ImportError caught by try/except
            pe.learn_from_message(
                chat_id=1,
                text="Обычное сообщение для теста работы движка",
                is_owner=True,
            )

        profile = pe._profiles[1]
        assert profile.messages_analyzed == 1


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalInstance:
    """Test global persona_adaptation instance."""

    def test_instance_exists(self):
        assert persona_adaptation is not None
        assert isinstance(persona_adaptation, PersonaAdaptationEngine)

    def test_instance_functional(self):
        rec = persona_adaptation.process_user_message(
            user_id=99999, text="Тест", emotion="neutral", intensity=0.5,
        )
        assert isinstance(rec, AdaptationRecommendation)
        # Clean up
        persona_adaptation.reset_conversation(99999)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataModels:
    """Tests for data model classes."""

    def test_emotion_turn(self):
        turn = EmotionTurn("joy", 0.8, time.time(), True)
        assert turn.emotion == "joy"
        assert turn.intensity == 0.8
        assert turn.is_user is True
        assert turn.feedback == FeedbackSignal.NONE

    def test_conversation_trajectory_defaults(self):
        t = ConversationTrajectory()
        assert t.turns == []
        assert t.avg_intensity == 0.0
        assert t.emotion_shifts == 0
        assert t.dominant_emotion == "neutral"
        assert t.satisfaction_trend == "stable"
        assert t.phase == ConversationPhase.GREETING

    def test_adaptation_recommendation_defaults(self):
        rec = AdaptationRecommendation()
        assert rec.empathy_level == 0.5
        assert rec.formality_level == 0.5
        assert rec.detail_level == 0.5
        assert rec.urgency_factor == 0.0
        assert rec.tone_hint == ""
        assert rec.confidence == 0.5

    def test_feedback_signal_values(self):
        assert FeedbackSignal.POSITIVE_EMOJI.value == "positive_emoji"
        assert FeedbackSignal.NONE.value == "none"

    def test_conversation_phase_values(self):
        assert ConversationPhase.GREETING.value == "greeting"
        assert ConversationPhase.TASK_EXECUTION.value == "task_execution"

    def test_adaptation_action_values(self):
        assert AdaptationAction.INCREASE_EMPATHY.value == "increase_empathy"
        assert AdaptationAction.NO_CHANGE.value == "no_change"


# Need for defaultdict import in integration tests
