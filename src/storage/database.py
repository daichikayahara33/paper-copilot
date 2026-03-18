"""SQLite storage for papers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.fetcher.models import Paper

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 0,
    venue TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    arxiv_id TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    references_json TEXT NOT NULL DEFAULT '[]',
    cited_by_count INTEGER NOT NULL DEFAULT 0,
    full_text TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    research_question TEXT NOT NULL DEFAULT '',
    method_keywords TEXT NOT NULL DEFAULT '[]',
    key_contribution TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '[]',
    related_work_summary TEXT NOT NULL DEFAULT '',
    analyzed INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """SQLite persistence for papers."""

    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def save_paper(self, paper: Paper, analyzed: bool = False) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO papers
            (id, title, authors, abstract, year, venue, url, arxiv_id, doi,
             pdf_url, references_json, cited_by_count, full_text, topic, summary,
             research_question, method_keywords, key_contribution, limitations,
             related_work_summary, analyzed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper.id,
                paper.title,
                json.dumps(paper.authors, ensure_ascii=False),
                paper.abstract,
                paper.year,
                paper.venue,
                paper.url,
                paper.arxiv_id,
                paper.doi,
                paper.pdf_url,
                json.dumps(paper.references, ensure_ascii=False),
                paper.cited_by_count,
                paper.full_text,
                paper.topic,
                paper.summary,
                paper.research_question,
                json.dumps(paper.method_keywords, ensure_ascii=False),
                paper.key_contribution,
                json.dumps(paper.limitations, ensure_ascii=False),
                paper.related_work_summary,
                1 if analyzed else 0,
            ),
        )
        self.conn.commit()

    def get_paper(self, paper_id: str) -> Paper | None:
        row = self.conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_paper(row)

    def get_all_papers(self) -> list[Paper]:
        rows = self.conn.execute("SELECT * FROM papers").fetchall()
        return [self._row_to_paper(r) for r in rows]

    def get_unanalyzed(self) -> list[Paper]:
        rows = self.conn.execute(
            "SELECT * FROM papers WHERE analyzed = 0"
        ).fetchall()
        return [self._row_to_paper(r) for r in rows]

    def get_topics(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT topic FROM papers WHERE topic != '' ORDER BY topic"
        ).fetchall()
        return [r["topic"] for r in rows]

    def get_papers_by_topic(self, topic: str) -> list[Paper]:
        rows = self.conn.execute(
            "SELECT * FROM papers WHERE topic = ?", (topic,)
        ).fetchall()
        return [self._row_to_paper(r) for r in rows]

    def _row_to_paper(self, row: sqlite3.Row) -> Paper:
        return Paper(
            id=row["id"],
            title=row["title"],
            authors=json.loads(row["authors"]),
            abstract=row["abstract"],
            year=row["year"],
            venue=row["venue"],
            url=row["url"],
            arxiv_id=row["arxiv_id"],
            doi=row["doi"],
            pdf_url=row["pdf_url"],
            references=json.loads(row["references_json"]),
            cited_by_count=row["cited_by_count"],
            full_text=row["full_text"],
            topic=row["topic"],
            summary=row["summary"],
            research_question=row["research_question"],
            method_keywords=json.loads(row["method_keywords"]),
            key_contribution=row["key_contribution"],
            limitations=json.loads(row["limitations"]),
            related_work_summary=row["related_work_summary"],
        )

    def close(self) -> None:
        self.conn.close()
