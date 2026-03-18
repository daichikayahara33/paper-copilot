"""Data models for papers and relations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    """A research paper with metadata and analysis."""

    id: str  # OpenAlex ID (e.g. "W2741809807") or arXiv ID
    title: str
    authors: list[str]
    abstract: str
    year: int
    venue: str = ""
    url: str = ""
    arxiv_id: str = ""
    doi: str = ""
    pdf_url: str = ""

    # Citation graph (OpenAlex IDs)
    references: list[str] = field(default_factory=list)  # papers this cites
    cited_by_count: int = 0

    # Full text (from pymupdf4llm)
    full_text: str = ""

    # Topic (research keyword used to find this paper)
    topic: str = ""

    # Analysis (from OpenAI)
    summary: str = ""
    research_question: str = ""
    method_keywords: list[str] = field(default_factory=list)
    key_contribution: str = ""
    limitations: list[str] = field(default_factory=list)
    related_work_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "url": self.url,
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "pdf_url": self.pdf_url,
            "references": self.references,
            "cited_by_count": self.cited_by_count,
            "full_text": self.full_text,
            "summary": self.summary,
            "research_question": self.research_question,
            "method_keywords": self.method_keywords,
            "key_contribution": self.key_contribution,
            "limitations": self.limitations,
            "related_work_summary": self.related_work_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Paper:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
