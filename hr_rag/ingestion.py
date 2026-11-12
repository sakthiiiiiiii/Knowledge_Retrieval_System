"""Permission-first ingestion and invalidation. Pilots need serialized admin writes."""

import hashlib
import uuid
from pathlib import Path
from .parse import parse, check_file
from .policy import policy_for, classify, Quarantined
from .chunking import chunk_blocks
from .embeddings import evidence_text
from .security import require_admin


class Ingestor:
    def __init__(self, registry, store, embedder, settings, cache=None):
        self.registry = registry
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self.cache = cache

    def ingest(self, name, raw, admin, tenant_id=None):
        # Step 1: Require administrator access and keep ingestion inside the
        # administrator's tenant.
        require_admin(admin)
        tenant = tenant_id or admin.tenant_id
        if tenant != admin.tenant_id:
            raise PermissionError("Cross-tenant ingestion forbidden")
        check_file(name, raw)
        policy = policy_for(name)

        # Identify unchanged source bytes so repeated uploads can reuse an already
        # active version.
        sha = hashlib.sha256(raw).hexdigest()
        namespace = policy["namespace"]
        old = self.registry.find(tenant, namespace, name)
        if (
            old
            and old["sha"] == sha
            and len([p for p in self.store.get(old["chunk_ids"]) if p.get("active")])
            == len(old["chunk_ids"])
        ):
            return {
                "status": "duplicate",
                "document_id": old["document_id"],
                "version": old["version"],
            }

        # Step 2: Apply access rules before chunking so restricted material never
        # inherits broader permissions.
        blocks = classify(parse(name, raw), policy)
        doc_id = old["document_id"] if old else str(uuid.uuid4())

        # Allocate a new document version so replacements remain distinct from older
        # evidence.
        with self.registry.lock:
            version = self.registry.conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM docs WHERE document_id=?",
                (doc_id,),
            ).fetchone()[0]
        chunks = chunk_blocks(
            blocks,
            document_id=doc_id,
            source_filename=Path(name).name,
            source_group=policy["source_group"],
            tenant_id=tenant,
            namespace=namespace,
            version=version,
            source_hash=sha,
            size=self.settings.chunk_tokens,
            overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            raise Quarantined("No classified content to publish")
        for c in chunks:
            c.model_id = self.settings.retrieval_id

        # Step 3: Encode chunks in order and verify counts so each payload gets its
        # own embedding.
        texts = [evidence_text(c) for c in chunks]
        vectors = self.embedder.encode_passages(texts)
        if len(vectors) != len(chunks):
            raise ValueError("Embedding count mismatch")
        outdir = self.settings.data_dir / "documents"
        outdir.mkdir(parents=True, exist_ok=True)
        # Original bytes are private, never written into a web-served/static directory.
        path = outdir / (doc_id + "-v" + str(version) + Path(name).suffix.lower())
        path.write_bytes(raw)
        path.chmod(0o600)

        # Step 4: Stage the new chunks before making them visible, then retire the old
        # version.
        ids = [c.chunk_id for c in chunks]
        try:
            self.store.upsert(chunks, vectors)  # staged; not active
            self.registry.add(
                doc_id, version, tenant, namespace, name, sha, path, "staged", ids
            )
            if old:
                self.store.mark(old["chunk_ids"], False)
            self.store.mark(ids, True)
            if old:
                self.registry.set_status(doc_id, old["version"], "superseded")
            self.registry.set_status(doc_id, version, "ready")
            self.registry.bump()  # immediately changes every exact-cache lookup key
            # Retire obsolete embeddings after new version is visible.
            if old:
                try:
                    self.store.delete(old["chunk_ids"])
                except Exception:
                    pass  # still inactive; admin cleanup/reconciliation needed

        # Remove partially staged data and reactivate the earlier chunks if
        # publication fails.
        except Exception:
            self.store.delete(ids)
            if old:
                self.store.mark(old["chunk_ids"], True)
            try:
                self.registry.set_status(doc_id, version, "failed")
            except Exception:
                pass
            path.unlink(missing_ok=True)
            raise
        return {
            "status": "ready",
            "document_id": doc_id,
            "version": version,
            "chunks": len(chunks),
            "namespace": namespace,
        }

    # Delete indexed content and stored bytes together, then invalidate old answer-
    # cache keys.
    def delete(self, doc_id, admin):
        require_admin(admin)
        with self.registry.lock:
            rows = self.registry.conn.execute(
                (
                    "SELECT version,chunk_ids,local_path FROM docs WHERE document_id=? "
                    "AND tenant=? AND status!='deleted'"
                ),
                (doc_id, admin.tenant_id),
            ).fetchall()
            if not rows:
                raise KeyError("Active document not found")
            for _, ids, _ in rows:
                self.store.delete(__import__("json").loads(ids))
            for version, _, path in rows:
                self.registry.set_status(doc_id, version, "deleted")
                Path(path).unlink(missing_ok=True)
            self.registry.bump()
        return {"status": "deleted", "document_id": doc_id}
