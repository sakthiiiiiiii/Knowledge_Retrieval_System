# Use small deterministic doubles to isolate document replacement, cache invalidation
# and access behavior.

import json
from dataclasses import replace
from hr_rag.models import Principal
from hr_rag.config import Settings
from hr_rag.vectors import MemoryStore
from hr_rag.registry import Registry
from hr_rag.ingestion import Ingestor
from hr_rag.engine import AnswerEngine
from hr_rag.cache import MemoryCache
from hr_rag.generation import validate_answer, ABSTAIN


class FakeEmbedder:
    def encode_passages(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_query(self, text):
        return [1.0, 0.0]


class FakeGenerator:
    def __init__(self):
        self.calls = 0

    def generate(self, q, evidence, history=None):
        self.calls += 1
        return json.dumps(
            {
                "answer": "According to the policy, review the cited section. [C1]",
                "cited_ids": ["C1"],
            }
        )


def setup(tmp_path):
    s = replace(
        Settings(),
        data_dir=tmp_path,
        retrieval_mode="dense",
        embed_model="fake",
        embed_revision="unit",
    )
    registry = Registry(tmp_path / "state" / "registry.sqlite3")
    store = MemoryStore()
    cache = MemoryCache()
    gen = FakeGenerator()
    embed = FakeEmbedder()
    ingest = Ingestor(registry, store, embed, s, cache)
    engine = AnswerEngine(s, registry, store, embed, gen, cache)
    user = Principal("employee", "swiftpay", groups=("employees",), acl_revision="1")
    admin = Principal("admin", "swiftpay", groups=("hr_rag_admin",), admin=True)
    name = "POL-HR-010_Leave_Travel_and_Expense_Policy.docx"
    from docx import Document
    import io

    d = Document()
    d.add_heading("4.1 Leave entitlement", level=1)
    d.add_paragraph("The annual sick leave entitlement is 10 working days.")
    f = io.BytesIO()
    d.save(f)
    return ingest, engine, gen, store, registry, user, admin, name, f.getvalue()


def test_ingest_query_cache_update_delete(tmp_path):
    ing, eng, gen, store, reg, user, admin, name, raw = setup(tmp_path)
    first = ing.ingest(name, raw, admin)
    assert first["status"] == "ready" and first["chunks"]
    assert ing.ingest(name, raw, admin)["status"] == "duplicate"
    res = eng.ask("What is the sick leave entitlement?", user)
    assert res["status"] == "answered" and res["sources"][0]["locator"].startswith(
        "paragraph"
    )
    assert gen.calls == 1
    second = eng.ask("What is the sick leave entitlement?", user)
    assert second["cached"] and gen.calls == 1
    assert not eng.ask("What is the sick leave entitlement?", Principal("x", "other"))[
        "sources"
    ]
    newer = raw.replace(b"ZZZ", b"YYY") if b"ZZZ" in raw else raw + b" "
    # A changed byte stream with valid docx is required for a real update.
    from docx import Document
    import io

    d = Document(io.BytesIO(raw))
    d.add_paragraph("A later clarification about leave.")
    f = io.BytesIO()
    d.save(f)
    updated = ing.ingest(name, f.getvalue(), admin)
    assert updated["version"] == 2
    assert eng.ask("What is the sick leave entitlement?", user)["cached"] is False
    assert gen.calls == 2
    ing.delete(first["document_id"], admin)
    gone = eng.ask("What is the sick leave entitlement?", user)
    assert gone["status"] == "no_evidence" and not gone["sources"]


def test_invalid_citation_fail_closed():
    evidence = [{"source_filename": "policy.txt"}]
    assert (
        validate_answer({"answer": "A claim [C5]", "cited_ids": ["C5"]}, evidence)[
            "status"
        ]
        == "invalid_citations"
    )
    assert (
        validate_answer(
            {"answer": "A claim without a citation", "cited_ids": []}, evidence
        )["answer"]
        == ABSTAIN
    )


def test_cloud_confidential_block(tmp_path):
    ing, eng, gen, store, reg, user, admin, name, raw = setup(tmp_path)
    # Simulate classified authorized restricted block without cloud transfer
    from hr_rag.models import Chunk

    restricted = Chunk(
        chunk_id="cid",
        document_id="id",
        source_filename="private",
        source_group="private",
        text="secret",
        heading="",
        locator="row1",
        tenant_id="swiftpay",
        namespace="hr",
        access_scopes=["group:hr"],
        classification="restricted-personal",
        model_id=eng.settings.retrieval_id,
        active=True,
    )
    store.upsert([restricted], [[1.0, 0.0]])
    hr = Principal("hr", "swiftpay", groups=("hr",))
    result = eng.ask("What is the secret?", hr)
    assert (
        result["status"] == "cloud_privacy_blocked"
        and not result["sources"]
        and gen.calls == 0
    )
