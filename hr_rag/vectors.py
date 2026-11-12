"""Mandatory server-side filtered Qdrant retrieval; in-memory fake for deterministic tests."""

import math
from .security import allowed


# Build database filters from verified identity using the same grants as the
# application access check.
def grant_scopes(p):
    scopes = (
        (["internal"] if (p.groups or p.teams or p.employee_id or p.admin) else [])
        + ["group:" + g for g in p.groups]
        + ["team:" + t for t in p.teams]
    )
    if p.employee_id:
        scopes.append("employee:" + p.employee_id)
    if p.admin:
        scopes.append("admin")
    return scopes


class QdrantStore:
    def __init__(self, url, collection, dimension):
        from qdrant_client import QdrantClient, models

        self.models = models
        self.collection = collection
        self.client = QdrantClient(url=url, timeout=30)
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config=models.VectorParams(
                    size=dimension, distance=models.Distance.COSINE
                ),
            )

        # Reject incompatible vector dimensions instead of mixing embeddings from
        # different model shapes.
        elif (
            self.client.get_collection(collection).config.params.vectors.size
            != dimension
        ):
            raise ValueError(
                "Collection dimension mismatch: create a fresh model collection"
            )
        for key, ty in [
            ("tenant_id", models.PayloadSchemaType.KEYWORD),
            ("namespace", models.PayloadSchemaType.KEYWORD),
            ("access_scopes", models.PayloadSchemaType.KEYWORD),
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("active", models.PayloadSchemaType.BOOL),
            ("model_id", models.PayloadSchemaType.KEYWORD),
        ]:
            try:
                self.client.create_payload_index(collection, key, ty, wait=True)
            except Exception:
                pass  # may already exist; retrieval filter is still enforced

    def upsert(self, chunks, vectors):
        m = self.models
        self.client.upsert(
            self.collection,
            points=[
                m.PointStruct(id=c.chunk_id, vector=v, payload=c.payload())
                for c, v in zip(chunks, vectors)
            ],
            wait=True,
        )

    def mark(self, ids, active):
        if ids:
            self.client.set_payload(
                self.collection, payload={"active": active}, points=ids, wait=True
            )

    def delete(self, ids):
        if ids:
            self.client.delete(
                self.collection,
                points_selector=self.models.PointIdsList(points=ids),
                wait=True,
            )

    def get(self, ids):
        if not ids:
            return []
        return [
            p.payload
            for p in self.client.retrieve(
                self.collection, ids=ids, with_payload=True, with_vectors=False
            )
        ]

    def search(
        self, vector, principal, namespace, limit=10, min_score=0, model_id=None
    ):
        m = self.models

        # Filter by tenant, area, active status and permissions inside Qdrant before
        # ranking results.
        must = [
            m.FieldCondition(
                key="tenant_id", match=m.MatchValue(value=principal.tenant_id)
            ),
            m.FieldCondition(key="namespace", match=m.MatchValue(value=namespace)),
            m.FieldCondition(key="active", match=m.MatchValue(value=True)),
            m.FieldCondition(
                key="access_scopes", match=m.MatchAny(any=grant_scopes(principal))
            ),
        ]
        if model_id:
            must.append(
                m.FieldCondition(key="model_id", match=m.MatchValue(value=model_id))
            )
        result = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=m.Filter(must=must),
            with_payload=True,
            limit=limit,
            score_threshold=(min_score if min_score > 0 else None),
        ).points

        # Check permissions again when results return so the application maintains its
        # own access boundary.
        return [
            (float(x.score), x.payload) for x in result if allowed(principal, x.payload)
        ]


class MemoryStore:
    """Non-production fake to test the entire ACL and document lifecycle without Qdrant."""

    def __init__(self):
        self.points = {}

    def upsert(self, chunks, vectors):
        for c, v in zip(chunks, vectors):
            self.points[c.chunk_id] = (v, c.payload())

    def mark(self, ids, active):
        for i in ids:
            if i in self.points:
                self.points[i][1]["active"] = active

    def delete(self, ids):
        for i in ids:
            self.points.pop(i, None)

    def get(self, ids):
        return [self.points[i][1] for i in ids if i in self.points]

    def search(
        self, vector, principal, namespace, limit=10, min_score=0, model_id=None
    ):
        out = []
        for v, p in self.points.values():
            if (
                not p.get("active")
                or p.get("namespace") != namespace
                or (model_id and p.get("model_id") != model_id)
                or not allowed(principal, p)
            ):
                continue
            norm = math.sqrt(sum(x * x for x in vector)) * math.sqrt(
                sum(x * x for x in v)
            )
            s = sum(a * b for a, b in zip(vector, v)) / norm if norm else 0.0
            if s >= min_score:
                out.append((s, p))
        return sorted(out, key=lambda t: -t[0])[:limit]
