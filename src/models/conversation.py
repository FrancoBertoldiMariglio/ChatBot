"""Conversation models for session and context management."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConversationStatus(str, Enum):
    """Status of a conversation."""

    ACTIVE = "active"  # Bot is handling
    HANDOFF_PENDING = "handoff_pending"  # Waiting for human agent
    HANDOFF_ACTIVE = "handoff_active"  # Human agent is handling
    RESOLVED = "resolved"  # Conversation ended
    EXPIRED = "expired"  # Session timeout


class ConversationSummary(BaseModel):
    """Compressed summary of conversation history for long-term memory."""

    summary_text: str
    key_topics: list[str] = Field(default_factory=list)
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    unresolved_issues: list[str] = Field(default_factory=list)
    sentiment_trend: str = "neutral"  # positive, neutral, negative
    created_at: datetime = Field(default_factory=datetime.utcnow)
    message_range: tuple[int, int] = (0, 0)  # Start and end message indices


class ConversationContext(BaseModel):
    """Context information passed to the LLM."""

    # From RAG
    knowledge_base_context: list[str] = Field(default_factory=list)

    # From memory
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    conversation_summaries: list[str] = Field(default_factory=list)

    # User info
    user_name: str | None = None
    user_preferences: dict[str, Any] = Field(default_factory=dict)

    # Current state
    detected_intent: str | None = None
    detected_entities: dict[str, Any] = Field(default_factory=dict)
    sentiment_score: float = 0.0

    # Metadata
    turn_count: int = 0
    fallback_count: int = 0

    def to_prompt_context(self) -> str:
        """Format context for LLM prompt."""
        parts = []

        if self.knowledge_base_context:
            parts.append("## Relevant Information from Knowledge Base:")
            for i, ctx in enumerate(self.knowledge_base_context, 1):
                parts.append(f"{i}. {ctx}")

        if self.conversation_summaries:
            parts.append("\n## Previous Conversation Summary:")
            for summary in self.conversation_summaries:
                parts.append(summary)

        if self.user_preferences:
            parts.append(f"\n## User Preferences: {self.user_preferences}")

        return "\n".join(parts) if parts else ""


class Conversation(BaseModel):
    """Main conversation model representing a chat session."""

    id: str = Field(..., description="Unique conversation identifier")
    tenant_id: str = Field(..., description="Tenant this conversation belongs to")
    user_id: str = Field(..., description="External user identifier (e.g., WhatsApp ID)")

    # Status
    status: ConversationStatus = ConversationStatus.ACTIVE
    channel: str = "whatsapp"

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_at: datetime | None = None

    # WhatsApp 24h window tracking
    last_user_message_at: datetime | None = None  # For session window

    # Counters
    message_count: int = 0
    user_message_count: int = 0
    bot_message_count: int = 0
    fallback_count: int = 0

    # Sentiment tracking
    average_sentiment: float = 0.0
    sentiment_history: list[float] = Field(default_factory=list)

    # Memory
    summaries: list[ConversationSummary] = Field(default_factory=list)

    # Handoff
    handoff_reason: str | None = None
    assigned_agent_id: str | None = None
    chatwoot_conversation_id: int | None = None

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_within_session_window(self, window_hours: int = 24) -> bool:
        """Check if conversation is within WhatsApp's session window."""
        if not self.last_user_message_at:
            return False
        elapsed = datetime.utcnow() - self.last_user_message_at
        return elapsed.total_seconds() < (window_hours * 3600)

    def update_sentiment(self, new_score: float) -> None:
        """Update sentiment tracking with new score."""
        self.sentiment_history.append(new_score)
        # Keep last 10 sentiment scores
        if len(self.sentiment_history) > 10:
            self.sentiment_history = self.sentiment_history[-10:]
        # Calculate weighted average (recent scores matter more)
        weights = list(range(1, len(self.sentiment_history) + 1))
        total_weight = sum(weights)
        weighted_sum = sum(s * w for s, w in zip(self.sentiment_history, weights))
        self.average_sentiment = weighted_sum / total_weight

    def increment_fallback(self) -> int:
        """Increment fallback counter and return new count."""
        self.fallback_count += 1
        return self.fallback_count

    def should_summarize(self, threshold: int = 15) -> bool:
        """Check if conversation should be summarized."""
        last_summarized = 0
        if self.summaries:
            last_summarized = self.summaries[-1].message_range[1]
        messages_since_summary = self.message_count - last_summarized
        return messages_since_summary >= threshold
