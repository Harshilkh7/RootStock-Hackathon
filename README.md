# Rootstock Hackathon Research Engine

This repository contains a working prototype for the Rootstock hackathon brief: an agentic deep research engine that accepts a research query, builds a research plan, searches a prepared corpus, retrieves and ranks evidence with VGRH logic, and generates a cited report.

## Why this implementation

The brief explicitly prioritizes:

- Correctness and traceability over decorative UI
- A working end-to-end prototype over incomplete advanced architecture
- Explainable ranking over generic chatbot behavior

This prototype is therefore optimized around:

- End-to-end query-to-report flow
- Visible source selection and VGRH score breakdown
- Evidence snippets tied to source URLs
- Confidence signaling and lightweight contradiction flags
- A simple local setup with no third-party dependencies

Rust was preferred by the brief request, but `rustc` and `cargo` are not installed in this workspace. To keep the prototype runnable within the hackathon timeline, the implementation uses Python 3.11 standard library only.

## Implemented architecture

The app maps directly to the brief's layered pipeline:

1. User query input via browser UI or CLI
2. Research planner that creates sub-questions and information goals
3. Query generator with term expansion
4. Source discovery over a prepared local corpus
5. Web/PDF source abstraction through document metadata
6. Parser and chunker over source text
7. Hybrid retrieval using BM25-style lexical scoring plus token-overlap semantic scoring
8. VGRH ranker with visible score components
9. Evidence extraction into structured records
10. Claim verification heuristics with confidence and contradiction flags
11. Report generation with citations and limitations

## Features

### Minimum expected outcome

- Query input
- Research plan / sub-question flow
- Source collection from a prepared dataset
- Source parsing and chunking
- Retrieval and ranking
- Evidence extraction
- Final cited report

### Strong outcome items included

- Hybrid retrieval
- Visible source ranking with score breakdown
- VGRH-based ranking
- PDF-tagged source support in the corpus
- Confidence scoring
- Clear UI for research steps, selected sources, evidence, and report

### Partial bonus items

- Iterative retrieval loop with gap-aware follow-up queries
- Cross-source claim verification with support counts
- Lightweight contradiction and uncertainty flags
- Exportable Markdown/HTML report output
- Modular code and setup instructions

## Project structure

- [app.py](C:/Users/HITS/Documents/RootStock%20Hackathon/app.py): HTTP server and CLI entrypoint
- [engine.py](C:/Users/HITS/Documents/RootStock%20Hackathon/engine.py): research pipeline
- [data/corpus.json](C:/Users/HITS/Documents/RootStock%20Hackathon/data/corpus.json): prepared research corpus
- [static/index.html](C:/Users/HITS/Documents/RootStock%20Hackathon/static/index.html): frontend
- [static/app.js](C:/Users/HITS/Documents/RootStock%20Hackathon/static/app.js): browser logic
- [static/styles.css](C:/Users/HITS/Documents/RootStock%20Hackathon/static/styles.css): UI styles

## How to run

### Web app

```powershell
python app.py
```

Then open `http://127.0.0.1:8000`.

### CLI mode

```powershell
python app.py --query "Compare three low-cost methods for improving air quality in classrooms."
```

### CLI export options

```powershell
python app.py --query "Compare three low-cost methods for improving air quality in classrooms." --export-format markdown --export-path report.md
python app.py --query "Compare three low-cost methods for improving air quality in classrooms." --export-format html --export-path report.html
```

## Sample query

```text
Compare three low-cost methods for improving air quality in classrooms.
```

## Output format

The generated report includes:

- Executive summary
- Research plan
- Iterative loop trace
- Source table with score breakdown
- Evidence table with citations, confidence, and verification status
- Final report
- Limitations

## Current limitations

- The prototype uses a prepared corpus rather than live web search APIs.
- Claim verification uses multi-source support and contradiction heuristics, not external fact-check APIs.
- PDF support is represented through corpus ingestion and source typing, not a live upload flow in the UI.
- Export currently supports Markdown and HTML (PDF/DOCX are not implemented).

## Submission readiness notes

This repo is structured to support the brief's checklist:

- Clear README and run instructions
- End-to-end query-to-report demo path
- Source references and citations in the report
- No API keys required
- Organized, explainable code suitable for a short demo video
