"""Regression coverage for the reported API failures using the actual supplied dataset."""

# Use the supplied source files and simulated provider responses to check API behavior
# without a real Groq key.

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from hr_rag import api
from hr_rag.bootstrap import build
from hr_rag.config import ROOT, Settings
from hr_rag.generation import GroqGenerator, GenerationError, validate_answer
from hr_rag.models import Principal
from hr_rag.parse import parse

TOKEN = "test-only-session-token-32-characters"


@pytest.fixture
def app_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_API_TOKEN", TOKEN)
    shutil.copytree(ROOT / "data" / "source", tmp_path / "source")
    settings = replace(
        Settings(),
        data_dir=tmp_path,
        retrieval_mode="lexical",
        generation_mode="extractive",
        enable_external_llm=False,
        redis_url="",
        auto_import=True,
    )
    runtime = build(settings)
    monkeypatch.setattr(api, "runtime", lambda: runtime)
    with TestClient(api.app) as client:
        client.headers["Authorization"] = "Bearer " + TOKEN
        yield client, runtime[0], settings
    for obj in (runtime[0].registry, runtime[0].store):
        obj.conn.close()


def test_supplied_six_originals_parse():
    files = list((ROOT / "data" / "source").iterdir())
    assert len(files) == 6
    assert all(
        path.suffix.lower() in {".docx", ".pdf", ".xls", ".xlsx"} for path in files
    )
    for path in files:
        blocks = parse(path.name, path.read_bytes())
        assert blocks and all(b.text and b.locator for b in blocks)


def test_readiness_reports_actual_accessible_corpus(app_runtime):
    client, engine, _ = app_runtime
    assert client.get("/health").json()["status"] == "running"
    data = client.get("/ready").json()
    assert data["status"] == "ready" and data["document_count"] == 4
    assert data["chunk_count"] > 0
    assert not any(
        "Training" in d["name"] or "Monthly" in d["name"] for d in data["documents"]
    )
    assert len(engine.import_report) == 6
    assert all(x["status"] == "ready" for x in engine.import_report)


def test_original_leave_question_returns_cited_source_rows(app_runtime):
    client, _, _ = app_runtime
    response = client.post(
        "/ask", json={"question": "How many leaves is the employee entitled to?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "source_excerpts"
    for fact in [
        "Annual leave",
        "20 working days",
        "Sick leave",
        "10 working days",
        "Casual leave",
        "6 working days",
        "permanent employees",
        "proportion",
    ]:
        assert fact in data["answer"]
    assert len(data["sources"]) == 8
    assert all(
        s["source_filename"].endswith(".docx") and s["locator"] and s["excerpt"]
        for s in data["sources"]
    )


@pytest.mark.parametrize(
    "question",
    [
        "Where is Bangalore?",
        "What is my remaining live leave balance?",
        "What is the speed of a spacecraft on Mars?",
    ],
)
def test_unsupported_question_returns_message_not_error(app_runtime, question):
    client, _, _ = app_runtime
    response = client.post("/ask", json={"question": question})
    assert response.status_code == 200
    assert response.json()["status"] in {"no_evidence", "abstained"}
    assert response.json()["sources"] == []


def test_city_alias_keeps_hotel_answer_in_scope(app_runtime):
    client, _, _ = app_runtime
    result = client.post(
        "/ask",
        json={
            "question": "What is the Bangalore hotel limit and above-limit approval?"
        },
    ).json()
    assert result["status"] == "source_excerpts"
    assert "4,000" in result["answer"] and "department head" in result["answer"]
    assert "Chief Financial Officer" not in result["answer"]


def test_sick_leave_and_short_followup(app_runtime):
    client, _, _ = app_runtime
    first = "How many sick leave days are permanent employees entitled to?"
    result = client.post("/ask", json={"question": first}).json()
    assert (
        "10 working days" in result["answer"] and "Annual leave" not in result["answer"]
    )
    followup = client.post(
        "/ask", json={"question": "What about casual?", "history": [first]}
    ).json()
    assert "6 working days" in followup["answer"]


def test_invalid_auth_and_input_are_actionable(app_runtime):
    client, _, _ = app_runtime
    response = client.post(
        "/ask", headers={"Authorization": "Bearer wrong"}, json={"question": "leave?"}
    )
    assert (
        response.status_code == 401
        and response.json()["detail"]["code"] == "authentication"
    )
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert (
        client.post(
            "/ask", json={"question": "leave?", "namespace": "invalid"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/ask", json={"question": "leave?", "history": ["x" * 1501]}
        ).status_code
        == 422
    )
    assert (
        client.post("/documents", files={"file": ("notes.txt", b"private")}).status_code
        == 403
    )


def test_missing_key_degrades_explicitly_to_evidence(app_runtime):
    client, engine, settings = app_runtime
    settings = replace(settings, enable_external_llm=True, groq_key="")
    engine.settings = settings
    engine.generator = GroqGenerator(settings)
    data = client.post("/ask", json={"question": "How many sick leave days?"}).json()
    assert data["status"] == "source_excerpts"
    assert data["error_code"] == "missing_key" and "10 working days" in data["answer"]
    assert "GROQ_API_KEY" in data["warning"]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "groq_auth"),
        (429, "groq_rate_limit"),
        (400, "groq_model"),
        (503, "groq_unavailable"),
    ],
)
def test_provider_failures_return_cited_fallback_without_secret(
    app_runtime, status, code
):
    client, engine, settings = app_runtime

    class ProviderFailure(Exception):
        status_code = status

    mock = Mock()
    mock.chat.completions.create.side_effect = ProviderFailure("do-not-expose-secret")
    settings = replace(
        settings, enable_external_llm=True, groq_key="test-only-not-real"
    )
    engine.settings = settings
    engine.generator = GroqGenerator(settings, mock)
    response = client.post("/ask", json={"question": "How many sick leave days?"})
    assert response.status_code == 200
    data = response.json()
    assert data["error_code"] == code and data["status"] == "source_excerpts"
    assert data["sources"] and "do-not-expose-secret" not in response.text


def test_groq_evidence_dictionary_regression_and_citation_ids(app_runtime):
    client, engine, settings = app_runtime
    mock = Mock()
    mock.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "answer": "Sick leave is 10 working days per year [C1].",
                            "cited_ids": ["C1"],
                        }
                    )
                )
            )
        ]
    )
    settings = replace(
        settings, enable_external_llm=True, groq_key="test-only-not-real"
    )
    engine.settings = settings
    engine.generator = GroqGenerator(settings, mock)
    response = client.post(
        "/ask",
        json={
            "question": "How many sick leave days?",
            "history": ["Tell me about leave"],
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "answered"
    call = mock.chat.completions.create.call_args.kwargs
    prompt = json.loads(call["messages"][1]["content"])
    assert prompt["evidence"][0]["citation_id"] == "C1"
    assert [e["citation_id"] for e in prompt["evidence"]] == [
        f"C{i}" for i in range(1, len(prompt["evidence"]) + 1)
    ]
    assert prompt["previous_user_questions"] == ["Tell me about leave"]
    assert call["response_format"] == {"type": "json_object"}


def test_invalid_model_citation_falls_back(app_runtime):
    client, engine, settings = app_runtime
    mock = Mock()
    mock.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"answer":"Invented [C99]","cited_ids":["C99"]}'
                )
            )
        ]
    )
    engine.generator = GroqGenerator(
        replace(settings, enable_external_llm=True, groq_key="test-only-not-real"), mock
    )
    data = client.post("/ask", json={"question": "How many sick leave days?"}).json()
    assert (
        data["status"] == "source_excerpts"
        and data["error_code"] == "invalid_citations"
    )
    assert "Invented" not in data["answer"]


def test_restart_reuses_persistent_index(app_runtime):
    client, engine, settings = app_runtime
    before = engine.registry.epoch()
    second, _ = build(settings)
    assert second.registry.epoch() == before
    assert sum(r["status"] == "duplicate" for r in second.import_report) == 6
    assert (
        second.ask(
            "How many sick leave days?",
            Principal("d", "swiftpay", groups=("employees",)),
        )["status"]
        == "source_excerpts"
    )
    second.registry.conn.close()
    second.store.conn.close()


def test_empty_index_and_backend_error_are_distinct(app_runtime, tmp_path, monkeypatch):
    client, _, settings = app_runtime
    empty = build(replace(settings, data_dir=tmp_path / "empty", auto_import=False))
    monkeypatch.setattr(api, "runtime", lambda: empty)
    assert client.get("/ready").json()["status"] == "empty"
    assert (
        client.post("/ask", json={"question": "How many leaves?"}).json()["status"]
        == "no_evidence"
    )

    def fail():
        raise OSError("sensitive-detail")

    monkeypatch.setattr(api, "runtime", fail)
    response = client.get("/ready")
    assert (
        response.status_code == 503
        and response.json()["detail"]["code"] == "backend_unavailable"
    )
    assert "sensitive-detail" not in response.text
    empty[0].registry.conn.close()
    empty[0].store.conn.close()


def test_explicit_delete_is_not_reimported_on_restart(app_runtime):
    client, engine, settings = app_runtime
    from hr_rag.ingestion import Ingestor

    admin = Principal("admin", "swiftpay", groups=("hr_rag_admin",), admin=True)
    name = "POL-HR-010_Leave_Travel_and_Expense_Policy.docx"
    row = engine.registry.find("swiftpay", "hr", name)
    Ingestor(engine.registry, engine.store, engine.embedder, settings).delete(
        row["document_id"], admin
    )
    restarted, _ = build(settings)
    assert (
        restarted.ask(
            "How many sick leave days?",
            Principal("d", "swiftpay", groups=("employees",)),
        )["status"]
        == "no_evidence"
    )
    assert (
        next(r for r in restarted.import_report if r["name"] == name)["status"]
        == "deleted"
    )
    restarted.registry.conn.close()
    restarted.store.conn.close()


def test_model_timeout_and_empty_response_are_actionable(app_runtime):
    client, engine, settings = app_runtime

    class APITimeoutError(Exception):
        pass

    mock = Mock()
    mock.chat.completions.create.side_effect = APITimeoutError("private detail")
    engine.generator = GroqGenerator(
        replace(settings, enable_external_llm=True, groq_key="test-only"), mock
    )
    data = client.post("/ask", json={"question": "How many sick leave days?"}).json()
    assert data["error_code"] == "groq_timeout" and data["status"] == "source_excerpts"
    mock.chat.completions.create.side_effect = None
    mock.chat.completions.create.return_value = SimpleNamespace(choices=[])
    data = client.post("/ask", json={"question": "How many sick leave days?"}).json()
    assert (
        data["error_code"] == "empty_response" and data["status"] == "source_excerpts"
    )


def test_pdf_backup_table_keeps_the_correct_database_and_rpo(app_runtime):
    client, _, _ = app_runtime
    data = client.post(
        "/ask",
        json={
            "question": "What is the Payments database RPO in the backup SOP?",
            "namespace": "operations",
        },
    ).json()
    assert data["status"] == "source_excerpts"
    assert (
        "Database: Payments" in data["answer"] and "RPO: 15 minutes" in data["answer"]
    )
    assert any("page 2 table 3 row 2" == s["locator"] for s in data["sources"])


def test_pdf_table_rows_and_headings_are_preserved():
    name = "SOP-OPS-005_Database_Backup_and_Restore.pdf"
    blocks = parse(name, (ROOT / "data" / "source" / name).read_bytes())
    row = next(b for b in blocks if b.text.startswith("Database: Payments"))
    assert row.kind == "table_row" and row.heading == "7.1 Backup schedule"
    assert "RPO: 15 minutes" in row.text and "RTO: 1 hour" in row.text
    assert row.locator == "page 2 table 3 row 2"
