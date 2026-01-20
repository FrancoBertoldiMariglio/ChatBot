"""Embedding service with multi-provider support (OpenAI, Google, etc.)."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings

logger = structlog.get_logger()


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""

    OPENAI = "openai"
    GOOGLE = "google"


class BaseEmbeddingService(ABC):
    """Abstract base class for embedding services."""

    @property
    @abstractmethod
    def vector_size(self) -> int:
        """Get the vector size for this embedding model."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        pass

    async def embed_for_search(self, query: str) -> list[float]:
        """Generate embedding optimized for search queries."""
        return await self.embed_text(query)

    async def embed_for_storage(self, document: str) -> list[float]:
        """Generate embedding optimized for document storage."""
        return await self.embed_text(document)


class OpenAIEmbeddingService(BaseEmbeddingService):
    """OpenAI embedding service using text-embedding-3-small/large.

    Pricing (as of 2024):
    - text-embedding-3-small: $0.02/1M tokens (1536 dims)
    - text-embedding-3-large: $0.13/1M tokens (3072 dims)
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions

        self._model_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

        logger.info("OpenAI Embedding service initialized", model=self.model)

    @property
    def vector_size(self) -> int:
        if self.dimensions:
            return self.dimensions
        return self._model_dimensions.get(self.model, 1536)

    @property
    def provider_name(self) -> str:
        return "openai"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            import litellm

            kwargs: dict[str, Any] = {}
            if self.dimensions and "text-embedding-3" in self.model:
                kwargs["dimensions"] = self.dimensions

            response = await litellm.aembedding(
                model=self.model,
                input=texts,
                **kwargs,
            )

            embeddings = [item["embedding"] for item in response.data]

            logger.debug(
                "Generated OpenAI embeddings",
                count=len(texts),
                model=self.model,
                dimensions=len(embeddings[0]) if embeddings else 0,
            )

            return embeddings

        except Exception as e:
            logger.error("Failed to generate OpenAI embeddings", error=str(e))
            raise


class GoogleEmbeddingService(BaseEmbeddingService):
    """Google AI embedding service using text-embedding-004.

    Free tier: 1,500 requests per minute
    Model: text-embedding-004 (768 dimensions)

    This is the recommended option for MVP to minimize costs.
    """

    def __init__(
        self,
        model: str = "text-embedding-004",
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> None:
        self.model = model
        self.task_type = task_type
        self._client = None
        self._initialized = False

        self._model_dimensions = {
            "text-embedding-004": 768,
            "embedding-001": 768,
        }

        logger.info("Google Embedding service initialized", model=self.model)

    def _ensure_initialized(self) -> None:
        """Lazy initialization of Google AI client."""
        if self._initialized:
            return

        try:
            import google.generativeai as genai

            api_key = settings.google_api_key
            if not api_key:
                raise ValueError("GOOGLE_API_KEY is required for Google embeddings")

            genai.configure(api_key=api_key)
            self._initialized = True
            logger.info("Google AI client initialized for embeddings")

        except ImportError:
            raise ImportError(
                "google-generativeai package is required for Google embeddings. "
                "Install with: pip install google-generativeai"
            )

    @property
    def vector_size(self) -> int:
        return self._model_dimensions.get(self.model, 768)

    @property
    def provider_name(self) -> str:
        return "google"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        self._ensure_initialized()

        try:
            import asyncio

            import google.generativeai as genai

            # Google's embed_content is sync, so we run in executor
            def _embed_batch(batch: list[str], task_type: str) -> list[list[float]]:
                results = []
                for text in batch:
                    result = genai.embed_content(
                        model=f"models/{self.model}",
                        content=text,
                        task_type=task_type,
                    )
                    results.append(result["embedding"])
                return results

            # Run sync function in thread pool
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                _embed_batch,
                texts,
                self.task_type,
            )

            logger.debug(
                "Generated Google embeddings",
                count=len(texts),
                model=self.model,
                dimensions=len(embeddings[0]) if embeddings else 0,
            )

            return embeddings

        except Exception as e:
            logger.error("Failed to generate Google embeddings", error=str(e))
            raise

    async def embed_for_search(self, query: str) -> list[float]:
        """Generate embedding optimized for search queries.

        Uses RETRIEVAL_QUERY task type for better search relevance.
        """
        original_task = self.task_type
        self.task_type = "RETRIEVAL_QUERY"
        try:
            return await self.embed_text(query)
        finally:
            self.task_type = original_task

    async def embed_for_storage(self, document: str) -> list[float]:
        """Generate embedding optimized for document storage.

        Uses RETRIEVAL_DOCUMENT task type.
        """
        original_task = self.task_type
        self.task_type = "RETRIEVAL_DOCUMENT"
        try:
            return await self.embed_text(document)
        finally:
            self.task_type = original_task


class EmbeddingService(BaseEmbeddingService):
    """Unified embedding service that delegates to the configured provider.

    Supports automatic fallback between providers.
    """

    def __init__(
        self,
        provider: EmbeddingProvider | str | None = None,
        model: str | None = None,
        fallback_provider: EmbeddingProvider | str | None = None,
    ) -> None:
        # Determine provider from settings or parameter
        if provider is None:
            provider = settings.embedding_provider

        if isinstance(provider, str):
            provider = EmbeddingProvider(provider.lower())

        self._provider_type = provider
        self._fallback_provider_type = None

        if fallback_provider:
            if isinstance(fallback_provider, str):
                fallback_provider = EmbeddingProvider(fallback_provider.lower())
            self._fallback_provider_type = fallback_provider

        # Initialize primary provider
        self._service = self._create_provider(provider, model)
        self._fallback_service = None

        if self._fallback_provider_type:
            self._fallback_service = self._create_provider(self._fallback_provider_type)

        logger.info(
            "Embedding service initialized",
            provider=provider.value,
            fallback=fallback_provider.value if fallback_provider else None,
            vector_size=self.vector_size,
        )

    def _create_provider(
        self,
        provider: EmbeddingProvider,
        model: str | None = None,
    ) -> BaseEmbeddingService:
        """Create embedding provider instance."""
        if provider == EmbeddingProvider.OPENAI:
            return OpenAIEmbeddingService(
                model=model or settings.openai_embedding_model,
            )
        elif provider == EmbeddingProvider.GOOGLE:
            return GoogleEmbeddingService(
                model=model or settings.google_embedding_model,
            )
        else:
            raise ValueError(f"Unknown embedding provider: {provider}")

    @property
    def vector_size(self) -> int:
        return self._service.vector_size

    @property
    def provider_name(self) -> str:
        return self._service.provider_name

    async def embed_text(self, text: str) -> list[float]:
        try:
            return await self._service.embed_text(text)
        except Exception as e:
            if self._fallback_service:
                logger.warning(
                    "Primary embedding failed, using fallback",
                    primary=self._provider_type.value,
                    fallback=self._fallback_provider_type.value,
                    error=str(e),
                )
                return await self._fallback_service.embed_text(text)
            raise

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self._service.embed_texts(texts)
        except Exception as e:
            if self._fallback_service:
                logger.warning(
                    "Primary embedding failed, using fallback",
                    primary=self._provider_type.value,
                    fallback=self._fallback_provider_type.value,
                    error=str(e),
                )
                return await self._fallback_service.embed_texts(texts)
            raise

    async def embed_for_search(self, query: str) -> list[float]:
        try:
            return await self._service.embed_for_search(query)
        except Exception as e:
            if self._fallback_service:
                return await self._fallback_service.embed_for_search(query)
            raise

    async def embed_for_storage(self, document: str) -> list[float]:
        try:
            return await self._service.embed_for_storage(document)
        except Exception as e:
            if self._fallback_service:
                return await self._fallback_service.embed_for_storage(document)
            raise


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def reset_embedding_service() -> None:
    """Reset the embedding service singleton (for testing or reconfiguration)."""
    global _embedding_service
    _embedding_service = None
