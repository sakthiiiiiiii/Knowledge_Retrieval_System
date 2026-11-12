"""Aggregate independently reviewed answer-level metrics; leave missing values as not scored."""

import sys
import csv
import json
import statistics
from pathlib import Path


def main(src, out):
    rows = list(csv.DictReader(Path(src).open(encoding="utf-8-sig")))
    scored = {}
    for field in (
        "answer_correct",
        "faithful",
        "citation_correct",
        "abstain_correct",
        "unauthorized_disclosure",
    ):
        # Count only explicit reviewer scores; missing reviews must not be treated as
        # passes or failures.
        values = [int(r[field]) for r in rows if r.get(field, "").strip() in {"0", "1"}]
        scored[field] = {
            "n": len(values),
            "mean": round(statistics.mean(values), 4) if values else None,
        }
    lat = [float(r["latency_ms"]) for r in rows if r.get("latency_ms", "").strip()]
    scored["latency_ms"] = {
        "n": len(lat),
        "median": statistics.median(lat) if lat else None,
        "p95": sorted(lat)[max(0, int(len(lat) * 0.95) - 1)] if lat else None,
    }
    Path(out).write_text(json.dumps(scored, indent=2))
    print(json.dumps(scored, indent=2))


if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else "reports/answer_review_scores.json",
    )
