"""Authenticated FastAPI API with separate liveness and actual readiness checks."""

import logging
import threading
from functools import lru_cache
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Header
from pydantic import BaseModel, Field, field_validator
from .bootstrap import build
from .config import Settings
from .security import authenticate, AccessDenied, allowed

app = FastAPI(title="SwiftPay Knowledge Desk", version="0.2.0", docs_url="/docs")
log = logging.getLogger(__name__)
_runtime_lock = threading.RLock()


# Reuse the initialized models and index instead of rebuilding them for every request.
@lru_cache(maxsize=1)
def _build_once():
    return build()


def runtime():
    # lru_cache alone can construct multiple runtimes during simultaneous first
    # requests.
    with _runtime_lock:
        return _build_once()


# Derive identity from a verified token; never accept permissions from a question or
# UI field.
def principal(authorization: str | None = Header(None)):
    try:
        settings = Settings().validate()
    except ValueError as exc:
        raise HTTPException(
            503, detail={"code": "configuration", "message": str(exc)}
        ) from exc
    try:
        return authenticate(
            (authorization or "").removeprefix("Bearer ").strip(), settings
        )
    except AccessDenied as exc:
        raise HTTPException(
            401,
            detail={
                "code": "authentication",
                "message": (
                    "Session token is missing or invalid. Run python start.py or enter a "
                    "valid token in Connection settings."
                ),
            },
        ) from exc
    except Exception as exc:
        log.warning("Identity verification failed: %s", type(exc).__name__)
        raise HTTPException(
            401,
            detail={
                "code": "authentication",
                "message": (
                    "Unable to verify this session. Check the "
                    "identity-provider configuration."
                ),
            },
        ) from exc


# Bound question and history sizes before they enter retrieval or a provider request.
class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1500)
    namespace: str = "hr"
    history: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a question first")
        return value.strip()

    @field_validator("history")
    @classmethod
    def bounded_history(cls, value):
        if any(len(item) > 1500 for item in value):
            raise ValueError("History questions must be at most 1500 characters")
        return value


def backend_error(exc):
    # Log error category, not raw provider responses, keys, user prompts or document
    # text.
    log.error("Runtime operation failed (%s)", type(exc).__name__)
    return HTTPException(
        503,
        detail={
            "code": "backend_unavailable",
            "message": "The search index could not be opened. Check the data folder and write permissions. "
            "For dense retrieval, also check Qdrant and the embedding-model download. "
            "Use RETRIEVAL_MODE=lexical for local setup, then restart.",
        },
    )


@app.get("/health")
# Keep liveness cheap: a running server does not yet prove that its documents are
# searchable.
def health():
    return {"status": "running", "ready_check": "/ready"}


@app.get("/ready")
def ready(user=Depends(principal)):
    try:
        engine, _ = runtime()
        with engine.registry.lock:
            rows = engine.registry.conn.execute(
                (
                    "SELECT name, namespace, chunk_ids FROM docs "
                    "WHERE tenant=? AND status='ready'"
                ),
                (user.tenant_id,),
            ).fetchall()
        import json

        # Count only accessible active chunks so readiness does not reveal restricted
        # source names.
        documents = []
        chunks = 0
        for name, namespace, ids in rows:
            accessible = [
                p
                for p in engine.store.get(json.loads(ids))
                if p.get("active") and allowed(user, p)
            ]
            if accessible:
                chunks += len(accessible)
                documents.append(
                    {"name": name, "namespace": namespace, "chunks": len(accessible)}
                )

        # Report configuration here; actual Groq access is checked only when a
        # question is sent.
        cloud = getattr(engine.generator, "external", False)
        settings = engine.settings
        if not cloud:
            generation = "Local source excerpts"
        elif not settings.enable_external_llm:
            generation = "Groq disabled; source excerpts available"
        elif not settings.groq_key or settings.groq_key.startswith("REPLACE"):
            generation = "Groq key missing; source excerpts available"
        else:
            generation = "Groq configured; verified when a question is sent"
        return {
            "status": "ready" if chunks else "empty",
            "documents": documents,
            "document_count": len(documents),
            "chunk_count": chunks,
            "generation": generation,
            "retrieval": settings.retrieval_mode,
            "admin": user.admin,
        }
    except Exception as exc:
        raise backend_error(exc) from exc


@app.post("/ask")
def ask(req: Question, user=Depends(principal)):
    try:
        engine, _ = runtime()
        return engine.ask(req.question, user, req.namespace, req.history)
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "invalid_question", "message": str(exc)}
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            403, detail={"code": "access_denied", "message": str(exc)}
        ) from exc
    except Exception as exc:
        raise backend_error(exc) from exc


@app.post("/documents")
async def upload(file: UploadFile = File(...), user=Depends(principal)):
    if not user.admin:
        raise HTTPException(
            403,
            detail={
                "code": "admin_only",
                "message": "Document updates require administrator access.",
            },
        )

    # Read at most one byte beyond the limit so oversized uploads can be rejected
    # before parsing.
    data = await file.read(Settings().max_upload_mb * 1024 * 1024 + 1)
    if len(data) > Settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(
            413,
            detail={
                "code": "file_too_large",
                "message": "Choose a file smaller than 50 MB.",
            },
        )
    try:
        _, ingestor = runtime()

        # Serialize document writes so concurrent uploads do not publish competing
        # versions.
        with _runtime_lock:
            return ingestor.ingest(file.filename or "", data, user)
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "invalid_document", "message": str(exc)}
        ) from exc
    except Exception as exc:
        raise backend_error(exc) from exc


@app.delete("/documents/{document_id}")
def delete(document_id: str, user=Depends(principal)):
    if not user.admin:
        raise HTTPException(403, "Admin only")
    try:
        _, ingestor = runtime()
        with _runtime_lock:
            return ingestor.delete(document_id, user)
    except KeyError:
        raise HTTPException(404, "Not found")
    except Exception as exc:
        raise backend_error(exc) from exc
