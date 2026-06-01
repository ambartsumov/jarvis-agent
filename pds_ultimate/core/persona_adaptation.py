"""
PDS-Ultimate Real-time Persona Adaptation Engine
==================================================
Step 9: Bridges PersonaEngine + EmotionalIntelligence for real-time adaptation.

Key capabilities:
1. ConversationEmotionTracker — tracks emotional trajectory within a conversation
2. FeedbackLoop — user reactions (emoji, short replies) update persona in real-time
3. AdaptiveStyleSelector — dynamically adjusts tone based on EQ + persona data
4. PersonaAdaptationEngine — orchestrates all components

Design: Pure logic, no LLM calls, no async, no I/O in hot path.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from pds_ultimate.config import logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class FeedbackSignal(str, Enum):
    """Types of implicit feedback from user behavior."""
    POSITIVE_EMOJI = "positive_emoji"       # 👍 ❤️ 🔥 etc.
    NEGATIVE_EMOJI = "negative_emoji"       # 👎 😡 etc.
    THANKS = "thanks"                       # спасибо, thank you
    COMPLAINT = "complaint"                 # не то, не работает
    SHORT_ACK = "short_ack"                 # ок, да, хорошо
    REPEAT_REQUEST = "repeat_request"       # повтори, ещё раз
    ESCALATION = "escalation"              # уже N раз прошу...
    TOPIC_CHANGE = "topic_change"          # abrupt topic switch
    ELABORATION = "elaboration"            # user explains more → confusion
    NONE = "none"


class ConversationPhase(str, Enum):
    """Phase of the conversation — affects style decisions."""
    GREETING = "greeting"
    EXPLORATION = "exploration"     # user exploring capabilities
    TASK_EXECUTION = "task_execution"
    PROBLEM_SOLVING = "problem_solving"
    WINDING_DOWN = "winding_down"
    FOLLOW_UP = "follow_up"


class AdaptationAction(str, Enum):
    """Actions the adaptation engine recommends."""
    INCREASE_EMPATHY = "increase_empathy"
    DECREASE_EMPATHY = "decrease_empathy"
    INCREASE_FORMALITY = "increase_formality"
    DECREASE_FORMALITY = "decrease_formality"
    INCREASE_DETAIL = "increase_detail"
    DECREASE_DETAIL = "decrease_detail"
    ADD_ENCOURAGEMENT = "add_encouragement"
    ADD_FOLLOWUP = "add_followup"
    SIMPLIFY_LANGUAGE = "simplify_language"
    SPEED_UP = "speed_up"
    NO_CHANGE = "no_change"


@dataclass
class EmotionTurn:
    """Single turn's emotional data."""
    emotion: str
    intensity: float
    timestamp: float
    is_user: bool  # True = user message, False = agent response
    feedback: FeedbackSignal = FeedbackSignal.NONE


@dataclass
class ConversationTrajectory:
    """Summary of emotional trajectory across a conversation."""
    turns: list[EmotionTurn] = field(default_factory=list)
    avg_intensity: float = 0.0
    emotion_shifts: int = 0
    dominant_emotion: str = "neutral"
    satisfaction_trend: str = "stable"  # improving, declining, stable
    phase: ConversationPhase = ConversationPhase.GREETING
    escalation_count: int = 0


@dataclass
class AdaptationRecommendation:
    """What the engine recommends for the next response."""
    actions: list[AdaptationAction] = field(default_factory=list)
    empathy_level: float = 0.5      # 0-1 how empathetic to be
    formality_level: float = 0.5    # 0-1
    detail_level: float = 0.5       # 0-1 how detailed
    urgency_factor: float = 0.0     # 0-1
    tone_hint: str = ""             # free-form hint for LLM
    confidence: float = 0.5         # how confident in recommendation

    def to_prompt_fragment(self) -> str:
        """Convert to a fragment for LLM system prompt."""
        parts: list[str] = []

        if self.empathy_level > 0.7:
            parts.append(
                "Будь очень эмпатичным и внимательным к чувствам пользователя.")
        elif self.empathy_level < 0.3:
            parts.append("Отвечай по делу, без лишних эмоций.")

        if self.formality_level > 0.7:
            parts.append("Используй формальный стиль, обращение на «Вы».")
        elif self.formality_level < 0.3:
            parts.append("Общайся неформально, как друг.")

        if self.detail_level > 0.7:
            parts.append("Давай подробный развёрнутый ответ.")
        elif self.detail_level < 0.3:
            parts.append("Будь максимально кратким.")

        if self.urgency_factor > 0.6:
            parts.append("Отвечай быстро и по существу, это срочно!")

        if self.tone_hint:
            parts.append(self.tone_hint)

        return " ".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK SIGNAL DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns for feedback detection
_POSITIVE_EMOJI_SET = frozenset("👍❤️🔥💪👏✨🎉🥳😊😄💐🌟⭐🙏")
_NEGATIVE_EMOJI_SET = frozenset("👎😡🤬💢😤😩🙄😑")
_THANKS_PATTERNS = frozenset([
    "спасибо", "благодарю", "thank", "thanks", "thx", "мерси",
    "выручил", "помог", "appreciate",
])
_COMPLAINT_PATTERNS = frozenset([
    "не то", "не работает", "неправильно", "ошибка", "не так",
    "wrong", "incorrect", "doesn't work", "not what", "broken",
])
_ACK_PATTERNS = frozenset([
    "ок", "ok", "да", "хорошо", "ладно", "понял", "принял",
    "ясно", "угу", "ага", "got it", "fine", "alright", "yes",
])
_REPEAT_PATTERNS = frozenset([
    "повтори", "ещё раз", "снова", "опять", "заново",
    "repeat", "again", "retry", "one more time",
])
_ESCALATION_PATTERNS = frozenset([
    "уже", "сколько можно", "в который раз", "опять не",
    "я же говорил", "я просил", "already",
])


def detect_feedback(text: str, previous_emotion: str = "neutral") -> FeedbackSignal:
    """
    Detect implicit feedback signal from user message.

    Checks emoji, keywords, and context to determine user's reaction
    to the previous agent response.
    """
    if not text or not text.strip():
        return FeedbackSignal.NONE

    text_lower = text.lower().strip()

    # Check emoji first (strong signal)
    for ch in text:
        if ch in _POSITIVE_EMOJI_SET:
            return FeedbackSignal.POSITIVE_EMOJI
        if ch in _NEGATIVE_EMOJI_SET:
            return FeedbackSignal.NEGATIVE_EMOJI

    words = text_lower.split()

    # Thanks check BEFORE short ack (thanks is stronger signal)
    for pattern in _THANKS_PATTERNS:
        if pattern in text_lower:
            return FeedbackSignal.THANKS

    # Escalation BEFORE complaint (escalation is a stronger signal)
    for pattern in _ESCALATION_PATTERNS:
        if pattern in text_lower:
            return FeedbackSignal.ESCALATION

    # Complaint
    for pattern in _COMPLAINT_PATTERNS:
        if pattern in text_lower:
            return FeedbackSignal.COMPLAINT

    # Repeat request
    for pattern in _REPEAT_PATTERNS:
        if pattern in text_lower:
            return FeedbackSignal.REPEAT_REQUEST

    # Short acknowledgment (< 4 words, whole-message match)
    if len(words) <= 3:
        for pattern in _ACK_PATTERNS:
            if text_lower == pattern or text_lower.rstrip("!.") == pattern:
                return FeedbackSignal.SHORT_ACK

    # Long explanation after confusion → elaboration
    if previous_emotion in ("confusion", "frustration") and len(words) > 10:
        return FeedbackSignal.ELABORATION

    return FeedbackSignal.NONE


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATION EMOTION TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


class ConversationEmotionTracker:
    """
    Tracks emotional trajectory within a single conversation.

    Unlike EmotionalStateTracker which tracks across all conversations,
    this focuses on the flow within one chat session.
    """

    MAX_TURNS = 50

    def __init__(self):
        self._conversations: dict[int, deque[EmotionTurn]] = {}
        self._phase: dict[int, ConversationPhase] = {}
        self._escalation_counts: dict[int, int] = {}
        self._last_agent_emotion: dict[int, str] = {}

    def record_turn(
        self,
        user_id: int,
        emotion: str,
        intensity: float,
        is_user: bool = True,
        feedback: FeedbackSignal = FeedbackSignal.NONE,
    ) -> None:
        """Record an emotional turn in the conversation."""
        if user_id not in self._conversations:
            self._conversations[user_id] = deque(maxlen=self.MAX_TURNS)
            self._escalation_counts[user_id] = 0

        turn = EmotionTurn(
            emotion=emotion,
            intensity=intensity,
            timestamp=time.time(),
            is_user=is_user,
            feedback=feedback,
        )
        self._conversations[user_id].append(turn)

        # Track escalation
        if feedback == FeedbackSignal.ESCALATION:
            self._escalation_counts[user_id] = (
                self._escalation_counts.get(user_id, 0) + 1
            )

        # Update phase
        self._update_phase(user_id)

    def get_trajectory(self, user_id: int) -> ConversationTrajectory:
        """Get the emotional trajectory for a conversation."""
        turns = list(self._conversations.get(user_id, []))
        if not turns:
            return ConversationTrajectory()

        user_turns = [t for t in turns if t.is_user]
        if not user_turns:
            return ConversationTrajectory(turns=turns)

        # Average intensity
        avg_intensity = sum(t.intensity for t in user_turns) / len(user_turns)

        # Count emotion shifts
        shifts = 0
        for i in range(1, len(user_turns)):
            if user_turns[i].emotion != user_turns[i - 1].emotion:
                shifts += 1

        # Dominant emotion (most frequent)
        emotion_counts: dict[str, int] = {}
        for t in user_turns:
            emotion_counts[t.emotion] = emotion_counts.get(t.emotion, 0) + 1
        dominant = max(emotion_counts, key=emotion_counts.get)

        # Satisfaction trend (based on recent feedback)
        recent_feedback = [
            t.feedback for t in user_turns[-5:]
            if t.feedback != FeedbackSignal.NONE
        ]
        positive_count = sum(
            1 for f in recent_feedback
            if f in (FeedbackSignal.POSITIVE_EMOJI, FeedbackSignal.THANKS,
                     FeedbackSignal.SHORT_ACK)
        )
        negative_count = sum(
            1 for f in recent_feedback
            if f in (FeedbackSignal.NEGATIVE_EMOJI, FeedbackSignal.COMPLAINT,
                     FeedbackSignal.ESCALATION, FeedbackSignal.REPEAT_REQUEST)
        )
        if positive_count > negative_count:
            sat_trend = "improving"
        elif negative_count > positive_count:
            sat_trend = "declining"
        else:
            sat_trend = "stable"

        return ConversationTrajectory(
            turns=turns,
            avg_intensity=round(avg_intensity, 2),
            emotion_shifts=shifts,
            dominant_emotion=dominant,
            satisfaction_trend=sat_trend,
            phase=self._phase.get(user_id, ConversationPhase.GREETING),
            escalation_count=self._escalation_counts.get(user_id, 0),
        )

    def _update_phase(self, user_id: int) -> None:
        """Determine conversation phase from turn count and content."""
        turns = self._conversations.get(user_id, deque())
        user_turns = [t for t in turns if t.is_user]
        count = len(user_turns)

        if count <= 1:
            self._phase[user_id] = ConversationPhase.GREETING
        elif count <= 3:
            self._phase[user_id] = ConversationPhase.EXPLORATION
        else:
            # Check if problem-solving (high frustration/confusion)
            recent = user_turns[-3:]
            problem_emotions = {"frustration", "confusion", "anger"}
            if any(t.emotion in problem_emotions for t in recent):
                self._phase[user_id] = ConversationPhase.PROBLEM_SOLVING
            elif any(t.feedback == FeedbackSignal.THANKS for t in recent):
                self._phase[user_id] = ConversationPhase.WINDING_DOWN
            else:
                self._phase[user_id] = ConversationPhase.TASK_EXECUTION

    def reset(self, user_id: int) -> None:
        """Reset conversation tracking for a user."""
        self._conversations.pop(user_id, None)
        self._phase.pop(user_id, None)
        self._escalation_counts.pop(user_id, None)
        self._last_agent_emotion.pop(user_id, None)

    def get_turn_count(self, user_id: int) -> int:
        """Get number of turns for a user."""
        return len(self._conversations.get(user_id, []))

    def get_stats(self) -> dict:
        """Get statistics about tracked conversations."""
        return {
            "active_conversations": len(self._conversations),
            "total_turns": sum(
                len(turns) for turns in self._conversations.values()
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE STYLE SELECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class AdaptiveStyleSelector:
    """
    Dynamically adjusts response style based on:
    - Conversation trajectory (emotional flow)
    - Persona profile (learned preferences)
    - Feedback signals (implicit reactions)

    Pure logic, no external calls.
    """

    # Weight configuration
    PERSONA_WEIGHT = 0.5      # Long-term learned preferences
    TRAJECTORY_WEIGHT = 0.3   # In-conversation dynamics
    FEEDBACK_WEIGHT = 0.2     # Immediate reaction

    def recommend(
        self,
        trajectory: ConversationTrajectory,
        persona_formality: float = 0.5,
        persona_emoji_freq: float = 0.0,
        persona_humor: float = 0.3,
        persona_avg_msg_len: float = 50.0,
    ) -> AdaptationRecommendation:
        """
        Generate style recommendation based on all available signals.

        Args:
            trajectory: Current conversation emotional trajectory
            persona_formality: Learned formality (0-1) from PersonaEngine
            persona_emoji_freq: Learned emoji frequency from PersonaEngine
            persona_humor: Learned humor level from PersonaEngine
            persona_avg_msg_len: Learned average message length

        Returns:
            AdaptationRecommendation with style parameters
        """
        actions: list[AdaptationAction] = []

        # --- Formality ---
        traj_formality = self._trajectory_formality(trajectory)
        formality = (
            self.PERSONA_WEIGHT * persona_formality
            + self.TRAJECTORY_WEIGHT * traj_formality
            + self.FEEDBACK_WEIGHT * self._feedback_formality(trajectory)
        )
        formality = max(0.0, min(1.0, formality))

        # --- Empathy ---
        empathy = self._compute_empathy(trajectory)

        # --- Detail level ---
        detail = self._compute_detail(trajectory, persona_avg_msg_len)

        # --- Urgency ---
        urgency = self._compute_urgency(trajectory)

        # --- Actions ---
        if empathy > 0.7:
            actions.append(AdaptationAction.INCREASE_EMPATHY)
        elif empathy < 0.3:
            actions.append(AdaptationAction.DECREASE_EMPATHY)

        if formality > 0.7:
            actions.append(AdaptationAction.INCREASE_FORMALITY)
        elif formality < 0.3:
            actions.append(AdaptationAction.DECREASE_FORMALITY)

        if detail > 0.7:
            actions.append(AdaptationAction.INCREASE_DETAIL)
        elif detail < 0.3:
            actions.append(AdaptationAction.DECREASE_DETAIL)

        if urgency > 0.6:
            actions.append(AdaptationAction.SPEED_UP)

        # Escalation → increase empathy + add followup
        if trajectory.escalation_count > 0:
            if AdaptationAction.INCREASE_EMPATHY not in actions:
                actions.append(AdaptationAction.INCREASE_EMPATHY)
            actions.append(AdaptationAction.ADD_FOLLOWUP)
            empathy = max(empathy, 0.7)

        # Problem-solving phase → simplify
        if trajectory.phase == ConversationPhase.PROBLEM_SOLVING:
            if AdaptationAction.SIMPLIFY_LANGUAGE not in actions:
                actions.append(AdaptationAction.SIMPLIFY_LANGUAGE)

        # Declining satisfaction → add encouragement
        if trajectory.satisfaction_trend == "declining":
            actions.append(AdaptationAction.ADD_ENCOURAGEMENT)
            empathy = max(empathy, 0.6)

        if not actions:
            actions.append(AdaptationAction.NO_CHANGE)

        # Tone hint
        tone_hint = self._generate_tone_hint(trajectory, persona_humor)

        # Confidence based on data availability
        confidence = min(
            0.95,
            0.3 + len(trajectory.turns) * 0.05
        )

        return AdaptationRecommendation(
            actions=actions,
            empathy_level=round(empathy, 2),
            formality_level=round(formality, 2),
            detail_level=round(detail, 2),
            urgency_factor=round(urgency, 2),
            tone_hint=tone_hint,
            confidence=round(confidence, 2),
        )

    def _trajectory_formality(self, trajectory: ConversationTrajectory) -> float:
        """Estimate formality from conversation trajectory."""
        if not trajectory.turns:
            return 0.5

        # If user is in greeting phase, slightly more formal
        if trajectory.phase == ConversationPhase.GREETING:
            return 0.6
        # Winding down → more informal
        if trajectory.phase == ConversationPhase.WINDING_DOWN:
            return 0.3
        return 0.5

    def _feedback_formality(self, trajectory: ConversationTrajectory) -> float:
        """Estimate formality adjustment from feedback."""
        if not trajectory.turns:
            return 0.5

        recent = [t for t in trajectory.turns[-5:] if t.is_user]
        for t in recent:
            if t.feedback == FeedbackSignal.THANKS:
                return 0.5  # Neutral → user is polite
            if t.feedback == FeedbackSignal.SHORT_ACK:
                return 0.3  # Informal → short replies
        return 0.5

    def _compute_empathy(self, trajectory: ConversationTrajectory) -> float:
        """Compute recommended empathy level."""
        if not trajectory.turns:
            return 0.5

        base = 0.5

        # High intensity → more empathy
        base += (trajectory.avg_intensity - 0.5) * 0.3

        # Negative emotions → more empathy
        negative_emotions = {"anger", "frustration",
                             "sadness", "fear", "confusion"}
        if trajectory.dominant_emotion in negative_emotions:
            base += 0.2

        # Escalation → maximum empathy
        if trajectory.escalation_count > 0:
            base += 0.2

        # Problem solving → more empathy
        if trajectory.phase == ConversationPhase.PROBLEM_SOLVING:
            base += 0.1

        return max(0.0, min(1.0, base))

    def _compute_detail(
        self, trajectory: ConversationTrajectory, avg_msg_len: float
    ) -> float:
        """Compute recommended detail level."""
        # Start from persona's message length preference
        if avg_msg_len < 30:
            base = 0.2
        elif avg_msg_len < 80:
            base = 0.5
        else:
            base = 0.8

        # Confusion → more detail
        if trajectory.dominant_emotion == "confusion":
            base = min(1.0, base + 0.2)

        # Elaboration feedback → more detail
        for t in trajectory.turns[-3:]:
            if t.feedback == FeedbackSignal.ELABORATION:
                base = min(1.0, base + 0.15)

        # Short ack → less detail (user wants brevity)
        for t in trajectory.turns[-3:]:
            if t.feedback == FeedbackSignal.SHORT_ACK:
                base = max(0.0, base - 0.1)

        return max(0.0, min(1.0, base))

    def _compute_urgency(self, trajectory: ConversationTrajectory) -> float:
        """Compute urgency factor."""
        if not trajectory.turns:
            return 0.0

        # Check recent turns for urgency emotion
        recent_user = [t for t in trajectory.turns[-3:] if t.is_user]
        for t in recent_user:
            if t.emotion == "urgency":
                return max(0.6, t.intensity)

        # Escalation implies urgency
        if trajectory.escalation_count > 1:
            return 0.5

        return 0.0

    def _generate_tone_hint(
        self, trajectory: ConversationTrajectory, humor_level: float
    ) -> str:
        """Generate a free-form tone hint."""
        hints: list[str] = []

        if trajectory.phase == ConversationPhase.PROBLEM_SOLVING:
            hints.append(
                "Пользователь решает проблему — будь терпеливым и конкретным.")

        if trajectory.satisfaction_trend == "declining":
            hints.append("Качество общения снижается — постарайся лучше.")

        if trajectory.escalation_count >= 2:
            hints.append(
                "Пользователь повторяет запрос — обрати особое внимание.")

        if humor_level > 0.6 and trajectory.dominant_emotion in ("joy", "neutral"):
            hints.append("Можно использовать лёгкий юмор.")

        return " ".join(hints) if hints else ""


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK LOOP — Learning from reactions
# ═══════════════════════════════════════════════════════════════════════════════


class FeedbackLearner:
    """
    Updates persona profile based on implicit feedback signals.

    Adjusts formality, emoji preference, detail preference, etc.
    based on how the user reacts to agent responses.
    """

    # Learning rates
    FAST_LR = 0.05     # For strong signals (emoji, explicit thanks)
    SLOW_LR = 0.02     # For weak signals (short ack, topic change)

    def compute_adjustments(
        self,
        feedback: FeedbackSignal,
        current_formality: float = 0.5,
        current_humor: float = 0.3,
        current_emoji_freq: float = 0.0,
    ) -> dict[str, float]:
        """
        Compute persona adjustments based on feedback signal.

        Returns dict of field_name → delta to apply.
        """
        adjustments: dict[str, float] = {}

        if feedback == FeedbackSignal.POSITIVE_EMOJI:
            # User uses emoji → they like them
            adjustments["emoji_frequency"] = self.FAST_LR
            # Positive reaction → current style is good, slight humor boost
            adjustments["humor_level"] = self.SLOW_LR

        elif feedback == FeedbackSignal.NEGATIVE_EMOJI:
            # User is unhappy → increase formality slightly
            adjustments["formality_level"] = self.SLOW_LR
            adjustments["humor_level"] = -self.SLOW_LR

        elif feedback == FeedbackSignal.THANKS:
            # Positive → keep current style
            adjustments["agreeableness"] = self.SLOW_LR

        elif feedback == FeedbackSignal.COMPLAINT:
            # Negative → need to adjust
            adjustments["formality_level"] = self.FAST_LR
            adjustments["humor_level"] = -self.FAST_LR

        elif feedback == FeedbackSignal.SHORT_ACK:
            # User prefers brief communication
            adjustments["formality_level"] = -self.SLOW_LR

        elif feedback == FeedbackSignal.REPEAT_REQUEST:
            # We weren't clear enough → no humor, more formal
            adjustments["humor_level"] = -self.FAST_LR

        elif feedback == FeedbackSignal.ESCALATION:
            # Critical — user is losing patience
            adjustments["humor_level"] = -self.FAST_LR
            adjustments["formality_level"] = self.FAST_LR

        elif feedback == FeedbackSignal.ELABORATION:
            # User needed to explain more → we should be more detailed
            pass  # No persona change, just affects current response

        return adjustments

    def apply_adjustments(
        self,
        profile_data: dict[str, float],
        adjustments: dict[str, float],
    ) -> dict[str, float]:
        """
        Apply computed adjustments to a profile data dict.

        Clamps all values to [0.0, 1.0].

        Args:
            profile_data: dict with current values
            adjustments: dict with deltas

        Returns:
            Updated profile data dict
        """
        result = dict(profile_data)
        for key, delta in adjustments.items():
            if key in result:
                result[key] = max(0.0, min(1.0, result[key] + delta))
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA ADAPTATION ENGINE — Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


class PersonaAdaptationEngine:
    """
    Main orchestrator for real-time persona adaptation.

    Combines:
    - ConversationEmotionTracker (in-conversation dynamics)
    - FeedbackLearner (implicit reaction learning)
    - AdaptiveStyleSelector (style recommendations)

    Usage:
        engine = PersonaAdaptationEngine()

        # On each user message:
        recommendation = engine.process_user_message(
            user_id=123,
            text="Это неправильно! Уже третий раз прошу!",
            emotion="frustration",
            intensity=0.8,
            persona_formality=0.5,
            persona_emoji_freq=0.1,
            persona_humor=0.3,
            persona_avg_msg_len=45.0,
        )
        # recommendation.to_prompt_fragment() → add to LLM prompt
    """

    def __init__(self):
        self._tracker = ConversationEmotionTracker()
        self._learner = FeedbackLearner()
        self._selector = AdaptiveStyleSelector()

    @property
    def tracker(self) -> ConversationEmotionTracker:
        return self._tracker

    @property
    def learner(self) -> FeedbackLearner:
        return self._learner

    @property
    def selector(self) -> AdaptiveStyleSelector:
        return self._selector

    def process_user_message(
        self,
        user_id: int,
        text: str,
        emotion: str,
        intensity: float,
        persona_formality: float = 0.5,
        persona_emoji_freq: float = 0.0,
        persona_humor: float = 0.3,
        persona_avg_msg_len: float = 50.0,
    ) -> AdaptationRecommendation:
        """
        Full pipeline: detect feedback → record turn → get recommendation.

        Args:
            user_id: Telegram user ID
            text: User message text
            emotion: Detected primary emotion
            intensity: Emotion intensity 0-1
            persona_*: Learned persona parameters

        Returns:
            AdaptationRecommendation for the next agent response
        """
        # 1. Detect feedback from previous response
        prev_emotion = self._get_prev_user_emotion(user_id)
        feedback = detect_feedback(text, prev_emotion)

        # 2. Record turn
        self._tracker.record_turn(
            user_id=user_id,
            emotion=emotion,
            intensity=intensity,
            is_user=True,
            feedback=feedback,
        )

        # 3. Get trajectory
        trajectory = self._tracker.get_trajectory(user_id)

        # 4. Compute persona adjustments (to be applied externally)
        self._last_adjustments = self._learner.compute_adjustments(
            feedback=feedback,
            current_formality=persona_formality,
            current_humor=persona_humor,
            current_emoji_freq=persona_emoji_freq,
        )

        # 5. Get style recommendation
        recommendation = self._selector.recommend(
            trajectory=trajectory,
            persona_formality=persona_formality,
            persona_emoji_freq=persona_emoji_freq,
            persona_humor=persona_humor,
            persona_avg_msg_len=persona_avg_msg_len,
        )

        logger.debug(
            f"PersonaAdapt[{user_id}]: feedback={feedback.value}, "
            f"phase={trajectory.phase.value}, "
            f"empathy={recommendation.empathy_level}, "
            f"actions={[a.value for a in recommendation.actions]}"
        )

        return recommendation

    def get_persona_adjustments(self) -> dict[str, float]:
        """
        Get the last computed persona adjustments.

        These should be applied to UserPersonaProfile externally.
        """
        return getattr(self, "_last_adjustments", {})

    def record_agent_response(
        self,
        user_id: int,
        emotion: str = "neutral",
        intensity: float = 0.3,
    ) -> None:
        """Record the agent's response emotion (optional, for trajectory tracking)."""
        self._tracker.record_turn(
            user_id=user_id,
            emotion=emotion,
            intensity=intensity,
            is_user=False,
        )

    def reset_conversation(self, user_id: int) -> None:
        """Reset conversation tracking for a user."""
        self._tracker.reset(user_id)

    def _get_prev_user_emotion(self, user_id: int) -> str:
        """Get the previous user emotion from conversation history."""
        turns = list(self._tracker._conversations.get(user_id, []))
        user_turns = [t for t in turns if t.is_user]
        if user_turns:
            return user_turns[-1].emotion
        return "neutral"

    def get_stats(self) -> dict:
        """Get engine statistics."""
        return self._tracker.get_stats()


# ─── Global instance ────────────────────────────────────────────────────────

persona_adaptation = PersonaAdaptationEngine()
