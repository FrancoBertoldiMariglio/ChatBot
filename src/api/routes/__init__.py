"""API routes."""

from src.api.routes.admin import router as admin_router
from src.api.routes.health import router as health_router
from src.api.routes.webhooks import router as webhooks_router

__all__ = ["admin_router", "health_router", "webhooks_router"]
