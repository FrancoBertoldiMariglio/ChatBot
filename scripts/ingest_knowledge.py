#!/usr/bin/env python3
"""Script to ingest documents into a tenant's knowledge base."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.rag.embeddings import EmbeddingService
from src.services.rag.vectorstore import QdrantVectorStore


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into chunks with overlap."""
    words = text.split()
    chunks = []

    for i in range(0, len(words), chunk_size - overlap):
        chunk = ' '.join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)

    return chunks


async def ingest_file(
    file_path: Path,
    tenant_id: str,
    vector_store: QdrantVectorStore,
    chunk_size: int = 500,
) -> int:
    """Ingest a single file into the knowledge base."""
    print(f"Processing: {file_path}")

    # Read file content
    content = file_path.read_text(encoding='utf-8')

    # Chunk the content
    chunks = chunk_text(content, chunk_size=chunk_size)

    if not chunks:
        print(f"  No content to ingest")
        return 0

    # Prepare metadata
    metadata = [
        {
            "source": str(file_path),
            "filename": file_path.name,
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]

    # Add to vector store
    doc_ids = await vector_store.add_documents(
        documents=chunks,
        tenant_id=tenant_id,
        doc_type="knowledge",
        metadata_list=metadata,
    )

    print(f"  Ingested {len(doc_ids)} chunks")
    return len(doc_ids)


async def ingest_json_faqs(
    file_path: Path,
    tenant_id: str,
    vector_store: QdrantVectorStore,
) -> int:
    """Ingest FAQ-style JSON file.

    Expected format:
    [
        {"question": "...", "answer": "..."},
        ...
    ]
    """
    print(f"Processing FAQs: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        faqs = json.load(f)

    documents = []
    metadata_list = []

    for i, faq in enumerate(faqs):
        question = faq.get('question', '')
        answer = faq.get('answer', '')

        if question and answer:
            # Combine Q&A for better retrieval
            doc = f"Question: {question}\n\nAnswer: {answer}"
            documents.append(doc)
            metadata_list.append({
                "source": str(file_path),
                "type": "faq",
                "faq_index": i,
                "question": question[:100],  # Truncate for metadata
            })

    if not documents:
        print(f"  No FAQs to ingest")
        return 0

    doc_ids = await vector_store.add_documents(
        documents=documents,
        tenant_id=tenant_id,
        doc_type="knowledge",
        metadata_list=metadata_list,
    )

    print(f"  Ingested {len(doc_ids)} FAQs")
    return len(doc_ids)


async def main():
    parser = argparse.ArgumentParser(description="Ingest documents into knowledge base")
    parser.add_argument("tenant_id", help="Tenant ID")
    parser.add_argument("path", help="File or directory path to ingest")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size in words")
    parser.add_argument("--extensions", nargs="+", default=[".txt", ".md"], help="File extensions to process")

    args = parser.parse_args()

    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path does not exist: {path}")
        sys.exit(1)

    # Initialize services
    embedding_service = EmbeddingService()
    vector_store = QdrantVectorStore(embedding_service=embedding_service)

    # Ensure collection exists
    await vector_store.ensure_collection()

    total_docs = 0

    if path.is_file():
        # Single file
        if path.suffix == '.json':
            total_docs = await ingest_json_faqs(path, args.tenant_id, vector_store)
        else:
            total_docs = await ingest_file(path, args.tenant_id, vector_store, args.chunk_size)
    else:
        # Directory
        for ext in args.extensions:
            for file_path in path.rglob(f"*{ext}"):
                docs = await ingest_file(file_path, args.tenant_id, vector_store, args.chunk_size)
                total_docs += docs

        # Also process JSON files
        for file_path in path.rglob("*.json"):
            docs = await ingest_json_faqs(file_path, args.tenant_id, vector_store)
            total_docs += docs

    print(f"\nTotal documents ingested: {total_docs}")


if __name__ == "__main__":
    asyncio.run(main())
