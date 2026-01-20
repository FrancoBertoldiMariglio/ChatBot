"""Handoff evaluator - determines when to escalate to human agent."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

from src.core.config import settings
from src.core.exceptions import HandoffRequired
from src.models import Conversation, Message, Tenant
from src.services.sentiment.analyzer import SentimentAnalyzer, SentimentResult, get_sentiment_analyzer

logger = structlog.get_logger()


class HandoffTrigger(str, Enum):
    """Reasons for triggering handoff."""

    NEGATIVE_SENTIMENT = "negative_sentiment"
    EXPLICIT_REQUEST = "explicit_request"
    MAX_FALLBACKS = "max_fallbacks"
    LOW_CONFIDENCE = "low_confidence"
    LOOP_DETECTED = "loop_detected"
    SENSITIVE_TOPIC = "sensitive_topic"
    MANUAL = "manual"


@dataclass
class HandoffDecision:
    """Result of handoff evaluation."""

    should_handoff: bool
    trigger: HandoffTrigger | None = None
    confidence: float = 0.0
    reason: str = ""
    context: dict[str, Any] | None = None


class HandoffEvaluator:
    """Evaluates whether a conversation should be escalated to a human agent.

    Checks multiple triggers:
    - Sentiment analysis (negative sentiment threshold)
    - Explicit request keywords
    - Fallback count threshold
    - Loop detection (repeated similar queries)
    """

    def __init__(
        self,
        sentiment_analyzer: SentimentAnalyzer | None = None,
        sentiment_threshold: float | None = None,
        max_fallbacks: int | None = None,
    ) -> None:
        self.sentiment = sentiment_analyzer or get_sentiment_analyzer()
        self.sentiment_threshold = sentiment_threshold or settings.handoff_sentiment_threshold
        self.max_fallbacks = max_fallbacks or settings.handoff_max_fallbacks

        # Default handoff keywords (can be overridden per tenant)
        self.default_handoff_keywords = {
            "agent", "human", "person", "representative", "operator",
            "speak to someone", "talk to someone", "real person",
            "agente", "humano", "persona", "representante",
            "hablar con alguien",
        }

    async def evaluate(
        self,
        message: str,
        conversation: Conversation,
        tenant: Tenant,
        sentiment_result: SentimentResult | None = None,
    ) -> HandoffDecision:
        """Evaluate whether handoff is needed.

        Args:
            message: Current user message
            conversation: Conversation context
            tenant: Tenant configuration
            sentiment_result: Pre-computed sentiment (optional)

        Returns:
            HandoffDecision with recommendation
        """
        # Check if auto-handoff is enabled for tenant
        if not tenant.config.enable_auto_handoff:
            return HandoffDecision(should_handoff=False)

        # 1. Check for explicit request
        explicit_decision = self._check_explicit_request(message, tenant)
        if explicit_decision.should_handoff:
            logger.info(
                "Handoff triggered: explicit request",
                conversation_id=conversation.id,
            )
            return explicit_decision

        # 2. Check sentiment
        if tenant.config.enable_sentiment_analysis:
            sentiment = sentiment_result or await self.sentiment.analyze(message)
            sentiment_decision = self._check_sentiment(sentiment, conversation)
            if sentiment_decision.should_handoff:
                logger.info(
                    "Handoff triggered: negative sentiment",
                    conversation_id=conversation.id,
                    sentiment_score=sentiment.score,
                )
                return sentiment_decision

        # 3. Check fallback count
        fallback_decision = self._check_fallbacks(conversation)
        if fallback_decision.should_handoff:
            logger.info(
                "Handoff triggered: max fallbacks",
                conversation_id=conversation.id,
                fallback_count=conversation.fallback_count,
            )
            return fallback_decision

        # 4. Check for conversation loops
        loop_decision = await self._check_loop(message, conversation)
        if loop_decision.should_handoff:
            logger.info(
                "Handoff triggered: loop detected",
                conversation_id=conversation.id,
            )
            return loop_decision

        return HandoffDecision(should_handoff=False)

    def _check_explicit_request(
        self,
        message: str,
        tenant: Tenant,
    ) -> HandoffDecision:
        """Check if user explicitly requested human agent."""
        message_lower = message.lower()

        # Use tenant's custom keywords or defaults
        keywords = set(tenant.config.handoff_keywords) or self.default_handoff_keywords

        for keyword in keywords:
            if keyword.lower() in message_lower:
                return HandoffDecision(
                    should_handoff=True,
                    trigger=HandoffTrigger.EXPLICIT_REQUEST,
                    confidence=1.0,
                    reason=f"User requested human agent (keyword: {keyword})",
                    context={"matched_keyword": keyword},
                )

        return HandoffDecision(should_handoff=False)

    def _check_sentiment(
        self,
        sentiment: SentimentResult,
        conversation: Conversation,
    ) -> HandoffDecision:
        """Check if sentiment indicates need for human help."""
        # Check against threshold
        if sentiment.score < self.sentiment_threshold:
            return HandoffDecision(
                should_handoff=True,
                trigger=HandoffTrigger.NEGATIVE_SENTIMENT,
                confidence=sentiment.confidence,
                reason=f"Negative sentiment detected (score: {sentiment.score:.2f})",
                context={
                    "sentiment": sentiment.sentiment,
                    "score": sentiment.score,
                    "threshold": self.sentiment_threshold,
                },
            )

        # Also check for sustained negative sentiment
        if len(conversation.sentiment_history) >= 3:
            recent_avg = sum(conversation.sentiment_history[-3:]) / 3
            if recent_avg < self.sentiment_threshold:
                return HandoffDecision(
                    should_handoff=True,
                    trigger=HandoffTrigger.NEGATIVE_SENTIMENT,
                    confidence=0.8,
                    reason=f"Sustained negative sentiment (avg: {recent_avg:.2f})",
                    context={
                        "recent_average": recent_avg,
                        "history": conversation.sentiment_history[-3:],
                    },
                )

        return HandoffDecision(should_handoff=False)

    def _check_fallbacks(self, conversation: Conversation) -> HandoffDecision:
        """Check if too many fallbacks have occurred."""
        if conversation.fallback_count >= self.max_fallbacks:
            return HandoffDecision(
                should_handoff=True,
                trigger=HandoffTrigger.MAX_FALLBACKS,
                confidence=1.0,
                reason=f"Max fallbacks reached ({conversation.fallback_count})",
                context={
                    "fallback_count": conversation.fallback_count,
                    "threshold": self.max_fallbacks,
                },
            )

        return HandoffDecision(should_handoff=False)

    async def _check_loop(
        self,
        message: str,
        conversation: Conversation,
    ) -> HandoffDecision:
        """Check if conversation is in a loop (user repeating similar questions).

        Simple implementation - could be enhanced with embeddings for semantic similarity.
        """
        # This would need message history - simplified for MVP
        # In production, check if user has asked similar question 3+ times

        return HandoffDecision(should_handoff=False)

    async def trigger_handoff(
        self,
        conversation: Conversation,
        decision: HandoffDecision,
    ) -> None:
        """Trigger the handoff process.

        Args:
            conversation: Conversation to hand off
            decision: Handoff decision with context

        Raises:
            HandoffRequired: Always raised to signal handoff needed
        """
        raise HandoffRequired(
            reason=decision.reason,
            conversation_id=conversation.id,
            context={
                "trigger": decision.trigger.value if decision.trigger else "manual",
                "confidence": decision.confidence,
                **(decision.context or {}),
            },
        )


# Singleton instance
_handoff_evaluator: HandoffEvaluator | None = None


def get_handoff_evaluator() -> HandoffEvaluator:
    """Get or create the handoff evaluator singleton."""
    global _handoff_evaluator
    if _handoff_evaluator is None:
        _handoff_evaluator = HandoffEvaluator()
    return _handoff_evaluator
