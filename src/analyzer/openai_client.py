"""OpenAI-based paper analyzer."""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from src.analyzer.prompts import (
    ANALYZE_PAPER,
    ANALYZE_PAPER_SYSTEM,
    GENERATE_RELATED_WORK,
    GENERATE_RELATED_WORK_SYSTEM,
    RANK_PAPERS,
    RANK_PAPERS_SYSTEM,
    SUGGEST_KEYWORDS,
    SUGGEST_KEYWORDS_SYSTEM,
    LANG_EN,
    LANG_JA,
)
from src.fetcher.models import Paper

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000  # Truncate full text to fit context window


class PaperAnalyzer:
    """Analyze papers using OpenAI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        language: str = "ja",
    ) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.lang_instruction = LANG_JA if language == "ja" else LANG_EN

    def analyze(self, paper: Paper) -> Paper:
        """Analyze a paper and fill in analysis fields."""
        # Build text section: prefer full text, fall back to abstract
        if paper.full_text:
            text = paper.full_text[:MAX_TEXT_CHARS]
            text_section = f"## Full Text\n{text}"
        else:
            text_section = f"## Abstract\n{paper.abstract}"

        prompt = ANALYZE_PAPER.format(
            title=paper.title,
            authors=", ".join(paper.authors[:10]),
            year=paper.year,
            text_section=text_section,
        )
        system = ANALYZE_PAPER_SYSTEM.format(lang_instruction=self.lang_instruction)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        text_resp = response.choices[0].message.content or ""
        data = self._parse_json(text_resp)

        if data:
            paper.summary = data.get("summary", "")
            paper.research_question = data.get("research_question", "")
            paper.method_keywords = data.get("method_keywords", [])
            paper.key_contribution = data.get("key_contribution", "")
            paper.limitations = data.get("limitations", [])
            paper.related_work_summary = data.get("related_work_summary", "")

        return paper

    def generate_related_work(
        self, my_title: str, my_abstract: str, papers: list[Paper]
    ) -> str:
        """Generate a Related Work section based on collected papers."""
        # Build papers section from abstracts
        papers_lines = []
        for i, p in enumerate(papers, 1):
            abstract = p.abstract[:500] if p.abstract else "(no abstract)"
            papers_lines.append(
                f"[{i}] {p.title} ({', '.join(p.authors[:3])}, {p.year})\n"
                f"    Abstract: {abstract}\n"
            )

        prompt = GENERATE_RELATED_WORK.format(
            my_title=my_title,
            my_abstract=my_abstract,
            papers_section="\n".join(papers_lines),
        )
        system = GENERATE_RELATED_WORK_SYSTEM.format(
            lang_instruction=self.lang_instruction
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )

        return response.choices[0].message.content or ""

    def suggest_keywords(self, my_title: str, my_abstract: str) -> list[dict]:
        """Suggest search keywords for finding related work."""
        prompt = SUGGEST_KEYWORDS.format(my_title=my_title, my_abstract=my_abstract)
        system = SUGGEST_KEYWORDS_SYSTEM.format(lang_instruction=self.lang_instruction)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        data = self._parse_json(response.choices[0].message.content or "")
        return data.get("keywords", [])

    def rank_papers(
        self, my_title: str, my_abstract: str, papers: list[Paper]
    ) -> list[dict]:
        """Rank papers by relevance to user's research."""
        papers_lines = []
        for i, p in enumerate(papers, 1):
            abstract = p.abstract[:300] if p.abstract else "(no abstract)"
            papers_lines.append(
                f"[{i}] {p.title} ({p.year})\n    Abstract: {abstract}\n"
            )

        prompt = RANK_PAPERS.format(
            my_title=my_title,
            my_abstract=my_abstract,
            papers_section="\n".join(papers_lines),
        )
        system = RANK_PAPERS_SYSTEM.format(lang_instruction=self.lang_instruction)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        data = self._parse_json(response.choices[0].message.content or "")
        return data.get("ranked", [])

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try extracting from markdown code block
            if "```" in text:
                start = text.find("```")
                end = text.rfind("```")
                inner = text[start:end] if end > start else text[start:]
                nl = inner.find("\n")
                if nl >= 0:
                    text = inner[nl + 1:]
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                try:
                    return json.loads(text[brace_start : brace_end + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning("Failed to parse JSON: %s", text[:200])
            return {}
