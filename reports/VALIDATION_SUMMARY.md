# Validation summary — updated 6 November 2026

## Documentation update — 6 November 2026

Expanded the main README and added `docs/README.md` and `docs/RUN_GUIDE.md`. The guides explain the project, RAG stages, source permissions, default excerpts, Groq generation, optional dense retrieval, Windows/macOS/Linux startup, restart and troubleshooting. Relative links and anchors, configuration keys and command file targets were checked against the packaged code. All 33 Python files and all 12 source/export data files remain byte-identical to the previous release. No application tests or live model calls were rerun for this documentation-only update. See `documentation_checks.json`.

## Readability update — 6 November 2026

All 33 Python files now use consistent formatting. Major steps have `#` comments explaining their purpose, and semicolon-separated statements were expanded. Black 25.1.0 formatting checks, compilation and an AST comparison against the previous archive passed. The comparison normalizes combined imports into separate statements without changing their order; executable expressions, literal values and control flow are unchanged. All six original datasets and all six parsed JSONL exports remain byte-identical. The two unrelated HTML sources remain absent.

The runtime and browser suites were not rerun for this comments-and-formatting-only update. Their results below describe the earlier functional release. See `code_readability_checks.json` for checks run on this update.

## Verified outcomes

- All 6 retained HR and operations originals preserved byte-for-byte (SHA-256 checked against Dataset(1).zip).
- All 6 retained originals parsed successfully: 442 text/table blocks, including 187 table-row blocks. PDF cells retain column names and page/table/row provenance.
- Six approved originals indexed on first startup; the demo employee sees four documents. The two unrelated research HTML files and their parsed outputs were removed from the package and configuration. The report and training workbook retain restricted access.
- Generated source duplicates and their derivation script removed. No virtual environment, live secret, stale index or runtime document copies are shipped.
- Actual leave question: annual 20 working days, sick 10, casual 6, plus the other leave types, eligibility and pro-rata crediting conditions; original Word-table citations retained.
- Bangalore geography question: explicit no-evidence response, HTTP 200.
- Bangalore hotel question: INR 4,000 and prior written department-head approval; city alias recognized.
- Payments backup question: PDF row with RPO 15 minutes, citation page 2 / table 3 / row 2.
- Tier 0 catalogue question: RPO 5 minutes from its own source. This distinct value is not substituted for the Payments database SOP.
- Work-from-home question: 2 days per week with manager approval, cited from the policy.

## Automated checks

For this dataset-only cleanup, archive consistency, SHA-256 preservation of all six retained sources and parsed outputs, JSONL validity, policy/manifest agreement, and Python compilation passed. Full pytest was not rerun successfully because the refreshed environment has no pytest installation. Runtime application code and UI were unchanged; corpus-count assertions were adjusted. See `dataset_cleanup_checks.json`.

Prior release baseline, before HTML cleanup: `python -m pytest -ra`: **40 passed**, no failures or skips. Six upstream deprecation warnings (Starlette/AnyIO and PyMuPDF SWIG type metadata). The suite covers actual supplied files, persistent retrieval, authorization, document lifecycle, fresh readiness, empty index, question validation, unsupported questions, provider auth/rate-limit/model/timeout failures, empty model responses, citation mismatch fallback, correct Groq evidence IDs, transcript recovery and UI state.

`python -m compileall -q app.py start.py hr_rag scripts tests`: passed.

UI static ownership audit: passed with zero findings. DESIGN.md lint: zero errors; six advisory orphaned-token warnings because component colors are owned in CSS and mirrored in prose rather than component frontmatter. Runtime theme values are tested for drift.

All pinned base requirements were installed. `reports/runtime_versions.json` records the environment. The optional Qdrant client integration test ran against its in-process local backend and passed; that is not a test of a Docker-hosted Qdrant server.

## Browser checks

Before this dataset-only cleanup, a real Chromium browser exercised the running FastAPI and Streamlit services at 1440px and 390px widths. Results are in `browser_checks.json`:

- Desktop empty state loaded with document readiness, source list and example questions.
- Pending request disables the composer and exposes a loading message.
- Leave question returns the real policy rows and eight inspectable source passages.
- Out-of-document geography question returns clear abstention without an API error.
- Operations backup question returns the Payments PDF table row with RPO 15 minutes.
- Knowledge-area switch clears history and shows a distinct empty-source state.
- Invalid session displays an actionable authentication error.
- Keyboard navigation moves focus from the labelled composer.
- Computed beige background and global scrollbar theme match the design; no desktop horizontal overflow.
- 390px mobile layout has no horizontal overflow and retains the composer.

The final mobile header spacing was inspected visually. No page JavaScript errors were recorded. Browser screenshots were used only for internal visual review and are not included in the package.

## Limits of this verification

- No real Groq API key was supplied. The SDK request structure and response/failure handling were tested with simulated provider responses, not a live account. Set the key and enable external generation in .env, then restart to use generated answers.
- Default local mode is BM25 keyword retrieval plus labelled direct excerpts. It does not claim LLM synthesis, semantic understanding, calibrated retrieval accuracy or live employee balances.
- The neural embedding download, Docker-hosted Qdrant/Redis and a real enterprise JWT issuer were not run end-to-end. Those remain optional environment-specific checks.
- Tested on Python 3.12/Linux. Windows setup commands and portable launcher are included; a physical Windows machine was not available for a platform-specific run.
- PDF table extraction is verified for these supplied digital PDFs. Scans need OCR and complex/unusual tables need review.
- Citation validation checks citation mechanics, not proof of entailment. This remains a local single-writer project, not a production certification.
