
import re
from typing import Dict, List, Any, Optional

from ..services.llm import call_gemini, SYSTEM_BASE
from ..services.search import web_search
from ..services.index import VectorIndex

# ---------- Planner Agent ----------
class PlannerAgent:
    def plan(self, company: str, user_prompt: str, kb_ready: bool) -> Dict[str, Any]:
        """
        Plan next steps for QA/report generation:
        - Decide whether fresh web search is needed.
        - Derive 2–4 focused search queries from the prompt.
        - Propose 2–3 follow-up questions.
        """
        need_fresh_search = True
        # If the user explicitly asks to use KB only, skip fresh search
        if kb_ready and any(k in user_prompt.lower() for k in ["use kb", "from cached", "from pdf", "from overview"]):
            need_fresh_search = False

        prompt = (
            "Derive 2–4 focused web search queries from the user's request. "
            "Queries MUST be specific to the company and the metrics/entities mentioned. "
            "No bullets, no commentary—one query per line.\n"
            f"Company: {company}\nUser request: {user_prompt}\n"
        )
        try:
            qtext = call_gemini(SYSTEM_BASE, prompt) or ""
            lines = [l.strip() for l in qtext.splitlines() if l.strip()]
        except Exception:
            lines = []

        if not lines:
            base = company.strip()
            up = user_prompt.strip()
            lines = [
                f"{base} {up} latest figures",
                f"{base} segment revenue by product last year",
                f"{base} top products revenue {up}",
                f"{base} annual report product revenue breakdown"
            ]

        followups = [
            "Should I compare the last 3 years or focus on the latest year?",
            "Do you want product-level revenue or segment-level revenue?",
            "Should I include competitor benchmarks for context?"
        ]

        return {
            "need_fresh_search": need_fresh_search,
            "search_queries": lines[:4],
            "followups": followups
        }

# ---------- Retriever Agent ----------
class RetrieverAgent:
    def gather_snippets(self, queries: List[str], count: int = 6) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for q in queries:
            hits = web_search(q, count=count) or []
            for h in hits:
                item = {
                    "name": h.get("name", ""),
                    "url": h.get("url", ""),
                    "snippet": h.get("snippet", "")
                }
                if item["url"]:
                    results.append(item)
        # De-duplicate by URL
        seen, uniq = set(), []
        for r in results:
            u = r["url"]
            if u not in seen:
                seen.add(u)
                uniq.append(r)
        return uniq[:20]

# ---------- Synthesizer Agent ----------
class SynthesizerAgent:
    def __init__(self, vector_index: Optional[VectorIndex] = None):
        self.index = vector_index

    def _clean(self, text: str) -> str:
        text = (text or "")
        text = text.replace("\\(", "(").replace("\\)", ")").replace("\\*", "*").replace("\\-", "-").replace("\\#", "#")
        text = re.sub(r",(?=\S)", ", ", text)
        # Ensure space between units and numbers, e.g., USD20B -> USD 20B
        text = re.sub(r"\b(USD|EUR)(?=\d)", r"\1 ", text)
        return text.strip()

    def answer(self, company: str, question: str, overview_results: List[Dict[str, Any]],
               fresh_snippets: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Compose an answer using:
        - KB index (if present)
        - overview search results
        - fresh snippets aligned to the user's prompt
        """
        overview_snips = "\n".join([r.get("snippet", "") for r in overview_results if r.get("snippet")])
        fresh_snips = "\n".join([f"- {r.get('name','')}: {r.get('snippet','')} ({r.get('url','')})"
                                 for r in fresh_snippets])

        pdf_sources: List[str] = []
        hits = []
        if self.index and getattr(self.index, "vectors", None) is not None and len(self.index.texts) > 0:
            hits = self.index.search(question, k=5)
            pdf_sources = [h[1]["source"] for h in hits]

        prompt = (
            f"Company: {company}\n"
            f"Question: {question}\n\n"
            "Use ALL available context (overview + KB evidence + fresh web snippets).\n"
            "Produce a direct, well-reasoned answer with:\n"
            "- 1 short paragraph summarizing the answer and key drivers/insights\n"
            "- 3–5 bullets of suggestions or inferred implications (NOT just restating data)\n"
            "Rules:\n"
            "- Plain Markdown only (no backslashes, no odd escapes)\n"
            "- Include numbers with spaces (e.g., 'USD 20.8B')\n"
            "- If confidence is low, explicitly say what’s missing and propose follow-ups\n\n"
            f"Overview snippets:\n{overview_snips}\n\n"
            f"KB PDF sources:\n{pdf_sources}\n\n"
            f"Fresh web snippets:\n{fresh_snips}\n"
        )
        ans = call_gemini(SYSTEM_BASE, prompt)
        return {
            "answer": self._clean(ans),
            "sources": list(dict.fromkeys(pdf_sources + [r.get("url","") for r in fresh_snippets if r.get("url")]))[:6],
            "hits": hits
        }

    def build_report_sections(self, company: str, directive: str, overview_text: str,
                              fresh_snippets: List[Dict[str, str]]) -> Dict[str, str]:
        """
        Build structured report sections; if directive requests TABLE(S),
        emit Markdown tables that the UI will convert to Word tables.
        """
        fresh_snips = "\n".join([f"- {r.get('name','')}: {r.get('snippet','')} ({r.get('url','')})"
                                 for r in fresh_snippets])
        prompt = (
            f"Create a structured account plan for {company}.\n"
            f"Directive from user: {directive}\n"
            "Sections required:\n"
            "- Company Overview (3–5 bullets)\n"
            "- Main Products (5–8 items)\n"
            "- Competitors (6–10 names + 1-line descriptors)\n"
            "- Market Position (2–4 bullets)\n"
            "- Financial Summary (revenue, growth % if present)\n"
            "- SWOT Analysis (4–6 bullets each)\n"
            "- If the directive requests a TOP PRODUCTS TABLE with revenue, produce a Markdown table:\n"
            "  | Product | FY (year) | Revenue (USD) | Source |\n"
            "Use both the overview and the fresh web snippets below.\n"
            "Rules:\n"
            "- Plain Markdown only; bullets or tables; no pseudo formatting\n"
            "- If data for a requested table is incomplete, include rows with 'N/A' and provide sources\n\n"
            f"Overview:\n{overview_text}\n\n"
            f"Fresh snippets:\n{fresh_snips}\n"
        )
        content = call_gemini(SYSTEM_BASE, prompt)
        return {"Structured Insights": self._clean(content)}

# ---------- Critic Agent ----------
class CriticAgent:
    def needs_retry(self, answer_text: str) -> bool:
        if not answer_text or "(No answer)" in answer_text:
            return True
        bad = ["[Insert", "Cite Source]", "Not available", "(Overview)"]
        if any(b in answer_text for b in bad):
            return True
        # Require at least one number or year for substance
        return not bool(re.search(r"\b(19|20)\d{2}\b|\d", answer_text))
