"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from typing import TypeVar

from src.models import Conversation, Message, Tenant

T = TypeVar("T")


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    # ==================== Tenant Operations ====================

    @abstractmethod
    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        """Get a tenant by ID."""
        ...

    @abstractmethod
    async def save_tenant(self, tenant: Tenant) -> Tenant:
        """Save or update a tenant."""
        ...

    @abstractmethod
    async def list_tenants(self, status: str | None = None) -> list[Tenant]:
        """List all tenants, optionally filtered by status."""
        ...

    @abstractmethod
    async def delete_tenant(self, tenant_id: str) -> bool:
        """Delete a tenant."""
        ...

    # ==================== Conversation Operations ====================

    @abstractmethod
    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        ...

    @abstractmethod
    async def get_conversation_by_user(
        self,
        tenant_id: str,
        user_id: str,
        channel: str = "whatsapp",
    ) -> Conversation | None:
        """Get active conversation for a user."""
        ...

    @abstractmethod
    async def save_conversation(self, conversation: Conversation) -> Conversation:
        """Save or update a conversation."""
        ...

    @abstractmethod
    async def list_conversations(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        """List conversations for a tenant."""
        ...

    # ==================== Message Operations ====================

    @abstractmethod
    async def get_message(self, message_id: str) -> Message | None:
        """Get a message by ID."""
        ...

    @abstractmethod
    async def save_message(self, message: Message) -> Message:
        """Save a message."""
        ...

    @abstractmethod
    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[Message]:
        """Get messages for a conversation."""
        ...

    @abstractmethod
    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 10,
    ) -> list[Message]:
        """Get most recent messages for context."""
        ...

    # ==================== Session/Cache Operations ====================

    @abstractmethod
    async def set_session_data(
        self,
        key: str,
        data: dict,
        ttl_seconds: int = 1800,
    ) -> None:
        """Store session data with TTL."""
        ...

    @abstractmethod
    async def get_session_data(self, key: str) -> dict | None:
        """Get session data."""
        ...

    @abstractmethod
    async def delete_session_data(self, key: str) -> bool:
        """Delete session data."""
        ...

    # ==================== Health Check ====================

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if storage is healthy."""
        ...
