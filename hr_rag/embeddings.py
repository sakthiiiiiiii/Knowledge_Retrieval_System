"""Local embeddings; only generation can use external API (with explicit opt-in)."""

import numpy as np

MODEL_CANDIDATES = [
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
    "intfloat/e5-base-v2",
    "BAAI/bge-base-en-v1.5",
    "thenlper/gte-base",
    "intfloat/multilingual-e5-small",  # user-requested optional multilingual candidate
]
BGE_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class LocalEmbedder:
    def __init__(self, model_id="BAAI/bge-small-en-v1.5", revision="main"):
        # Load the optional neural model only for dense retrieval, keeping the default
        # local path lightweight.
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self.revision = revision
        self.model = SentenceTransformer(
            model_id, revision=revision, trust_remote_code=False
        )
        self.max_tokens = min(int(self.model.max_seq_length or 512), 512)
        self.dimension = int(self.model.get_sentence_embedding_dimension())

    def _format(self, texts, query):
        # Use each model family's query and passage prefixes so its representations
        # match its training format.
        if "e5-" in self.model_id:
            prefix = "query: " if query else "passage: "
        elif query and "/bge-" in self.model_id:
            prefix = BGE_INSTRUCTION
        else:
            prefix = ""
        out = [prefix + t for t in texts]

        # Reject overlong inputs instead of silently truncating evidence during
        # indexing.
        for t in out:
            count = len(
                self.model.tokenizer.encode(
                    t, add_special_tokens=True, truncation=False
                )
            )
            if count > self.max_tokens:
                raise ValueError(
                    f"Embedding input has {count} tokens (limit {self.max_tokens}); "
                    "rechunk before indexing"
                )
        return out

    # Normalize passage vectors so cosine comparison uses direction rather than vector
    # magnitude.
    def encode_passages(self, texts):
        return self.model.encode(
            self._format(texts, False), normalize_embeddings=True, convert_to_numpy=True
        ).tolist()

    def encode_query(self, text):
        return self.model.encode(
            self._format([text], True), normalize_embeddings=True, convert_to_numpy=True
        )[0].tolist()


# Include source and heading context so a short table row has enough meaning for
# semantic retrieval.
def evidence_text(chunk):
    return f"{chunk.source_filename}\n{chunk.heading}\n{chunk.text}"
