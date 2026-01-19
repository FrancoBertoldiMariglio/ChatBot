"""Embedding service using OpenAI or other providers via LiteLLM."""

from typing import Any

import litellm
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings

logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating text embeddings.

    Uses OpenAI's text-embedding-3-small by default for best cost/performance.
    """

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model = model or settings.litellm_embedding_model
        # text-embedding-3-small supports dimensions parameter
        self.dimensions = dimensions  # None = use default (1536 for text-embedding-3-small)

        # Model info for vector store
        self._model_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

        logger.info("Embedding service initialized", model=self.model)

    @property
    def vector_size(self) -> int:
        """Get the vector size for this embedding model."""
        if self.dimensions:
            return self.dimensions
        return self._model_dimensions.get(self.model, 1536)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            kwargs: dict[str, Any] = {}
            if self.dimensions and "text-embedding-3" in self.model:
                kwargs["dimensions"] = self.dimensions

            response = await litellm.aembedding(
                model=self.model,
                input=texts,
                **kwargs,
            )

            # Extract embeddings from response
            embeddings = [item["embedding"] for item in response.data]

            logger.debug(
                "Generated embeddings",
                count=len(texts),
                model=self.model,
                dimensions=len(embeddings[0]) if embeddings else 0,
            )

            return embeddings

        except Exception as e:
            logger.error("Failed to generate embeddings", error=str(e))
            raise

    async def embed_for_search(self, query: str) -> list[float]:
        """Generate embedding optimized for search queries.

        For some models, query embeddings might be processed differently.
        """
        return await self.embed_text(query)

    async def embed_for_storage(self, document: str) -> list[float]:
        """Generate embedding optimized for document storage."""
        return await self.embed_text(document)


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
