"""RAG Retriever with hybrid search support."""

from dataclasses import dataclass
from typing import Any

import structlog

from src.services.rag.vectorstore import QdrantVectorStore, SearchResult, get_vector_store

logger = structlog.get_logger()


@dataclass
class RetrievalResult:
    """Combined retrieval result for RAG."""

    knowledge_base_results: list[SearchResult]
    memory_results: list[SearchResult]
    formatted_context: str


class RAGRetriever:
    """RAG retriever combining knowledge base and conversation memory.

    Supports:
    - Vector similarity search
    - Tenant-isolated retrieval
    - Memory retrieval for personalization
    """

    def __init__(
        self,
        vector_store: QdrantVectorStore | None = None,
        default_kb_limit: int = 5,
        default_memory_limit: int = 3,
        score_threshold: float = 0.5,
    ) -> None:
        self.vector_store = vector_store or get_vector_store()
        self.default_kb_limit = default_kb_limit
        self.default_memory_limit = default_memory_limit
        self.score_threshold = score_threshold

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        user_id: str | None = None,
        include_kb: bool = True,
        include_memory: bool = True,
        kb_limit: int | None = None,
        memory_limit: int | None = None,
    ) -> RetrievalResult:
        """Retrieve relevant context for a query.

        Args:
            query: User query
            tenant_id: Tenant ID for knowledge base
            user_id: Optional user ID for memory retrieval
            include_kb: Whether to search knowledge base
            include_memory: Whether to search conversation memory
            kb_limit: Override knowledge base result limit
            memory_limit: Override memory result limit

        Returns:
            RetrievalResult with formatted context
        """
        kb_results: list[SearchResult] = []
        memory_results: list[SearchResult] = []

        # Search knowledge base
        if include_kb:
            kb_results = await self.vector_store.search(
                query=query,
                tenant_id=tenant_id,
                doc_type="knowledge",
                limit=kb_limit or self.default_kb_limit,
                score_threshold=self.score_threshold,
            )
            logger.debug("KB retrieval", results=len(kb_results), tenant_id=tenant_id)

        # Search user memory (conversation summaries)
        if include_memory and user_id:
            memory_results = await self.vector_store.search(
                query=query,
                tenant_id=tenant_id,
                doc_type="memory",
                limit=memory_limit or self.default_memory_limit,
                score_threshold=self.score_threshold,
                additional_filters={"user_id": user_id},
            )
            logger.debug("Memory retrieval", results=len(memory_results), user_id=user_id)

        # Format context for LLM
        formatted_context = self._format_context(kb_results, memory_results)

        return RetrievalResult(
            knowledge_base_results=kb_results,
            memory_results=memory_results,
            formatted_context=formatted_context,
        )

    def _format_context(
        self,
        kb_results: list[SearchResult],
        memory_results: list[SearchResult],
    ) -> str:
        """Format retrieval results into context string for LLM."""
        parts = []

        if kb_results:
            parts.append("## Relevant Information from Knowledge Base:")
            for i, result in enumerate(kb_results, 1):
                # Include source if available
                source = result.metadata.get("source", "")
                source_info = f" (Source: {source})" if source else ""
                parts.append(f"{i}. {result.content}{source_info}")

        if memory_results:
            parts.append("\n## Previous Conversation Context:")
            for i, result in enumerate(memory_results, 1):
                parts.append(f"- {result.content}")

        return "\n".join(parts) if parts else ""

    async def retrieve_kb_only(
        self,
        query: str,
        tenant_id: str,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """Retrieve only from knowledge base."""
        return await self.vector_store.search(
            query=query,
            tenant_id=tenant_id,
            doc_type="knowledge",
            limit=limit or self.default_kb_limit,
            score_threshold=self.score_threshold,
        )

    async def add_to_knowledge_base(
        self,
        documents: list[str],
        tenant_id: str,
        metadata_list: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Add documents to the knowledge base.

        Args:
            documents: List of document texts
            tenant_id: Tenant ID
            metadata_list: Optional metadata for each document

        Returns:
            List of document IDs
        """
        return await self.vector_store.add_documents(
            documents=documents,
            tenant_id=tenant_id,
            doc_type="knowledge",
            metadata_list=metadata_list,
        )

    async def add_to_memory(
        self,
        content: str,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add conversation summary to user memory.

        Args:
            content: Summary or memory content
            tenant_id: Tenant ID
            user_id: User ID
            conversation_id: Source conversation ID
            metadata: Additional metadata

        Returns:
            Document ID
        """
        full_metadata = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            **(metadata or {}),
        }

        ids = await self.vector_store.add_documents(
            documents=[content],
            tenant_id=tenant_id,
            doc_type="memory",
            metadata_list=[full_metadata],
        )

        return ids[0] if ids else ""


# Singleton instance
_rag_retriever: RAGRetriever | None = None


def get_rag_retriever() -> RAGRetriever:
    """Get or create the RAG retriever singleton."""
    global _rag_retriever
    if _rag_retriever is None:
        _rag_retriever = RAGRetriever()
    return _rag_retriever
