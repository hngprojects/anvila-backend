import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from app.services.file_extractor import MAX_CHARS, extract_text


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


async def test_extracts_plain_text_file() -> None:
    file = _upload("notes.txt", b"hello world\nsecond line")
    assert await extract_text(file) == "hello world\nsecond line"


async def test_extracts_markdown_file() -> None:
    file = _upload("readme.md", b"# Heading\n\nbody")
    assert await extract_text(file) == "# Heading\n\nbody"


async def test_decodes_malformed_utf8_without_crashing() -> None:
    file = _upload("broken.txt", b"good\xffbad")
    result = await extract_text(file)
    assert "good" in result and "bad" in result


async def test_extracts_pdf_via_pdfplumber(mocker) -> None:
    page_a = SimpleNamespace(extract_text=lambda: "page one text")
    page_b = SimpleNamespace(extract_text=lambda: "page two text")
    pdf = MagicMock()
    pdf.pages = [page_a, page_b]
    pdf.__enter__.return_value = pdf
    pdf.__exit__.return_value = False
    mocker.patch("app.services.file_extractor.pdfplumber.open", return_value=pdf)

    file = _upload("doc.pdf", b"%PDF-fake-bytes")
    result = await extract_text(file)
    assert result == "page one text\npage two text"


async def test_extracts_pdf_handles_image_only_pages(mocker) -> None:
    page = SimpleNamespace(extract_text=lambda: None)
    pdf = MagicMock()
    pdf.pages = [page]
    pdf.__enter__.return_value = pdf
    pdf.__exit__.return_value = False
    mocker.patch("app.services.file_extractor.pdfplumber.open", return_value=pdf)

    file = _upload("image-only.pdf", b"%PDF-fake")
    assert await extract_text(file) == ""


async def test_extracts_docx_via_docx2txt(mocker) -> None:
    mocker.patch(
        "app.services.file_extractor.docx2txt.process",
        return_value="docx body text",
    )
    file = _upload("doc.docx", b"PK-fake-bytes")
    assert await extract_text(file) == "docx body text"


async def test_unsupported_extension_raises_value_error() -> None:
    file = _upload("logo.png", b"\x89PNG")
    with pytest.raises(ValueError, match="Unsupported file type"):
        await extract_text(file)


async def test_truncates_long_input_to_max_chars() -> None:
    body = ("a" * (MAX_CHARS + 1000)).encode("utf-8")
    file = _upload("big.txt", body)
    result = await extract_text(file)
    assert len(result) == MAX_CHARS
