"""PDF full-text extraction using pymupdf4llm."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx


async def download_pdf(url: str) -> Path:
    """Download a PDF to a temporary file."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

        suffix = ".pdf"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(resp.content)
        tmp.close()
        return Path(tmp.name)


def extract_text(pdf_path: str | Path) -> str:
    """Extract markdown text from a PDF using pymupdf4llm."""
    import pymupdf4llm

    return pymupdf4llm.to_markdown(str(pdf_path))


async def extract_from_url(url: str) -> str:
    """Download a PDF and extract its text."""
    if not url:
        return ""
    try:
        pdf_path = await download_pdf(url)
        text = extract_text(pdf_path)
        pdf_path.unlink(missing_ok=True)
        return text
    except Exception:
        return ""
