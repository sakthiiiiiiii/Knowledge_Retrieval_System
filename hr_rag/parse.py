"""Source-aware parsers. No OCR, scripts or network fetches of arbitrary uploaded HTML."""

from __future__ import annotations
import csv
import io
import re
import zipfile
from pathlib import Path
from .models import Block

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".txt", ".md"}
MAX_BYTES = 50 * 1024 * 1024


def check_file(name: str, raw: bytes):
    # Check type, size and file signatures before handing untrusted bytes to a format-
    # specific parser.
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED or not raw or len(raw) > MAX_BYTES:
        raise ValueError("Unsupported, empty or oversized document")
    if ext in {".docx", ".xlsx"}:
        if not raw.startswith(b"PK\x03\x04"):
            raise ValueError("Invalid Office document signature")

        # Office files are ZIP containers; limit expanded size as well as uploaded
        # size.
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if (
                len(z.infolist()) > 3000
                or sum(x.file_size for x in z.infolist()) > 120 * 1024 * 1024
            ):
                raise ValueError("Office archive too large or complex")
    if ext == ".pdf" and not raw.startswith(b"%PDF"):
        raise ValueError("Invalid PDF signature")
    if ext == ".xls" and not raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("Invalid XLS signature")
    return ext


def _tidy(s):
    return re.sub(r"\s+", " ", "" if s is None else str(s)).strip()


def _workbook(data, ext):
    if ext == ".xlsx":
        from openpyxl import load_workbook

        # Read stored cell values without editing the workbook or evaluating formulas.
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        return [(ws.title, list(ws.values)) for ws in wb.worksheets]
    import xlrd

    wb = xlrd.open_workbook(file_contents=data, on_demand=True)
    return [
        (s.name, [[s.cell_value(r, c) for c in range(s.ncols)] for r in range(s.nrows)])
        for s in wb.sheets()
    ]


def parse(name: str, raw: bytes) -> list[Block]:
    # Step 1: Validate the source and produce a common Block structure for every
    # supported format.
    ext = check_file(name, raw)
    blocks = []
    if ext == ".pdf":
        import fitz

        heading = ""
        with fitz.open(stream=raw, filetype="pdf") as document:
            if len(document) > 300:
                raise ValueError("PDF page limit exceeded")
            for page_number, page in enumerate(document, 1):
                # Extract rows while the page is alive; do not flatten column
                # relationships.
                detected = page.find_tables().tables
                tables = [(tuple(t.bbox), t.extract()) for t in detected]
                events = []
                for table_number, (bbox, rows) in enumerate(tables, 1):
                    events.append((bbox[1], bbox[0], "table", (table_number, rows)))

                # Read prose outside detected tables so table text is not indexed
                # twice.
                for block in page.get_text("dict", sort=True)["blocks"]:
                    for line in block.get("lines", []):
                        x0, y0, x1, y1 = line["bbox"]
                        center = ((x0 + x1) / 2, (y0 + y1) / 2)
                        if any(
                            b[0] <= center[0] <= b[2] and b[1] <= center[1] <= b[3]
                            for b, _ in tables
                        ):
                            continue
                        text = _tidy("".join(span["text"] for span in line["spans"]))
                        if text:
                            events.append((y0, x0, "text", text))

                # Restore page reading order so each table keeps the section heading
                # that precedes it.
                for index, (_, _, kind, value) in enumerate(
                    sorted(events, key=lambda e: (e[0], e[1])), 1
                ):
                    if kind == "table":
                        table_number, rows = value
                        if not rows:
                            continue
                        header = [
                            _tidy(v) or f"Column {i+1}" for i, v in enumerate(rows[0])
                        ]

                        # Keep each cell paired with its column name so numbers remain
                        # attached to their meaning.
                        for row_number, row in enumerate(rows[1:], 2):
                            text = " | ".join(
                                f"{key}: {_tidy(cell)}"
                                for key, cell in zip(header, row)
                            )
                            blocks.append(
                                Block(
                                    text,
                                    heading=heading,
                                    locator=(
                                        f"page {page_number} table {table_number} "
                                        f"row {row_number}"
                                    ),
                                    kind="table_row",
                                )
                            )
                    else:
                        text = value
                        if re.match(
                            r"^(Uncontrolled when printed|Check the document system|Page \d+$)",
                            text,
                        ):
                            continue
                        if re.match(
                            r"^(?:\d+\.\s+[A-Z]|\d+\.\d+(?:\.\d+)*\s+[A-Z]|Appendix [A-Z])",
                            text,
                        ):
                            heading = text
                        blocks.append(
                            Block(
                                text,
                                heading=heading,
                                locator=f"page {page_number} text {index}",
                            )
                        )
        if not blocks:
            raise ValueError("Image-only PDF requires OCR review")
    elif ext == ".docx":
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(io.BytesIO(raw))
        heading = ""
        pcount = 0
        tcount = 0

        # Walk paragraphs and tables in document order so table rows inherit the
        # correct heading.
        for el in doc.element.body.iterchildren():
            if el.tag == qn("w:p"):
                p = Paragraph(el, doc)
                text = _tidy(p.text)
                if not text:
                    continue
                pcount += 1
                if (p.style and p.style.name.startswith("Heading")) or re.match(
                    r"^(?:Appendix [A-Z]|\d+(?:\.\d+)*\.?)\s+[A-Z]", text
                ):
                    heading = text
                blocks.append(
                    Block(text, heading=heading, locator=f"paragraph {pcount}")
                )
            elif el.tag == qn("w:tbl"):
                tcount += 1
                t = Table(el, doc)
                rows = [[_tidy(c.text) for c in r.cells] for r in t.rows]
                if rows:
                    header = rows[0]
                    for j, row in enumerate(rows[1:] or rows):
                        data = " | ".join(f"{k}: {v}" for k, v in zip(header, row))
                        if data.strip(" |:"):
                            blocks.append(
                                Block(
                                    data,
                                    heading=heading,
                                    locator=f"table {tcount} row {j+2}",
                                    kind="table_row",
                                )
                            )
    elif ext in {".xlsx", ".xls"}:
        sheets = _workbook(raw, ext)
        for sheet, rows in sheets:
            if sheet.lower() in ("about", "summary") and "Training" in name:
                # Whole-register summary violates per-employee scopes; withhold.
                continue
            if sheet.lower() == "about":
                continue  # document title / field metadata is not retrieval content
            start = next(
                (
                    j
                    for j, row in enumerate(rows)
                    if sum(bool(_tidy(v)) for v in row) >= 2
                ),
                None,
            )
            if start is None:
                continue
            header = [_tidy(v) or f"Column {i}" for i, v in enumerate(rows[start])]
            for rowno, row in enumerate(rows[start + 1 :], start + 2):
                if not any(_tidy(v) for v in row):
                    continue
                kv = dict(zip(header, [_tidy(v) for v in row]))

                # Preserve employee and team fields so row access can be assigned
                # before chunking.
                emp = kv.get("Employee ID")
                team = kv.get("Team")
                blocks.append(
                    Block(
                        " | ".join(f"{k}: {v}" for k, v in kv.items()),
                        heading=f"Sheet {sheet}",
                        locator=f"sheet {sheet} row {rowno}",
                        kind="table_row",
                        employee_id=emp,
                        team=team,
                        metadata={"sheet": sheet, "row": rowno},
                    )
                )
    elif ext == ".csv":
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for i, row in enumerate(reader, 2):
            blocks.append(
                Block(
                    " | ".join(f"{k}: {_tidy(v)}" for k, v in row.items()),
                    heading="CSV",
                    locator=f"row {i}",
                    kind="table_row",
                )
            )
    elif ext in {".html", ".htm"}:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")

        # Remove scripts and navigation from HTML parsing; none of this content is
        # executed or fetched.
        for tag in soup(
            ["script", "style", "nav", "footer", "header", "iframe", "form"]
        ):
            tag.decompose()
        heading = ""
        seen = set()
        ix = 0
        for el in soup.select("h1,h2,h3,h4,p,li,tr"):
            if el.find_parent("tr") and el.name != "tr":
                continue
            text = _tidy(el.get_text(" ", strip=True))
            if not text or (el.name not in {"tr"} and text in seen):
                continue
            seen.add(text)
            ix += 1
            if el.name.startswith("h"):
                heading = text
            blocks.append(
                Block(
                    text,
                    heading=heading,
                    locator=f"html {el.name} {ix}",
                    kind="table_row" if el.name == "tr" else "paragraph",
                )
            )
    else:
        text = raw.decode("utf-8-sig")
        heading = ""
        for i, part in enumerate(re.split(r"\n\s*\n", text), 1):
            part = part.strip()
            if not part:
                continue
            if part.startswith("#"):
                heading = _tidy(part.splitlines()[0].lstrip("#"))
            blocks.append(Block(part, heading=heading, locator=f"block {i}"))

    # Fail explicitly when extraction yields nothing so an empty file cannot appear
    # successfully parsed.
    if not blocks:
        raise ValueError("No extractable text")
    return blocks
