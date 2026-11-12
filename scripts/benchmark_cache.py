"""Measure two authorized exact repeats (live services required); does not claim universal gains."""

import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.bootstrap import build
from hr_rag.models import Principal


def main(question, namespace):
    engine, _ = build()
    # Only internal pilot identity; never impersonate HR. This is a local CLI benchmark.
    user = Principal(
        "benchmark", "swiftpay", groups=("employees",), acl_revision="benchmark"
    )
    rows = []

    # Repeat the exact authorized question to observe whether the second request uses
    # the cache.
    for n in range(2):
        start = time.perf_counter()
        result = engine.ask(question, user, namespace)
        rows.append(
            {
                "iteration": n + 1,
                "status": result["status"],
                "cache_hit": result["cached"],
                "wall_time_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        )
    Path("reports/cache_benchmark.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "How many sick leave days for employees?",
        sys.argv[2] if len(sys.argv) > 2 else "hr",
    )
