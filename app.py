"""A small, document-grounded knowledge desk. All permissions remain in the API."""

import hashlib
import html
import os
from pathlib import Path

import requests
import streamlit as st
from hr_rag.config import ROOT, Settings


# Load the shared theme once per render so the beige, red and black UI stays
# consistent.
st.set_page_config(page_title="SwiftPay · Knowledge Desk", page_icon="▤", layout="wide")
st.markdown(
    "<style>" + (ROOT / "ui" / "styles.css").read_text() + "</style>",
    unsafe_allow_html=True,
)

TITLES = {
    "POL-HR-010_Leave_Travel_and_Expense_Policy.docx": "Leave, travel & expenses",
    "SOP-OPS-001_Incident_Management_and_Escalation.pdf": "Incident management",
    "SOP-OPS-005_Database_Backup_and_Restore.pdf": "Database backup & restore",
    "SwiftPay_Service_Catalogue_and_Ownership.xlsx": "Service catalogue",
    "RPT-OPS-2026-09_Monthly_IT_Operations_Report_September_2026.docx": "Monthly operations report",
    "SwiftPay_Employee_Training_Records.xls": "Employee training records",
}
AREAS = {
    "People & policies": "hr",
    "IT & operations": "operations",
    "Research": "research",
}
SUGGESTIONS = {
    "hr": [
        ("Leave entitlement", "How many leaves is the employee entitled to?"),
        (
            "Business travel",
            "What is the Bengaluru hotel limit and above-limit approval?",
        ),
        ("Working from home", "How many days can employees work from home?"),
    ],
    "operations": [
        ("Database backups", "What is the Payments database RPO in the backup SOP?"),
        ("Service recovery", "What is the Tier 0 RPO in the service catalogue?"),
        ("Incident response", "What are the incident escalation steps?"),
    ],
    "research": [],
}


# Translate API failures into readable next steps instead of exposing raw error
# bodies.
def api_message(response):
    try:
        detail = response.json().get("detail", {})
        if isinstance(detail, dict):
            return detail.get(
                "message", "The request could not be completed. Try again."
            )
        if isinstance(detail, list):
            return "Check your question: use 1–1,500 characters and try again."
        if isinstance(detail, str) and len(detail) < 300:
            return detail
    except ValueError:
        pass
    return f"The service returned HTTP {response.status_code}. Check Connection settings and retry."


# Cache readiness briefly to avoid reopening the index on every Streamlit rerun.
@st.cache_data(ttl=30, show_spinner=False)
def get_readiness(api_url, bearer):
    try:
        response = requests.get(
            api_url + "/ready",
            headers={"Authorization": "Bearer " + bearer},
            timeout=90,
        )
        if response.ok:
            return response.json(), None
        return None, api_message(response)
    except requests.Timeout:
        return (
            None,
            (
                "Preparing the search index took too long. Wait "
                "a moment, then select Check connection."
            ),
        )
    except requests.RequestException:
        return None, (
            "The API is not reachable. Run python start.py from the project "
            "folder, then check the connection."
        )
    except ValueError:
        return (
            None,
            (
                "The API returned an unexpected response. Check "
                "the API address and restart."
            ),
        )


def render_answer(message):
    if message.get("error"):
        st.error(message["content"])
        return

    # Label excerpts and generated answers separately so users know how the answer was
    # produced.
    status = message.get("status", "")
    if message.get("warning"):
        st.warning(message["warning"])
    if status == "source_excerpts":
        st.caption("SOURCE EXCERPTS · Quoted from your documents")
    elif status == "answered":
        st.caption("DOCUMENT ANSWER · Generated with Groq")
    if status in {"no_evidence", "abstained", "invalid_citations"}:
        st.markdown("**I couldn’t find that in your documents.**")
        st.write(
            (
                "Ask about a policy or procedure in the selected knowledge area. "
                "General questions and live employee balances need another source."
            )
        )
    else:
        st.markdown(message["content"])

    # Keep the original passages visible so users can check each answer against its
    # evidence.
    sources = message.get("sources", [])
    if sources:
        with st.expander(f"View evidence · {len(sources)} passages"):
            for source in sources:
                st.markdown(
                    f"**[{source['citation']}] "
                    f"{TITLES.get(source['source_filename'], source['source_filename'])}**"
                )
                st.caption(f"{source['heading']} · {source['locator']}")
                st.text(source.get("excerpt", ""))
    if "latency_ms" in message:
        st.caption(
            f"{message['latency_ms'] / 1000:.2f} s"
            + (" · From cache" if message.get("cached") else "")
        )


# Keep authentication and document permissions in the API; the UI only sends the
# session token.
api = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
settings = Settings()
with st.sidebar:
    st.markdown(
        (
            '<div class="brand"><div class="brand-mark">S</div><div><div '
            'class="brand-name">SwiftPay</div><div '
            'class="brand-caption">KNOWLEDGE DESK</div></div></div>'
        ),
        unsafe_allow_html=True,
    )
    if st.button(
        "New conversation",
        use_container_width=True,
        disabled=bool(st.session_state.get("pending")),
    ):
        st.session_state.chat = []
        st.session_state.failed_question = None
        st.rerun()
    area = st.radio(
        "Knowledge area", list(AREAS), disabled=bool(st.session_state.get("pending"))
    )
    namespace = AREAS[area]
    with st.expander("Connection settings"):
        st.caption("Local sessions connect automatically when started with start.py.")
        manual_token = st.text_input(
            "Session token",
            type="password",
            help="Only needed for a manually started API or an enterprise login.",
            disabled=bool(st.session_state.get("pending")),
        )
        st.caption("API address: " + api)
        if st.button(
            "Check connection",
            use_container_width=True,
            disabled=bool(st.session_state.get("pending")),
        ):
            get_readiness.clear()
        st.caption(
            (
                "For Groq answers, set GROQ_API_KEY and "
                "ENABLE_EXTERNAL_LLM=true in .env, then restart."
            )
        )

    # Reuse the launcher token for local sessions so users do not have to copy
    # credentials.
    token = manual_token or (
        settings.demo_token if settings.auth_mode == "demo" else ""
    )
    with st.spinner("Checking your documents…"):
        readiness, connection_error = get_readiness(api, token)
    if readiness:
        st.caption(readiness["generation"])
        docs = [d for d in readiness["documents"] if d["namespace"] == namespace]
        st.markdown(
            f'<div class="section-label">Your sources / {len(docs):02d}</div>',
            unsafe_allow_html=True,
        )
        for doc in docs:
            # Escape source names before inserting them into HTML so filenames remain
            # plain text.
            title = html.escape(TITLES.get(doc["name"], doc["name"]))
            kind = html.escape(Path(doc["name"]).suffix.lstrip(".").upper())
            st.markdown(
                f'<div class="source-item">{title}<small>{kind} · '
                f'{doc["chunks"]} indexed passages</small></div>',
                unsafe_allow_html=True,
            )
        if not docs:
            st.info(
                "No approved documents are available in this area for your session."
            )
        if readiness.get("admin"):
            with st.expander("Update a document"):
                upload = st.file_uploader(
                    "Choose an approved source file",
                    type=[
                        "pdf",
                        "docx",
                        "xlsx",
                        "xls",
                        "csv",
                        "html",
                        "htm",
                        "txt",
                        "md",
                    ],
                )
                if st.button(
                    "Upload document",
                    disabled=not bool(upload),
                    use_container_width=True,
                ):
                    try:
                        with st.spinner("Parsing and indexing…"):
                            response = requests.post(
                                api + "/documents",
                                headers={"Authorization": "Bearer " + token},
                                files={"file": (upload.name, upload.getvalue())},
                                timeout=180,
                            )
                        if response.ok:
                            st.success(
                                (
                                    "Document indexed. Select Check connection to "
                                    "refresh the source list."
                                )
                            )
                            get_readiness.clear()
                        else:
                            st.error(api_message(response))
                    except requests.RequestException:
                        st.error(
                            (
                                "Upload could not finish. Check the connection "
                                "and retry; repeated files are not duplicated."
                            )
                        )
    else:
        docs = []
        st.warning("Connection needs attention")
    st.markdown(
        (
            '<div class="desk-note">Every answer starts with your documents. '
            "Open the evidence to see the original passage.</div>"
        ),
        unsafe_allow_html=True,
    )


# Clear conversation state when the identity or knowledge area changes to avoid mixing
# sessions.
scope = hashlib.sha256((api + token + namespace).encode()).hexdigest()
if st.session_state.get("scope") != scope:
    st.session_state.update(scope=scope, chat=[], pending=None, failed_question=None)

status_text = (
    "Documents ready"
    if readiness and docs
    else ("No sources in this area" if readiness else "Connection unavailable")
)
st.markdown(
    f'<div class="topline"><strong>{html.escape(area)}</strong>'
    f"<small>{html.escape(status_text)}</small></div>",
    unsafe_allow_html=True,
)

if not st.session_state.chat:
    st.markdown(
        (
            '<div class="eyebrow">Ask your knowledge desk</div><h1 '
            'class="hero-title">Work questions.<br><span>Clear '
            'answers.</span></h1><p class="hero-copy">Find the policy, check the '
            "details, and see exactly where the answer comes from.</p>"
        ),
        unsafe_allow_html=True,
    )
    if docs:
        st.markdown(
            '<div class="section-label">Start with a question</div>',
            unsafe_allow_html=True,
        )
        columns = st.columns(3)
        for column, (label, question) in zip(columns, SUGGESTIONS[namespace]):
            with column:
                if st.button(
                    label + "  ↗",
                    use_container_width=True,
                    disabled=bool(st.session_state.get("pending")),
                ):
                    st.session_state.chat.append({"role": "user", "content": question})
                    st.session_state.pending = question
                    st.rerun()
        st.markdown(
            '<div class="footer-note">POLICIES · PROCEDURES · SOURCE CITATIONS</div>',
            unsafe_allow_html=True,
        )

if connection_error:
    st.error(connection_error)
elif not docs:
    st.info(
        (
            "This knowledge area has no approved sources for your session. "
            "Choose People & policies or IT & operations to begin."
        )
    )

for message in st.session_state.chat:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            render_answer(message)
        else:
            st.markdown(message["content"])

if st.session_state.get("failed_question") and not st.session_state.get("pending"):
    if st.button("Retry last question", type="primary"):
        st.session_state.pending = st.session_state.failed_question
        st.session_state.failed_question = None
        st.rerun()


# Disable submission while a question is pending to prevent duplicate requests.
question = st.chat_input(
    "Ask about your documents…",
    max_chars=1500,
    disabled=not bool(readiness and docs) or bool(st.session_state.get("pending")),
)
if question and question.strip():
    st.session_state.chat.append({"role": "user", "content": question.strip()})
    st.session_state.pending = question.strip()
    st.session_state.failed_question = None
    st.rerun()

if st.session_state.get("pending"):
    question = st.session_state.pending
    with st.chat_message("assistant"):
        with st.spinner("Reading the relevant passages…"):
            # Send only recent user questions to support short follow-ups without
            # growing the request indefinitely.
            history = [
                m["content"] for m in st.session_state.chat if m["role"] == "user"
            ][:-1][-4:]
            try:
                response = requests.post(
                    api + "/ask",
                    headers={"Authorization": "Bearer " + token},
                    json={
                        "question": question,
                        "namespace": namespace,
                        "history": history,
                    },
                    timeout=100,
                )
                if response.ok:
                    payload = response.json()
                    message = {
                        "role": "assistant",
                        "content": payload["answer"],
                        **{k: v for k, v in payload.items() if k != "answer"},
                    }
                else:
                    message = {
                        "role": "assistant",
                        "content": api_message(response),
                        "error": True,
                    }
            except requests.Timeout:
                message = {
                    "role": "assistant",
                    "content": (
                        "The request took too long. Your question is "
                        "saved; try again."
                    ),
                    "error": True,
                }
            except requests.RequestException:
                message = {
                    "role": "assistant",
                    "content": (
                        "The connection was interrupted. Start the API "
                        "again and retry your question."
                    ),
                    "error": True,
                }
            except (ValueError, KeyError):
                message = {
                    "role": "assistant",
                    "content": (
                        "The service returned an unexpected response. "
                        "Restart it and retry."
                    ),
                    "error": True,
                }
            st.session_state.chat.append(message)

            # Retain a failed question for retry so a connection problem does not
            # erase the user's work.
            st.session_state.failed_question = (
                question if message.get("error") else None
            )
            st.session_state.pending = None
    st.rerun()
