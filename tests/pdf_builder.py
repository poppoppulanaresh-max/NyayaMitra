"""Synthetic PDFs for tests. These are fixtures, never verified law."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path


def text_pdf_bytes(text: str) -> bytes:
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")[:200]
    )
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1", errors="replace")
    objects = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    add(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    add(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    add(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
    )
    add(b"4 0 obj << /Length %d >> stream\n" % len(stream) + stream + b"endstream\nendobj\n")
    add(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    body = b""
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        body += obj
        pos += len(obj)
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets[1:]:
        xref += b"%010d 00000 n \n" % off
    trailer = b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        len(header) + len(body),
    )
    return header + body + xref + trailer


def write_text_pdf(path: Path, text: str) -> Path:
    path.write_bytes(text_pdf_bytes(text))
    return path


def blank_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def encrypted_pdf_bytes(text: str = "secret legal text for tests") -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(text_pdf_bytes(text)))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("test-password")
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()
