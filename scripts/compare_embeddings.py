"""Actual local model evaluation, no claimed scores until models are installed and run.
Run with source ZIP and curated qrels. Excludes unapproved research/personal sources.
"""

import sys
import json
import time
import zipfile

try:
    import resource
except ImportError:
    resource = None
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hr_rag.embeddings import LocalEmbedder, MODEL_CANDIDATES, evidence_text
from hr_rag.parse import parse
from hr_rag.policy import policy_for, classify, Quarantined
from hr_rag.chunking import chunk_blocks


def run(src, qrels_path, out, model_names):
    # Use reviewed relevance labels so model scores have an explicit reference answer
    # source.
    qrels = json.loads(Path(qrels_path).read_text())
    docs = []
    with zipfile.ZipFile(src) as z:
        for item in z.infolist():
            if item.is_dir():
                continue
            try:
                pol = policy_for(Path(item.filename).name)
            except Quarantined:
                continue
            # Compare only internal evidence: restricted personal/confidential is not a
            # general retrieval benchmark.
            if pol["classification"] != "internal":
                continue
            blocks = classify(parse(Path(item.filename).name, z.read(item)), pol)
            docs += chunk_blocks(
                blocks,
                document_id=pol["id"],
                source_filename=Path(item.filename).name,
                source_group=pol["source_group"],
                tenant_id="swiftpay",
                namespace=pol["namespace"],
                size=180,
                overlap=20,
            )
    results = []
    for model in model_names:
        start = time.perf_counter()
        entry = {"model": model, "status": "pending"}
        try:
            embed = LocalEmbedder(model)

            # Exclude passages exceeding this model's limit rather than silently
            # measuring truncated text.
            allowed_docs = [
                d
                for d in docs
                if len(
                    embed.model.tokenizer.encode(
                        evidence_text(d), add_special_tokens=True
                    )
                )
                <= embed.max_tokens
            ]
            texts = [evidence_text(d) for d in allowed_docs]
            matrix = np.array(embed.encode_passages(texts))
            secs = time.perf_counter() - start
            scores = []
            mrr = []
            lat = []
            for q in qrels:
                if q.get("expected_behavior") != "answer" or not q.get(
                    "gold_document_id"
                ):
                    continue
                tic = time.perf_counter()
                v = np.array(embed.encode_query(q["question"]))

                # Normalized embeddings make the dot product a cosine similarity for
                # ranking.
                sim = matrix @ v
                ranked = [allowed_docs[i].source_group for i in np.argsort(-sim)[:10]]
                gold = q["gold_document_id"]
                rank = next((i + 1 for i, s in enumerate(ranked) if s == gold), None)
                scores.append(int(rank is not None and rank <= 5))
                mrr.append(1 / rank if rank else 0.0)
                lat.append((time.perf_counter() - tic) * 1000)
            entry.update(
                status="measured",
                corpus_chunks=len(allowed_docs),
                recall_at_5=sum(scores) / len(scores) if scores else None,
                mrr_at_10=sum(mrr) / len(mrr) if mrr else None,
                index_seconds=secs,
                embed_chunks_per_s=len(texts) / secs if secs else None,
                query_latency_mean_ms=sum(lat) / len(lat) if lat else None,
                vector_bytes=matrix.nbytes,
                peak_rss_kb=(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    if resource
                    else None
                ),
                question_count=len(scores),
            )
        except Exception as ex:
            entry.update(status="failed", reason=str(ex)[:400])
        results.append(entry)
        print(entry)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(
            (
                "Usage: python scripts/compare_embeddings.py dataset.zip "
                "config/evaluation_seed.json [model...]"
            )
        )
    run(
        sys.argv[1],
        sys.argv[2],
        "reports/embedding_comparison.json",
        sys.argv[3:] or MODEL_CANDIDATES,
    )
