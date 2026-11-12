"""SQLite metadata, source versions and index revision. Single-writer pilot use."""

import json
import sqlite3
import threading
from pathlib import Path


class Registry:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Store source versions separately from the search index so publication state
        # can be tracked.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.execute(
            (
                "CREATE TABLE IF NOT EXISTS docs (document_id TEXT, version INTEGER, "
                "tenant TEXT, namespace TEXT, name TEXT, sha TEXT, local_path TEXT, "
                "status TEXT, chunk_ids TEXT, created_at TEXT DEFAULT "
                "CURRENT_TIMESTAMP, PRIMARY KEY(document_id,version))"
            )
        )
        self.conn.execute(
            (
                "CREATE TABLE IF NOT EXISTS state (key TEXT "
                "PRIMARY KEY, value INTEGER NOT NULL)"
            )
        )
        self.conn.execute("INSERT OR IGNORE INTO state VALUES ('epoch',0)")
        self.conn.commit()

    def epoch(self):
        return self.conn.execute(
            "SELECT value FROM state WHERE key='epoch'"
        ).fetchone()[0]

    # Advance the corpus revision so cached answers from older document states are no
    # longer reused.
    def bump(self):
        with self.lock:
            self.conn.execute("UPDATE state SET value=value+1 WHERE key='epoch'")
            self.conn.commit()

    # Select the latest ready version; staged or failed uploads must not replace
    # active evidence.
    def find(self, tenant, namespace, name):
        row = self.conn.execute(
            (
                "SELECT document_id,version,sha,chunk_ids,local_path FROM docs WHERE "
                "tenant=? AND namespace=? AND name=? AND status=? ORDER BY version "
                "DESC LIMIT 1"
            ),
            (tenant, namespace, name, "ready"),
        ).fetchone()
        return (
            {
                "document_id": row[0],
                "version": row[1],
                "sha": row[2],
                "chunk_ids": json.loads(row[3]),
                "local_path": row[4],
            }
            if row
            else None
        )

    # Bind SQL values as parameters so document metadata is stored as data, never
    # executable SQL.
    def add(self, doc_id, version, tenant, namespace, name, sha, path, status, ids):
        with self.lock:
            self.conn.execute(
                (
                    "INSERT INTO docs (document_id,version,tenant,"
                    "namespace,name,sha,local_path,status,chunk_ids) "
                    "VALUES (?,?,?,?,?,?,?,?,?)"
                ),
                (
                    doc_id,
                    version,
                    tenant,
                    namespace,
                    name,
                    sha,
                    str(path),
                    status,
                    json.dumps(ids),
                ),
            )
            self.conn.commit()

    def set_status(self, doc_id, version, status):
        with self.lock:
            self.conn.execute(
                "UPDATE docs SET status=? WHERE document_id=? AND version=?",
                (status, doc_id, version),
            )
            self.conn.commit()
