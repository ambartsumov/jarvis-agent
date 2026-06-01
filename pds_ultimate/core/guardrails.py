"""
PDS-Ultimate Guardrails — Input/Output Safety Layer
=====================================================
Step 15: Prompt injection protection, PII redaction, output validation.

ARCHITECTURE:
    User Input → InputGuard → [Agent Pipeline] → OutputGuard → User
                    │                                   │
               PromptInjectionDetector            PIIRedactor
               InputSanitizer                     OutputValidator
               RateLimiter (per-user)             ContentFilter

Design:
- Zero false positives on normal Russian/English text
- Pattern-based + heuristic scoring (no LLM cost for guardrails)
- All checks are synchronous for low latency
- Configurable sensitivity levels
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS & DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class ThreatLevel(str, Enum):
    """Threat classification levels."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GuardAction(str, Enum):
    """What to do when a threat is detected."""
    ALLOW = "allow"
    WARN = "warn"
    SANITIZE = "sanitize"
    BLOCK = "block"


@dataclass
class GuardResult:
    """Result of a guardrail check."""
    allowed: bool
    threat_level: ThreatLevel
    action: GuardAction
    threats: list[str] = field(default_factory=list)
    sanitized_text: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_safe(self) -> bool:
        return self.threat_level == ThreatLevel.SAFE

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "threat_level": self.threat_level.value,
            "action": self.action.value,
            "threats": self.threats,
            "has_sanitized": self.sanitized_text is not None,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT INJECTION DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class PromptInjectionDetector:
    """
    Detect prompt injection attempts in user input.

    Uses multi-layer detection:
    1. Pattern matching — known injection templates
    2. Heuristic scoring — suspicious characteristics
    3. Role confusion — attempts to override system prompt
    """

    # ── Known injection patterns ──
    _INJECTION_PATTERNS: tuple[tuple[str, float, str], ...] = (
        # (pattern, score, description)
        (r"ignore\s+(all\s+)?previous\s+(instructions?|prompts?|rules?)",
         0.9, "ignore_previous"),
        (r"forget\s+(all\s+)?previous\s+(instructions?|prompts?|context|rules?)",
         0.9, "forget_previous"),
        (r"forget\s+(all\s+)?previous",
         0.7, "forget_previous_generic"),
        (r"disregard\s+(all\s+)?previous",
         0.9, "disregard_previous"),
        (r"you\s+are\s+now\s+(?:a|an)\s+",
         0.7, "role_reassignment"),
        (r"from\s+now\s+on\s*,?\s*you\s+(are|will|must|should)",
         0.7, "role_override"),
        (r"new\s+instructions?\s*:",
         0.8, "new_instructions"),
        (r"system\s*:\s*",
         0.6, "system_prefix"),
        (r"\[system\]|\[INST\]|\<\|im_start\|>|<\|system\|>",
         0.9, "special_tokens"),
        (r"<<SYS>>|<s>|</s>|\[\/INST\]",
         0.9, "llama_tokens"),
        (r"respond\s+only\s+with|output\s+only|just\s+say",
         0.5, "output_control"),
        (r"do\s+not\s+follow\s+(any\s+)?(previous|prior|above)\s+(rules?|instructions?)",
         0.9, "override_rules"),
        (r"override\s+(system|safety|content)\s*(prompt|filter|policy)",
         0.9, "override_safety"),
        (r"jailbreak|DAN\s+mode|developer\s+mode",
         0.9, "jailbreak_keyword"),
        (r"pretend\s+you\s+(are|have)\s+no\s+(rules?|restrictions?|limits?)",
         0.8, "pretend_no_rules"),
        # Russian patterns
        (r"игнорируй\s+(все\s+)?предыдущие\s+(инструкции|правила|указания)",
         0.9, "ignore_previous_ru"),
        (r"забудь\s+(все\s+)?предыдущие",
         0.9, "forget_previous_ru"),
        (r"ты\s+теперь\s+",
         0.5, "role_reassignment_ru"),
        (r"новые\s+инструкции\s*:",
         0.8, "new_instructions_ru"),
        (r"не\s+следуй\s+(предыдущим|прошлым)\s+(правилам|инструкциям)",
         0.9, "override_rules_ru"),
    )

    # Pre-compile for performance
    _COMPILED_PATTERNS: list[tuple[re.Pattern, float, str]] = [
        (re.compile(p, re.IGNORECASE), score, desc)
        for p, score, desc in _INJECTION_PATTERNS
    ]

    # Suspicious characteristics
    _SUSPICIOUS_MARKERS: tuple[tuple[str, float], ...] = (
        ("```", 0.1),          # code blocks (mild)
        ("system:", 0.3),
        ("assistant:", 0.2),
        ("user:", 0.2),
        ("<|", 0.4),           # special token markers
        ("|>", 0.4),
        ("\\n\\n", 0.05),     # literal escaped newlines
    )

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    def detect(self, text: str) -> GuardResult:
        """
        Check text for prompt injection attempts.

        Returns GuardResult with threat level and details.
        """
        if not text or not text.strip():
            return GuardResult(
                allowed=True,
                threat_level=ThreatLevel.SAFE,
                action=GuardAction.ALLOW,
            )

        score = 0.0
        threats: list[str] = []
        matched_patterns: list[str] = []

        # Layer 1: Pattern matching
        for pattern, pattern_score, desc in self._COMPILED_PATTERNS:
            if pattern.search(text):
                score = max(score, pattern_score)
                threats.append(f"injection_pattern:{desc}")
                matched_patterns.append(desc)

        # Layer 2: Heuristic markers
        text_lower = text.lower()
        marker_score = 0.0
        for marker, mscore in self._SUSPICIOUS_MARKERS:
            if marker in text_lower:
                marker_score += mscore
        # Cap marker contribution
        score = max(score, min(marker_score, 0.5))

        # Layer 3: Role confusion (multiple role-like prefixes)
        role_count = sum(
            1 for r in ("system:", "assistant:", "user:", "human:", "ai:")
            if r in text_lower
        )
        if role_count >= 2:
            score = max(score, 0.7)
            threats.append("role_confusion")

        # Classify
        if score >= 0.8:
            threat_level = ThreatLevel.CRITICAL
            action = GuardAction.BLOCK
        elif score >= 0.6:
            threat_level = ThreatLevel.HIGH
            action = GuardAction.BLOCK
        elif score >= 0.4:
            threat_level = ThreatLevel.MEDIUM
            action = GuardAction.WARN
        elif score >= 0.2:
            threat_level = ThreatLevel.LOW
            action = GuardAction.ALLOW
        else:
            threat_level = ThreatLevel.SAFE
            action = GuardAction.ALLOW

        return GuardResult(
            allowed=action != GuardAction.BLOCK,
            threat_level=threat_level,
            action=action,
            threats=threats,
            details={
                "score": round(score, 3),
                "matched_patterns": matched_patterns,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PII REDACTOR
# ═══════════════════════════════════════════════════════════════════════════════


class PIIRedactor:
    """
    Detect and redact Personally Identifiable Information.

    Patterns: email, phone, credit card, passport, IP address, SSN.
    """

    _PII_PATTERNS: tuple[tuple[str, str, str], ...] = (
        # (pattern, replacement, pii_type)
        # ORDER MATTERS: specific patterns first, broad patterns last
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
         "[EMAIL_REDACTED]", "email"),
        (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
         "[CARD_REDACTED]", "credit_card"),
        (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
         "[IP_REDACTED]", "ip_address"),
        (r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b",
         "[SSN_REDACTED]", "ssn"),
        (r"(?:\+[1-9]\d{0,2}[-.\s]?)\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}\b",
         "[PHONE_REDACTED]", "phone"),
    )

    _COMPILED_PII: list[tuple[re.Pattern, str, str]] = [
        (re.compile(p), repl, ptype)
        for p, repl, ptype in _PII_PATTERNS
    ]

    def redact(self, text: str) -> tuple[str, list[str]]:
        """
        Redact PII from text.

        Returns: (redacted_text, list of PII types found)
        """
        if not text:
            return text, []

        found_types: list[str] = []
        result = text

        for pattern, replacement, pii_type in self._COMPILED_PII:
            if pattern.search(result):
                result = pattern.sub(replacement, result)
                if pii_type not in found_types:
                    found_types.append(pii_type)

        return result, found_types

    def has_pii(self, text: str) -> bool:
        """Quick check if text contains PII."""
        if not text:
            return False
        return any(p.search(text) for p, _, _ in self._COMPILED_PII)


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════


class OutputValidator:
    """
    Validate agent output before sending to user.

    Checks for:
    - Code injection (SQL, XSS, shell commands)
    - Internal prompt leaks
    - Hallucinated URLs
    - Excessive repetition
    """

    _DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"<script\b[^>]*>", "xss_script_tag"),
        (r"on\w+\s*=\s*['\"]", "xss_event_handler"),
        (r"javascript\s*:", "xss_javascript_uri"),
        (r";\s*(DROP|DELETE|UPDATE|INSERT|ALTER)\s+",
         "sql_injection"),
        (r"(?:rm\s+-rf|sudo\s+|chmod\s+777|:\(\)\s*\{)",
         "shell_injection"),
    )

    _COMPILED_DANGEROUS: list[tuple[re.Pattern, str]] = [
        (re.compile(p, re.IGNORECASE), desc)
        for p, desc in _DANGEROUS_PATTERNS
    ]

    _LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"system\s*prompt\s*:", "system_prompt_leak"),
        (r"my\s+instructions?\s+(are|say|tell)", "instruction_leak"),
        (r"I\s+was\s+told\s+to", "instruction_leak"),
    )

    _COMPILED_LEAKS: list[tuple[re.Pattern, str]] = [
        (re.compile(p, re.IGNORECASE), desc)
        for p, desc in _LEAK_PATTERNS
    ]

    def validate(self, text: str) -> GuardResult:
        """Validate output text for dangerous content."""
        if not text:
            return GuardResult(
                allowed=True,
                threat_level=ThreatLevel.SAFE,
                action=GuardAction.ALLOW,
            )

        threats: list[str] = []

        # Check dangerous patterns
        for pattern, desc in self._COMPILED_DANGEROUS:
            if pattern.search(text):
                threats.append(f"dangerous_output:{desc}")

        # Check for prompt leaks
        for pattern, desc in self._COMPILED_LEAKS:
            if pattern.search(text):
                threats.append(f"leak:{desc}")

        # Check for excessive repetition
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        if len(sentences) >= 5:
            unique = len(set(s.lower() for s in sentences))
            if unique < len(sentences) * 0.3:
                threats.append("excessive_repetition")

        if not threats:
            return GuardResult(
                allowed=True,
                threat_level=ThreatLevel.SAFE,
                action=GuardAction.ALLOW,
            )

        has_dangerous = any("dangerous_output" in t for t in threats)
        if has_dangerous:
            return GuardResult(
                allowed=False,
                threat_level=ThreatLevel.HIGH,
                action=GuardAction.SANITIZE,
                threats=threats,
            )

        return GuardResult(
            allowed=True,
            threat_level=ThreatLevel.LOW,
            action=GuardAction.WARN,
            threats=threats,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PER-USER RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════════


class UserRateLimiter:
    """
    Per-user rate limiting with sliding window.

    Default: 30 requests/minute, 200 requests/hour.
    """

    def __init__(
        self,
        max_per_minute: int = 30,
        max_per_hour: int = 200,
    ):
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self._requests: dict[int, list[float]] = defaultdict(list)

    def check(self, user_id: int) -> GuardResult:
        """Check if user is within rate limits."""
        now = time.time()
        timestamps = self._requests[user_id]

        # Cleanup old entries
        cutoff_hour = now - 3600
        self._requests[user_id] = [
            t for t in timestamps if t > cutoff_hour
        ]
        timestamps = self._requests[user_id]

        # Count recent
        minute_count = sum(1 for t in timestamps if t > now - 60)
        hour_count = len(timestamps)

        if minute_count >= self.max_per_minute:
            return GuardResult(
                allowed=False,
                threat_level=ThreatLevel.MEDIUM,
                action=GuardAction.BLOCK,
                threats=["rate_limit:per_minute"],
                details={
                    "minute_count": minute_count,
                    "limit": self.max_per_minute,
                },
            )

        if hour_count >= self.max_per_hour:
            return GuardResult(
                allowed=False,
                threat_level=ThreatLevel.MEDIUM,
                action=GuardAction.BLOCK,
                threats=["rate_limit:per_hour"],
                details={
                    "hour_count": hour_count,
                    "limit": self.max_per_hour,
                },
            )

        return GuardResult(
            allowed=True,
            threat_level=ThreatLevel.SAFE,
            action=GuardAction.ALLOW,
        )

    def record(self, user_id: int) -> None:
        """Record a request for rate limiting."""
        self._requests[user_id].append(time.time())

    def reset(self, user_id: int | None = None) -> None:
        """Reset rate limits for a user or all users."""
        if user_id is not None:
            self._requests.pop(user_id, None)
        else:
            self._requests.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED GUARDRAILS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class GuardrailsEngine:
    """
    Unified guardrails pipeline.

    Combines all safety checks into a single API:
    - check_input(text, user_id) → GuardResult
    - check_output(text) → GuardResult
    """

    def __init__(
        self,
        injection_threshold: float = 0.6,
        rate_limit_per_minute: int = 30,
        rate_limit_per_hour: int = 200,
        redact_pii_in_logs: bool = True,
    ):
        self.injection_detector = PromptInjectionDetector(
            threshold=injection_threshold,
        )
        self.pii_redactor = PIIRedactor()
        self.output_validator = OutputValidator()
        self.rate_limiter = UserRateLimiter(
            max_per_minute=rate_limit_per_minute,
            max_per_hour=rate_limit_per_hour,
        )
        self.redact_pii_in_logs = redact_pii_in_logs
        self._stats: dict[str, int] = defaultdict(int)

    def check_input(
        self,
        text: str,
        user_id: int | None = None,
    ) -> GuardResult:
        """
        Full input validation pipeline.

        1. Rate limit check (if user_id provided)
        2. Prompt injection detection
        3. PII detection (for logging)
        """
        self._stats["total_checks"] += 1

        # Rate limit
        if user_id is not None:
            rate_result = self.rate_limiter.check(user_id)
            if not rate_result.allowed:
                self._stats["rate_limited"] += 1
                return rate_result
            self.rate_limiter.record(user_id)

        # Prompt injection
        injection_result = self.injection_detector.detect(text)
        if not injection_result.allowed:
            self._stats["injections_blocked"] += 1
            return injection_result

        # PII check (just flag, don't block)
        if self.redact_pii_in_logs and self.pii_redactor.has_pii(text):
            self._stats["pii_detected"] += 1
            injection_result.details["has_pii"] = True

        return injection_result

    def check_output(self, text: str) -> GuardResult:
        """
        Output validation pipeline.

        1. Dangerous content check
        2. PII redaction
        """
        self._stats["output_checks"] += 1

        # Validate output
        result = self.output_validator.validate(text)

        # PII redaction in output
        if self.redact_pii_in_logs:
            redacted, pii_types = self.pii_redactor.redact(text)
            if pii_types:
                result.sanitized_text = redacted
                result.details["pii_redacted"] = pii_types
                self._stats["pii_redacted_output"] += 1

        return result

    def redact_for_log(self, text: str) -> str:
        """Redact PII before writing to logs."""
        redacted, _ = self.pii_redactor.redact(text)
        return redacted

    def get_stats(self) -> dict[str, int]:
        """Return guardrails statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats.clear()


# ─── Global Instance ─────────────────────────────────────────────────────────

guardrails = GuardrailsEngine()
