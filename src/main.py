"""Paper Copilot — CLI entry point."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.analyzer.openai_client import PaperAnalyzer
from src.extractor.pdf import extract_from_url
from src.fetcher.arxiv import ArxivClient
from src.fetcher.models import Paper
from src.fetcher.semantic_scholar import SemanticScholarClient
from src.obsidian.exporter import ObsidianExporter
from src.obsidian.graph_html import export_graph_html
from src.storage.database import Database

console = Console()

DEFAULT_CONFIG = {
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "semantic_scholar_api_key": "",
    "arxiv_categories": ["cs.AI"],
    "arxiv_fetch_days": 7,
    "arxiv_max_results": 50,
    "database_path": "./data/papers.db",
    "obsidian_vault_path": "./vault",
    "language": "ja",
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        config.update(loaded)
    else:
        console.print("[yellow]config.yaml not found. Copy config.yaml.example and edit it.[/yellow]")
    return config


class App:
    def __init__(self) -> None:
        self.config = load_config()
        self.db = Database(self.config["database_path"])
        self.arxiv = ArxivClient()
        self.s2 = SemanticScholarClient(
            api_key=self.config.get("semantic_scholar_api_key", "")
        )
        self.exporter = ObsidianExporter()

        api_key = self.config.get("openai_api_key", "")
        if api_key:
            self.analyzer = PaperAnalyzer(
                api_key=api_key,
                model=self.config.get("openai_model", "gpt-4o-mini"),
                language=self.config.get("language", "ja"),
            )
        else:
            self.analyzer = None

    # ── Collect by keyword ──

    async def cmd_collect(self, keyword: str, limit: int = 10, deep: bool = False) -> None:
        """Search S2 by keyword and collect papers.

        deep=False (default): lightweight — abstract only, no PDF/analysis. Fast.
        deep=True: full processing — PDF extraction + OpenAI analysis.
        """
        mode = "deep" if deep else "light"
        console.print(f"[bold]Collecting papers for:[/bold] {keyword} (mode: {mode}, limit: {limit})")

        # Step 1: Search Semantic Scholar
        with console.status("Searching Semantic Scholar..."):
            papers = await self.s2.search(keyword, limit=limit)

        if not papers:
            console.print("[yellow]No results found.[/yellow]")
            return

        console.print(f"Found {len(papers)} papers. Processing...")

        added = 0
        for i, paper in enumerate(papers, 1):
            # Skip if already in DB
            existing = self.db.get_paper(paper.id)
            if existing:
                console.print(f"  ({i}/{len(papers)}) [dim]Skip (exists):[/dim] {paper.title[:50]}")
                continue

            console.print(f"  ({i}/{len(papers)}) {paper.title[:50]}...")

            # Fetch full details (including references) from S2 with retry
            full_paper = None
            for attempt in range(3):
                await asyncio.sleep(1.5)
                try:
                    full_paper = await self.s2.get_paper(paper.id)
                    break
                except Exception:
                    if attempt < 2:
                        console.print(f"    [dim]Retry ({attempt+1}/3)...[/dim]")
                        await asyncio.sleep(3)
            if full_paper:
                full_paper.topic = keyword
                paper = full_paper
            else:
                paper.topic = keyword

            if deep:
                # Extract full text from PDF
                if paper.pdf_url:
                    with console.status("    Extracting PDF..."):
                        paper.full_text = await extract_from_url(paper.pdf_url)

                # Analyze with OpenAI
                analyzed = False
                if self.analyzer:
                    try:
                        with console.status("    Analyzing..."):
                            paper = self.analyzer.analyze(paper)
                            analyzed = True
                    except Exception as e:
                        console.print(f"    [red]Analysis failed: {e}[/red]")

                self.db.save_paper(paper, analyzed=analyzed)
            else:
                # Lightweight: just save with abstract
                self.db.save_paper(paper, analyzed=False)

            added += 1

            # Also save referenced papers (lightweight) so wiki-links resolve
            for ref_id in paper.references:
                if not self.db.get_paper(ref_id):
                    ref_paper = None
                    for other in papers:
                        if other.id == ref_id:
                            ref_paper = other
                            break
                    if ref_paper:
                        ref_paper.topic = keyword
                        self.db.save_paper(ref_paper, analyzed=False)

        console.print(f"[green]Added {added} papers for topic '{keyword}'.[/green]")

        # Auto-export
        self.cmd_export()

    # ── Copilot: survey ──

    async def cmd_survey(self, my_title: str, my_abstract: str, papers_per_keyword: int = 10) -> None:
        """Copilot: suggest keywords → collect papers → rank by relevance."""
        if not self.analyzer:
            console.print("[red]Set openai_api_key in config.yaml first.[/red]")
            return

        # Step 1: Suggest keywords
        console.print("[bold]Step 1:[/bold] Suggesting search keywords...")
        with console.status("Asking LLM for keywords..."):
            suggestions = self.analyzer.suggest_keywords(my_title, my_abstract)

        if not suggestions:
            console.print("[red]Failed to get keyword suggestions.[/red]")
            return

        table = Table(title="Suggested Keywords")
        table.add_column("#", width=3)
        table.add_column("Keyword", max_width=40)
        table.add_column("Reason", max_width=50)

        for i, s in enumerate(suggestions, 1):
            table.add_row(str(i), s.get("keyword", ""), s.get("reason", ""))
        console.print(table)

        # Ask which keywords to use
        console.print("\n[dim]Enter numbers to use (e.g. '1,3,5'), 'all', or 'q' to cancel:[/dim]")
        choice = Prompt.ask("[bold blue]keywords>[/bold blue]")

        if choice.strip().lower() == "q":
            return

        if choice.strip().lower() == "all":
            selected = suggestions
        else:
            indices = []
            for part in choice.split(","):
                try:
                    idx = int(part.strip()) - 1
                    if 0 <= idx < len(suggestions):
                        indices.append(idx)
                except ValueError:
                    pass
            selected = [suggestions[i] for i in indices]

        if not selected:
            console.print("[yellow]No keywords selected.[/yellow]")
            return

        # Step 2: Collect papers for each keyword
        console.print(f"\n[bold]Step 2:[/bold] Collecting papers for {len(selected)} keywords...")
        for s in selected:
            kw = s["keyword"]
            try:
                await self.cmd_collect(kw, limit=papers_per_keyword, deep=False)
            except Exception as e:
                console.print(f"  [red]Failed for '{kw}': {e}[/red]")
                continue

        # Step 3: Rank by relevance
        all_papers = [p for p in self.db.get_all_papers() if p.abstract]
        if not all_papers:
            console.print("[yellow]No papers collected.[/yellow]")
            return

        console.print(f"\n[bold]Step 3:[/bold] Ranking {len(all_papers)} papers by relevance...")
        with console.status("Ranking with LLM..."):
            ranked = self.analyzer.rank_papers(my_title, my_abstract, all_papers)

        if ranked:
            table = Table(title="Papers Ranked by Relevance")
            table.add_column("Score", width=5)
            table.add_column("Title", max_width=55)
            table.add_column("Year", width=5)
            table.add_column("Reason", max_width=40)

            for r in ranked:
                idx = r.get("index", 0) - 1
                if 0 <= idx < len(all_papers):
                    p = all_papers[idx]
                    table.add_row(
                        str(r.get("score", "?")),
                        p.title[:55],
                        str(p.year),
                        r.get("reason", "")[:40],
                    )
            console.print(table)

        console.print("\n[dim]Run 'related-work <title> | <abstract>' to generate Related Work section.[/dim]")

    # ── Related Work generation ──

    def cmd_related_work(self, my_title: str, my_abstract: str, topic: str = "") -> None:
        """Generate a Related Work section from collected papers."""
        if not self.analyzer:
            console.print("[red]Set openai_api_key in config.yaml first.[/red]")
            return

        # Get papers: filter by topic if given, otherwise use all
        if topic:
            papers = self.db.get_papers_by_topic(topic)
        else:
            papers = self.db.get_all_papers()

        # Only use papers that have an abstract
        papers = [p for p in papers if p.abstract]

        if not papers:
            console.print("[yellow]No papers with abstracts found. Run 'collect' first.[/yellow]")
            return

        console.print(f"Generating Related Work from {len(papers)} papers...")

        with console.status("Generating with OpenAI..."):
            text = self.analyzer.generate_related_work(my_title, my_abstract, papers)

        console.print()
        console.print(Panel(text, title="Generated Related Work", border_style="green"))

        # Save to file
        vault_path = self.config.get("obsidian_vault_path", "./vault")
        out_dir = Path(vault_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "Related Work Draft.md"
        out_file.write_text(
            f"# Related Work\n\n{text}\n",
            encoding="utf-8",
        )
        console.print(f"\n[dim]Saved to {out_file}[/dim]")

    # ── Add paper ──

    async def cmd_add(self, paper_id: str) -> None:
        """Add a paper by arXiv ID. Fetches metadata, full text, citations, and analyzes."""
        # Step 1: Fetch from Semantic Scholar (includes references)
        with console.status("Fetching from Semantic Scholar..."):
            paper = await self.s2.get_paper(paper_id)

        if not paper:
            # Fallback to arXiv
            with console.status("Falling back to arXiv..."):
                paper = await self.arxiv.get_paper(paper_id)
            if not paper:
                console.print(f"[red]Paper not found: {paper_id}[/red]")
                return

        # Check if already in DB
        existing = self.db.get_paper(paper.id)
        if existing:
            console.print(f"[yellow]Already in database: {existing.title}[/yellow]")
            return

        console.print(f"[green]Found:[/green] {paper.title} ({paper.year})")
        console.print(
            f"  References: {len(paper.references)}, "
            f"Cited by: {paper.cited_by_count}"
        )

        # Step 2: Extract full text from PDF
        if paper.pdf_url:
            with console.status("Extracting full text from PDF..."):
                paper.full_text = await extract_from_url(paper.pdf_url)
            if paper.full_text:
                console.print(f"  Full text: {len(paper.full_text):,} chars")
            else:
                console.print("  [dim]PDF extraction failed, using abstract only[/dim]")

        # Step 3: Analyze with OpenAI
        analyzed = False
        if self.analyzer:
            with console.status("Analyzing with OpenAI..."):
                paper = self.analyzer.analyze(paper)
                analyzed = True
            console.print(f"  Keywords: {', '.join(paper.method_keywords[:5])}")

        # Save
        self.db.save_paper(paper, analyzed=analyzed)
        self._print_summary(paper)

    async def cmd_add_batch(self, file_path: str) -> None:
        """Add papers from a file (one arXiv ID per line)."""
        path = Path(file_path)
        if not path.exists():
            console.print(f"[red]File not found: {file_path}[/red]")
            return
        ids = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        console.print(f"Adding {len(ids)} papers...")
        for i, pid in enumerate(ids, 1):
            console.print(f"\n[bold]({i}/{len(ids)})[/bold] {pid}")
            await self.cmd_add(pid)

    # ── Search ──

    async def cmd_search(self, query: str) -> None:
        """Search for papers on Semantic Scholar."""
        with console.status("Searching..."):
            try:
                papers = await self.s2.search(query, limit=10)
            except Exception:
                papers = await self.arxiv.search(query, limit=10)
                console.print("[dim]S2 unavailable, fell back to arXiv[/dim]")

        if not papers:
            console.print("[yellow]No results.[/yellow]")
            return

        table = Table(title=f"Search: {query}")
        table.add_column("#", width=3)
        table.add_column("Title", max_width=55)
        table.add_column("Year", width=5)
        table.add_column("Cited", width=6)
        table.add_column("ID", max_width=18)

        for i, p in enumerate(papers, 1):
            display_id = p.arxiv_id or p.id[:16]
            table.add_row(str(i), p.title, str(p.year), str(p.cited_by_count), display_id)

        console.print(table)
        console.print("[dim]Add with: add <arXiv ID or S2 ID>[/dim]")

    async def cmd_fetch_recent(self) -> None:
        """Fetch recent papers from configured categories."""
        categories = self.config.get("arxiv_categories", ["cs.AI"])
        days = self.config.get("arxiv_fetch_days", 7)
        limit = self.config.get("arxiv_max_results", 50)

        with console.status(f"Fetching recent papers ({', '.join(categories)})..."):
            papers = await self.arxiv.search_recent(categories, days=days, limit=limit)

        if not papers:
            console.print("[yellow]No recent papers found.[/yellow]")
            return

        table = Table(title=f"Recent papers (last {days} days)")
        table.add_column("#", width=3)
        table.add_column("Title", max_width=55)
        table.add_column("Year", width=5)
        table.add_column("arXiv ID", max_width=18)

        for i, p in enumerate(papers[:20], 1):
            table.add_row(str(i), p.title, str(p.year), p.arxiv_id)

        console.print(table)
        console.print(f"[dim]Showing {min(20, len(papers))}/{len(papers)}. Add with: add <arXiv ID>[/dim]")

    # ── Expand references ──

    async def cmd_expand(self, paper_id: str, limit: int = 10) -> None:
        """Fetch referenced papers to build the citation graph."""
        paper = self._find_paper(paper_id)
        if not paper:
            console.print(f"[red]Paper not in database: {paper_id}. Add it first.[/red]")
            return

        console.print(f"Expanding: {paper.title[:50]}...")

        # Fetch references from S2
        with console.status("Fetching references from Semantic Scholar..."):
            ref_papers = await self.s2.get_references(paper.id, limit=limit)

        if not ref_papers:
            console.print("[yellow]No references found.[/yellow]")
            return

        added = 0
        for ref in ref_papers:
            if self.db.get_paper(ref.id):
                continue
            self.db.save_paper(ref, analyzed=False)
            console.print(f"  + {ref.title[:55]}... ({ref.year})")
            added += 1

        # Update the paper's reference list if it was empty
        if not paper.references and ref_papers:
            paper.references = [r.id for r in ref_papers]
            self.db.save_paper(paper, analyzed=bool(paper.summary))

        console.print(f"[green]Added {added} referenced papers.[/green]")
        if added > 0:
            console.print("[dim]Run 'analyze-all' to analyze, then 'export' to update Obsidian.[/dim]")

    # ── Analyze ──

    async def cmd_analyze_all(self) -> None:
        """Analyze all unanalyzed papers with OpenAI."""
        if not self.analyzer:
            console.print("[red]Set openai_api_key in config.yaml first.[/red]")
            return

        papers = self.db.get_unanalyzed()
        if not papers:
            console.print("[green]All papers are analyzed.[/green]")
            return

        console.print(f"Analyzing {len(papers)} papers...")
        for i, paper in enumerate(papers, 1):
            console.print(f"  ({i}/{len(papers)}) {paper.title[:50]}...")

            if not paper.full_text and paper.pdf_url:
                with console.status("    Extracting PDF..."):
                    paper.full_text = await extract_from_url(paper.pdf_url)

            try:
                with console.status("    Analyzing..."):
                    paper = self.analyzer.analyze(paper)
                self.db.save_paper(paper, analyzed=True)
            except Exception as e:
                console.print(f"    [red]Failed: {e}[/red]")

        console.print("[green]Done.[/green]")

    # ── Export ──

    def cmd_export(self) -> None:
        """Export all papers to Obsidian vault."""
        papers = self.db.get_all_papers()
        if not papers:
            console.print("[yellow]No papers in database. Add some first.[/yellow]")
            return

        lookup = {p.id: p for p in papers}
        vault_path = self.config.get("obsidian_vault_path", "./vault")
        count = self.exporter.export(papers, vault_path, lookup)
        console.print(f"[green]Exported {count} files to {vault_path}/[/green]")
        console.print("[dim]Open this folder as an Obsidian vault to see the graph view.[/dim]")

    # ── Graph HTML ──

    def cmd_graph(self, topic: str = "") -> None:
        """Export interactive graph as HTML. Optionally filter by topic."""
        if topic:
            papers = self.db.get_papers_by_topic(topic)
            if not papers:
                console.print(f"[yellow]No papers for topic '{topic}'.[/yellow]")
                return
        else:
            papers = self.db.get_all_papers()
            if not papers:
                console.print("[yellow]No papers in database.[/yellow]")
                return

        vault_path = self.config.get("obsidian_vault_path", "./vault")
        out = export_graph_html(papers, f"{vault_path}/graph.html")
        console.print(f"[green]Graph exported to {out} ({len(papers)} papers)[/green]")
        import webbrowser
        webbrowser.open(f"file://{Path(out).resolve()}")

    # ── Stats ──

    def cmd_stats(self) -> None:
        papers = self.db.get_all_papers()
        analyzed = sum(1 for p in papers if p.summary)
        with_refs = sum(1 for p in papers if p.references)
        total_refs = sum(len(p.references) for p in papers)
        all_ids = {p.id for p in papers}
        linked_refs = sum(
            1 for p in papers for ref in p.references if ref in all_ids
        )

        console.print(Panel(
            f"Papers: {len(papers)}\n"
            f"Analyzed: {analyzed}\n"
            f"With references: {with_refs}\n"
            f"Total reference links: {total_refs}\n"
            f"Internal links (graph edges): {linked_refs}",
            title="Database Stats",
        ))

    # ── List ──

    def cmd_list(self) -> None:
        papers = self.db.get_all_papers()
        if not papers:
            console.print("[yellow]No papers in database.[/yellow]")
            return

        table = Table(title=f"Papers ({len(papers)})")
        table.add_column("#", width=3)
        table.add_column("Title", max_width=50)
        table.add_column("Year", width=5)
        table.add_column("Refs", width=5)
        table.add_column("Cited", width=6)
        table.add_column("OK", width=3)

        for i, p in enumerate(sorted(papers, key=lambda x: x.year, reverse=True), 1):
            table.add_row(
                str(i), p.title[:50], str(p.year),
                str(len(p.references)), str(p.cited_by_count),
                "o" if p.summary else "",
            )
        console.print(table)

    # ── Helpers ──

    def _find_paper(self, query: str) -> Paper | None:
        paper = self.db.get_paper(query)
        if paper:
            return paper
        for p in self.db.get_all_papers():
            if p.arxiv_id and (p.arxiv_id == query or p.arxiv_id.split("v")[0] == query.split("v")[0]):
                return p
            if query.lower() in p.title.lower():
                return p
        return None

    def _print_summary(self, paper: Paper) -> None:
        lines = [f"[bold]{paper.title}[/bold] ({paper.year})"]
        if paper.authors:
            lines.append(f"Authors: {', '.join(paper.authors[:3])}{'...' if len(paper.authors) > 3 else ''}")
        if paper.key_contribution:
            lines.append(f"Contribution: {paper.key_contribution}")
        if paper.method_keywords:
            lines.append(f"Keywords: {', '.join(paper.method_keywords)}")
        if paper.summary:
            lines.append(f"\n{paper.summary}")
        console.print(Panel("\n".join(lines), title="Paper Added"))

    def print_help(self) -> None:
        console.print("""
[bold]Paper Copilot[/bold]

[bold cyan]Copilot[/bold cyan]
  survey <title> | <abstract>
                          Auto: suggest keywords → collect → rank by relevance
  related-work <title> | <abstract>
                          Generate Related Work section from collected papers

[bold cyan]Collect[/bold cyan]
  collect <keyword>       Collect papers by keyword (lightweight, fast)
    --limit N               Number of papers (default: 10)
    --deep                  Full mode: PDF extraction + OpenAI analysis

[bold cyan]Paper Management[/bold cyan]
  add <arXiv ID>          Add paper (fetch + analyze + store)
  add-batch <file>        Add papers from file (one ID per line)
  search <query>          Search Semantic Scholar
  fetch-recent            Fetch recent arXiv papers

[bold cyan]Graph Building[/bold cyan]
  expand <paper ID>       Fetch referenced papers (builds citation graph)
  analyze-all             Analyze all unanalyzed papers with OpenAI

[bold cyan]Export[/bold cyan]
  export                  Export to Obsidian vault (markdown + wiki-links)
  graph [keyword]         Open interactive citation graph in browser
                          (filter by keyword, or show all)

[bold cyan]Info[/bold cyan]
  list                    List all papers
  stats                   Show database statistics

[bold cyan]Other[/bold cyan]
  help                    Show this help
  quit                    Exit
""")

    async def run_command(self, cmd: str) -> bool:
        parts = cmd.strip().split(maxsplit=1)
        if not parts:
            return True
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        try:
            if command in ("quit", "exit", "q"):
                return False
            elif command == "help":
                self.print_help()
            elif command == "survey":
                if not args:
                    console.print("[red]Usage: survey <title> | <abstract>[/red]")
                else:
                    parts_sv = args.split("|", maxsplit=1)
                    sv_title = parts_sv[0].strip()
                    sv_abstract = parts_sv[1].strip() if len(parts_sv) > 1 else ""
                    await self.cmd_survey(sv_title, sv_abstract)
            elif command == "collect":
                if not args:
                    console.print("[red]Usage: collect <keyword> [--limit N] [--deep][/red]")
                else:
                    deep = "--deep" in args
                    args_clean = args.replace("--deep", "")
                    collect_parts = args_clean.split("--limit")
                    keyword = collect_parts[0].strip().strip('"').strip("'")
                    limit = 10
                    if len(collect_parts) > 1:
                        try:
                            limit = int(collect_parts[1].strip())
                        except ValueError:
                            pass
                    await self.cmd_collect(keyword, limit=limit, deep=deep)
            elif command == "related-work":
                if not args:
                    console.print("[red]Usage: related-work <title> | <abstract>[/red]")
                    console.print("[dim]Separate title and abstract with ' | '[/dim]")
                else:
                    parts_rw = args.split("|", maxsplit=1)
                    my_title = parts_rw[0].strip()
                    my_abstract = parts_rw[1].strip() if len(parts_rw) > 1 else ""
                    self.cmd_related_work(my_title, my_abstract)
            elif command == "add":
                if not args:
                    console.print("[red]Usage: add <arXiv ID>[/red]")
                else:
                    await self.cmd_add(args)
            elif command == "add-batch":
                if not args:
                    console.print("[red]Usage: add-batch <file>[/red]")
                else:
                    await self.cmd_add_batch(args)
            elif command == "search":
                if not args:
                    console.print("[red]Usage: search <query>[/red]")
                else:
                    await self.cmd_search(args)
            elif command == "fetch-recent":
                await self.cmd_fetch_recent()
            elif command == "expand":
                if not args:
                    console.print("[red]Usage: expand <paper ID>[/red]")
                else:
                    expand_parts = args.split()
                    limit = 10
                    if "--limit" in expand_parts:
                        idx = expand_parts.index("--limit")
                        try:
                            limit = int(expand_parts[idx + 1])
                            expand_parts = expand_parts[:idx] + expand_parts[idx + 2:]
                        except (ValueError, IndexError):
                            pass
                    await self.cmd_expand(expand_parts[0], limit=limit)
            elif command == "analyze-all":
                await self.cmd_analyze_all()
            elif command == "export":
                self.cmd_export()
            elif command == "graph":
                self.cmd_graph(args.strip().strip('"').strip("'") if args else "")
            elif command == "list":
                self.cmd_list()
            elif command == "stats":
                self.cmd_stats()
            else:
                console.print(f"[red]Unknown command: {command}. Type 'help'.[/red]")
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

        return True

    async def run(self) -> None:
        console.print(Panel(
            "[bold]Paper Copilot[/bold]\n"
            f"DB: {len(self.db.get_all_papers())} papers\n"
            "Type 'help' for commands.",
            style="bold blue",
        ))

        while True:
            try:
                cmd = Prompt.ask("\n[bold blue]paper>[/bold blue]")
            except (EOFError, KeyboardInterrupt):
                break
            if not await self.run_command(cmd):
                break

        console.print("[dim]Goodbye.[/dim]")
        await self.close()

    async def close(self) -> None:
        await self.arxiv.close()
        await self.s2.close()
        self.db.close()


async def run_cli(argv: list[str] | None = None) -> int:
    app = App()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args:
            await app.run_command(" ".join(args))
            return 0
        await app.run()
        return 0
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        return 130
    finally:
        await app.close()


def main() -> None:
    raise SystemExit(asyncio.run(run_cli()))


if __name__ == "__main__":
    main()
