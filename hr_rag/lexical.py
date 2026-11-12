"""Small-corpus BM25 retrieval. Persistent, local, permission-filtered; no model download."""

import json
import math
import re
import sqlite3
import threading
from collections import Counter
from pathlib import Path
from .security import allowed

STOP = set(
    (
        "a an the is are was were be been to of in on at for by with and or "
        "from as it its this that these those i my me we our you your they "
        "their what which who where when how many much can could would "
        "should do does did tell give about please employee employees "
        "permanent entitled entitlement policy document documents available "
        "sop"
    ).split()
)

# Normalize equivalent forms so terms like "leaves" and "leave" can retrieve the same
# policy.
ALIASES = {
    "leaves": "leave",
    "bangalore": "bengaluru",
    "limits": "limit",
    "days": "day",
    "years": "year",
    "payments": "payment",
    "backups": "backup",
    "services": "service",
    "expenses": "expense",
    "claims": "claim",
    "approvals": "approval",
    "hotels": "hotel",
    "records": "record",
    "sickness": "sick",
    "illness": "sick",
}


# Remove common question words so ranking focuses on the subject of the request.
def terms(text):
    return [
        ALIASES.get(t, t)
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in STOP
    ]


class LexicalEncoder:
    """Pass text to BM25. This is deliberately not a neural embedding model."""

    def encode_passages(self, texts):
        return list(texts)

    def encode_query(self, text):
        return text


class SQLiteLexicalStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Persist chunks locally so restarting the app does not require rebuilding an
        # unchanged corpus.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.execute(
            (
                "CREATE TABLE IF NOT EXISTS chunks (id TEXT "
                "PRIMARY KEY, payload TEXT NOT NULL)"
            )
        )
        self.conn.commit()

    def upsert(self, chunks, vectors):
        with self.lock, self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO chunks VALUES (?, ?)",
                [(c.chunk_id, json.dumps(c.payload())) for c in chunks],
            )

    def get(self, ids):
        with self.lock:
            return [
                json.loads(row[0])
                for cid in ids
                if (
                    row := self.conn.execute(
                        "SELECT payload FROM chunks WHERE id=?", (cid,)
                    ).fetchone()
                )
            ]

    def mark(self, ids, active):
        with self.lock, self.conn:
            for p in self.get(ids):
                p["active"] = active
                self.conn.execute(
                    "UPDATE chunks SET payload=? WHERE id=?",
                    (json.dumps(p), p["chunk_id"]),
                )

    def delete(self, ids):
        with self.lock, self.conn:
            self.conn.executemany("DELETE FROM chunks WHERE id=?", [(x,) for x in ids])

    def search(
        self, vector, principal, namespace, limit=16, min_score=0, model_id=None
    ):
        query = set(terms(vector))
        if not query:
            return []
        with self.lock:
            payloads = [
                json.loads(x[0])
                for x in self.conn.execute("SELECT payload FROM chunks")
            ]
        # Filter before relevance statistics/ranking. No inaccessible evidence enters
        # retrieval.
        corpus = [
            p
            for p in payloads
            if p.get("active")
            and p["namespace"] == namespace
            and (not model_id or p["model_id"] == model_id)
            and allowed(principal, p)
        ]
        counts = [Counter(terms(p["heading"] + " " + p["text"])) for p in corpus]
        if not counts:
            return []

        # Compare term frequency and document length only within the authorized
        # corpus.
        avg_len = sum(sum(c.values()) for c in counts) / len(counts) or 1
        df = {t: sum(t in c for c in counts) for t in query}
        results = []
        for p, count in zip(corpus, counts):
            overlap = query & count.keys()
            if not overlap:
                continue
            score = 0
            for t in overlap:
                # Weight rarer matching terms more strongly while reducing the
                # advantage of long passages.
                idf = math.log(1 + (len(counts) - df[t] + 0.5) / (df[t] + 0.5))
                tf = count[t]
                score += (
                    idf
                    * tf
                    * 2.5
                    / (tf + 1.5 * (0.25 + 0.75 * sum(count.values()) / avg_len))
                )

            # Reward coverage of the whole query so a single shared word is less
            # likely to dominate.
            score *= len(overlap) / len(query)
            if score > max(0, min_score):
                results.append((score, p))
        return sorted(results, key=lambda x: -x[0])[:limit]
