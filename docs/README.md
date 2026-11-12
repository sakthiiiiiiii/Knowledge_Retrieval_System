# Project walkthrough

[Main README](../README.md) · [Run guide](RUN_GUIDE.md)

## Purpose

SwiftPay Knowledge Desk turns the supplied HR and operations documents into a searchable question-answering application. The user asks a question in Streamlit; FastAPI retrieves permitted evidence and returns either direct excerpts or a Groq-generated answer with citations.

The key idea is to connect each answer to the source passage that supports it. A language model is optional. Parsing, access checks, indexing, retrieval and citations still work in local excerpt mode.

## Components and why they exist

| Component | What it does | Why it is needed |
|---|---|---|
| Streamlit interface | Collects questions and shows answers, warnings and source passages | Makes the document search usable without writing API calls |
| FastAPI service | Validates requests and verifies the session identity | Keeps access decisions on the server |
| Parsers | Convert DOCX, PDF, XLS and XLSX contents into blocks | Makes different document formats usable by the same pipeline |
| Policy classification | Assigns document, section or row access scopes | Prevents restricted content from acquiring broader permissions during chunking |
| Chunking | Splits content while retaining headings, locations and access metadata | Gives retrieval smaller pieces of evidence without losing provenance |
| SQLite BM25 backend | Ranks authorized passages by keyword relevance | Allows a local first run without model downloads or external services |
| Optional embeddings and Qdrant | Represent text as vectors and search by similarity | Provides an alternative retrieval method for semantic matching |
| Answer engine | Orchestrates retrieval, evidence selection, generation and validation | Keeps these stages consistent for API and command-line use |
| Groq generator | Requests a structured answer from the configured hosted model | Allows synthesis across retrieved evidence when explicitly enabled |
| Extractive generator | Returns cited passages without a language model call | Supports local use and clear recovery when Groq is unavailable |
| Registry | Tracks documents, versions, status and corpus revision | Supports duplicate detection, replacement and cache invalidation |
| Optional Redis cache | Stores scoped exact answers | Can avoid repeating eligible work for the same request context |

## Data preparation: source to index

### 1. Check the file

`hr_rag/parse.py` checks the extension, size and relevant format signatures. Office ZIP containers have limits on expanded size and complexity. Invalid or empty documents fail explicitly.

### 2. Preserve document structure

The parser creates `Block` objects containing text, a heading, a source locator and a block kind. A PDF table row retains its column labels and page/table/row location. A spreadsheet row retains its sheet and row location. Word paragraphs and tables are read in document order so section headings remain attached to the right content.

These fields are important: a number such as “15 minutes” is not useful evidence unless the database, measurement and source location remain associated with it.

### 3. Assign access rules before splitting

`hr_rag/policy.py` loads approved rules from `config/dataset_policies.json`. Unknown documents are held for review. Sensitive sections and employee-related rows are classified before chunking, so a chunk cannot accidentally mix public and restricted sections.

### 4. Create chunks

`hr_rag/chunking.py` groups compatible prose, prefers sentence boundaries and uses overlap to retain context around boundaries. Table rows are kept separate from neighbouring rows; a long row can still be split to fit the chunk size. Access, heading and page changes break the group.

Despite the configuration names `CHUNK_TOKENS` and `CHUNK_OVERLAP`, this chunker measures **words**. The dense embedder separately checks the model's actual token limit and rejects overlong inputs rather than silently truncating them.

### 5. Publish an indexed version

`hr_rag/ingestion.py` hashes the original bytes to detect duplicates, prepares chunks, records a version and publishes active searchable content. Replacement retires the previous version. The registry's corpus revision changes so earlier cached answers are no longer reused.

The supported pilot workflow serializes administrator writes. It is not a general distributed transaction system.

## Question flow: request to answer

1. `app.py` submits the question, selected namespace and up to four previous user questions to `/ask`.
2. `api.py` verifies the bearer token and validates the request. A prompt cannot grant the user additional permissions.
3. `engine.py` handles known unsupported requests and checks for a valid scoped cached answer when caching is configured.
4. The selected retrieval backend searches active content within the user's tenant, knowledge area and access scopes. Short leave follow-ups can reuse recent question context.
5. The engine removes duplicate passages and includes relevant leave eligibility/crediting qualifications when available.
6. If Groq is selected, the cloud-disclosure rules are checked before sending evidence. `generation.py` labels evidence as `C1`, `C2`, and so on, then requests `answer` and `cited_ids` in JSON.
7. Citation validation checks that referenced IDs exist and that inline citations agree with the returned list. It checks citation mechanics, not semantic truth.
8. Provider or citation failures produce an explained fallback to source excerpts where possible. The UI labels this outcome accurately and lets the user inspect the source passages.

A question such as “Where is Bangalore?” receives a no-evidence response because the supplied hotel-limit table does not establish geographical location. A question about the Bangalore hotel allowance can use that table. The system does not fill gaps with general model knowledge.

## Dataset and access rules

The package contains six relevant originals and six parser exports. The two unrelated research HTML files and generated duplicate datasets are absent. Generic HTML parsing support remains available in the code, but there are no bundled HTML sources or approved research entries.

The local demo identity is an ordinary internal employee. It sees the HR policy, two operations SOPs and service catalogue. The monthly operations report and training workbook remain restricted. Report access requires the relevant group; Appendix B has its own on-call scope. Training records use HR/L&D and derived team scopes according to the policy implementation.

`data/parsed/` is an inspection/export folder. Runtime startup parses and indexes approved originals from `data/source/` rather than reading those exports. Consequently, rerunning `scripts/parse_dataset.py` alone does not change an already active index.

For an approved existing source, replace its original in `data/source/` and restart the local launcher to import changed bytes. New filenames require a reviewed entry in `config/dataset_policies.json`; adding a file alone is insufficient. API upload and delete routes require administrator access, which the demo token does not grant. Explicit deletions are remembered and are not automatically undone by restart.

## Model configuration

| Setting | Meaning |
|---|---|
| `RETRIEVAL_MODE=lexical` | Use local BM25 keyword search |
| `RETRIEVAL_MODE=dense` | Use local embeddings plus Qdrant |
| `GENERATION_MODE=auto` | Select Groq when external generation is enabled; otherwise use excerpts |
| `GENERATION_MODE=extractive` | Always return local source excerpts |
| `GENERATION_MODE=groq` | Select the Groq generator; opt-in and valid credentials are still required |
| `ENABLE_EXTERNAL_LLM=true` | Allow external generation requests |
| `GROQ_MODEL` | Hosted model name used in the Groq request |
| `EMBED_MODEL` | Local embedding model used only in dense mode |
| `ALLOW_EXTERNAL_CONFIDENTIAL=false` | Keep restricted/confidential evidence out of cloud requests under the default policy |

There is no model-training step or training checkpoint in this repository. The optional embedding model is pretrained; the generation model is hosted by Groq. Rebuilding an index means preparing searchable evidence, not training a model.

## Code reading order

Read `start.py` and `app.py` first to understand how the user starts and interacts with the system. Then read `hr_rag/api.py`, `bootstrap.py` and `engine.py` to follow a request. For data preparation, follow `parse.py`, `policy.py`, `chunking.py` and `ingestion.py`. Finally, inspect `generation.py`, `security.py`, `registry.py` and the selected retrieval backend.

The Python files use spacing between logical stages and `#` comments explaining the purpose of key decisions. Tests cover the behavioral boundaries; reports distinguish recorded checks from environment-specific work that has not been run.

## API routes

| Route | Purpose | Access |
|---|---|---|
| `GET /health` | Check that the process responds | No token; does not prove index or model readiness |
| `GET /ready` | Open the runtime and report accessible indexed documents and generation configuration | Verified session |
| `POST /ask` | Answer a question within a namespace | Verified session |
| `POST /documents` | Ingest an approved document | Administrator |
| `DELETE /documents/{document_id}` | Delete a document | Administrator |

The interactive API page is [http://localhost:8000/docs](http://localhost:8000/docs) with default ports. This project accepts the bearer value in the `Authorization` header; its custom header dependency is not an OAuth login flow.

## Evaluation and limits

`tests/` checks parsing, permissions, lifecycle behavior, API recovery and UI state. The Groq tests simulate responses and failures. `scripts/evaluate.py` measures document-level retrieval against supplied relevance labels; those labels still need independent review before treating scores as quality evidence. `scripts/compare_embeddings.py` and `compare_chunking.py` are optional experiments. `scripts/score_answers.py` aggregates independently reviewed answer scores.

See [the validation summary](../reports/VALIDATION_SUMMARY.md) for actual recorded checks. A passing syntax or citation check is not a guarantee of factual correctness. Live Groq account access and external dense services must be checked separately in the environment where the project runs.
