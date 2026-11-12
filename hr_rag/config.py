"""Read project-local configuration when Settings is constructed, not at import time."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv


# Resolve configuration relative to the project so launching from another folder still
# works.
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def env(name, default="", cast=str):
    # Read each value when Settings is created so environment changes are not frozen
    # at import time.
    return field(default_factory=lambda: cast(os.getenv(name, default)))


def boolean(value):
    return str(value).lower() == "true"


@dataclass(frozen=True)
class Settings:
    # Local retrieval and excerpts make the default setup usable without a cloud key
    # or Docker.
    data_dir: Path = env("DATA_DIR", str(ROOT / "data"), Path)
    retrieval_mode: str = env("RETRIEVAL_MODE", "lexical")
    generation_mode: str = env("GENERATION_MODE", "auto")
    auto_import: bool = env("AUTO_IMPORT_DATASET", "true", boolean)
    qdrant_url: str = env("QDRANT_URL", "http://localhost:6333")
    redis_url: str = env("REDIS_URL")
    collection: str = env("QDRANT_COLLECTION", "enterprise_bge_small_v1")
    embed_model: str = env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    embed_revision: str = env("EMBED_REVISION", "main")
    groq_model: str = env("GROQ_MODEL", "llama-3.3-70b-versatile")
    groq_key: str = env("GROQ_API_KEY")
    enable_external_llm: bool = env("ENABLE_EXTERNAL_LLM", "false", boolean)
    allow_external_confidential: bool = env(
        "ALLOW_EXTERNAL_CONFIDENTIAL", "false", boolean
    )
    auth_mode: str = env("AUTH_MODE", "disabled")
    demo_token: str = env("DEMO_API_TOKEN")
    jwt_issuer: str = env("JWT_ISSUER")
    jwt_audience: str = env("JWT_AUDIENCE")
    jwt_jwks_url: str = env("JWT_JWKS_URL")
    chunk_tokens: int = env("CHUNK_TOKENS", "180", int)
    chunk_overlap: int = env("CHUNK_OVERLAP", "30", int)
    top_candidates: int = env("TOP_CANDIDATES", "16", int)
    top_k: int = env("TOP_K", "8", int)
    min_score: float = env("MIN_RETRIEVAL_SCORE", "0", float)
    max_upload_mb: int = 50

    # Include parser and chunk settings in the index identity to prevent reuse of
    # incompatible data.
    @property
    def retrieval_id(self):
        return (
            "bm25-local@1"
            if self.retrieval_mode == "lexical"
            else self.embed_model + "@" + self.embed_revision
        ) + f":parse2:w{self.chunk_tokens}:o{self.chunk_overlap}"

    # Reject invalid configuration early so setup failures have a specific, actionable
    # cause.
    def validate(self):
        if self.retrieval_mode not in {"lexical", "dense"}:
            raise ValueError("RETRIEVAL_MODE must be lexical or dense")
        if self.generation_mode not in {"auto", "groq", "extractive"}:
            raise ValueError("GENERATION_MODE must be auto, groq or extractive")
        if self.auth_mode not in {"disabled", "demo", "jwt"}:
            raise ValueError("AUTH_MODE must be disabled, demo or jwt")
        if self.auth_mode == "demo" and (
            len(self.demo_token) < 24 or self.demo_token.startswith("REPLACE")
        ):
            raise ValueError(
                (
                    "Run python start.py to create a local session "
                    "token, or set DEMO_API_TOKEN (24+ characters)"
                )
            )
        if self.auth_mode == "jwt" and not all(
            (self.jwt_issuer, self.jwt_audience, self.jwt_jwks_url)
        ):
            raise ValueError("JWT issuer, audience and JWKS URL required")
        if self.auth_mode == "jwt" and not self.jwt_jwks_url.startswith("https://"):
            raise ValueError("JWKS URL must use HTTPS")
        if not 1 <= self.top_k <= self.top_candidates <= 100:
            raise ValueError("Invalid retrieval limits")
        if not 0 <= self.chunk_overlap < self.chunk_tokens:
            raise ValueError("Invalid chunk sizes")
        return self
