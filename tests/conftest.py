"""Pytest configuration and fixtures."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.api.main import create_app
from src.models import Tenant, TenantConfig, TenantStatus
from src.storage.memory import InMemoryStorage


@pytest.fixture
def app():
    """Create test application."""
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    """Create test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def storage():
    """Create in-memory storage for tests."""
    return InMemoryStorage()


@pytest_asyncio.fixture
async def demo_tenant(storage):
    """Create a demo tenant for tests."""
    tenant = Tenant(
        id="test-tenant",
        name="Test Company",
        status=TenantStatus.ACTIVE,
        config=TenantConfig(
            company_name="Test Company",
            welcome_message="Welcome to Test Company!",
        ),
    )
    await storage.save_tenant(tenant)
    return tenant
