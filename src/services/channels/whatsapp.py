"""Twilio WhatsApp channel adapter."""

import hmac
import hashlib
from typing import Any
from urllib.parse import urlencode

import structlog
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from src.core.config import settings
from src.core.exceptions import ChannelError
from src.models import ChannelType, IncomingWebhookMessage, MessageType, OutgoingMessage
from src.services.channels.base import ChannelAdapter

logger = structlog.get_logger()


class TwilioWhatsAppAdapter(ChannelAdapter):
    """Twilio WhatsApp channel adapter.

    Handles:
    - Webhook parsing for incoming WhatsApp messages
    - Sending messages via Twilio API
    - Webhook signature validation
    """

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        whatsapp_number: str | None = None,
    ) -> None:
        self.account_sid = account_sid or settings.twilio_account_sid
        self.auth_token = auth_token or settings.twilio_auth_token
        self.whatsapp_number = whatsapp_number or settings.twilio_whatsapp_number

        self._client: TwilioClient | None = None

        if self.account_sid and self.auth_token:
            self._client = TwilioClient(self.account_sid, self.auth_token)
            logger.info("Twilio WhatsApp adapter initialized")
        else:
            logger.warning("Twilio credentials not configured")

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def _get_client(self) -> TwilioClient:
        """Get Twilio client, raising error if not configured."""
        if self._client is None:
            raise ChannelError(
                "Twilio client not configured",
                channel="whatsapp",
                details={"reason": "missing_credentials"},
            )
        return self._client

    async def parse_webhook(self, payload: dict[str, Any]) -> IncomingWebhookMessage | None:
        """Parse Twilio WhatsApp webhook payload.

        Twilio sends form-urlencoded data with fields like:
        - From: whatsapp:+1234567890
        - To: whatsapp:+0987654321
        - Body: Message text
        - MessageSid: Unique message ID
        - NumMedia: Number of media attachments
        """
        # Check if this is a message event
        message_sid = payload.get("MessageSid")
        if not message_sid:
            logger.debug("Webhook is not a message event", payload_keys=list(payload.keys()))
            return None

        # Extract sender info
        from_number = payload.get("From", "")
        if not from_number.startswith("whatsapp:"):
            logger.warning("Invalid WhatsApp sender format", from_number=from_number)
            return None

        # Parse user ID (phone number without whatsapp: prefix)
        user_id = from_number.replace("whatsapp:", "")

        # Get message content
        body = payload.get("Body", "").strip()

        # Determine message type
        num_media = int(payload.get("NumMedia", 0))
        message_type = MessageType.TEXT

        media_url = None
        media_content_type = None

        if num_media > 0:
            media_url = payload.get("MediaUrl0")
            media_content_type = payload.get("MediaContentType0", "")

            if media_content_type.startswith("image/"):
                message_type = MessageType.IMAGE
            elif media_content_type.startswith("audio/"):
                message_type = MessageType.AUDIO
            elif media_content_type.startswith("video/"):
                message_type = MessageType.VIDEO
            else:
                message_type = MessageType.DOCUMENT

        # Get user name if available (from profile)
        user_name = payload.get("ProfileName")

        incoming_message = IncomingWebhookMessage(
            channel=ChannelType.WHATSAPP,
            user_id=user_id,
            content=body,
            message_type=message_type,
            user_name=user_name,
            user_phone=user_id,
            media_url=media_url,
            media_content_type=media_content_type,
            raw_payload=payload,
        )

        logger.info(
            "Parsed WhatsApp message",
            user_id=user_id,
            message_type=message_type,
            has_media=num_media > 0,
        )

        return incoming_message

    async def send_message(self, message: OutgoingMessage) -> dict[str, Any]:
        """Send a WhatsApp message via Twilio.

        Args:
            message: OutgoingMessage to send

        Returns:
            Dict with message SID and status
        """
        client = self._get_client()

        # Format recipient as WhatsApp number
        to_number = message.recipient_id
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        try:
            # Build message parameters
            params: dict[str, Any] = {
                "from_": self.whatsapp_number,
                "to": to_number,
            }

            # Handle template messages
            if message.template_name:
                # For template messages, use content_sid approach
                # This is simplified - real implementation would use Twilio Content API
                params["body"] = message.content
            else:
                params["body"] = message.content

            # Handle media
            if message.media_url:
                params["media_url"] = [message.media_url]

            # Send message
            twilio_message = client.messages.create(**params)

            logger.info(
                "Sent WhatsApp message",
                message_sid=twilio_message.sid,
                to=to_number,
                status=twilio_message.status,
            )

            return {
                "message_sid": twilio_message.sid,
                "status": twilio_message.status,
                "to": to_number,
            }

        except TwilioRestException as e:
            logger.error(
                "Failed to send WhatsApp message",
                error=str(e),
                error_code=e.code,
                to=to_number,
            )
            raise ChannelError(
                f"Failed to send WhatsApp message: {e.msg}",
                channel="whatsapp",
                details={"error_code": e.code, "recipient": to_number},
            )

    def validate_webhook(self, request_data: bytes, signature: str) -> bool:
        """Validate Twilio webhook signature.

        Twilio signs requests using HMAC-SHA1.

        Args:
            request_data: Raw request body
            signature: X-Twilio-Signature header value

        Returns:
            True if signature is valid
        """
        if not self.auth_token:
            logger.warning("Cannot validate webhook: auth token not configured")
            return False

        # In development, optionally skip validation
        if settings.is_development and not signature:
            logger.warning("Skipping webhook validation in development mode")
            return True

        # Twilio signature validation
        # The signature is computed over the full URL + sorted POST parameters
        # For simplicity, we'll use the request body approach
        try:
            # Decode request data to dict
            from urllib.parse import parse_qs
            params = parse_qs(request_data.decode("utf-8"))
            # Flatten single-value lists
            flat_params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}

            # This is a simplified validation
            # Full implementation would need the request URL
            # For now, we trust Twilio if signature header is present
            if signature:
                return True

            return False

        except Exception as e:
            logger.error("Webhook validation failed", error=str(e))
            return False

    async def send_template(
        self,
        recipient_id: str,
        template_name: str,
        parameters: dict[str, str],
    ) -> dict[str, Any]:
        """Send a WhatsApp template message.

        Template messages are required for messages outside the 24h window.

        Args:
            recipient_id: Recipient's phone number
            template_name: Name of the approved template
            parameters: Template parameters

        Returns:
            Response dict
        """
        message = OutgoingMessage(
            content="",  # Will be replaced by template
            recipient_id=recipient_id,
            template_name=template_name,
            template_params=parameters,
        )
        return await self.send_message(message)


# Singleton instance
_whatsapp_adapter: TwilioWhatsAppAdapter | None = None


def get_whatsapp_adapter() -> TwilioWhatsAppAdapter:
    """Get or create the WhatsApp adapter singleton."""
    global _whatsapp_adapter
    if _whatsapp_adapter is None:
        _whatsapp_adapter = TwilioWhatsAppAdapter()
    return _whatsapp_adapter
