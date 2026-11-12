"""One runtime for API and CLI; local setup needs neither Docker nor a model download."""

import hashlib
import logging
from .config import Settings
from .embeddings import LocalEmbedder
from .registry import Registry
from .vectors import QdrantStore
from .lexical import LexicalEncoder, SQLiteLexicalStore
from .cache import ExactCache
from .generation import GroqGenerator, ExtractiveGenerator
from .engine import AnswerEngine
from .ingestion import Ingestor
from .models import Principal
from .policy import policy_for, Quarantined

log = logging.getLogger(__name__)


def build(settings=None):
    settings = (settings or Settings()).validate()
    # Separate indexes and registries: a backend/model change must never reuse stale
    # metadata.
    identity = (
        settings.retrieval_id + "|" + settings.collection + "|" + settings.qdrant_url
    )
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:12]
    state_dir = settings.data_dir / "state" / (settings.retrieval_mode + "-" + suffix)
    registry = Registry(state_dir / "registry.sqlite3")

    # Choose the local backend by default; load neural embeddings only when dense
    # retrieval is requested.
    if settings.retrieval_mode == "lexical":
        embedder = LexicalEncoder()
        store = SQLiteLexicalStore(state_dir / "search.sqlite3")
    else:
        embedder = LocalEmbedder(settings.embed_model, settings.embed_revision)
        store = QdrantStore(
            settings.qdrant_url, settings.collection, embedder.dimension
        )
    cache = None

    # Treat caching as optional so a local installation can run without a Redis
    # service.
    if settings.redis_url:
        try:
            cache = ExactCache(settings.redis_url)
        except ImportError:
            log.warning("Redis dependency missing; answer caching is disabled")

    # Select a cloud generator only through configuration; otherwise return labelled
    # source excerpts.
    cloud = settings.generation_mode == "groq" or (
        settings.generation_mode == "auto" and settings.enable_external_llm
    )
    generator = GroqGenerator(settings) if cloud else ExtractiveGenerator()
    engine = AnswerEngine(settings, registry, store, embedder, generator, cache)
    ingestor = Ingestor(registry, store, embedder, settings, cache)
    engine.import_report = []

    # Import bundled originals on startup so a fresh extraction has a searchable
    # corpus.
    if settings.auto_import:
        admin = Principal(
            "local-import", "swiftpay", groups=("hr_rag_admin",), admin=True
        )
        for path in sorted((settings.data_dir / "source").glob("*")):
            if not path.is_file():
                continue
            try:
                # Require an approved policy before any bundled file can become
                # searchable.
                policy_for(path.name)
            except Quarantined:
                engine.import_report.append(
                    {"name": path.name, "status": "held_for_review"}
                )
                continue
            # An explicit deletion remains deleted across restarts, even if a bundled
            # original exists.
            with registry.lock:
                tombstone = registry.conn.execute(
                    (
                        "SELECT status FROM docs WHERE tenant=? AND name=? ORDER BY "
                        "created_at DESC, version DESC LIMIT 1"
                    ),
                    (admin.tenant_id, path.name),
                ).fetchone()
            if tombstone and tombstone[0] == "deleted":
                engine.import_report.append({"name": path.name, "status": "deleted"})
                continue
            result = ingestor.ingest(path.name, path.read_bytes(), admin)
            engine.import_report.append({"name": path.name, **result})
    return engine, ingestor
