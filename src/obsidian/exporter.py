"""Export papers to Obsidian vault with wiki-links for graph view."""

from __future__ import annotations

import re
from pathlib import Path

from src.fetcher.models import Paper


MAX_FILENAME_LEN = 50


def _sanitize(title: str) -> str:
    """Make a title safe for filenames, keeping it short for graph view."""
    name = re.sub(r'[<>:"/\\|?*]', "", title)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > MAX_FILENAME_LEN:
        # Cut at word boundary
        name = name[:MAX_FILENAME_LEN].rsplit(" ", 1)[0]
    return name


class ObsidianExporter:
    """Write papers as markdown files with [[wiki-links]] for Obsidian graph view."""

    def export(
        self,
        papers: list[Paper],
        vault_path: str,
        all_papers_by_id: dict[str, Paper] | None = None,
    ) -> int:
        """Export papers to vault. Returns number of files written.

        Papers with a topic go into vault/<topic>/.
        Papers without a topic go into vault/papers/.

        all_papers_by_id: lookup table to resolve reference IDs to Paper objects.
        If a reference ID is found in this dict, a [[wiki-link]] is created.
        """
        vault = Path(vault_path)

        lookup = all_papers_by_id or {}
        # Also index by current batch
        for p in papers:
            lookup[p.id] = p

        count = 0
        for paper in papers:
            if paper.topic:
                paper_dir = vault / _sanitize(paper.topic)
            else:
                paper_dir = vault / "papers"
            paper_dir.mkdir(parents=True, exist_ok=True)

            md = self._render_paper(paper, lookup)
            filepath = paper_dir / f"{_sanitize(paper.title)}.md"
            filepath.write_text(md, encoding="utf-8")
            count += 1

        # Write index
        index = self._render_index(papers, lookup)
        (vault / "Research Index.md").write_text(index, encoding="utf-8")
        count += 1

        return count

    def _render_paper(self, paper: Paper, lookup: dict[str, Paper]) -> str:
        lines: list[str] = []

        # YAML frontmatter
        lines.append("---")
        lines.append(f'title: "{paper.title}"')
        lines.append(f"year: {paper.year}")
        if paper.authors:
            a = ", ".join(paper.authors[:5])
            if len(paper.authors) > 5:
                a += " et al."
            lines.append(f'authors: "{a}"')
        if paper.venue:
            lines.append(f'venue: "{paper.venue}"')
        if paper.arxiv_id:
            lines.append(f'arxiv_id: "{paper.arxiv_id}"')
        if paper.doi:
            lines.append(f'doi: "{paper.doi}"')
        if paper.cited_by_count:
            lines.append(f"cited_by_count: {paper.cited_by_count}")
        if paper.method_keywords:
            kw = "[" + ", ".join(f'"{k}"' for k in paper.method_keywords) + "]"
            lines.append(f"keywords: {kw}")
        tags = [k.replace(" ", "_") for k in paper.method_keywords[:5]]
        if tags:
            lines.append(f"tags: [{', '.join(tags)}]")
        lines.append("---")
        lines.append("")

        # Title
        lines.append(f"# {paper.title}")
        lines.append("")

        # Metadata
        if paper.authors:
            lines.append(f"**Authors:** {', '.join(paper.authors)}")
        lines.append(f"**Year:** {paper.year}")
        if paper.venue:
            lines.append(f"**Venue:** {paper.venue}")
        if paper.arxiv_id:
            lines.append(
                f"**arXiv:** [{paper.arxiv_id}](https://arxiv.org/abs/{paper.arxiv_id})"
            )
        if paper.doi:
            lines.append(f"**DOI:** [{paper.doi}](https://doi.org/{paper.doi})")
        if paper.cited_by_count:
            lines.append(f"**Cited by:** {paper.cited_by_count}")
        lines.append("")

        # Abstract
        if paper.abstract:
            lines.append("## Abstract")
            lines.append(paper.abstract)
            lines.append("")

        # Analysis sections
        if paper.summary:
            lines.append("## Summary")
            lines.append(paper.summary)
            lines.append("")

        if paper.research_question:
            lines.append("## Research Question")
            lines.append(paper.research_question)
            lines.append("")

        if paper.key_contribution:
            lines.append("## Key Contribution")
            lines.append(paper.key_contribution)
            lines.append("")

        if paper.method_keywords:
            lines.append("## Keywords")
            lines.append(" ".join(f"`{kw}`" for kw in paper.method_keywords))
            lines.append("")

        if paper.related_work_summary:
            lines.append("## Related Work")
            lines.append(paper.related_work_summary)
            lines.append("")

        if paper.limitations:
            lines.append("## Limitations")
            for lim in paper.limitations:
                lines.append(f"- {lim}")
            lines.append("")

        # References (wiki-links) — the key part for Obsidian graph view
        ref_papers = [lookup[ref_id] for ref_id in paper.references if ref_id in lookup]
        if ref_papers:
            lines.append("## References (cited by this paper)")
            for ref in ref_papers:
                fname = _sanitize(ref.title)
                lines.append(f"- [[{fname}]] ({ref.year})")
            lines.append("")

        return "\n".join(lines)

    def _render_index(self, papers: list[Paper], lookup: dict[str, Paper]) -> str:
        lines = ["# Research Index", ""]
        lines.append(f"**Total papers:** {len(papers)}")
        lines.append("")

        # Group by topic
        by_topic: dict[str, list[Paper]] = {}
        for p in papers:
            topic = p.topic or "Uncategorized"
            by_topic.setdefault(topic, []).append(p)

        for topic in sorted(by_topic.keys()):
            lines.append(f"## {topic}")
            lines.append("")
            for p in sorted(by_topic[topic], key=lambda x: x.year, reverse=True):
                cited = f" (cited: {p.cited_by_count})" if p.cited_by_count else ""
                lines.append(f"- {p.title} ({p.year}){cited}")
            lines.append("")

        return "\n".join(lines)
