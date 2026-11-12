"""Typed models for a trust-boundary-first RAG application."""

from dataclasses import dataclass, field, asdict
from typing import Any


# Keep verified identity separate from user-supplied question text.
@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    groups: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()  # managed teams, from verified token only
    employee_id: str | None = None
    acl_revision: str = "0"
    admin: bool = False


# Carry source location and classification through parsing so later stages retain
# provenance.
@dataclass
class Block:
    text: str
    heading: str = ""
    locator: str = ""
    kind: str = "paragraph"
    employee_id: str | None = None
    team: str | None = None
    scope: tuple[str, ...] = ()
    classification: str = "unclassified"
    metadata: dict[str, Any] = field(default_factory=dict)


# Store evidence and permissions together so search results can be filtered and cited
# reliably.
@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    source_filename: str
    source_group: str
    text: str
    heading: str
    locator: str
    tenant_id: str
    namespace: str
    access_scopes: list[str]
    classification: str
    version: int = 1
    employee_id: str | None = None
    team: str | None = None
    source_hash: str = ""
    active: bool = False
    model_id: str = ""

    def payload(self):
        return asdict(self)
