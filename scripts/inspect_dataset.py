"""Offline inspection of source ZIP; no sensitive extracted text stored in reports."""

import sys
import json
import zipfile
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.parse import parse, check_file
from hr_rag.policy import policy_for, classify, Quarantined
from hr_rag.chunking import chunk_blocks


def inspect(src):
    results = []
    with zipfile.ZipFile(src) as z:
        for x in z.infolist():
            if x.is_dir():
                continue
            name = Path(x.filename).name

            # Record hashes and counts for auditability without putting extracted
            # private text into reports.
            row = {
                "name": name,
                "size": x.file_size,
                "sha256": hashlib.sha256(z.read(x)).hexdigest(),
            }
            try:
                policy = policy_for(name)
                blocks = classify(parse(name, z.read(x)), policy)
                chunks = chunk_blocks(
                    blocks,
                    document_id=policy["id"],
                    source_filename=name,
                    source_group=policy["source_group"],
                    tenant_id="swiftpay",
                    namespace=policy["namespace"],
                    source_hash=row["sha256"],
                )
                row.update(
                    status="processed",
                    block_count=len(blocks),
                    classified_blocks=sum(bool(b.scope) for b in blocks),
                    chunk_count=len(chunks),
                    namespace=policy["namespace"],
                )
                if policy["id"] == "D06":
                    row["training_record_count"] = len(
                        {b.employee_id for b in blocks if b.employee_id}
                    )
            except Exception as exc:
                row.update(
                    status="not_processed", reason=str(exc).splitlines()[0][:160]
                )
            results.append(row)
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python scripts/inspect_dataset.py input.zip [output.json]"
        )
    result = inspect(sys.argv[1])
    target = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path("reports/dataset_inspection.json")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            [
                {
                    "name": r["name"],
                    "status": r["status"],
                    "blocks": r.get("block_count"),
                    "chunks": r.get("chunk_count"),
                    "reason": r.get("reason"),
                }
                for r in result
            ],
            indent=2,
        )
    )
