"""arXiv API client."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import httpx

from src.fetcher.models import Paper

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _parse_entry(entry: ET.Element) -> Paper:
    """Parse a single Atom entry into a Paper."""
    raw_id = entry.findtext(f"{ATOM_NS}id", "")
    arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", raw_id).strip()

    title = (entry.findtext(f"{ATOM_NS}title", "") or "").replace("\n", " ").strip()
    abstract = (entry.findtext(f"{ATOM_NS}summary", "") or "").strip()

    authors = []
    for author_el in entry.findall(f"{ATOM_NS}author"):
        name = author_el.findtext(f"{ATOM_NS}name", "")
        if name:
            authors.append(name)

    published = entry.findtext(f"{ATOM_NS}published", "")
    year = int(published[:4]) if published else 0

    pdf_url = ""
    abs_url = ""
    for link in entry.findall(f"{ATOM_NS}link"):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
        elif link.get("rel") == "alternate":
            abs_url = link.get("href", "")

    categories = [
        cat.get("term", "")
        for cat in entry.findall(f"{ARXIV_NS}primary_category")
    ]
    venue = categories[0] if categories else ""

    return Paper(
        id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        year=year,
        venue=venue,
        url=abs_url or f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
        pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
    )


class ArxivClient:
    """Async arXiv API client."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._last_request = 0.0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        wait = 3.0 - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = asyncio.get_event_loop().time()

    async def search(self, query: str, limit: int = 20) -> list[Paper]:
        """Search arXiv by query string."""
        await self._throttle()
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        resp = await self._client.get(ARXIV_API, params=params)
        resp.raise_for_status()
        return self._parse_response(resp.text)

    async def search_recent(
        self, categories: list[str], days: int = 7, limit: int = 50
    ) -> list[Paper]:
        """Fetch recent papers from given categories."""
        await self._throttle()
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        date_range = f"[{start:%Y%m%d}0000+TO+{now:%Y%m%d}2359]"

        cat_query = "+OR+".join(f"cat:{c}" for c in categories)
        query = f"({cat_query})+AND+submittedDate:{date_range}"

        params = {
            "search_query": query,
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = await self._client.get(ARXIV_API, params=params)
        resp.raise_for_status()
        return self._parse_response(resp.text)

    async def get_paper(self, arxiv_id: str) -> Paper | None:
        """Fetch a single paper by arXiv ID."""
        arxiv_id = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", arxiv_id).strip()
        arxiv_id = arxiv_id.rstrip("/")

        await self._throttle()
        params = {"id_list": arxiv_id, "max_results": 1}
        resp = await self._client.get(ARXIV_API, params=params)
        resp.raise_for_status()
        papers = self._parse_response(resp.text)
        return papers[0] if papers else None

    def _parse_response(self, xml_text: str) -> list[Paper]:
        root = ET.fromstring(xml_text)
        papers = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            title = entry.findtext(f"{ATOM_NS}title", "")
            if title and "Error" not in title:
                papers.append(_parse_entry(entry))
        return papers

    async def close(self) -> None:
        await self._client.aclose()
