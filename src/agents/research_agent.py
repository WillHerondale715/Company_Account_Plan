
import os, time, re
from typing import Dict, List, Tuple, Optional
from ..services.llm import (
    call_gemini, SYSTEM_BASE, clarify_questions,
    overview_summarizer_prompt, evidence_card_prompt,
    # ▼ NEW: JSON structured sections honoring directive
    call_gemini_json
)
from ..services.search import web_search
from ..services.scrape import find_pdf_links, dynamic_collect_links, download_file
from ..services.pdf_extract import extract_pdf_text
from ..services.index import VectorIndex
from ..services.cache import write_json, read_json, path_for, is_cache_stale, list_cached_downloads, prune_company_cache
# NEW: multi-agent orchestration
from .multi_agent import PlannerAgent, RetrieverAgent, SynthesizerAgent, CriticAgent

TIMEBOX_MIN = int(os.getenv("RESEARCH_TIMEBOX_MINUTES", "5"))
EURUSD = float(os.getenv("EURUSD_RATE", "1.08"))  # optional env for EUR→USD conversion

def _clean(text: str) -> str:
    text = re.sub(r"[\u200b\u200c\u200d\u2060]", "", text or "")
    text = re.sub(r"[\t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = text.replace("\\(", "(").replace("\\)", ")").replace("\\*", "*").replace("\\-", "-").replace("\\#", "#")
    text = re.sub(r",(?=\S)", ", ", text)
    text = re.sub(r"\b(USD|EUR)(?=\d)", r"\1 ", text)
    return text.strip()

def _convert_usd(val_bil: float, currency: str) -> float:
    if not isinstance(val_bil, (int, float)): return val_bil
    if currency and currency.upper().startswith("EUR"): return float(val_bil) * EURUSD
    return float(val_bil)

class ResearchAgent:
    def __init__(self, company: str, years: int = 3, dept: Optional[str] = None):
        self.company = company
        self.years = years
        self.dept = dept
        self.index = VectorIndex()
        # Multi agents
        self.planner = PlannerAgent()
        self.retriever = RetrieverAgent()
        self.synthesizer = SynthesizerAgent(self.index)
        self.critic = CriticAgent()

    # ---------- Index management ----------
    def ensure_index_loaded(self) -> None:
        if getattr(self.index, "vectors", None) is not None and len(self.index.texts) > 0:
            return
        deep = read_json(self.company, "deep_collect")
        downloaded = deep.get("downloaded", [])
        if not downloaded: return
        texts, metas = [], []
        for d in downloaded:
            p = d.get("path"); src = d.get("url")
            try: txt = extract_pdf_text(p, max_pages=40)
            except Exception: txt = ""
            if txt:
                texts.append(txt); metas.append({"source": src, "path": p})
        if texts: self.index.add(texts, metas)

    # ---------- Clarifications ----------
    def ask_clarifications(self) -> str:
        return call_gemini(SYSTEM_BASE, clarify_questions(self.company, self.years, self.dept))

    # ---------- Overview ----------
    def basic_overview(self) -> Dict:
        queries = [
            f"{self.company} finances overview",
            f"{self.company} annual report",
            f"{self.company} revenue {self.years} years",
        ]
        results = []
        for q in queries: results.extend(web_search(q, count=5))
        snippets = "\n".join([f"- {r['name']}: {r.get('snippet','')} ({r['url']})" for r in results if r.get('url')])
        summary = call_gemini(SYSTEM_BASE, overview_summarizer_prompt(snippets))
        write_json(self.company, "basic_overview", {"summary": summary, "results": results})
        return {"summary": summary, "results": results}

    # ---------- Quick answer (overview snippets only) ----------
    def quick_answer(self, question: str) -> Dict:
        ov = read_json(self.company, "basic_overview")
        results = ov.get("results", [])
        if not results:
            return {"answer": "(No overview data available. Run overview first.)", "sources": []}
        snippets = "\n".join([r.get("snippet","") for r in results if r.get("snippet")])
        prompt = (
            "Answer concisely using ONLY these snippets. "
            "Return plain Markdown.\n\n"
            f"{snippets}\n\nQuestion: {question}"
        )
        ans = call_gemini(SYSTEM_BASE, prompt)
        return {"answer": _clean(ans), "sources": [r["url"] for r in results[:3] if r.get("url")]}

    # ---------- Deep collect (reuse cache if fresh; refresh if stale) ----------
    def deep_collect(self, timebox_min: int = TIMEBOX_MIN, ttl_days: Optional[int] = None) -> Dict:
        if ttl_days and not is_cache_stale(self.company, ttl_days):
            cached = list_cached_downloads(self.company)
            if cached:
                write_json(self.company, "deep_collect", {"pdf_links": [d["url"] for d in cached], "downloaded": cached})
                texts, metas = [], []
                for d in cached:
                    try: txt = extract_pdf_text(d["path"], max_pages=40)
                    except Exception: txt = ""
                    if txt:
                        texts.append(txt); metas.append({"source": d["url"], "path": d["path"]})
                if texts: self.index.add(texts, metas)
                return {"pdf_links": [d["url"] for d in cached], "downloaded": cached}
        if ttl_days: prune_company_cache(self.company, ttl_days)

        start = time.time()
        targets = read_json(self.company, "basic_overview").get("results", [])
        pdf_links: List[str] = []
        for r in targets:
            if time.time() - start > timebox_min * 60: break
            url = r.get("url")
            if not url: continue
            pdf_links.extend(find_pdf_links(url, max_links=5))
            if len(pdf_links) < 2:
                pdf_links.extend(dynamic_collect_links(url, max_links=3))
        pdf_links = list(dict.fromkeys(pdf_links))

        downloaded: List[Dict] = []
        for i, pdf in enumerate(pdf_links[:10]):
            dest = str(path_for(self.company, f"doc_{i+1}.pdf"))
            if download_file(pdf, dest):
                downloaded.append({"path": dest, "url": pdf})

        texts, metas = [], []
        for d in downloaded:
            try: txt = extract_pdf_text(d["path"], max_pages=40)
            except Exception: txt = ""
            if txt:
                texts.append(txt); metas.append({"source": d["url"], "path": d["path"]})
        if texts: self.index.add(texts, metas)

        write_json(self.company, "deep_collect", {"pdf_links": pdf_links, "downloaded": downloaded})
        return {"pdf_links": pdf_links, "downloaded": downloaded}

    # ---------- Evidence answer ----------
    def answer_with_evidence(self, question: str, k: int = 5) -> Dict:
        self.ensure_index_loaded()
        hits = self.index.search(question, k=k)
        sources = [h[1]["source"] for h in hits]
        if not sources:
            return {"claim": "(No evidence found — please run deep research)", "sources": [], "card": "", "hits": []}
        claim = call_gemini(SYSTEM_BASE, f"Answer concisely: {question} based only on sources: {sources}")
        card = call_gemini(SYSTEM_BASE, evidence_card_prompt(claim, str(sources)))
        return {"claim": _clean(claim), "sources": sources, "card": _clean(card), "hits": hits}

    # ---------- Hybrid answer (overview + evidence) ----------
    def answer_hybrid(self, question: str, k: int = 5) -> Dict:
        ov = read_json(self.company, "basic_overview")
        overview_snippets = "\n".join([r.get("snippet","") for r in ov.get("results", []) if r.get("snippet")])
        self.ensure_index_loaded()
        hits = self.index.search(question, k=k)
        pdf_sources = [h[1]["source"] for h in hits]
        combined_context = f"Overview:\n{overview_snippets}\n\nPDF sources:\n{pdf_sources}"
        prompt = (
            f"Answer the question using BOTH overview snippets and PDF sources.\n"
            f"Question: {question}\nContext:\n{combined_context}\n"
            "Return a concise, factual answer in plain Markdown."
        )
        answer = call_gemini(SYSTEM_BASE, prompt)
        return {"answer": _clean(answer), "sources": pdf_sources[:3], "hits": hits}

    # ---------- NEW: Multi-agent pipeline for chat QA ----------
    def answer_multi(self, user_prompt: str, kb_ready: bool = True) -> Dict:
        ov = read_json(self.company, "basic_overview")
        overview_results = ov.get("results", [])
        plan = self.planner.plan(self.company, user_prompt, kb_ready)
        fresh_snippets = []
        if plan["need_fresh_search"]:
            fresh_snippets = self.retriever.gather_snippets(plan["search_queries"])
        resp = self.synthesizer.answer(self.company, user_prompt, overview_results, fresh_snippets)
        if self.critic.needs_retry(resp.get("answer", "")):
            refine_q = [
                f"{self.company} {user_prompt} latest report",
                f"{self.company} product revenue table FY {self.years}",
                f"{self.company} segment revenue by product"
            ]
            fresh_snippets2 = self.retriever.gather_snippets(refine_q)
            resp = self.synthesizer.answer(self.company, user_prompt, overview_results, fresh_snippets2)
        resp["followups"] = plan.get("followups", [])
        return resp

    # ---------- Existing resilient pipeline now calls multi-agent ----------
    def answer_resilient(self, question: str, k: int = 5) -> Dict:
        return self.answer_multi(question, kb_ready=True)

    # ---------- Structured sections (retain original) ----------
    def generate_structured_sections(self) -> Dict:
        self.ensure_index_loaded()
        overview = read_json(self.company, "basic_overview").get("summary", "")
        prompt = (
            f"Create structured account plan sections for {self.company}.\n"
            "- Company Overview (3–5 bullets)\n"
            "- Main Products (5–8 items)\n"
            "- Competitors (6–10 names + 1-line descriptors)\n"
            "- Market Position (2–4 bullets)\n"
            "- Financial Summary (revenue, growth % if present)\n"
            "- SWOT Analysis (4–6 bullets each)\n"
            "Use insights from cached PDFs and overview. Plain Markdown lists."
        )
        content = call_gemini(SYSTEM_BASE, prompt)
        return {"overview": overview, "structured": _clean(content)}

    # ---------- NEW: Multi-agent report generation honoring user directive ----------
    def generate_report_multi(self, directive: str) -> Dict[str, str]:
        """
        Directive-aware structured generation.
        Returns standard sections + (NEW) 'Directive Response' when available.
        Preserves previous behavior if JSON fails.
        """
        # 1) Try directive-aware JSON sections first (NEW)
        try:
            sections = call_gemini_json(
                company=self.company,
                years=self.years,
                dept=self.dept or "",
                directive=directive
            )
            if sections and any((v or "").strip() for v in sections.values()):
                return sections
        except Exception:
            # gracefully fall back
            pass

        # 2) Fallback: previous multi-agent synthesis (UNCHANGED)
        ov = read_json(self.company, "basic_overview").get("summary", "")
        plan = self.planner.plan(self.company, directive, kb_ready=True)
        fresh_snippets = []
        if plan.get("need_fresh_search"):
            fresh_snippets = self.retriever.gather_snippets(plan.get("search_queries", []))
        sections = self.synthesizer.build_report_sections(self.company, directive, ov, fresh_snippets)

        # 3) Add a Directive Response placeholder (NEW, minimal)
        if "Directive Response" not in sections:
            sections["Directive Response"] = (
                f"(Directive was: {directive}. This build used the older 'Structured Insights' bucket. "
                f"Edit this section in the UI if you want to add directive-specific notes.)"
            )

        # Preserve all original keys even if empty (defensive)
        for k in ["Overview","Competitors","Market Position","Financial Summary","SWOT","Strategy","TOP PRODUCTS TABLE","Revenue Graph","Structured Insights"]:
            sections.setdefault(k, "")

        return sections

    # ---------- Competitor extraction (unchanged) ----------
    def extract_competitors(self, text: str) -> List[Tuple[str, str]]:
        items = []
        lines = (text or "").splitlines()
        in_competitors = False
        for line in lines:
            s = line.strip()
            if not s: continue
            if re.search(r"^\s*competitor", s, re.I):
                in_competitors = True; continue
            if in_competitors and re.search(r"^\s*(company overview|main products|market position|financial summary|swot)", s, re.I):
                in_competitors = False
            if not in_competitors: continue
            if ":" in s:
                name, desc = s.lstrip("-*• ").split(":", 1)
                name, desc = name.strip(), desc.strip()
                if name and desc and len(name) <= 60:
                    items.append((name, desc))
            else:
                m = re.match(r"[-*•]\s*([A-Za-z0-9&.\- ]+)$", s)
                if m:
                    name = m.group(1).strip()
                    if len(name.split()) <= 4:
                        items.append((name, ""))
        uniq, seen = [], set()
        for n, d in items:
            if n.lower() not in seen:
                seen.add(n.lower())
                uniq.append((n, d))
        return uniq[:10]

    # ---------- SWOT extraction (unchanged) ----------
    def extract_swot(self, text: str) -> Dict[str, List[str]]:
        swot = {"Strengths": [], "Weaknesses": [], "Opportunities": [], "Threats": []}
        current = None
        for line in (text or "").splitlines():
            h = line.strip().lower()
            if "strength" in h: current = "Strengths"; continue
            if "weakness" in h: current = "Weaknesses"; continue
            if "opportunit" in h: current = "Opportunities"; continue
            if "threat" in h: current = "Threats"; continue
            if current:
                m = re.match(r"[-*]\s*(.+)", line.strip())
                if m: swot[current].append(m.group(1).strip())
        for k in swot: swot[k] = swot[k][:6]
        return swot

    # ---------- Financial extraction (unchanged) ----------
    def extract_financials_from_pdfs(self, max_docs: int = 9) -> Dict:
        deep = read_json(self.company, "deep_collect")
        downloaded = deep.get("downloaded", [])[:max_docs]
        series, notes = [], []
        year_pat = r"(20[0-9]{2}|19[0-9]{2})"
        pat = re.compile(
            rf"(revenue|net sales|sales)\s*(?:in|for|,)?\s*(?P<year>{year_pat})?.{{{0,40}}}?(?P<curr>USD|US\$|\$|EUR|€)?\s*(?P<amt>[0-9][0-9,.\s]*)(?P<unit>billion|million|B|M)?",
            re.I
        )
        for d in downloaded:
            p = d.get("path"); src = d.get("url")
            txt = ""
            try: txt = extract_pdf_text(p, max_pages=40)
            except Exception: pass
            if not txt: continue
            for line in txt.splitlines():
                m = pat.search(line)
                if m:
                    year = m.group("year")
                    curr = m.group("curr") or ""
                    amt_raw = (m.group("amt") or "").replace(",", "").replace(" ", "")
                    unit = (m.group("unit") or "").lower()
                    try: val = float(amt_raw)
                    except Exception: continue
                    val_bil = val / 1000.0 if unit in ("million","m") else val
                    curr_norm = "USD" if curr in ["USD","US$","$"] else ("EUR" if curr in ["EUR","€"] else "")
                    usd_bil = _convert_usd(val_bil, curr_norm)
                    if usd_bil is None or not (0.05 <= usd_bil <= 500): continue
                    try: y = int(year) if year else None
                    except Exception: y = None
                    if not (y and 1990 <= y <= 2100): continue
                    series.append({
                        "year": y,
                        "value_bil_usd": round(usd_bil, 3),
                        "currency": curr_norm or "USD",
                        "raw": line.strip(),
                        "source": src
                    })
        by_year = {}
        for s in series:
            y = s.get("year")
            if not y: continue
            if y not in by_year or s["value_bil_usd"] > by_year[y]["value_bil_usd"]:
                by_year[y] = s
        series_sorted = [by_year[y] for y in sorted(by_year.keys())]
        if not series_sorted:
            notes.append("No revenue series found in PDFs. Ensure annual report PDFs were captured.")
        return {"series": series_sorted, "notes": "\n".join(notes)}
