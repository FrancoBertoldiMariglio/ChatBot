"""Webhook endpoints for channel integrations."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Form, HTTPException, Request, Response, status

from src.api.dependencies import (
    EngineDep,
    HandoffDep,
    SentimentDep,
    StorageDep,
    TwilioAuthDep,
    WhatsAppDep,
)
from src.core.exceptions import HandoffRequired, TenantNotFound
from src.models import ConversationStatus, MessageMetadata

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/whatsapp/{tenant_id}")
async def whatsapp_webhook(
    tenant_id: str,
    request: Request,
    storage: StorageDep,
    engine: EngineDep,
    whatsapp: WhatsAppDep,
    sentiment: SentimentDep,
    handoff: HandoffDep,
    # Twilio sends form data
    From: Annotated[str, Form()] = "",
    Body: Annotated[str, Form()] = "",
    MessageSid: Annotated[str, Form()] = "",
    ProfileName: Annotated[str | None, Form()] = None,
    NumMedia: Annotated[int, Form()] = 0,
) -> Response:
    """Handle incoming WhatsApp messages via Twilio webhook.

    Twilio expects a TwiML response or empty 200.
    """
    try:
        # Parse the form data into dict for adapter
        form_data = await request.form()
        payload = dict(form_data)

        # Parse webhook
        incoming = await whatsapp.parse_webhook(payload)

        if not incoming:
            # Not a message event (could be status callback)
            return Response(status_code=status.HTTP_200_OK)

        # Get tenant
        tenant = await storage.get_tenant(tenant_id)
        if not tenant:
            logger.error("Tenant not found for webhook", tenant_id=tenant_id)
            # Still return 200 to prevent Twilio from retrying
            return Response(status_code=status.HTTP_200_OK)

        # Get or create conversation
        conversation = await engine.get_or_create_conversation(
            tenant_id=tenant_id,
            user_id=incoming.user_id,
            channel="whatsapp",
        )

        # Check if conversation is in handoff mode
        if conversation.status in [ConversationStatus.HANDOFF_ACTIVE, ConversationStatus.HANDOFF_PENDING]:
            logger.info(
                "Message received during handoff, skipping bot response",
                conversation_id=conversation.id,
            )
            return Response(status_code=status.HTTP_200_OK)

        # Analyze sentiment
        sentiment_result = await sentiment.analyze(incoming.content)

        # Update conversation sentiment
        conversation.update_sentiment(sentiment_result.score)

        # Check for handoff triggers
        handoff_decision = await handoff.evaluate(
            message=incoming.content,
            conversation=conversation,
            tenant=tenant,
            sentiment_result=sentiment_result,
        )

        if handoff_decision.should_handoff:
            # Trigger handoff
            conversation.status = ConversationStatus.HANDOFF_PENDING
            conversation.handoff_reason = handoff_decision.reason
            await storage.save_conversation(conversation)

            # Send handoff message
            handoff_message = "I'm connecting you with a human agent who can better assist you. Please hold on a moment."
            await whatsapp.send_text(incoming.user_id, handoff_message)

            logger.info(
                "Handoff triggered",
                conversation_id=conversation.id,
                trigger=handoff_decision.trigger,
            )

            # TODO: Create ticket in Chatwoot
            return Response(status_code=status.HTTP_200_OK)

        # Process message with AI
        metadata = MessageMetadata(
            twilio_message_sid=MessageSid,
            sentiment_score=sentiment_result.score,
            sentiment_label=sentiment_result.sentiment,
        )

        response_text, _, llm_response = await engine.process_message(
            tenant=tenant,
            conversation=conversation,
            user_message=incoming.content,
            message_metadata=metadata,
        )

        # Send response via WhatsApp
        await whatsapp.send_text(incoming.user_id, response_text)

        logger.info(
            "Processed WhatsApp message",
            conversation_id=conversation.id,
            user_id=incoming.user_id,
            response_length=len(response_text),
        )

        return Response(status_code=status.HTTP_200_OK)

    except HandoffRequired as e:
        logger.info("Handoff required exception", details=e.details)
        return Response(status_code=status.HTTP_200_OK)

    except Exception as e:
        logger.error("Error processing WhatsApp webhook", error=str(e), exc_info=True)
        # Return 200 to prevent Twilio from retrying on our errors
        return Response(status_code=status.HTTP_200_OK)


@router.post("/whatsapp/{tenant_id}/status")
async def whatsapp_status_callback(
    tenant_id: str,
    request: Request,
) -> Response:
    """Handle WhatsApp message status callbacks from Twilio.

    Updates message delivery/read status.
    """
    form_data = await request.form()
    message_sid = form_data.get("MessageSid")
    message_status = form_data.get("MessageStatus")

    logger.debug(
        "WhatsApp status callback",
        tenant_id=tenant_id,
        message_sid=message_sid,
        status=message_status,
    )

    # TODO: Update message status in storage

    return Response(status_code=status.HTTP_200_OK)
