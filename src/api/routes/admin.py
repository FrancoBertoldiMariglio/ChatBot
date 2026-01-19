"""Admin endpoints for tenant and system management."""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.api.dependencies import EngineDep, RAGDep, StorageDep
from src.models import Tenant, TenantConfig, TenantStatus

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["Admin"])


# ==================== Pydantic Schemas ====================


class TenantCreate(BaseModel):
    """Schema for creating a tenant."""

    id: str
    name: str
    company_name: str
    welcome_message: str | None = None
    system_prompt: str | None = None


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""

    name: str | None = None
    status: TenantStatus | None = None
    welcome_message: str | None = None
    system_prompt: str | None = None
    enable_auto_handoff: bool | None = None
    handoff_keywords: list[str] | None = None


class DocumentIngest(BaseModel):
    """Schema for ingesting documents."""

    documents: list[str]
    metadata: list[dict[str, Any]] | None = None


class TenantResponse(BaseModel):
    """Response schema for tenant."""

    id: str
    name: str
    status: TenantStatus
    config: TenantConfig
    total_conversations: int
    total_messages: int


# ==================== Tenant Endpoints ====================


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    storage: StorageDep,
) -> Tenant:
    """Create a new tenant."""
    # Check if tenant already exists
    existing = await storage.get_tenant(data.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant already exists: {data.id}",
        )

    config = TenantConfig(
        company_name=data.company_name,
        welcome_message=data.welcome_message or f"Welcome to {data.company_name}! How can I help you?",
        system_prompt=data.system_prompt or "",
    )

    tenant = Tenant(
        id=data.id,
        name=data.name,
        status=TenantStatus.TRIAL,
        config=config,
    )

    await storage.save_tenant(tenant)

    logger.info("Created tenant", tenant_id=tenant.id)

    return tenant


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    storage: StorageDep,
    status_filter: TenantStatus | None = None,
) -> list[Tenant]:
    """List all tenants."""
    return await storage.list_tenants(status=status_filter.value if status_filter else None)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    storage: StorageDep,
) -> Tenant:
    """Get a specific tenant."""
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    data: TenantUpdate,
    storage: StorageDep,
) -> Tenant:
    """Update a tenant."""
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )

    # Update fields
    if data.name is not None:
        tenant.name = data.name
    if data.status is not None:
        tenant.status = data.status
    if data.welcome_message is not None:
        tenant.config.welcome_message = data.welcome_message
    if data.system_prompt is not None:
        tenant.config.system_prompt = data.system_prompt
    if data.enable_auto_handoff is not None:
        tenant.config.enable_auto_handoff = data.enable_auto_handoff
    if data.handoff_keywords is not None:
        tenant.config.handoff_keywords = data.handoff_keywords

    await storage.save_tenant(tenant)

    logger.info("Updated tenant", tenant_id=tenant_id)

    return tenant


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    storage: StorageDep,
    rag: RAGDep,
) -> None:
    """Delete a tenant and all associated data."""
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )

    # Delete from vector store
    await rag.vector_store.delete_by_tenant(tenant_id)

    # Delete tenant
    await storage.delete_tenant(tenant_id)

    logger.info("Deleted tenant", tenant_id=tenant_id)


# ==================== Knowledge Base Endpoints ====================


@router.post("/tenants/{tenant_id}/knowledge", status_code=status.HTTP_201_CREATED)
async def ingest_knowledge(
    tenant_id: str,
    data: DocumentIngest,
    storage: StorageDep,
    rag: RAGDep,
) -> dict[str, Any]:
    """Ingest documents into tenant's knowledge base."""
    # Verify tenant exists
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )

    # Add to knowledge base
    doc_ids = await rag.add_to_knowledge_base(
        documents=data.documents,
        tenant_id=tenant_id,
        metadata_list=data.metadata,
    )

    logger.info(
        "Ingested knowledge",
        tenant_id=tenant_id,
        document_count=len(doc_ids),
    )

    return {
        "status": "success",
        "documents_ingested": len(doc_ids),
        "document_ids": doc_ids,
    }


@router.post("/tenants/{tenant_id}/knowledge/search")
async def search_knowledge(
    tenant_id: str,
    query: str,
    limit: int = 5,
    storage: StorageDep = None,
    rag: RAGDep = None,
) -> dict[str, Any]:
    """Search tenant's knowledge base."""
    # Verify tenant exists
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )

    results = await rag.retrieve_kb_only(
        query=query,
        tenant_id=tenant_id,
        limit=limit,
    )

    return {
        "query": query,
        "results": [
            {
                "id": r.id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ],
    }


# ==================== Conversation Endpoints ====================


@router.get("/tenants/{tenant_id}/conversations")
async def list_conversations(
    tenant_id: str,
    storage: StorageDep,
    status_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List conversations for a tenant."""
    conversations = await storage.list_conversations(
        tenant_id=tenant_id,
        status=status_filter,
        limit=limit,
    )

    return {
        "tenant_id": tenant_id,
        "count": len(conversations),
        "conversations": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "status": c.status,
                "channel": c.channel,
                "message_count": c.message_count,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in conversations
        ],
    }


@router.get("/tenants/{tenant_id}/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    tenant_id: str,
    conversation_id: str,
    storage: StorageDep,
    limit: int = 50,
) -> dict[str, Any]:
    """Get messages for a conversation."""
    conversation = await storage.get_conversation(conversation_id)
    if not conversation or conversation.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    messages = await storage.get_messages(conversation_id, limit=limit)

    return {
        "conversation_id": conversation_id,
        "count": len(messages),
        "messages": [
            {
                "id": m.id,
                "content": m.content,
                "direction": m.direction,
                "is_from_bot": m.is_from_bot,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }
