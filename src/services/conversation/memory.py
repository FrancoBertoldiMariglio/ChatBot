"""Conversation memory management - short-term and long-term memory."""

from datetime import datetime

import structlog

from src.core.config import settings
from src.models import Conversation, ConversationSummary, Message
from src.services.llm.provider import LLMProvider, get_llm_provider
from src.services.rag.retriever import RAGRetriever, get_rag_retriever
from src.storage.base import StorageBackend

logger = structlog.get_logger()


class ConversationMemory:
    """Manages conversation memory: short-term (messages) and long-term (summaries).

    Short-term: Recent messages kept in session
    Long-term: Periodic summaries stored as embeddings for retrieval
    """

    def __init__(
        self,
        storage: StorageBackend,
        llm_provider: LLMProvider | None = None,
        rag_retriever: RAGRetriever | None = None,
        max_context_messages: int | None = None,
        summary_threshold: int | None = None,
    ) -> None:
        self.storage = storage
        self.llm = llm_provider or get_llm_provider()
        self.retriever = rag_retriever or get_rag_retriever()
        self.max_context_messages = max_context_messages or settings.max_context_messages
        self.summary_threshold = summary_threshold or settings.summary_threshold_turns

    async def get_context_messages(
        self,
        conversation_id: str,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        """Get recent messages formatted for LLM context.

        Args:
            conversation_id: Conversation ID
            limit: Max messages to return

        Returns:
            List of message dicts with role and content
        """
        limit = limit or self.max_context_messages
        messages = await self.storage.get_recent_messages(conversation_id, limit=limit)

        return [msg.to_llm_message() for msg in messages]

    async def get_user_memory(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> list[str]:
        """Retrieve relevant user memory based on query.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            query: Current query for relevance matching
            limit: Max memories to return

        Returns:
            List of relevant memory strings
        """
        results = await self.retriever.vector_store.search(
            query=query,
            tenant_id=tenant_id,
            doc_type="memory",
            limit=limit,
            additional_filters={"user_id": user_id},
        )

        return [r.content for r in results]

    async def should_summarize(self, conversation: Conversation) -> bool:
        """Check if conversation should be summarized."""
        last_summarized = 0
        if conversation.summaries:
            last_summarized = conversation.summaries[-1].message_range[1]

        messages_since = conversation.message_count - last_summarized
        return messages_since >= self.summary_threshold

    async def create_summary(
        self,
        conversation: Conversation,
        messages: list[Message],
    ) -> ConversationSummary:
        """Create a summary of recent conversation messages.

        Args:
            conversation: Conversation object
            messages: Messages to summarize

        Returns:
            ConversationSummary object
        """
        if not messages:
            raise ValueError("No messages to summarize")

        # Format messages for summarization
        conversation_text = "\n".join([
            f"{'User' if msg.direction == 'inbound' else 'Assistant'}: {msg.content}"
            for msg in messages
        ])

        # Generate summary using LLM
        summary_text = await self.llm.summarize(conversation_text, max_length=200)

        # Extract key topics and entities
        extraction = await self.llm.extract_entities(conversation_text)

        summary = ConversationSummary(
            summary_text=summary_text,
            key_topics=extraction.get("entities", {}).get("topics", []),
            user_preferences=extraction.get("entities", {}).get("preferences", {}),
            unresolved_issues=extraction.get("entities", {}).get("unresolved", []),
            sentiment_trend=extraction.get("sentiment", "neutral"),
            message_range=(messages[0].created_at.timestamp(), messages[-1].created_at.timestamp()),
        )

        logger.info(
            "Created conversation summary",
            conversation_id=conversation.id,
            messages_summarized=len(messages),
        )

        return summary

    async def store_summary_as_memory(
        self,
        conversation: Conversation,
        summary: ConversationSummary,
    ) -> str:
        """Store summary in vector store for future retrieval.

        Args:
            conversation: Conversation object
            summary: Summary to store

        Returns:
            Memory document ID
        """
        memory_content = f"""Conversation Summary ({summary.created_at.isoformat()}):
{summary.summary_text}

Key Topics: {', '.join(summary.key_topics) if summary.key_topics else 'None'}
Sentiment: {summary.sentiment_trend}
"""

        doc_id = await self.retriever.add_to_memory(
            content=memory_content,
            tenant_id=conversation.tenant_id,
            user_id=conversation.user_id,
            conversation_id=conversation.id,
            metadata={
                "created_at": summary.created_at.isoformat(),
                "key_topics": summary.key_topics,
                "sentiment": summary.sentiment_trend,
            },
        )

        logger.info(
            "Stored summary as memory",
            conversation_id=conversation.id,
            doc_id=doc_id,
        )

        return doc_id

    async def process_conversation_memory(
        self,
        conversation: Conversation,
    ) -> ConversationSummary | None:
        """Process and potentially summarize conversation.

        Called after each message exchange to manage memory.

        Args:
            conversation: Conversation to process

        Returns:
            New summary if created, None otherwise
        """
        if not await self.should_summarize(conversation):
            return None

        # Get messages since last summary
        start_index = 0
        if conversation.summaries:
            start_index = int(conversation.summaries[-1].message_range[1])

        # Get all messages (we need to filter by index)
        all_messages = await self.storage.get_messages(
            conversation.id,
            limit=self.summary_threshold + 5,
        )

        # Take messages since last summary
        messages_to_summarize = all_messages[start_index:] if start_index < len(all_messages) else all_messages[-self.summary_threshold:]

        if len(messages_to_summarize) < self.summary_threshold:
            return None

        try:
            summary = await self.create_summary(conversation, messages_to_summarize)
            await self.store_summary_as_memory(conversation, summary)

            # Add to conversation
            conversation.summaries.append(summary)

            return summary

        except Exception as e:
            logger.error(
                "Failed to create conversation summary",
                conversation_id=conversation.id,
                error=str(e),
            )
            return None

    async def build_context(
        self,
        conversation: Conversation,
        current_query: str,
    ) -> dict:
        """Build complete context for LLM including all memory sources.

        Args:
            conversation: Current conversation
            current_query: User's current message

        Returns:
            Dict with all context components
        """
        # Get recent messages
        recent_messages = await self.get_context_messages(conversation.id)

        # Get relevant user memories
        user_memories = await self.get_user_memory(
            tenant_id=conversation.tenant_id,
            user_id=conversation.user_id,
            query=current_query,
        )

        # Get conversation summaries
        summaries = [s.summary_text for s in conversation.summaries[-2:]]  # Last 2 summaries

        return {
            "recent_messages": recent_messages,
            "user_memories": user_memories,
            "conversation_summaries": summaries,
            "turn_count": conversation.message_count,
            "average_sentiment": conversation.average_sentiment,
        }
