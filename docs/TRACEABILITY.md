# Repair traceability

| Requirement | Implementation | Evidence |
|---|---|---|
| Fix API errors for questions | generation.py enumerates evidence, maps provider errors, validates citations | tests/test_api_recovery.py |
| Parse supplied data | parse.py and scripts/parse_dataset.py; original bytes in data/source | reports/dataset_parsing.json |
| Remove generated source duplicates | data/derivatives and derive_sources.py removed; manifest has 6 relevant originals | config/dataset_manifest.json |
| Return policy leave entitlement | actual DOCX tables and scope retained | test_original_leave_question_returns_cited_source_rows |
| Handle unsupported questions | explicit no-evidence response, no general-knowledge fabrication | test_unsupported_question_returns_message_not_error |
| Keep access boundaries | server identity, namespace/tenant/scopes, restricted records held from demo | tests/test_security.py and readiness tests |
| Operate without service setup | persistent SQLite/BM25 + extractive mode | restart and API integration tests |
| Beige/red/black UI | app.py, ui/styles.css, framework theme | tests/test_ui_contract.py and QA report |
| Groq-generated answer path | JSON Object Mode and sequential C IDs | mocked SDK request/response tests; no live key supplied |

Local excerpts are deliberately labelled. They are not evidence of LLM answer quality or neural retrieval performance. The two unrelated research HTML sources and their parser outputs were removed. Optional dense embeddings, external Qdrant/Redis, JWT issuer integration and a real Groq account require separate environment-specific checks.
