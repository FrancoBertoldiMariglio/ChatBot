"""Application configuration using Pydantic settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""

    # LLM Providers
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # Vertex AI (optional)
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # LiteLLM
    litellm_primary_model: str = "gemini/gemini-1.5-flash"
    litellm_fallback_model: str = "gpt-4o-mini"

    # Embeddings
    # Provider: "google" (free tier, recommended) or "openai" (paid)
    embedding_provider: Literal["google", "openai"] = "google"
    # Fallback provider (optional) - if primary fails, try this one
    embedding_fallback_provider: str | None = None
    # OpenAI models: text-embedding-3-small (1536d), text-embedding-3-large (3072d)
    openai_embedding_model: str = "text-embedding-3-small"
    # Google models: text-embedding-004 (768d, FREE)
    google_embedding_model: str = "text-embedding-004"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_url: str | None = None
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "knowledge_base"

    # Firestore
    firestore_emulator_host: str | None = None
    gcp_project_id: str = ""

    # AWS Comprehend
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Chatwoot
    chatwoot_base_url: str = ""
    chatwoot_api_key: str = ""
    chatwoot_account_id: int = 1

    # Security
    secret_key: str = Field(default="development-secret-key-change-in-production")

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Conversation settings
    max_context_messages: int = 10
    session_timeout_minutes: int = 30
    summary_threshold_turns: int = 15

    # Handoff triggers
    handoff_sentiment_threshold: float = -0.5
    handoff_confidence_threshold: float = 0.6
    handoff_max_fallbacks: int = 2

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
