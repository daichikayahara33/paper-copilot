"""Prompt templates for paper analysis (inspired by Qiita series #19-#20)."""

ANALYZE_PAPER = """Analyze the following research paper and extract structured information.

## Paper
Title: {title}
Authors: {authors}
Year: {year}

{text_section}

## Instructions
Extract the following in JSON format. Be concise but precise.

{{
  "summary": "3-5 sentence summary covering the problem, approach, and results",
  "research_question": "The main research question or problem being addressed",
  "method_keywords": ["keyword1", "keyword2", ...],
  "key_contribution": "One-line summary of the main contribution",
  "limitations": ["limitation1", "limitation2"],
  "related_work_summary": "Brief summary of how this paper positions itself relative to prior work"
}}

Respond ONLY with valid JSON."""

ANALYZE_PAPER_SYSTEM = (
    "You are a research paper analyst. "
    "Extract structured information from academic papers. "
    "Respond only with valid JSON. {lang_instruction}"
)

GENERATE_RELATED_WORK = """You are writing the "Related Work" section of a research paper.

## My Research
Title: {my_title}
Abstract: {my_abstract}

## Collected Papers
{papers_section}

## Instructions
Based on the collected papers above, write a Related Work section for my research paper.
- Identify which papers are most relevant to my research and explain how they relate
- Group related papers thematically
- Explain the gap that my research fills compared to existing work
- Use proper academic citation format: AuthorLastName et al. (Year)
- Write 3-5 paragraphs
- Be precise and scholarly in tone

Write the Related Work section directly (no JSON, no markdown headers)."""

GENERATE_RELATED_WORK_SYSTEM = (
    "You are an expert academic writer specializing in computer science. "
    "Write clear, well-structured Related Work sections. {lang_instruction}"
)

SUGGEST_KEYWORDS = """Given the following research description, suggest search keywords for finding related papers.

## My Research
Title: {my_title}
Abstract: {my_abstract}

## Instructions
Suggest 5-8 search keywords/phrases that would help find relevant related work.
- Include the obvious direct keywords AND adjacent/broader fields
- Include both specific technical terms and broader area terms
- Each keyword should be a useful search query for Semantic Scholar
- Think about: methods used, problem domain, theoretical foundations, application areas

Respond in JSON:
{{
  "keywords": [
    {{"keyword": "search phrase", "reason": "why this is relevant"}}
  ]
}}"""

SUGGEST_KEYWORDS_SYSTEM = (
    "You are a research advisor helping find related work. "
    "Suggest diverse, useful search keywords. "
    "Respond only with valid JSON. {lang_instruction}"
)

RANK_PAPERS = """Rank the following papers by relevance to my research.

## My Research
Title: {my_title}
Abstract: {my_abstract}

## Papers
{papers_section}

## Instructions
Score each paper's relevance from 0-10 and briefly explain why.
Only include papers with relevance >= 4.
Sort by score descending.

Respond in JSON:
{{
  "ranked": [
    {{"index": 1, "score": 9, "reason": "directly addresses same problem"}},
    ...
  ]
}}"""

RANK_PAPERS_SYSTEM = (
    "You are a research advisor assessing paper relevance. "
    "Be strict — only high scores for genuinely related work. "
    "Respond only with valid JSON. {lang_instruction}"
)

LANG_JA = "Write all analysis in Japanese."
LANG_EN = "Write all analysis in English."
