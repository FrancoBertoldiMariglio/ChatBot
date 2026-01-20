"""Qdrant vector store for knowledge base and memory."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import structlog
from qdrant_client import AsyncQdrantClient, models
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.exceptions import VectorStoreError
from src.services.rag.embeddings import EmbeddingService, get_embedding_service

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """Result from vector search."""

    id: str
    content: str
    score: float
    metadata: dict[str, Any]


class QdrantVectorStore:
    """Qdrant vector store with multi-tenant support.

    Uses metadata filtering for tenant isolation.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.embedding_service = embedding_service or get_embedding_service()
        self.default_collection = collection_name or settings.qdrant_collection_name
        self._client: AsyncQdrantClient | None = None
        self._initialized = False

    async def _get_client(self) -> AsyncQdrantClient:
        """Get or create the Qdrant client."""
        if self._client is None:
            if settings.qdrant_url:
                # Cloud/Remote Qdrant
                self._client = AsyncQdrantClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key or None,
                )
            else:
                # Local Qdrant
                self._client = AsyncQdrantClient(
                    host=settings.qdrant_host,
                    port=settings.qdrant_port,
                )
            logger.info("Qdrant client initialized")
        return self._client

    async def ensure_collection(self, collection_name: str | None = None) -> None:
        """Ensure the collection exists with proper configuration."""
        client = await self._get_client()
        name = collection_name or self.default_collection

        try:
            collections = await client.get_collections()
            exists = any(c.name == name for c in collections.collections)

            if not exists:
                await client.create_collection(
                    collection_name=name,
                    vectors_config=models.VectorParams(
                        size=self.embedding_service.vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection", collection=name)

                # Create payload indexes for filtering
                await client.create_payload_index(
                    collection_name=name,
                    field_name="tenant_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                await client.create_payload_index(
                    collection_name=name,
                    field_name="doc_type",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                logger.info("Created payload indexes", collection=name)
            else:
                logger.debug("Collection already exists", collection=name)

        except Exception as e:
            logger.error("Failed to ensure collection", collection=name, error=str(e))
            raise VectorStoreError(f"Failed to ensure collection: {e}", operation="ensure_collection")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def add_documents(
        self,
        documents: list[str],
        tenant_id: str,
        doc_type: str = "knowledge",
        metadata_list: list[dict[str, Any]] | None = None,
        collection_name: str | None = None,
    ) -> list[str]:
        """Add documents to the vector store.

        Args:
            documents: List of document texts
            tenant_id: Tenant ID for filtering
            doc_type: Type of document (knowledge, memory, summary)
            metadata_list: Optional metadata for each document
            collection_name: Override collection name

        Returns:
            List of document IDs
        """
        if not documents:
            return []

        client = await self._get_client()
        collection = collection_name or self.default_collection

        await self.ensure_collection(collection)

        # Generate embeddings
        embeddings = await self.embedding_service.embed_texts(documents)

        # Prepare points
        points = []
        ids = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            doc_id = str(uuid4())
            ids.append(doc_id)

            metadata = metadata_list[i] if metadata_list and i < len(metadata_list) else {}
            payload = {
                "content": doc,
                "tenant_id": tenant_id,
                "doc_type": doc_type,
                **metadata,
            }

            points.append(
                models.PointStruct(
                    id=doc_id,
                    vector=embedding,
                    payload=payload,
                )
            )

        # Upsert to Qdrant
        await client.upsert(collection_name=collection, points=points)

        logger.info(
            "Added documents to vector store",
            count=len(documents),
            tenant_id=tenant_id,
            collection=collection,
        )

        return ids

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        tenant_id: str,
        doc_type: str | None = None,
        limit: int = 5,
        score_threshold: float = 0.5,
        collection_name: str | None = None,
        additional_filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents.

        Args:
            query: Search query
            tenant_id: Tenant ID for filtering
            doc_type: Optional filter by document type
            limit: Maximum results to return
            score_threshold: Minimum similarity score
            collection_name: Override collection name
            additional_filters: Additional Qdrant filters

        Returns:
            List of SearchResult objects
        """
        client = await self._get_client()
        collection = collection_name or self.default_collection

        # Generate query embedding
        query_embedding = await self.embedding_service.embed_for_search(query)

        # Build filters
        must_conditions = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id),
            )
        ]

        if doc_type:
            must_conditions.append(
                models.FieldCondition(
                    key="doc_type",
                    match=models.MatchValue(value=doc_type),
                )
            )

        if additional_filters:
            for key, value in additional_filters.items():
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )

        query_filter = models.Filter(must=must_conditions)

        # Search
        try:
            results = await client.search(
                collection_name=collection,
                query_vector=query_embedding,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
            )

            search_results = [
                SearchResult(
                    id=str(r.id),
                    content=r.payload.get("content", ""),
                    score=r.score,
                    metadata={k: v for k, v in r.payload.items() if k != "content"},
                )
                for r in results
            ]

            logger.debug(
                "Vector search completed",
                query_length=len(query),
                results=len(search_results),
                tenant_id=tenant_id,
            )

            return search_results

        except Exception as e:
            logger.error("Vector search failed", error=str(e))
            raise VectorStoreError(f"Search failed: {e}", operation="search")

    async def delete_by_tenant(
        self,
        tenant_id: str,
        collection_name: str | None = None,
    ) -> int:
        """Delete all documents for a tenant."""
        client = await self._get_client()
        collection = collection_name or self.default_collection

        result = await client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        )
                    ]
                )
            ),
        )

        logger.info("Deleted tenant documents", tenant_id=tenant_id)
        return result.status

    async def health_check(self) -> bool:
        """Check if Qdrant is healthy."""
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception as e:
            logger.error("Qdrant health check failed", error=str(e))
            return False


# Singleton instance
_vector_store: QdrantVectorStore | None = None


def get_vector_store() -> QdrantVectorStore:
    """Get or create the vector store singleton."""
    global _vector_store
    if _vector_store is None:
        _vector_store = QdrantVectorStore()
    return _vector_store
