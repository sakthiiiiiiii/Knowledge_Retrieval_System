"""Configured-backend retrieval evaluation. Fill qrels after independent reviewer validation."""

import sys
import json
import time
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.bootstrap import build
from hr_rag.models import Principal


def evaluate(qrel_path, out):
    engine, _ = build()
    items = json.loads(Path(qrel_path).read_text())
    rows = []

    # Measure retrieval as an ordinary employee so the benchmark respects the same
    # access restrictions.
    principal = Principal("reviewer", "swiftpay", groups=("employees",))
    for item in items:
        if item.get("expected_behavior") != "answer":
            continue
        start = time.perf_counter()
        qv = engine.embedder.encode_query(item["question"])
        hits = engine.store.search(
            qv, principal, item["namespace"], 10, 0.0, engine.settings.retrieval_id
        )

        # Compare returned source groups with the labelled document to measure
        # document-level retrieval.
        ranked = [x["source_group"] for _, x in hits]
        gold = item["gold_document_id"]
        rank = next((i + 1 for i, d in enumerate(ranked) if d == gold), None)
        rows.append(
            {
                "id": item["id"],
                "gold_document": gold,
                "rank": rank,
                "recall_at_5": int(bool(rank and rank <= 5)),
                "rr_at_10": (1 / rank if rank else 0),
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        )
    result = {
        "status": "measured",
        "questions": len(rows),
        "recall_at_5": (
            statistics.mean(x["recall_at_5"] for x in rows) if rows else None
        ),
        "mrr_at_10": statistics.mean(x["rr_at_10"] for x in rows) if rows else None,
        "results": rows,
        "limitations": (
            "Seed qrels require independent review; document-level relevance is "
            "not chunk-level evidence recall. Answer faithfulness and citation "
            "accuracy require manual evaluation."
        ),
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    evaluate(
        sys.argv[1] if len(sys.argv) > 1 else "config/evaluation_seed.json",
        "reports/live_retrieval.json",
    )
