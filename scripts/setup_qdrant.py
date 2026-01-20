#!/usr/bin/env python3
"""Script to initialize Qdrant collections."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient, models

from src.core.config import settings


async def setup_collections():
    """Set up Qdrant collections with proper configuration."""
    print(f"Connecting to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}")

    if settings.qdrant_url:
        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )
    else:
        client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )

    collection_name = settings.qdrant_collection_name

    # Check if collection exists
    collections = client.get_collections()
    exists = any(c.name == collection_name for c in collections.collections)

    if exists:
        print(f"Collection '{collection_name}' already exists")
        response = input("Do you want to recreate it? (y/N): ")
        if response.lower() == 'y':
            print(f"Deleting collection '{collection_name}'...")
            client.delete_collection(collection_name)
        else:
            print("Skipping collection creation")
            return

    # Create collection
    print(f"Creating collection '{collection_name}'...")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=1536,  # text-embedding-3-small dimensions
            distance=models.Distance.COSINE,
        ),
    )

    # Create payload indexes for efficient filtering
    print("Creating payload indexes...")

    # Tenant ID index (required for multi-tenancy)
    client.create_payload_index(
        collection_name=collection_name,
        field_name="tenant_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    # Document type index
    client.create_payload_index(
        collection_name=collection_name,
        field_name="doc_type",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    # User ID index (for memory retrieval)
    client.create_payload_index(
        collection_name=collection_name,
        field_name="user_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    print(f"Collection '{collection_name}' created successfully!")

    # Show collection info
    info = client.get_collection(collection_name)
    print(f"\nCollection info:")
    print(f"  - Vectors count: {info.vectors_count}")
    print(f"  - Points count: {info.points_count}")
    print(f"  - Vector size: {info.config.params.vectors.size}")
    print(f"  - Distance: {info.config.params.vectors.distance}")


if __name__ == "__main__":
    asyncio.run(setup_collections())
