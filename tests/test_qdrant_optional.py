"""Real Qdrant local-memory integration test, executed when client dependency installed."""

# Exercise the Qdrant client locally to verify that retrieval filters are actually
# applied.

import pytest

pytest.importorskip("qdrant_client")
from hr_rag.vectors import QdrantStore
from hr_rag.models import Chunk, Principal


def test_qdrant_filtered_search(monkeypatch):
    from qdrant_client import QdrantClient
    from hr_rag import vectors

    # In-process Qdrant client; production uses HTTP service.
    original = vectors.QdrantStore
    client = QdrantClient(":memory:")
    from qdrant_client import models

    client.create_collection(
        "test",
        vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
    )
    from uuid import uuid4

    point = Chunk(
        chunk_id=str(uuid4()),
        document_id="x",
        source_filename="x",
        source_group="x",
        text="private",
        heading="",
        locator="row",
        tenant_id="tenant",
        namespace="hr",
        access_scopes=["group:hr"],
        classification="restricted",
        model_id="test@1",
        active=True,
    )
    client.upsert(
        "test",
        [
            models.PointStruct(
                id=point.chunk_id, vector=[1.0, 0.0], payload=point.payload()
            )
        ],
    )
    filt = models.Filter(
        must=[
            models.FieldCondition(
                key="tenant_id", match=models.MatchValue(value="tenant")
            ),
            models.FieldCondition(
                key="access_scopes", match=models.MatchAny(any=["group:hr"])
            ),
        ]
    )
    assert (
        len(client.query_points("test", query=[1.0, 0.0], query_filter=filt).points)
        == 1
    )
    deny = models.Filter(
        must=[
            models.FieldCondition(
                key="access_scopes", match=models.MatchAny(any=["group:finance"])
            )
        ]
    )
    assert (
        len(client.query_points("test", query=[1.0, 0.0], query_filter=deny).points)
        == 0
    )
