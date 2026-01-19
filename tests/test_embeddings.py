"""Tests for embedding service with multi-provider support."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.rag.embeddings import (
    EmbeddingProvider,
    EmbeddingService,
    GoogleEmbeddingService,
    OpenAIEmbeddingService,
    reset_embedding_service,
)


class TestOpenAIEmbeddingService:
    """Tests for OpenAI embedding service."""

    def test_vector_size_default(self):
        """Test default vector size for text-embedding-3-small."""
        service = OpenAIEmbeddingService(model="text-embedding-3-small")
        assert service.vector_size == 1536

    def test_vector_size_large(self):
        """Test vector size for text-embedding-3-large."""
        service = OpenAIEmbeddingService(model="text-embedding-3-large")
        assert service.vector_size == 3072

    def test_vector_size_custom_dimensions(self):
        """Test custom dimensions override."""
        service = OpenAIEmbeddingService(model="text-embedding-3-small", dimensions=512)
        assert service.vector_size == 512

    def test_provider_name(self):
        """Test provider name."""
        service = OpenAIEmbeddingService()
        assert service.provider_name == "openai"


class TestGoogleEmbeddingService:
    """Tests for Google embedding service."""

    def test_vector_size_default(self):
        """Test default vector size for text-embedding-004."""
        service = GoogleEmbeddingService(model="text-embedding-004")
        assert service.vector_size == 768

    def test_provider_name(self):
        """Test provider name."""
        service = GoogleEmbeddingService()
        assert service.provider_name == "google"


class TestEmbeddingService:
    """Tests for unified embedding service."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_embedding_service()

    @patch("src.services.rag.embeddings.settings")
    def test_google_provider_initialization(self, mock_settings):
        """Test initialization with Google provider."""
        mock_settings.embedding_provider = "google"
        mock_settings.google_embedding_model = "text-embedding-004"
        mock_settings.embedding_fallback_provider = None

        service = EmbeddingService(provider=EmbeddingProvider.GOOGLE)
        assert service.provider_name == "google"
        assert service.vector_size == 768

    @patch("src.services.rag.embeddings.settings")
    def test_openai_provider_initialization(self, mock_settings):
        """Test initialization with OpenAI provider."""
        mock_settings.embedding_provider = "openai"
        mock_settings.openai_embedding_model = "text-embedding-3-small"
        mock_settings.embedding_fallback_provider = None

        service = EmbeddingService(provider=EmbeddingProvider.OPENAI)
        assert service.provider_name == "openai"
        assert service.vector_size == 1536

    @patch("src.services.rag.embeddings.settings")
    def test_string_provider_initialization(self, mock_settings):
        """Test initialization with string provider."""
        mock_settings.embedding_provider = "google"
        mock_settings.google_embedding_model = "text-embedding-004"
        mock_settings.embedding_fallback_provider = None

        service = EmbeddingService(provider="google")
        assert service.provider_name == "google"

    @patch("src.services.rag.embeddings.settings")
    def test_fallback_configuration(self, mock_settings):
        """Test fallback provider configuration."""
        mock_settings.embedding_provider = "google"
        mock_settings.google_embedding_model = "text-embedding-004"
        mock_settings.openai_embedding_model = "text-embedding-3-small"
        mock_settings.embedding_fallback_provider = None

        service = EmbeddingService(
            provider=EmbeddingProvider.GOOGLE,
            fallback_provider=EmbeddingProvider.OPENAI,
        )
        assert service.provider_name == "google"
        assert service._fallback_service is not None
        assert service._fallback_service.provider_name == "openai"


class TestEmbeddingDimensions:
    """Test embedding dimensions for different providers."""

    def test_google_dimensions(self):
        """Google text-embedding-004 should have 768 dimensions."""
        service = GoogleEmbeddingService()
        assert service.vector_size == 768

    def test_openai_small_dimensions(self):
        """OpenAI text-embedding-3-small should have 1536 dimensions."""
        service = OpenAIEmbeddingService(model="text-embedding-3-small")
        assert service.vector_size == 1536

    def test_openai_large_dimensions(self):
        """OpenAI text-embedding-3-large should have 3072 dimensions."""
        service = OpenAIEmbeddingService(model="text-embedding-3-large")
        assert service.vector_size == 3072
