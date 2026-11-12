"""Structure-aware row/heading/ACL chunking, with recursive prose splitting."""

import re
import hashlib
import uuid
from .models import Chunk


def split_words(text: str, size=300, overlap=40):
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk configuration")

    # Use overlapping windows to keep some context on both sides of a chunk boundary.
    words = text.split()
    out = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        out.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return out


def recursive_split(text, size, overlap):
    """Prefer sentence boundaries, falling back to deterministic word windows."""
    if len(text.split()) <= size:
        return [text]

    # Prefer complete sentences so evidence is easier to understand and quote.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    if len(sentences) == 1:
        return split_words(text, size, overlap)
    pieces = []
    window = []
    n = 0
    for sentence in sentences:
        w = len(sentence.split())
        if w > size:
            if window:
                pieces.append(" ".join(window))
                window = []
                n = 0
            pieces.extend(split_words(sentence, size, overlap))
            continue
        if window and n + w > size:
            pieces.append(" ".join(window))
            tail = " ".join(window).split()[-overlap:] if overlap else []
            window = [" ".join(tail)] if tail else []
            n = len(tail)
        window.append(sentence)
        n += w
    if window:
        pieces.append(" ".join(window))
    return pieces


def chunk_blocks(
    blocks,
    *,
    document_id,
    source_filename,
    source_group,
    tenant_id,
    namespace,
    version=1,
    source_hash="",
    size=300,
    overlap=40,
):
    chunks = []
    buffer = []
    group_key = None

    def emit(text, heading, locator, scope, classification, employee_id, team):
        for part in recursive_split(text, size, overlap):
            if not part.strip():
                continue

            # Derive stable IDs from source and version information so chunk
            # references stay traceable.
            h = hashlib.sha256(
                f"{document_id}|{version}|{len(chunks)}|{source_hash}".encode()
            ).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=str(uuid.UUID(hex=h[:32])),
                    document_id=document_id,
                    source_filename=source_filename,
                    source_group=source_group,
                    text=part,
                    heading=heading,
                    locator=locator,
                    tenant_id=tenant_id,
                    namespace=namespace,
                    access_scopes=list(scope),
                    classification=classification,
                    version=version,
                    employee_id=employee_id,
                    team=team,
                    source_hash=source_hash,
                )
            )

    def flush():
        nonlocal buffer
        if buffer:
            first, last = buffer[0], buffer[-1]
            locator = (
                first.locator
                if first.locator == last.locator
                else first.locator + " – " + last.locator
            )
            emit(
                " ".join(b.text for b in buffer),
                first.heading,
                locator,
                first.scope,
                first.classification,
                first.employee_id,
                first.team,
            )
            buffer = []

    # Group only classified blocks; unknown permissions must never become searchable
    # content.
    for b in blocks:
        if not b.scope or b.classification == "unclassified":
            flush()
            group_key = None
            continue

        # Keep rows separate so neighbouring records or entitlements are not merged
        # together.
        if b.kind == "table_row":
            flush()
            group_key = None
            emit(
                b.text,
                b.heading,
                b.locator,
                b.scope,
                b.classification,
                b.employee_id,
                b.team,
            )
            continue
        page = re.match(r"page\s+\d+", b.locator)

        # Split at heading, page or access changes so no chunk mixes incompatible
        # source context or permissions.
        key = (
            b.heading,
            b.scope,
            b.classification,
            b.employee_id,
            b.team,
            page.group(0) if page else "",
        )
        if group_key is not None and key != group_key:
            flush()
        if (
            buffer
            and sum(len(x.text.split()) for x in buffer) + len(b.text.split()) > size
        ):
            flush()
        buffer.append(b)
        group_key = key
    flush()
    return chunks
