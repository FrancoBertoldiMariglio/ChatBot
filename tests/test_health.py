"""Tests for health check endpoints."""

import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    """Test basic health check."""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_liveness_check(client):
    """Test liveness probe."""
    response = await client.get("/health/live")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test root endpoint."""
    response = await client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert data["service"] == "AI Customer Support API"
    assert data["status"] == "running"
