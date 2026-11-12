# Create small fixtures so source locations, table structure and permission boundaries
# can be checked independently.

import io
import zipfile
from docx import Document
from hr_rag.parse import parse, check_file
from hr_rag.chunking import chunk_blocks
from hr_rag.models import Block
import pytest


def test_empty_and_spoofed_files_fail():
    with pytest.raises(ValueError):
        check_file("doc.pdf", b"")
    with pytest.raises(ValueError):
        check_file("doc.pdf", b"not a pdf")
    with pytest.raises(ValueError):
        check_file("doc.exe", b"executable")
    with pytest.raises(ValueError):
        check_file("doc.xlsx", b"fake file")


def test_docx_preserves_table_and_heading():
    d = Document()
    d.add_heading("4.1 Leave entitlement", level=1)
    d.add_paragraph("Employees receive 10 sick days annually")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "City"
    t.cell(0, 1).text = "Limit"
    t.cell(1, 0).text = "Bengaluru"
    t.cell(1, 1).text = "INR 4,000"
    f = io.BytesIO()
    d.save(f)
    out = parse("policy.docx", f.getvalue())
    assert any(
        "10 sick days" in x.text and x.heading == "4.1 Leave entitlement" for x in out
    )
    assert any(
        "City: Bengaluru" in x.text and x.kind == "table_row" and "table" in x.locator
        for x in out
    )


def test_csv_rows_have_locators():
    out = parse("data.csv", b"ID,Value\nS01,15 minutes\nS02,5 minutes")
    assert len(out) == 2 and out[1].locator == "row 3"


def test_html_does_not_include_script():
    out = parse(
        "test.html",
        b"<html><body><h1>Leave</h1><p>10 days</p><script>steal()</script></body></html>",
    )
    assert "steal" not in " ".join(x.text for x in out)
    assert any(x.heading == "Leave" for x in out)


def test_permissions_never_merge_in_chunking():
    blocks = [
        Block("open policy text", scope=("internal",), classification="internal"),
        Block(
            "personal detail", scope=("group:hr",), classification="restricted-personal"
        ),
        Block("classified unknown", scope=(), classification="unclassified"),
    ]
    chunks = chunk_blocks(
        blocks,
        document_id="D1",
        source_filename="a.txt",
        source_group="D1",
        tenant_id="org",
        namespace="hr",
        size=2,
        overlap=0,
    )
    assert all(
        "personal detail" not in c.text or c.access_scopes == ["group:hr"]
        for c in chunks
    )
    assert all("classified unknown" not in c.text for c in chunks)
