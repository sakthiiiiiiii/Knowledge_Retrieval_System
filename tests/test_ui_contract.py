"""State tests for the framework UI plus theme-adapter drift checks."""

# Mock API responses to check interface state and recovery without depending on a live
# service.

from unittest.mock import patch
import tomllib
import pytest
from streamlit.testing.v1 import AppTest
from hr_rag.config import ROOT

READY = {
    "status": "ready",
    "documents": [
        {
            "name": "POL-HR-010_Leave_Travel_and_Expense_Policy.docx",
            "namespace": "hr",
            "chunks": 50,
        }
    ],
    "document_count": 1,
    "chunk_count": 50,
    "generation": "Local source excerpts",
    "retrieval": "lexical",
    "admin": False,
}


class Response:
    ok = True
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_theme_adapter_matches_runtime():
    theme = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())["theme"]
    css = (ROOT / "ui/styles.css").read_text()
    for key in (
        "primaryColor",
        "backgroundColor",
        "secondaryBackgroundColor",
        "textColor",
    ):
        assert theme[key] in css
    assert "scrollbar-color:" in css and "scrollbar-width:" in css
    assert "prefers-reduced-motion" in css and ":focus-visible" in css


def test_ui_success_and_new_conversation():
    with (
        patch("requests.get", return_value=Response(READY)),
        patch(
            "requests.post",
            return_value=Response(
                {
                    "answer": "Annual leave: 20 working days [C1].",
                    "status": "source_excerpts",
                    "sources": [],
                    "latency_ms": 2.0,
                    "cached": False,
                }
            ),
        ),
    ):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        assert not app.exception
        app.chat_input[0].set_value("How many leaves?").run()
        assert not app.exception and len(app.chat_message) == 2
        assert any("20 working days" in x.value for x in app.markdown)
        next(b for b in app.button if "New conversation" in b.label).click().run()
        assert not app.exception and len(app.chat_message) == 0


def test_ui_failure_preserves_retry():
    import requests

    with (
        patch("requests.get", return_value=Response(READY)),
        patch("requests.post", side_effect=requests.ConnectionError()),
    ):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.chat_input[0].set_value("How many leaves?").run()
        assert not app.exception
        assert any("connection was interrupted" in x.value for x in app.error)
        assert any(x.label == "Retry last question" for x in app.button)
        assert not app.chat_input[0].disabled


def test_ui_namespace_switch_clears_history():
    with patch("requests.get", return_value=Response(READY)):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.radio[0].set_value("Research").run()
        assert not app.exception and app.chat_input[0].disabled
        assert any("no approved sources" in x.value for x in app.info)
