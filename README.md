Company Research Assistant — Account Plan Generator
An interactive conversational AI agent that helps users research companies and generate account plans through natural dialogue. It gathers information from multiple sources, synthesizes findings, and lets users edit selected sections of the generated report before downloading a final .docx. Designed to demonstrate agentic behaviour, intelligent orchestration, and thoughtful technical decisions.

✅ Quickstart
Prerequisites

Python 3.10+
Google Gemini API key (set GOOGLE_API_KEY in .env)
Recommended: virtual environment

Install
Shellpip install -r requirements.txtShow more lines
Run
Shellstreamlit run ui/app_streamlit.pyShow more lines
Environment Variables
Create a .env file in the project root:
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-1.5-flash-latest
CACHE_TTL_DAYS=30
RESEARCH_TIMEBOX_MINUTES=5
EURUSD_RATE=1.08


✅ Features

Chat Tab: Ask questions, run Deep Analysis (PDF download & KB build), get sourced answers.
Report Tab: Enter a directive (e.g., “compare 2025 vs 2024, reasons for decline”), generate a full report with:

Directive Response
Overview, Competitors, Market Position, Financial Summary, SWOT, Strategy
Revenue chart (multi-year only)
Top Products/Segments table (PDF-first, fallback to web)
References


Edit & Download: Modify generated content inline, save, and download .docx.


✅ Repository Structure
.
├─ ui/
│  └─ app_streamlit.py        # Streamlit UI (Chat & Report tabs)
├─ src/
│  ├─ agents/
│  │  ├─ research_agent.py    # Multi-agent orchestration + directive-aware generation
│  │  ├─ report_builder.py    # Word doc builder: sections + chart/table + references
│  │  └─ multi_agent.py       # Planner, Retriever, Synthesizer, Critic agents
│  ├─ services/
│  │  ├─ llm.py               # Gemini calls + prompt utilities + JSON section generator
│  │  ├─ search.py            # Web search abstraction
│  │  ├─ cache.py             # Cache management
│  │  ├─ pdf_parser.py        # PDF-first segment parsing; web fallback
│  │  ├─ pdf_extract.py       # Text extraction from PDFs
│  │  ├─ index.py             # Lightweight vector index for KB
│  │  └─ scrape.py            # Link discovery & downloads
├─ outputs/                   # Generated charts/docx per company
├─ data/cache/                # Cached JSON/PDF files
├─ requirements.txt
└─ README.md


✅ Architecture Notes
Multi-Agent Pipeline

PlannerAgent: Plans queries and decides if fresh search is needed.
RetrieverAgent: Fetches snippets from search results.
SynthesizerAgent: Combines KB + snippets + overview to generate answers.
CriticAgent: Validates response quality and triggers retries if needed.

Directive-Aware Report Generation

Uses Gemini in JSON mode to produce structured sections:

Directive Response, Overview, Competitors, Market Position, Financial Summary, SWOT, Strategy, TOP PRODUCTS TABLE, Revenue Graph, Structured Insights.


Falls back to older multi-agent synthesis if JSON fails.
Report builder inserts Directive Response first, then other sections, chart, table, and references.


✅ Design Decisions

Two-tab UI: Separates conversational research from report generation for clarity.
Directive-aware logic: Ensures user directives are explicitly addressed.
PDF-first financial data: Prioritizes authoritative sources; falls back to web when needed.
Editable reports: Users can modify generated content before saving and downloading.
Resilience: Fallbacks ensure usable output even if LLM or search fails.


✅ Demo Checklist

Show sidebar inputs; Build Overview.
In Chat tab: run Deep Analysis, ask a question, show sources & follow-ups.
In Report tab: enter a directive, Generate Full Report, preview sections.
Edit content, Save Edited Report, Download .docx.
Demonstrate at least two personas (Confused + Efficient) in the same run.


✅ Troubleshooting

No chart appears: Ensure Years of data ≥ 2; single-year disables chart.
Empty Directive Response: Add a clear directive (e.g., “compare 2025 vs 2024; explain declines; give next steps”).
Search disabled: If search.py is stubbed, enable your search provider or rely on Deep Analysis + PDFs.
Quota / Model errors: The LLM service selects fallbacks automatically and retries with lowered temperature.