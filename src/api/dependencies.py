"""FastAPI dependencies for dependency injection."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from src.core.config import Settings, settings
from src.services.channels.whatsapp import TwilioWhatsAppAdapter, get_whatsapp_adapter
from src.services.conversation.engine import ConversationEngine, get_conversation_engine
from src.services.conversation.handoff import HandoffEvaluator, get_handoff_evaluator
from src.services.llm.provider import LLMProvider, get_llm_provider
from src.services.rag.retriever import RAGRetriever, get_rag_retriever
from src.services.sentiment.analyzer import SentimentAnalyzer, get_sentiment_analyzer
from src.storage.base import StorageBackend
from src.storage.memory import InMemoryStorage


# Storage singleton
_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Get the storage backend singleton.

    Uses in-memory storage for development, Firestore for production.
    """
    global _storage
    if _storage is None:
        if settings.is_production and settings.gcp_project_id:
            from src.storage.firestore import FirestoreStorage
            _storage = FirestoreStorage(project_id=settings.gcp_project_id)
        else:
            _storage = InMemoryStorage()
    return _storage


# Type aliases for cleaner dependency injection
StorageDep = Annotated[StorageBackend, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(lambda: settings)]


def get_engine(storage: StorageDep) -> ConversationEngine:
    """Get conversation engine with storage dependency."""
    return get_conversation_engine(storage)


EngineDep = Annotated[ConversationEngine, Depends(get_engine)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
RAGDep = Annotated[RAGRetriever, Depends(get_rag_retriever)]
SentimentDep = Annotated[SentimentAnalyzer, Depends(get_sentiment_analyzer)]
HandoffDep = Annotated[HandoffEvaluator, Depends(get_handoff_evaluator)]
WhatsAppDep = Annotated[TwilioWhatsAppAdapter, Depends(get_whatsapp_adapter)]


async def verify_twilio_signature(
    request: Request,
    x_twilio_signature: str = Header(None),
) -> bool:
    """Verify Twilio webhook signature.

    In production, this should strictly validate the signature.
    In development, we can be more lenient.
    """
    if settings.is_development:
        return True

    if not x_twilio_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Twilio signature",
        )

    # Get adapter and validate
    adapter = get_whatsapp_adapter()
    body = await request.body()

    if not adapter.validate_webhook(body, x_twilio_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Twilio signature",
        )

    return True


TwilioAuthDep = Annotated[bool, Depends(verify_twilio_signature)]


async def get_tenant_from_path(
    tenant_id: str,
    storage: StorageDep,
):
    """Get tenant from path parameter."""
    tenant = await storage.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {tenant_id}",
        )
    return tenant
