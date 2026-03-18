"""Semantic Scholar API client for citation graph data."""

from __future__ import annotations

import asyncio

import httpx

from src.fetcher.models import Paper

S2_API = "https://api.semanticscholar.org/graph/v1"
FIELDS = "paperId,title,authors,abstract,year,venue,url,externalIds,citationCount,referenceCount,references,citations"
FIELDS_LIGHT = "paperId,title,authors,abstract,year,venue,url,externalIds,citationCount"


def _parse_paper(data: dict) -> Paper:
    """Parse an S2 paper object into a Paper."""
    paper_id = data.get("paperId", "")
    title = data.get("title", "") or ""
    abstract = data.get("abstract", "") or ""
    year = data.get("year", 0) or 0
    venue = data.get("venue", "") or ""
    url = data.get("url", "") or ""
    cited_by_count = data.get("citationCount", 0) or 0

    authors = []
    for a in data.get("authors", []) or []:
        name = a.get("name", "")
        if name:
            authors.append(name)

    ext_ids = data.get("externalIds", {}) or {}
    arxiv_id = ext_ids.get("ArXiv", "") or ""
    doi = ext_ids.get("DOI", "") or ""

    pdf_url = ""
    if arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        if not url:
            url = f"https://arxiv.org/abs/{arxiv_id}"

    # References: list of S2 paper IDs this paper cites
    references: list[str] = []
    for ref in data.get("references", []) or []:
        if ref and ref.get("paperId"):
            references.append(ref["paperId"])

    return Paper(
        id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        year=year,
        venue=venue,
        url=url,
        arxiv_id=arxiv_id,
        doi=doi,
        pdf_url=pdf_url,
        references=references,
        cited_by_count=cited_by_count,
    )


class SemanticScholarClient:
    """Async Semantic Scholar API client."""

    def __init__(self, api_key: str = "") -> None:
        headers = {}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=S2_API, timeout=30.0, headers=headers
        )
        self._has_key = bool(api_key)
        self._last_request = 0.0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        # With API key: 10 req/sec. Without: 1 req/sec
        interval = 0.12 if self._has_key else 1.1
        wait = interval - (now - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = asyncio.get_event_loop().time()

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Fetch a paper by S2 ID, arXiv ID, or DOI.

        Accepts: S2 ID, "arXiv:XXXX", "DOI:XXXX", or raw arXiv ID.
        """
        # Normalize ID format
        if "/" in paper_id or paper_id.startswith("10."):
            paper_id = f"DOI:{paper_id}"
        elif "." in paper_id and not paper_id.startswith(("arXiv:", "DOI:", "PMID:")):
            paper_id = f"arXiv:{paper_id}"

        await self._throttle()
        resp = await self._client.get(
            f"/paper/{paper_id}", params={"fields": FIELDS}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_paper(resp.json())

    async def search(self, query: str, limit: int = 10) -> list[Paper]:
        """Search for papers."""
        await self._throttle()
        resp = await self._client.get(
            "/paper/search",
            params={"query": query, "limit": limit, "fields": FIELDS_LIGHT},
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])
        return [_parse_paper(r) for r in results]

    async def get_references(self, paper_id: str, limit: int = 50) -> list[Paper]:
        """Get papers that this paper cites (references)."""
        await self._throttle()
        resp = await self._client.get(
            f"/paper/{paper_id}/references",
            params={"fields": FIELDS_LIGHT, "limit": limit},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        papers = []
        for item in resp.json().get("data", []):
            cited = item.get("citedPaper")
            if cited and cited.get("paperId") and cited.get("title"):
                papers.append(_parse_paper(cited))
        return papers

    async def get_citations(self, paper_id: str, limit: int = 50) -> list[Paper]:
        """Get papers that cite this paper."""
        await self._throttle()
        resp = await self._client.get(
            f"/paper/{paper_id}/citations",
            params={"fields": FIELDS_LIGHT, "limit": limit},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        papers = []
        for item in resp.json().get("data", []):
            citing = item.get("citingPaper")
            if citing and citing.get("paperId") and citing.get("title"):
                papers.append(_parse_paper(citing))
        return papers

    async def close(self) -> None:
        await self._client.aclose()
