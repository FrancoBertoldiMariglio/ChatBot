"""In-memory storage backend for development and testing."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from src.models import Conversation, Message, Tenant
from src.storage.base import StorageBackend


class InMemoryStorage(StorageBackend):
    """In-memory storage implementation for development."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, Message] = {}
        self._session_data: dict[str, tuple[dict[str, Any], datetime]] = {}
        self._lock = asyncio.Lock()

    # ==================== Tenant Operations ====================

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    async def save_tenant(self, tenant: Tenant) -> Tenant:
        tenant.updated_at = datetime.utcnow()
        self._tenants[tenant.id] = tenant
        return tenant

    async def list_tenants(self, status: str | None = None) -> list[Tenant]:
        tenants = list(self._tenants.values())
        if status:
            tenants = [t for t in tenants if t.status == status]
        return tenants

    async def delete_tenant(self, tenant_id: str) -> bool:
        if tenant_id in self._tenants:
            del self._tenants[tenant_id]
            return True
        return False

    # ==================== Conversation Operations ====================

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    async def get_conversation_by_user(
        self,
        tenant_id: str,
        user_id: str,
        channel: str = "whatsapp",
    ) -> Conversation | None:
        for conv in self._conversations.values():
            if (
                conv.tenant_id == tenant_id
                and conv.user_id == user_id
                and conv.channel == channel
                and conv.status in ["active", "handoff_pending", "handoff_active"]
            ):
                return conv
        return None

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        conversation.updated_at = datetime.utcnow()
        self._conversations[conversation.id] = conversation
        return conversation

    async def list_conversations(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        convs = [c for c in self._conversations.values() if c.tenant_id == tenant_id]
        if status:
            convs = [c for c in convs if c.status == status]
        convs.sort(key=lambda x: x.updated_at, reverse=True)
        return convs[:limit]

    # ==================== Message Operations ====================

    async def get_message(self, message_id: str) -> Message | None:
        return self._messages.get(message_id)

    async def save_message(self, message: Message) -> Message:
        self._messages[message.id] = message
        return message

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[Message]:
        messages = [m for m in self._messages.values() if m.conversation_id == conversation_id]
        messages.sort(key=lambda x: x.created_at)

        if before_id:
            try:
                idx = next(i for i, m in enumerate(messages) if m.id == before_id)
                messages = messages[:idx]
            except StopIteration:
                pass

        return messages[-limit:]

    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 10,
    ) -> list[Message]:
        return await self.get_messages(conversation_id, limit=limit)

    # ==================== Session/Cache Operations ====================

    async def set_session_data(
        self,
        key: str,
        data: dict,
        ttl_seconds: int = 1800,
    ) -> None:
        expiry = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        self._session_data[key] = (data, expiry)

    async def get_session_data(self, key: str) -> dict | None:
        if key not in self._session_data:
            return None

        data, expiry = self._session_data[key]
        if datetime.utcnow() > expiry:
            del self._session_data[key]
            return None

        return data

    async def delete_session_data(self, key: str) -> bool:
        if key in self._session_data:
            del self._session_data[key]
            return True
        return False

    # ==================== Health Check ====================

    async def health_check(self) -> bool:
        return True

    # ==================== Development Helpers ====================

    async def clear_all(self) -> None:
        """Clear all data (for testing)."""
        self._tenants.clear()
        self._conversations.clear()
        self._messages.clear()
        self._session_data.clear()

    async def seed_demo_tenant(self) -> Tenant:
        """Create a demo tenant for testing."""
        from src.models.tenant import TenantConfig, TenantStatus

        demo_tenant = Tenant(
            id="demo",
            name="Demo Company",
            status=TenantStatus.ACTIVE,
            config=TenantConfig(
                company_name="Demo Company",
                welcome_message="Welcome to Demo Company! How can I help you today?",
            ),
        )
        return await self.save_tenant(demo_tenant)
