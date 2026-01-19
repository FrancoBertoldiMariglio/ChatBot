"""Message models for all channels."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    """Supported communication channels."""

    WHATSAPP = "whatsapp"
    WEBCHAT = "webchat"
    EMAIL = "email"
    VOICE = "voice"  # Future


class MessageDirection(str, Enum):
    """Direction of the message."""

    INBOUND = "inbound"  # From user
    OUTBOUND = "outbound"  # To user


class MessageType(str, Enum):
    """Type of message content."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    TEMPLATE = "template"  # WhatsApp template message
    INTERACTIVE = "interactive"  # Buttons, lists


class MessageMetadata(BaseModel):
    """Channel-specific message metadata."""

    # Twilio/WhatsApp specific
    twilio_message_sid: str | None = None
    whatsapp_message_id: str | None = None

    # Media
    media_url: str | None = None
    media_content_type: str | None = None

    # Template (for outbound)
    template_name: str | None = None
    template_params: dict[str, str] | None = None

    # Processing
    processing_time_ms: int | None = None
    llm_model_used: str | None = None
    tokens_used: int | None = None

    # Sentiment
    sentiment_score: float | None = None
    sentiment_label: str | None = None

    # RAG
    knowledge_sources_used: list[str] = Field(default_factory=list)

    # Extra
    raw_payload: dict[str, Any] | None = None


class Message(BaseModel):
    """Universal message model for all channels."""

    id: str = Field(..., description="Unique message identifier")
    conversation_id: str = Field(..., description="Parent conversation ID")
    tenant_id: str = Field(..., description="Tenant ID")

    # Content
    content: str = Field(..., description="Message text content")
    message_type: MessageType = MessageType.TEXT
    direction: MessageDirection

    # Channel info
    channel: ChannelType = ChannelType.WHATSAPP

    # User info
    user_id: str = Field(..., description="External user identifier")
    user_name: str | None = None
    user_phone: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    delivered_at: datetime | None = None
    read_at: datetime | None = None

    # Status
    is_from_bot: bool = False
    is_from_agent: bool = False
    requires_response: bool = True

    # Metadata
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)

    def to_chat_format(self) -> dict[str, str]:
        """Convert to LangChain chat message format."""
        role = "assistant" if self.direction == MessageDirection.OUTBOUND else "user"
        return {"role": role, "content": self.content}

    def to_llm_message(self) -> dict[str, str]:
        """Convert to LLM message format for context."""
        if self.direction == MessageDirection.INBOUND:
            return {"role": "user", "content": self.content}
        else:
            return {"role": "assistant", "content": self.content}


class IncomingWebhookMessage(BaseModel):
    """Normalized incoming message from any webhook."""

    # Required fields
    channel: ChannelType
    user_id: str  # Channel-specific user ID
    content: str
    message_type: MessageType = MessageType.TEXT

    # Optional user info
    user_name: str | None = None
    user_phone: str | None = None

    # Tenant routing
    tenant_id: str | None = None  # May be determined by webhook path

    # Channel-specific data
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    # Media (if applicable)
    media_url: str | None = None
    media_content_type: str | None = None


class OutgoingMessage(BaseModel):
    """Message to be sent to user."""

    content: str
    message_type: MessageType = MessageType.TEXT
    recipient_id: str

    # Optional media
    media_url: str | None = None

    # Template (for WhatsApp)
    template_name: str | None = None
    template_params: dict[str, str] | None = None

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
