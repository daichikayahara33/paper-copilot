"""OpenAlex API client for citation graph data."""

from __future__ import annotations

import asyncio

import httpx

from src.fetcher.models import Paper

OPENALEX_API = "https://api.openalex.org"


def _parse_work(work: dict) -> Paper:
    """Parse an OpenAlex work object into a Paper."""
    oa_id = work.get("id", "").replace("https://openalex.org/", "")

    title = work.get("title", "") or ""

    authorships = work.get("authorships", [])
    authors = []
    for a in authorships:
        raw = a.get("raw_author_name") or (a.get("author", {}) or {}).get("display_name", "")
        if raw:
            authors.append(raw)

    abstract = ""
    inv_abstract = work.get("abstract_inverted_index")
    if inv_abstract:
        # Reconstruct abstract from inverted index
        word_positions: list[tuple[int, str]] = []
        for word, positions in inv_abstract.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        abstract = " ".join(w for _, w in word_positions)

    year = work.get("publication_year", 0) or 0

    venue = ""
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name", "")

    doi = (work.get("doi") or "").replace("https://doi.org/", "")

    # Extract arXiv ID from IDs
    ids = work.get("ids", {})
    arxiv_id = ""
    openalex_arxiv = ids.get("openalex", "")
    if "arxiv.org" in str(ids.get("arxiv", "")):
        arxiv_id = str(ids["arxiv"]).replace("https://arxiv.org/abs/", "")

    # PDF URL
    pdf_url = ""
    oa = work.get("open_access", {}) or {}
    pdf_url = oa.get("oa_url", "") or ""
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    url = work.get("id", "") or ""
    if arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"

    # References (OpenAlex IDs of cited works)
    referenced_works = work.get("referenced_works", [])
    references = [
        ref.replace("https://openalex.org/", "") for ref in referenced_works
    ]

    cited_by_count = work.get("cited_by_count", 0) or 0

    return Paper(
        id=oa_id,
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


class OpenAlexClient:
    """Async OpenAlex API client. Free, no API key required."""

    def __init__(self, email: str = "") -> None:
        headers = {}
        if email:
            # Polite pool: faster rate limits with email
            headers["User-Agent"] = f"paper-copilot/0.1 (mailto:{email})"
        self._client = httpx.AsyncClient(
            base_url=OPENALEX_API, timeout=30.0, headers=headers
        )
        self._last_request = 0.0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        wait = 0.15 - (now - self._last_request)  # ~7 req/sec
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = asyncio.get_event_loop().time()

    async def search(self, query: str, limit: int = 10) -> list[Paper]:
        """Search papers by title/keyword."""
        await self._throttle()
        resp = await self._client.get(
            "/works",
            params={
                "search": query,
                "per_page": limit,
                "sort": "relevance_score:desc",
            },
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [_parse_work(w) for w in results]

    async def get_paper_by_arxiv(
        self, arxiv_id: str, title: str = ""
    ) -> Paper | None:
        """Fetch a paper by arXiv ID. Tries DOI, then title search fallback."""
        clean_id = arxiv_id.split("v")[0]  # strip version

        # Try arXiv DOI format
        await self._throttle()
        resp = await self._client.get(
            f"/works/doi:10.48550/arXiv.{clean_id}"
        )
        if resp.status_code == 200:
            return _parse_work(resp.json())

        # Fallback: search by title, pick the best match by citation count
        if title:
            await self._throttle()
            resp = await self._client.get(
                "/works",
                params={
                    "search": title,
                    "per_page": 5,
                    "sort": "cited_by_count:desc",
                },
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                # Pick the result whose title best matches
                for r in results:
                    r_title = (r.get("title") or "").lower().strip()
                    if title.lower().strip() in r_title or r_title in title.lower().strip():
                        return _parse_work(r)
                # If no exact match, take the most-cited one
                if results and (results[0].get("cited_by_count", 0) or 0) > 10:
                    return _parse_work(results[0])

        return None

    async def get_paper_by_doi(self, doi: str) -> Paper | None:
        """Fetch a paper by DOI."""
        await self._throttle()
        resp = await self._client.get(f"/works/doi:{doi}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_work(resp.json())

    async def get_paper(self, openalex_id: str) -> Paper | None:
        """Fetch a paper by OpenAlex ID."""
        await self._throttle()
        oa_id = openalex_id if openalex_id.startswith("W") else openalex_id
        resp = await self._client.get(f"/works/{oa_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_work(resp.json())

    async def get_references(self, openalex_id: str, limit: int = 50) -> list[Paper]:
        """Get papers that this paper cites."""
        await self._throttle()
        resp = await self._client.get(
            "/works",
            params={
                "filter": f"cited_by:{openalex_id}",
                "per_page": min(limit, 50),
            },
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [_parse_work(w) for w in results]

    async def get_citations(self, openalex_id: str, limit: int = 50) -> list[Paper]:
        """Get papers that cite this paper."""
        await self._throttle()
        resp = await self._client.get(
            "/works",
            params={
                "filter": f"cites:{openalex_id}",
                "per_page": min(limit, 50),
                "sort": "cited_by_count:desc",
            },
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [_parse_work(w) for w in results]

    async def close(self) -> None:
        await self._client.aclose()
