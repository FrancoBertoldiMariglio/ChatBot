"""Abstract base class for channel adapters."""

from abc import ABC, abstractmethod
from typing import Any

from src.models import IncomingWebhookMessage, OutgoingMessage


class ChannelAdapter(ABC):
    """Abstract base class for communication channel adapters.

    Each channel (WhatsApp, WebChat, Voice, etc.) implements this interface.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Get the channel name identifier."""
        ...

    @abstractmethod
    async def parse_webhook(self, payload: dict[str, Any]) -> IncomingWebhookMessage | None:
        """Parse incoming webhook payload into a normalized message.

        Args:
            payload: Raw webhook payload from the channel

        Returns:
            IncomingWebhookMessage or None if not a message event
        """
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> dict[str, Any]:
        """Send a message through the channel.

        Args:
            message: OutgoingMessage to send

        Returns:
            Response dict with channel-specific info (message ID, status, etc.)
        """
        ...

    @abstractmethod
    def validate_webhook(self, request_data: bytes, signature: str) -> bool:
        """Validate webhook signature for security.

        Args:
            request_data: Raw request body
            signature: Signature header value

        Returns:
            True if valid, False otherwise
        """
        ...

    async def send_text(self, recipient_id: str, text: str) -> dict[str, Any]:
        """Convenience method to send a simple text message.

        Args:
            recipient_id: Recipient's channel ID
            text: Message text

        Returns:
            Response dict
        """
        message = OutgoingMessage(
            content=text,
            recipient_id=recipient_id,
        )
        return await self.send_message(message)
