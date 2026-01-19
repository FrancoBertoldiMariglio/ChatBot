"""Custom exceptions for the application."""

from typing import Any


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ConfigurationError(AppException):
    """Raised when there's a configuration problem."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="CONFIGURATION_ERROR", details=details)


class TenantNotFound(AppException):
    """Raised when a tenant is not found."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            f"Tenant not found: {tenant_id}",
            code="TENANT_NOT_FOUND",
            details={"tenant_id": tenant_id},
        )


class RateLimitExceeded(AppException):
    """Raised when rate limit is exceeded."""

    def __init__(self, tenant_id: str, limit: int, window: int) -> None:
        super().__init__(
            f"Rate limit exceeded for tenant {tenant_id}",
            code="RATE_LIMIT_EXCEEDED",
            details={"tenant_id": tenant_id, "limit": limit, "window_seconds": window},
        )


class HandoffRequired(AppException):
    """Raised when human handoff is required."""

    def __init__(
        self,
        reason: str,
        conversation_id: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"Human handoff required: {reason}",
            code="HANDOFF_REQUIRED",
            details={
                "reason": reason,
                "conversation_id": conversation_id,
                "context": context or {},
            },
        )


class LLMError(AppException):
    """Raised when LLM provider fails."""

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(
            message,
            code="LLM_ERROR",
            details={"provider": provider} if provider else {},
        )


class VectorStoreError(AppException):
    """Raised when vector store operations fail."""

    def __init__(self, message: str, operation: str | None = None) -> None:
        super().__init__(
            message,
            code="VECTOR_STORE_ERROR",
            details={"operation": operation} if operation else {},
        )


class ChannelError(AppException):
    """Raised when channel operations fail."""

    def __init__(self, message: str, channel: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="CHANNEL_ERROR",
            details={"channel": channel, **(details or {})},
        )
