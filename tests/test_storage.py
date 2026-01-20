"""Tests for storage backends."""

import pytest

from src.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    Tenant,
    TenantConfig,
    TenantStatus,
)
from src.storage.memory import InMemoryStorage


@pytest.mark.asyncio
async def test_tenant_crud(storage):
    """Test tenant CRUD operations."""
    # Create
    tenant = Tenant(
        id="test-1",
        name="Test Tenant",
        status=TenantStatus.ACTIVE,
        config=TenantConfig(company_name="Test Co"),
    )
    saved = await storage.save_tenant(tenant)
    assert saved.id == "test-1"

    # Read
    retrieved = await storage.get_tenant("test-1")
    assert retrieved is not None
    assert retrieved.name == "Test Tenant"

    # List
    tenants = await storage.list_tenants()
    assert len(tenants) >= 1

    # Delete
    deleted = await storage.delete_tenant("test-1")
    assert deleted is True

    # Verify deleted
    retrieved = await storage.get_tenant("test-1")
    assert retrieved is None


@pytest.mark.asyncio
async def test_conversation_crud(storage, demo_tenant):
    """Test conversation CRUD operations."""
    # Create
    conv = Conversation(
        id="conv-1",
        tenant_id=demo_tenant.id,
        user_id="user-123",
        channel="whatsapp",
    )
    saved = await storage.save_conversation(conv)
    assert saved.id == "conv-1"

    # Read
    retrieved = await storage.get_conversation("conv-1")
    assert retrieved is not None
    assert retrieved.user_id == "user-123"

    # Get by user
    by_user = await storage.get_conversation_by_user(
        tenant_id=demo_tenant.id,
        user_id="user-123",
    )
    assert by_user is not None
    assert by_user.id == "conv-1"


@pytest.mark.asyncio
async def test_message_crud(storage, demo_tenant):
    """Test message CRUD operations."""
    # Create conversation first
    conv = Conversation(
        id="conv-msg",
        tenant_id=demo_tenant.id,
        user_id="user-456",
    )
    await storage.save_conversation(conv)

    # Create messages
    msg1 = Message(
        id="msg-1",
        conversation_id="conv-msg",
        tenant_id=demo_tenant.id,
        content="Hello",
        direction=MessageDirection.INBOUND,
        user_id="user-456",
    )
    await storage.save_message(msg1)

    msg2 = Message(
        id="msg-2",
        conversation_id="conv-msg",
        tenant_id=demo_tenant.id,
        content="Hi there!",
        direction=MessageDirection.OUTBOUND,
        user_id="user-456",
        is_from_bot=True,
    )
    await storage.save_message(msg2)

    # Get messages
    messages = await storage.get_messages("conv-msg")
    assert len(messages) == 2

    # Get recent messages
    recent = await storage.get_recent_messages("conv-msg", limit=1)
    assert len(recent) == 1


@pytest.mark.asyncio
async def test_session_data(storage):
    """Test session data operations."""
    # Set
    await storage.set_session_data("test-key", {"foo": "bar"}, ttl_seconds=60)

    # Get
    data = await storage.get_session_data("test-key")
    assert data is not None
    assert data["foo"] == "bar"

    # Delete
    deleted = await storage.delete_session_data("test-key")
    assert deleted is True

    # Verify deleted
    data = await storage.get_session_data("test-key")
    assert data is None
