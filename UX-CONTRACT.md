# Knowledge Desk interaction contract

Business sources: `config/dataset_policies.json` controls document access and rejects unapproved files; `hr_rag/security.py` derives identity on the server; `hr_rag/api.py` defines validation and admin-only updates. The demo remains an internal employee identity, not an administrator. Neither UI selection nor prompt content can grant access.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Form | Streamlit chat_input, text_input and file_uploader | app.py and FastAPI Question | explicit chat submit; masked connection token; admin upload | tests/test_api_recovery.py and tests/test_ui_contract.py |
| Scrollbar | ui/styles.css global tokens | DESIGN.md | browser standards with WebKit fallback | stylesheet contract and browser inspection |
| Toast | Streamlit inline error, warning, info, success | app.py render_answer | message-scoped warning; page connection failure | API failure tests and browser inspection |

The knowledge-area selector uses a labelled Streamlit radio group; no select/listbox or calendar is introduced. Sources are a bounded list (the project corpus has six originals); no searchable data grid is needed. Chat questions and tokens stay out of URL state because questions may contain private content.

Ask → append user question → disable composer and conversation controls → show spinner → append cited answer/excerpts or inline failure → restore controls. A failed question is saved with a Retry action. A new conversation clears only current UI history. Switching knowledge area or credentials clears history to prevent cross-scope display.

Connection → call authenticated /ready → show actual accessible source counts. Empty index is different from unreachable backend. /health is process liveness only. The model may be configured without being tested; the label states that explicitly.

Upload → admin-only source picker → parse/index → show success or per-operation error. Exact duplicates do not re-index. Unknown and unreviewed sources are not published. No deletion control is exposed in the UI. API delete is admin-only; this is a local single-writer project, not a multi-user deployment.

Accessibility: semantic framework controls, visible focus, keyboard navigation, text status, readable contrast, responsive document scrolling, reduced motion and persistent source expanders. Source previews are displayed as plain text; user/document content is never passed to unsafe HTML. Only static layout and escaped source titles use HTML.
