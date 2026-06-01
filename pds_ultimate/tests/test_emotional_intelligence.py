"""
Тесты для Emotional Intelligence Engine.
==========================================
Покрывает: SentimentAnalyzer, EmotionalStateTracker,
EmpathyEngine, SocialContextAdapter, EmotionalIntelligenceEngine.
"""


from pds_ultimate.core.emotional_intelligence import (
    CommunicationStyle,
    Emotion,
    EmotionalIntelligenceEngine,
    EmotionalState,
    EmotionalStateTracker,
    EmotionScore,
    EmpathicResponse,
    EmpathyEngine,
    ResponseTone,
    SentimentAnalyzer,
    SocialContext,
    SocialContextAdapter,
    emotional_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION ENUM
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmotionEnum:
    """Тесты для Emotion enum."""

    def test_all_emotions_exist(self):
        """Все 12 эмоций доступны."""
        names = [e.value for e in Emotion]
        assert "joy" in names
        assert "anger" in names
        assert "frustration" in names
        assert "sadness" in names
        assert "fear" in names
        assert "surprise" in names
        assert "urgency" in names
        assert "confusion" in names
        assert "gratitude" in names
        assert "anticipation" in names
        assert "trust" in names
        assert "neutral" in names

    def test_emotion_count(self):
        assert len(Emotion) == 12


class TestCommunicationStyle:
    def test_styles_exist(self):
        assert CommunicationStyle.FORMAL.value == "formal"
        assert CommunicationStyle.INFORMAL.value == "informal"
        assert CommunicationStyle.BRIEF.value == "brief"


class TestResponseTone:
    def test_tones_exist(self):
        assert ResponseTone.PROFESSIONAL.value == "professional"
        assert ResponseTone.EMPATHETIC.value == "empathetic"
        assert ResponseTone.URGENT.value == "urgent"
        assert ResponseTone.CELEBRATORY.value == "celebratory"


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION SCORE
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmotionScore:
    def test_creation(self):
        score = EmotionScore(Emotion.JOY, 0.8, 0.9)
        assert score.emotion == Emotion.JOY
        assert score.intensity == 0.8
        assert score.confidence == 0.9

    def test_repr(self):
        score = EmotionScore(Emotion.ANGER, 0.5, 0.7)
        assert "anger" in repr(score)
        assert "50%" in repr(score)


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTIONAL STATE
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmotionalState:
    def test_default(self):
        state = EmotionalState()
        assert state.primary_emotion == Emotion.NEUTRAL
        assert state.secondary_emotion is None
        assert state.intensity == 0.5
        assert state.trend == "stable"
        assert state.stress_level == 0.0
        assert state.satisfaction == 0.5

    def test_to_dict(self):
        state = EmotionalState(
            primary_emotion=Emotion.JOY,
            intensity=0.8,
            stress_level=0.2,
        )
        d = state.to_dict()
        assert d["primary"] == "joy"
        assert d["intensity"] == 0.8
        assert d["stress"] == 0.2
        assert "history_len" in d


# ═══════════════════════════════════════════════════════════════════════════════
# SENTIMENT ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════


class TestSentimentAnalyzer:
    """Тесты SentimentAnalyzer — ядро EQ."""

    def setup_method(self):
        self.analyzer = SentimentAnalyzer()

    # ─── Базовые ─────────────────────────────────────────────────────

    def test_empty_text(self):
        result = self.analyzer.analyze("")
        assert len(result) == 1
        assert result[0].emotion == Emotion.NEUTRAL

    def test_whitespace_text(self):
        result = self.analyzer.analyze("   ")
        assert result[0].emotion == Emotion.NEUTRAL

    # ─── Детекция эмоций (русский) ───────────────────────────────────

    def test_joy_russian(self):
        result = self.analyzer.analyze("Отлично! Супер! Класс!")
        assert result[0].emotion == Emotion.JOY

    def test_anger_russian(self):
        result = self.analyzer.analyze("Это бесит меня!")
        assert result[0].emotion == Emotion.ANGER

    def test_frustration_russian(self):
        result = self.analyzer.analyze("Опять не работает, сколько можно!")
        assert result[0].emotion == Emotion.FRUSTRATION

    def test_sadness_russian(self):
        result = self.analyzer.analyze("Грустно, что не получилось")
        assert result[0].emotion == Emotion.SADNESS

    def test_fear_russian(self):
        result = self.analyzer.analyze("Боюсь, что это рискованно")
        assert result[0].emotion == Emotion.FEAR

    def test_urgency_russian(self):
        result = self.analyzer.analyze("Срочно! Немедленно! Горит!")
        assert result[0].emotion == Emotion.URGENCY

    def test_confusion_russian(self):
        result = self.analyzer.analyze("Не понимаю, как это работает")
        assert result[0].emotion == Emotion.CONFUSION

    def test_gratitude_russian(self):
        result = self.analyzer.analyze("Огромное спасибо, очень выручил! 🙏")
        emotions = {r.emotion for r in result}
        assert Emotion.GRATITUDE in emotions

    # ─── Детекция эмоций (English) ──────────────────────────────────

    def test_joy_english(self):
        result = self.analyzer.analyze("Great! Awesome! Perfect!")
        assert result[0].emotion == Emotion.JOY

    def test_frustration_english(self):
        result = self.analyzer.analyze("It doesn't work again, stuck!")
        assert result[0].emotion == Emotion.FRUSTRATION

    # ─── Emoji detection ────────────────────────────────────────────

    def test_emoji_joy(self):
        result = self.analyzer.analyze("😊 😄 🎉")
        assert result[0].emotion == Emotion.JOY

    def test_emoji_anger(self):
        result = self.analyzer.analyze("😡 🤬")
        assert result[0].emotion == Emotion.ANGER

    # ─── detect_primary ─────────────────────────────────────────────

    def test_detect_primary(self):
        assert self.analyzer.detect_primary("Супер!") == Emotion.JOY
        assert self.analyzer.detect_primary("нормально") == Emotion.NEUTRAL

    # ─── Формальность ───────────────────────────────────────────────

    def test_formality_formal(self):
        f = self.analyzer.detect_formality(
            "Уважаемый коллега, будьте добры, пожалуйста"
        )
        assert f > 0.5

    def test_formality_informal(self):
        f = self.analyzer.detect_formality(
            "Привет, хай, ну чё, окей"
        )
        assert f < 0.5

    def test_formality_neutral(self):
        f = self.analyzer.detect_formality("Перезвоню позже")
        assert f == 0.5

    # ─── Срочность ──────────────────────────────────────────────────

    def test_urgency_high(self):
        u = self.analyzer.detect_urgency("СРОЧНО! НЕМЕДЛЕННО!")
        assert u > 0.3

    def test_urgency_low(self):
        u = self.analyzer.detect_urgency("когда будет время, посмотри")
        assert u < 0.3

    # ─── Multiple emotions ──────────────────────────────────────────

    def test_multiple_emotions(self):
        result = self.analyzer.analyze(
            "Спасибо большое! Но боюсь, это рискованно"
        )
        emotions = {r.emotion for r in result}
        assert len(result) >= 2
        assert Emotion.GRATITUDE in emotions or Emotion.FEAR in emotions

    def test_max_5_emotions(self):
        result = self.analyzer.analyze(
            "Спасибо! Отлично! Супер! Срочно! Боюсь! "
            "Не понимаю! Бесит! Грустно!"
        )
        assert len(result) <= 5


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTIONAL STATE TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmotionalStateTracker:
    """Тесты EmotionalStateTracker."""

    def setup_method(self):
        self.tracker = EmotionalStateTracker()

    def test_get_initial_state(self):
        state = self.tracker.get_state(123)
        assert state.primary_emotion == Emotion.NEUTRAL
        assert state.intensity == 0.5

    def test_update_joy(self):
        emotions = [EmotionScore(Emotion.JOY, 0.8, 0.9)]
        state = self.tracker.update(123, emotions)
        assert state.primary_emotion == Emotion.JOY
        assert state.satisfaction > 0.5  # satisfaction растёт от joy

    def test_update_anger_stress(self):
        emotions = [EmotionScore(Emotion.ANGER, 0.9, 0.9)]
        state = self.tracker.update(123, emotions)
        assert state.primary_emotion == Emotion.ANGER
        assert state.stress_level > 0.0  # stress растёт от anger

    def test_ema_smoothing(self):
        """EMA сглаживает скачки."""
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 1.0, 0.9)])
        state = self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.2, 0.9)])
        # Из-за EMA intensity не упадёт до 0.2 сразу
        assert state.intensity > 0.2

    def test_trend_stable(self):
        self.tracker.update(1, [EmotionScore(Emotion.NEUTRAL, 0.5, 0.9)])
        state = self.tracker.update(
            1, [EmotionScore(Emotion.NEUTRAL, 0.5, 0.9)]
        )
        assert state.trend == "stable"

    def test_trend_changed(self):
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        state = self.tracker.update(
            1, [EmotionScore(Emotion.ANGER, 0.8, 0.9)]
        )
        assert state.trend == "changed"

    def test_history_tracking(self):
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        self.tracker.update(1, [EmotionScore(Emotion.ANGER, 0.5, 0.9)])
        state = self.tracker.get_state(1)
        assert len(state.history) == 2
        assert Emotion.JOY in state.history
        assert Emotion.ANGER in state.history

    def test_empty_emotions(self):
        state = self.tracker.update(1, [])
        assert state.primary_emotion == Emotion.NEUTRAL

    def test_secondary_emotion(self):
        emotions = [
            EmotionScore(Emotion.JOY, 0.8, 0.9),
            EmotionScore(Emotion.GRATITUDE, 0.5, 0.8),
        ]
        state = self.tracker.update(1, emotions)
        assert state.secondary_emotion == Emotion.GRATITUDE

    def test_mood_summary(self):
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        summary = self.tracker.get_mood_summary(1)
        assert "позитивное" in summary

    def test_mood_summary_stress(self):
        for _ in range(5):
            self.tracker.update(
                1, [EmotionScore(Emotion.ANGER, 0.9, 0.9)]
            )
        summary = self.tracker.get_mood_summary(1)
        assert "стресс" in summary

    def test_stats(self):
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        self.tracker.update(2, [EmotionScore(Emotion.NEUTRAL, 0.5, 0.9)])
        stats = self.tracker.get_stats()
        assert stats["tracked_users"] == 2

    def test_per_user_isolation(self):
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        self.tracker.update(2, [EmotionScore(Emotion.ANGER, 0.9, 0.9)])
        assert self.tracker.get_state(1).primary_emotion == Emotion.JOY
        assert self.tracker.get_state(2).primary_emotion == Emotion.ANGER

    def test_satisfaction_increases_on_positive(self):
        initial = self.tracker.get_state(1).satisfaction
        self.tracker.update(1, [EmotionScore(Emotion.JOY, 0.8, 0.9)])
        assert self.tracker.get_state(1).satisfaction > initial

    def test_satisfaction_decreases_on_negative(self):
        initial = self.tracker.get_state(1).satisfaction
        self.tracker.update(1, [EmotionScore(Emotion.ANGER, 0.8, 0.9)])
        assert self.tracker.get_state(1).satisfaction < initial


# ═══════════════════════════════════════════════════════════════════════════════
# EMPATHY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmpathyEngine:
    """Тесты EmpathyEngine."""

    def setup_method(self):
        self.engine = EmpathyEngine()

    def _make_state(self, emotion, intensity=0.7, stress=0.3):
        return EmotionalState(
            primary_emotion=emotion,
            intensity=intensity,
            stress_level=stress,
        )

    def test_joy_response(self):
        state = self._make_state(Emotion.JOY, 0.9)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.CELEBRATORY
        assert len(resp.prefix) > 0

    def test_urgency_response(self):
        state = self._make_state(Emotion.URGENCY)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.URGENT

    def test_anger_high_stress(self):
        state = self._make_state(Emotion.ANGER, stress=0.7)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.CALM

    def test_confusion_followup(self):
        state = self._make_state(Emotion.CONFUSION, intensity=0.8)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.should_ask_followup is True
        assert len(resp.suggested_followup) > 0

    def test_frustration_followup(self):
        state = self._make_state(Emotion.FRUSTRATION, intensity=0.8)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.should_ask_followup is True

    def test_neutral_no_followup(self):
        state = self._make_state(Emotion.NEUTRAL, intensity=0.3)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.should_ask_followup is False

    def test_formal_adaptation(self):
        state = self._make_state(Emotion.JOY, 0.9)
        social = SocialContext(formality_level=0.8)
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.CELEBRATORY

    def test_style_hints_present(self):
        state = self._make_state(Emotion.NEUTRAL)
        social = SocialContext(communication_style=CommunicationStyle.BRIEF)
        resp = self.engine.generate_response(state, social)
        assert "tone" in resp.style_hints
        assert "brevity" in resp.style_hints

    def test_gratitude_tone(self):
        state = self._make_state(Emotion.GRATITUDE)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.ENCOURAGING

    def test_sadness_empathetic(self):
        state = self._make_state(Emotion.SADNESS)
        social = SocialContext()
        resp = self.engine.generate_response(state, social)
        assert resp.tone == ResponseTone.EMPATHETIC


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL CONTEXT ADAPTER
# ═══════════════════════════════════════════════════════════════════════════════


class TestSocialContextAdapter:
    """Тесты SocialContextAdapter."""

    def setup_method(self):
        self.adapter = SocialContextAdapter()
        self.analyzer = SentimentAnalyzer()

    def test_initial_context(self):
        ctx = self.adapter.get_context(1)
        assert ctx.interaction_count == 0
        assert ctx.formality_level == 0.5

    def test_update_formal(self):
        ctx = self.adapter.update_from_message(
            1, "Уважаемый коллега, будьте добры, пожалуйста",
            self.analyzer,
        )
        assert ctx.formality_level > 0.5

    def test_update_informal(self):
        ctx = self.adapter.update_from_message(
            1, "Привет, хай, чё как, окей?",
            self.analyzer,
        )
        assert ctx.formality_level < 0.5

    def test_interaction_count(self):
        self.adapter.update_from_message(1, "привет", self.analyzer)
        self.adapter.update_from_message(1, "как дела", self.analyzer)
        ctx = self.adapter.get_context(1)
        assert ctx.interaction_count == 2

    def test_relationship_depth_grows(self):
        for _ in range(20):
            self.adapter.update_from_message(1, "тест", self.analyzer)
        ctx = self.adapter.get_context(1)
        assert ctx.relationship_depth > 0.0

    def test_brief_style(self):
        ctx = self.adapter.update_from_message(1, "окей", self.analyzer)
        assert ctx.communication_style == CommunicationStyle.BRIEF

    def test_style_prompt_formal(self):
        self.adapter._contexts[1] = SocialContext(formality_level=0.8)
        prompt = self.adapter.get_style_prompt(1)
        assert "формальный" in prompt or "Вы" in prompt

    def test_style_prompt_informal(self):
        self.adapter._contexts[1] = SocialContext(formality_level=0.2)
        prompt = self.adapter.get_style_prompt(1)
        assert "неформальный" in prompt or "ты" in prompt

    def test_style_prompt_empty(self):
        prompt = self.adapter.get_style_prompt(999)
        assert prompt == ""

    def test_urgency_detected(self):
        ctx = self.adapter.update_from_message(
            1, "СРОЧНО! НЕМЕДЛЕННО!",
            self.analyzer,
        )
        assert ctx.urgency_level > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# EMOTIONAL INTELLIGENCE ENGINE (main orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmotionalIntelligenceEngine:
    """Тесты EmotionalIntelligenceEngine — главный оркестратор."""

    def setup_method(self):
        self.engine = EmotionalIntelligenceEngine()

    def test_process_joy(self):
        resp = self.engine.process_message(1, "Отлично! Супер! Круто!")
        assert isinstance(resp, EmpathicResponse)
        state = self.engine.tracker.get_state(1)
        assert state.primary_emotion == Emotion.JOY

    def test_process_anger(self):
        resp = self.engine.process_message(1, "Это бесит! 😡")
        assert resp.tone in (ResponseTone.CALM, ResponseTone.SUPPORTIVE)

    def test_process_neutral(self):
        resp = self.engine.process_message(1, "Перезвони через час")
        assert resp.tone == ResponseTone.PROFESSIONAL

    def test_state_updated(self):
        self.engine.process_message(1, "Супер! Отлично!")
        state = self.engine.tracker.get_state(1)
        assert state.primary_emotion == Emotion.JOY

    def test_social_context_updated(self):
        self.engine.process_message(1, "Привет, хай!")
        ctx = self.engine.social.get_context(1)
        assert ctx.interaction_count == 1

    def test_emotional_context_string(self):
        self.engine.process_message(1, "Срочно! Горит!")
        context = self.engine.get_emotional_context(1)
        assert "Эмоциональный контекст" in context

    def test_emotional_context_stress_warning(self):
        for _ in range(5):
            self.engine.process_message(1, "Бесит! Злость! 😡")
        context = self.engine.get_emotional_context(1)
        assert "стресс" in context.lower() or "внимательным" in context

    def test_get_stats(self):
        self.engine.process_message(1, "тест")
        stats = self.engine.get_stats()
        assert stats["tracked_users"] >= 1
        assert "social_contexts" in stats

    def test_properties(self):
        assert isinstance(self.engine.analyzer, SentimentAnalyzer)
        assert isinstance(self.engine.tracker, EmotionalStateTracker)
        assert isinstance(self.engine.empathy, EmpathyEngine)
        assert isinstance(self.engine.social, SocialContextAdapter)

    def test_multi_user(self):
        self.engine.process_message(1, "Супер!")
        self.engine.process_message(2, "Бесит!")
        assert self.engine.tracker.get_state(1).primary_emotion == Emotion.JOY
        assert self.engine.tracker.get_state(
            2).primary_emotion == Emotion.ANGER


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalInstance:
    def test_emotional_engine_exists(self):
        assert emotional_engine is not None
        assert isinstance(emotional_engine, EmotionalIntelligenceEngine)
