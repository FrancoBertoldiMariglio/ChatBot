"""Main conversation engine - orchestrates RAG, LLM, and memory."""

from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog

from src.core.config import settings
from src.core.exceptions import HandoffRequired, TenantNotFound
from src.models import (
    Conversation,
    ConversationContext,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageMetadata,
    Tenant,
)
from src.services.conversation.memory import ConversationMemory
from src.services.llm.provider import LLMProvider, LLMResponse, get_llm_provider
from src.services.rag.retriever import RAGRetriever, get_rag_retriever
from src.storage.base import StorageBackend

logger = structlog.get_logger()


class ConversationEngine:
    """Main conversation engine that orchestrates all AI components.

    Handles:
    - Message processing
    - RAG retrieval
    - LLM completion
    - Memory management
    - Context building
    """

    def __init__(
        self,
        storage: StorageBackend,
        llm_provider: LLMProvider | None = None,
        rag_retriever: RAGRetriever | None = None,
    ) -> None:
        self.storage = storage
        self.llm = llm_provider or get_llm_provider()
        self.retriever = rag_retriever or get_rag_retriever()
        self.memory = ConversationMemory(
            storage=storage,
            llm_provider=self.llm,
            rag_retriever=self.retriever,
        )

    async def get_or_create_conversation(
        self,
        tenant_id: str,
        user_id: str,
        channel: str = "whatsapp",
    ) -> Conversation:
        """Get existing conversation or create a new one.

        Args:
            tenant_id: Tenant ID
            user_id: External user ID
            channel: Communication channel

        Returns:
            Conversation object
        """
        # Try to find existing active conversation
        conversation = await self.storage.get_conversation_by_user(
            tenant_id=tenant_id,
            user_id=user_id,
            channel=channel,
        )

        if conversation:
            logger.debug(
                "Found existing conversation",
                conversation_id=conversation.id,
                status=conversation.status,
            )
            return conversation

        # Create new conversation
        conversation = Conversation(
            id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            channel=channel,
            status=ConversationStatus.ACTIVE,
        )

        await self.storage.save_conversation(conversation)

        logger.info(
            "Created new conversation",
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        return conversation

    async def process_message(
        self,
        tenant: Tenant,
        conversation: Conversation,
        user_message: str,
        message_metadata: MessageMetadata | None = None,
    ) -> tuple[str, Message, LLMResponse]:
        """Process an incoming user message and generate response.

        Args:
            tenant: Tenant configuration
            conversation: Current conversation
            user_message: User's message content
            message_metadata: Optional metadata

        Returns:
            Tuple of (response_text, saved_message, llm_response)

        Raises:
            HandoffRequired: If human handoff is triggered
        """
        # Save incoming message
        incoming_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            content=user_message,
            direction=MessageDirection.INBOUND,
            user_id=conversation.user_id,
            metadata=message_metadata or MessageMetadata(),
        )
        await self.storage.save_message(incoming_msg)

        # Update conversation stats
        conversation.message_count += 1
        conversation.user_message_count += 1
        conversation.last_message_at = datetime.utcnow()
        conversation.last_user_message_at = datetime.utcnow()

        # Build context
        context = await self._build_context(tenant, conversation, user_message)

        # Generate response
        llm_response = await self._generate_response(
            tenant=tenant,
            conversation=conversation,
            user_message=user_message,
            context=context,
        )

        # Save outgoing message
        outgoing_msg = Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            content=llm_response.content,
            direction=MessageDirection.OUTBOUND,
            user_id=conversation.user_id,
            is_from_bot=True,
            metadata=MessageMetadata(
                llm_model_used=llm_response.model,
                tokens_used=llm_response.tokens_input + llm_response.tokens_output,
                processing_time_ms=int(llm_response.latency_ms),
                knowledge_sources_used=[
                    r.id for r in context.knowledge_base_results
                ] if hasattr(context, 'knowledge_base_results') else [],
            ),
        )
        await self.storage.save_message(outgoing_msg)

        # Update conversation
        conversation.message_count += 1
        conversation.bot_message_count += 1
        await self.storage.save_conversation(conversation)

        # Process memory (summarize if needed)
        await self.memory.process_conversation_memory(conversation)

        logger.info(
            "Processed message",
            conversation_id=conversation.id,
            response_length=len(llm_response.content),
            latency_ms=llm_response.latency_ms,
        )

        return llm_response.content, outgoing_msg, llm_response

    async def _build_context(
        self,
        tenant: Tenant,
        conversation: Conversation,
        user_message: str,
    ) -> ConversationContext:
        """Build context for LLM including RAG and memory.

        Args:
            tenant: Tenant configuration
            conversation: Current conversation
            user_message: Current user message

        Returns:
            ConversationContext object
        """
        # Retrieve from knowledge base
        retrieval_result = await self.retriever.retrieve(
            query=user_message,
            tenant_id=tenant.id,
            user_id=conversation.user_id,
            include_kb=True,
            include_memory=True,
        )

        # Get recent messages
        recent_messages = await self.memory.get_context_messages(conversation.id)

        # Get conversation summaries
        summaries = [s.summary_text for s in conversation.summaries[-2:]]

        context = ConversationContext(
            knowledge_base_context=[r.content for r in retrieval_result.knowledge_base_results],
            recent_messages=recent_messages,
            conversation_summaries=summaries,
            turn_count=conversation.message_count,
            fallback_count=conversation.fallback_count,
            sentiment_score=conversation.average_sentiment,
        )

        # Store retrieval results for metadata
        context._retrieval_result = retrieval_result  # type: ignore

        return context

    async def _generate_response(
        self,
        tenant: Tenant,
        conversation: Conversation,
        user_message: str,
        context: ConversationContext,
    ) -> LLMResponse:
        """Generate LLM response with context.

        Args:
            tenant: Tenant configuration
            conversation: Current conversation
            user_message: User's message
            context: Built context

        Returns:
            LLMResponse object
        """
        # Format context for prompt
        formatted_context = context.to_prompt_context()

        # Build messages for LLM
        messages = context.recent_messages.copy()
        messages.append({"role": "user", "content": user_message})

        # Generate response
        response = await self.llm.complete(
            messages=messages,
            system_prompt=f"{tenant.config.system_prompt}\n\n{formatted_context}",
            temperature=tenant.config.temperature,
            max_tokens=tenant.config.max_tokens,
        )

        return response

    async def handle_fallback(
        self,
        tenant: Tenant,
        conversation: Conversation,
    ) -> str:
        """Handle case when bot can't provide good response.

        Args:
            tenant: Tenant configuration
            conversation: Current conversation

        Returns:
            Fallback message
        """
        conversation.increment_fallback()
        await self.storage.save_conversation(conversation)

        # Check if should trigger handoff
        if conversation.fallback_count >= settings.handoff_max_fallbacks:
            if tenant.config.enable_auto_handoff:
                raise HandoffRequired(
                    reason="max_fallbacks_reached",
                    conversation_id=conversation.id,
                    context={"fallback_count": conversation.fallback_count},
                )

        return tenant.config.fallback_message

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """Get tenant by ID.

        Args:
            tenant_id: Tenant ID

        Returns:
            Tenant object

        Raises:
            TenantNotFound: If tenant doesn't exist
        """
        tenant = await self.storage.get_tenant(tenant_id)
        if not tenant:
            raise TenantNotFound(tenant_id)
        return tenant

    async def close_conversation(
        self,
        conversation: Conversation,
        reason: str = "resolved",
    ) -> Conversation:
        """Close a conversation.

        Args:
            conversation: Conversation to close
            reason: Closure reason

        Returns:
            Updated conversation
        """
        conversation.status = ConversationStatus.RESOLVED
        conversation.metadata["closure_reason"] = reason
        conversation.metadata["closed_at"] = datetime.utcnow().isoformat()

        await self.storage.save_conversation(conversation)

        logger.info(
            "Conversation closed",
            conversation_id=conversation.id,
            reason=reason,
        )

        return conversation


# Factory function for creating engine with storage
_engine_instance: ConversationEngine | None = None


def get_conversation_engine(storage: StorageBackend | None = None) -> ConversationEngine:
    """Get or create the conversation engine.

    Args:
        storage: Storage backend (required on first call)

    Returns:
        ConversationEngine instance
    """
    global _engine_instance

    if _engine_instance is None:
        if storage is None:
            raise ValueError("Storage backend required for first initialization")
        _engine_instance = ConversationEngine(storage=storage)

    return _engine_instance


def reset_conversation_engine() -> None:
    """Reset the conversation engine singleton (for testing)."""
    global _engine_instance
    _engine_instance = None
