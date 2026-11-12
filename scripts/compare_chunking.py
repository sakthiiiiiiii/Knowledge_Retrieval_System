"""Run actual chunk-count comparison. Recall depends on subsequent live retrieval evaluation."""

import sys
import json
import zipfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.parse import parse
from hr_rag.policy import policy_for, classify, Quarantined
from hr_rag.chunking import chunk_blocks


def main(src):
    report = []
    with zipfile.ZipFile(src) as z:
        # Keep the corpus fixed while varying chunk size and overlap to compare their
        # effect on chunk counts.
        for size, overlap in [(150, 20), (250, 40), (350, 40)]:
            count = 0
            errors = []
            start = time.perf_counter()
            for x in z.infolist():
                if x.is_dir():
                    continue
                n = Path(x.filename).name
                try:
                    p = policy_for(n)
                    b = classify(parse(n, z.read(x)), p)
                    count += len(
                        chunk_blocks(
                            b,
                            document_id=p["id"],
                            source_filename=n,
                            source_group=p["source_group"],
                            tenant_id="swiftpay",
                            namespace=p["namespace"],
                            size=size,
                            overlap=overlap,
                        )
                    )
                except Exception as ex:
                    errors.append(n + ": " + str(ex)[:80])
            report.append(
                {
                    "chunk_word_limit": size,
                    "overlap_words": overlap,
                    "chunk_count": count,
                    "elapsed_seconds": round(time.perf_counter() - start, 4),
                    "failures": errors,
                    "retrieval_recall": "not_run",
                }
            )
    Path("reports/chunk_comparison.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
