"""Firestore storage backend for production."""

import os
from datetime import datetime, timedelta
from typing import Any

import structlog

from src.models import Conversation, Message, Tenant
from src.storage.base import StorageBackend

logger = structlog.get_logger()


class FirestoreStorage(StorageBackend):
    """Firestore storage implementation for production.

    Collection structure:
    - tenants/{tenant_id}
    - tenants/{tenant_id}/conversations/{conversation_id}
    - tenants/{tenant_id}/conversations/{conversation_id}/messages/{message_id}
    - sessions/{session_key}
    """

    def __init__(self, project_id: str | None = None) -> None:
        self._project_id = project_id
        self._db = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of Firestore client."""
        if self._initialized:
            return

        try:
            from google.cloud import firestore

            # Check if using emulator
            if os.environ.get("FIRESTORE_EMULATOR_HOST"):
                logger.info("Using Firestore emulator")

            self._db = firestore.AsyncClient(project=self._project_id)
            self._initialized = True
            logger.info("Firestore client initialized", project=self._project_id)
        except Exception as e:
            logger.error("Failed to initialize Firestore", error=str(e))
            raise

    # ==================== Tenant Operations ====================

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        await self._ensure_initialized()
        doc = await self._db.collection("tenants").document(tenant_id).get()
        if not doc.exists:
            return None
        return Tenant(**doc.to_dict())

    async def save_tenant(self, tenant: Tenant) -> Tenant:
        await self._ensure_initialized()
        tenant.updated_at = datetime.utcnow()
        await self._db.collection("tenants").document(tenant.id).set(
            tenant.model_dump(mode="json")
        )
        return tenant

    async def list_tenants(self, status: str | None = None) -> list[Tenant]:
        await self._ensure_initialized()
        query = self._db.collection("tenants")
        if status:
            query = query.where("status", "==", status)

        docs = await query.get()
        return [Tenant(**doc.to_dict()) for doc in docs]

    async def delete_tenant(self, tenant_id: str) -> bool:
        await self._ensure_initialized()
        await self._db.collection("tenants").document(tenant_id).delete()
        return True

    # ==================== Conversation Operations ====================

    def _conversation_ref(self, tenant_id: str, conversation_id: str):
        """Get reference to a conversation document."""
        return (
            self._db.collection("tenants")
            .document(tenant_id)
            .collection("conversations")
            .document(conversation_id)
        )

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        await self._ensure_initialized()
        # Need to search across tenants - in production, you'd have conversation_id include tenant
        # For MVP, we use a flat conversations collection
        doc = await self._db.collection("conversations").document(conversation_id).get()
        if not doc.exists:
            return None
        return Conversation(**doc.to_dict())

    async def get_conversation_by_user(
        self,
        tenant_id: str,
        user_id: str,
        channel: str = "whatsapp",
    ) -> Conversation | None:
        await self._ensure_initialized()

        query = (
            self._db.collection("conversations")
            .where("tenant_id", "==", tenant_id)
            .where("user_id", "==", user_id)
            .where("channel", "==", channel)
            .where("status", "in", ["active", "handoff_pending", "handoff_active"])
            .limit(1)
        )

        docs = await query.get()
        for doc in docs:
            return Conversation(**doc.to_dict())
        return None

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        await self._ensure_initialized()
        conversation.updated_at = datetime.utcnow()
        await self._db.collection("conversations").document(conversation.id).set(
            conversation.model_dump(mode="json")
        )
        return conversation

    async def list_conversations(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        await self._ensure_initialized()

        query = self._db.collection("conversations").where("tenant_id", "==", tenant_id)

        if status:
            query = query.where("status", "==", status)

        query = query.order_by("updated_at", direction="DESCENDING").limit(limit)
        docs = await query.get()

        return [Conversation(**doc.to_dict()) for doc in docs]

    # ==================== Message Operations ====================

    async def get_message(self, message_id: str) -> Message | None:
        await self._ensure_initialized()
        doc = await self._db.collection("messages").document(message_id).get()
        if not doc.exists:
            return None
        return Message(**doc.to_dict())

    async def save_message(self, message: Message) -> Message:
        await self._ensure_initialized()
        await self._db.collection("messages").document(message.id).set(
            message.model_dump(mode="json")
        )
        return message

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        before_id: str | None = None,
    ) -> list[Message]:
        await self._ensure_initialized()

        query = (
            self._db.collection("messages")
            .where("conversation_id", "==", conversation_id)
            .order_by("created_at")
            .limit(limit)
        )

        # TODO: Implement cursor-based pagination with before_id
        docs = await query.get()
        return [Message(**doc.to_dict()) for doc in docs]

    async def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 10,
    ) -> list[Message]:
        await self._ensure_initialized()

        query = (
            self._db.collection("messages")
            .where("conversation_id", "==", conversation_id)
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )

        docs = await query.get()
        messages = [Message(**doc.to_dict()) for doc in docs]
        # Reverse to get chronological order
        return list(reversed(messages))

    # ==================== Session/Cache Operations ====================

    async def set_session_data(
        self,
        key: str,
        data: dict[str, Any],
        ttl_seconds: int = 1800,
    ) -> None:
        await self._ensure_initialized()
        expiry = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        await self._db.collection("sessions").document(key).set({
            "data": data,
            "expires_at": expiry,
            "created_at": datetime.utcnow(),
        })

    async def get_session_data(self, key: str) -> dict | None:
        await self._ensure_initialized()
        doc = await self._db.collection("sessions").document(key).get()

        if not doc.exists:
            return None

        doc_data = doc.to_dict()
        expires_at = doc_data.get("expires_at")

        if expires_at and datetime.utcnow() > expires_at:
            await self.delete_session_data(key)
            return None

        return doc_data.get("data")

    async def delete_session_data(self, key: str) -> bool:
        await self._ensure_initialized()
        await self._db.collection("sessions").document(key).delete()
        return True

    # ==================== Health Check ====================

    async def health_check(self) -> bool:
        try:
            await self._ensure_initialized()
            # Simple health check - try to access a collection
            await self._db.collection("_health").document("check").get()
            return True
        except Exception as e:
            logger.error("Firestore health check failed", error=str(e))
            return False
