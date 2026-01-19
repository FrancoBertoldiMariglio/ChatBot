"""Tenant models for multi-tenancy support."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TenantStatus(str, Enum):
    """Tenant account status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class TenantConfig(BaseModel):
    """Tenant-specific configuration."""

    # Branding
    company_name: str
    welcome_message: str = "Hello! How can I help you today?"
    fallback_message: str = "I'm sorry, I couldn't understand that. Would you like to speak with a human agent?"

    # AI Settings
    system_prompt: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=50, le=4000)

    # Handoff settings
    enable_auto_handoff: bool = True
    handoff_keywords: list[str] = Field(
        default_factory=lambda: ["agent", "human", "person", "representative", "agente", "humano"]
    )

    # Rate limiting (per tenant)
    rate_limit_messages_per_minute: int = 30
    rate_limit_messages_per_day: int = 1000

    # Feature flags
    enable_sentiment_analysis: bool = True
    enable_conversation_summary: bool = True

    # Channel-specific settings
    whatsapp_enabled: bool = True
    webchat_enabled: bool = False

    # Metadata
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class Tenant(BaseModel):
    """Tenant (customer organization) model."""

    id: str = Field(..., description="Unique tenant identifier")
    name: str = Field(..., description="Tenant display name")
    status: TenantStatus = TenantStatus.TRIAL
    config: TenantConfig

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Usage tracking
    total_conversations: int = 0
    total_messages: int = 0
    total_handoffs: int = 0

    # External integrations
    chatwoot_inbox_id: int | None = None
    qdrant_collection_suffix: str | None = None

    def get_collection_name(self, base_name: str = "knowledge_base") -> str:
        """Get the tenant-specific Qdrant collection name."""
        suffix = self.qdrant_collection_suffix or self.id
        return f"{base_name}_{suffix}"

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook."""
        if not self.config.system_prompt:
            self.config.system_prompt = self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Generate default system prompt for the tenant."""
        return f"""You are a helpful customer support assistant for {self.config.company_name}.

Your role is to:
- Answer questions about products, services, and policies
- Help resolve customer issues
- Provide accurate information based on the knowledge base
- Be polite, professional, and empathetic

Guidelines:
- If you don't know the answer, say so honestly and offer to connect with a human agent
- Never make up information
- Keep responses concise but helpful
- If the customer seems frustrated, acknowledge their feelings

Always respond in the same language the customer uses."""


class TenantUsageStats(BaseModel):
    """Tenant usage statistics for billing/monitoring."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Message counts
    messages_received: int = 0
    messages_sent: int = 0
    whatsapp_messages: int = 0

    # AI usage
    llm_tokens_input: int = 0
    llm_tokens_output: int = 0
    embeddings_generated: int = 0

    # Conversations
    conversations_started: int = 0
    conversations_resolved_by_ai: int = 0
    conversations_handed_off: int = 0

    # Costs (estimated)
    estimated_cost_usd: float = 0.0
