"""Scoped exact answer cache. No semantic cache until security tests pass."""

import json
import hashlib
from .security import allowed


def cache_key(p, namespace, question, history, settings, corpus_revision):
    # Include identity, access revision and corpus settings so answers cannot cross
    # users or become stale.
    obj = {
        "tenant": p.tenant_id,
        "user": p.user_id,
        "groups": sorted(p.groups),
        "teams": sorted(p.teams),
        "employee_id": p.employee_id,
        "acl_revision": p.acl_revision,
        "namespace": namespace,
        "question": " ".join(question.split()),
        "history_hash": hashlib.sha256(
            json.dumps(history, sort_keys=True).encode()
        ).hexdigest(),
        "corpus_revision": corpus_revision,
        "embedding": settings.retrieval_id,
        "llm": settings.groq_model,
        "prompt": "v2",
        "generation_mode": settings.generation_mode,
        "external_llm": settings.enable_external_llm,
        "external_confidential": settings.allow_external_confidential,
        "top_k": settings.top_k,
        "min_score": settings.min_score,
    }
    return (
        "hr_rag:exact:"
        + hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()
    )


class ExactCache:
    def __init__(self, url):
        import redis

        self.redis = redis.Redis.from_url(
            url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
        )

    def get(self, key):
        try:
            item = self.redis.get(key)
            return json.loads(item) if item else None
        except Exception:
            return None  # cache outage never becomes an auth bypass

    # Expire remote entries so cached answers have a bounded lifetime even without a
    # corpus change.
    def set(self, key, item, ttl=3600):
        try:
            self.redis.set(key, json.dumps(item), ex=ttl)
        except Exception:
            pass


# Use an in-memory cache only for deterministic tests; it does not implement Redis
# expiry.
class MemoryCache:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return self.items.get(key)

    def set(self, key, item, ttl=3600):
        self.items[key] = item


def valid_cached(cached, principal, store):
    # Recheck source existence and permissions on every hit in case access changed
    # after caching.
    ids = cached.get("chunk_ids") or []
    rows = store.get(ids)
    return (
        bool(ids)
        and len(rows) == len(ids)
        and all(x.get("active") and allowed(principal, x) for x in rows)
    )
