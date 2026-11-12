"""Parse every supplied original into local JSONL, preserving sections, tables and locations."""

import sys
import json
import hashlib
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.config import ROOT
from hr_rag.parse import parse
from hr_rag.policy import policy_for, classify, Quarantined


def parse_dataset(source=None, output=None, report=None):
    source = Path(source or ROOT / "data" / "source")
    output = Path(output or ROOT / "data" / "parsed")
    report = Path(report or ROOT / "reports" / "dataset_parsing.json")
    output.mkdir(parents=True, exist_ok=True)
    rows = []

    # Process originals in a stable order so per-file parsing reports are easy to
    # compare.
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        row = {
            "filename": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        try:
            blocks = parse(path.name, raw)
            try:
                policy = policy_for(path.name)
                blocks = classify(blocks, policy)
                row.update(index_status="approved", namespace=policy["namespace"])
            except Quarantined:
                row.update(index_status="held_for_review", namespace="research")

            # Save one JSON object per block to retain headings, row locations and
            # access metadata.
            destination = output / (path.name + ".jsonl")
            destination.write_text(
                "".join(
                    json.dumps(asdict(b), ensure_ascii=False) + "\n" for b in blocks
                ),
                encoding="utf-8",
            )

            # Limit local permissions because parsed text can contain the same private
            # data as the source.
            destination.chmod(0o600)
            row.update(
                status="parsed",
                blocks=len(blocks),
                table_rows=sum(b.kind == "table_row" for b in blocks),
            )
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
        rows.append(row)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


if __name__ == "__main__":
    rows = parse_dataset(sys.argv[1] if len(sys.argv) > 1 else None)
    for row in rows:
        print(
            row["filename"],
            row["status"],
            row.get("blocks", 0),
            "blocks",
            row.get("index_status", ""),
        )
    raise SystemExit(1 if not rows or any(r["status"] != "parsed" for r in rows) else 0)
