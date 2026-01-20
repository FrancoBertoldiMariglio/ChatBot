"""Health check endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, status

from src.api.dependencies import RAGDep, StorageDep
from src.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
@router.get("/")
async def health_check() -> dict[str, Any]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.app_env,
    }


@router.get("/ready")
async def readiness_check(
    storage: StorageDep,
    rag: RAGDep,
) -> dict[str, Any]:
    """Readiness check - verifies all dependencies are available."""
    checks = {
        "storage": False,
        "vector_store": False,
    }

    # Check storage
    try:
        checks["storage"] = await storage.health_check()
    except Exception:
        pass

    # Check vector store
    try:
        checks["vector_store"] = await rag.vector_store.health_check()
    except Exception:
        pass

    all_healthy = all(checks.values())

    return {
        "status": "ready" if all_healthy else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }


@router.get("/live")
async def liveness_check() -> dict[str, str]:
    """Liveness check - basic endpoint for kubernetes probes."""
    return {"status": "alive"}
