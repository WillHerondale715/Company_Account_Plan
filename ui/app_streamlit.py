
# -*- coding: utf-8 -*-
"""
Company Research Assistant — Account Plan Generator (Old UI + requested fixes)
- Two tabs: 💬 Chat (Deep Analysis here) and 📄 Report
- Chat input stays at the bottom
- Build Overview button in the left sidebar (under Company, Years, Dept)
- Removed debug toggles / quick info area
- Report shows section previews inline + editable text box
- Download uses bytes (fixes Windows 'seek' error)
Chat behavior:
- Try agent answer; if empty or no sources -> fast web-search fallback (1 query, top 3 results).
- Exploratory follow-ups: short questions/suggestions to help user reach their goal.
- Lower LLM temperature for speed & crispness.
Report behavior:
- Do NOT duplicate existing "Revenue Graph" or "TOP PRODUCTS TABLE".
- If years < 2 -> no chart; else line chart with labels.
- Update existing Top Products/Segments table in place via PDF-first, then web-search.
- If not found, write "Not publicly available" in the table cell.
"""
import os
import sys
import re
import time
from pathlib import Path
from typing import Dict, Any, List
import streamlit as st
from dotenv import load_dotenv

# ---------------- Project path setup ----------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------- Existing modules ----------------
from src.services.llm import call_gemini, SYSTEM_BASE
from src.agents.research_agent import ResearchAgent
# Additive builder
from src.agents.report_builder import (
    build_full_report,
    build_full_report_from_markdown
)

# Optional cache helpers (safe fallbacks)
try:
    from src.services.cache import read_json, path_for, is_cache_stale, write_json
    CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False
    def read_json(company: str, key: str) -> Dict[str, Any]:
        return {}
    def write_json(company: str, key: str, obj: Dict[str, Any]):
        pass
    def path_for(company: str, name: str) -> str:
        out_dir = Path("outputs") / company
        out_dir.mkdir(parents=True, exist_ok=True)
        return str(out_dir / name)
    def is_cache_stale(company: str, days: int) -> bool:
        return False

# Optional search utility (used for Chat fallback)
try:
    from src.services.search import web_search
    SEARCH_AVAILABLE = True
except Exception:
    SEARCH_AVAILABLE = False
    def web_search(query: str, count: int = 5) -> List[Dict]:
        return []

# ---------------- App config ----------------
load_dotenv()
st.set_page_config(page_title="Company Research Assistant", layout="wide")
st.title("📊 Company Research Assistant — Account Plan Generator")

# ---------------- Sidebar (old placement + Build Overview) ----------------
company = st.sidebar.text_input("Company name", "Nokia")
years = st.sidebar.number_input("Years of data", min_value=1, max_value=10, value=5)
dept = st.sidebar.text_input("Department focus (optional)", "Finance")
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))

if st.sidebar.button("🧭 Build Overview (optional)"):
    try:
        agent_for_overview = st.session_state.get("agent", ResearchAgent(company, years, dept))
        if CACHE_AVAILABLE and not is_cache_stale(company, CACHE_TTL_DAYS):
            ov = read_json(company, "basic_overview")
            if ov:
                st.sidebar.success("Loaded overview from cache.")
                st.session_state["cached_overview"] = ov.get("summary", "")
            else:
                out = agent_for_overview.basic_overview()
                st.sidebar.success("Overview built.")
                st.session_state["cached_overview"] = out.get("summary", "")
                write_json(company, "basic_overview", out)
        else:
            out = agent_for_overview.basic_overview()
            st.sidebar.success("Overview built (fresh).")
            st.session_state["cached_overview"] = out.get("summary", "")
            if CACHE_AVAILABLE:
                write_json(company, "basic_overview", out)
    except Exception as e:
        st.sidebar.error(f"Failed: {e}")

# ---------------- Session state ----------------
def _init_state():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("kb_ready", False)
    st.session_state.setdefault("pdfs", [])
    st.session_state.setdefault("financial_paths", {})
    st.session_state.setdefault("report_sections", None)
    st.session_state.setdefault("editable_report_md", "")
    st.session_state.setdefault("last_error", "")
    st.session_state.setdefault("ctx_company", company)
    st.session_state.setdefault("start_ts", int(time.time()))

if "agent" not in st.session_state or st.session_state.get("ctx_company") != company:
    st.session_state["agent"] = ResearchAgent(company, years, dept)
    st.session_state["ctx_company"] = company

agent: ResearchAgent = st.session_state["agent"]
_ = _init_state()

# ---------------- Helpers ----------------
def _normalize_md(t: str) -> str:
    t = (t or "")
    # Unescape common artifacts
    t = t.replace("\\(", "(").replace("\\)", ")").replace("\\*", "*").replace("\\-", "-").replace("\\#", "#")
    t = re.sub(r"\\([_`~>\[\]\(\)\#\*\-])", r"\1", t)
    # Spacing
    t = re.sub(r",(?=\S)", ", ", t)
    t = re.sub(r"\bUSD(?=\d)", "USD ", t)
    t = re.sub(r"\bEUR(?=\d)", "EUR ", t)
    return t.strip()

def _compose_sections_markdown(sections: Dict[str, str]) -> str:
    # ▼ NEW: Put "Directive Response" first so it appears at the top of the DOCX
    order = [
        ("Directive Response", "## Directive Response"),
        ("Overview", "## Overview"),
        ("Competitors", "## Competitors"),
        ("Market Position", "## Market Position"),
        ("Financial Summary", "## Financial Summary"),
        ("SWOT", "## SWOT Analysis"),
        ("Strategy", "## Strategy"),
        ("Structured Insights", "## Overview & Strategy (Structured)"),
        ("TOP PRODUCTS TABLE", "## Top Products / Segments"),
        ("Revenue Graph", "## Revenue Graph"),
    ]
    parts = []
    for key, title in order:
        body = sections.get(key, "")
        if body and body.strip():
            parts.append(f"{title}\n\n{_normalize_md(body.strip())}\n")
    return "\n".join(parts).strip()

def _chat_fallback_answer(user_q: str, prior_msg: str) -> Dict[str, Any]:
    """
    Fast fallback:
    - single query: company + user_q
    - top 3 results
    - lower temperature for speed
    """
    if not SEARCH_AVAILABLE:
        return {"answer": "(Search not available in this environment.)", "sources": []}
    q = f"{company} {user_q}".strip()
    results = []
    try:
        results = web_search(q, count=3) or []
    except Exception:
        pass
    snippet_lines = []
    urls = []
    for r in results[:3]:
        u = r.get("url", "")
        s = r.get("snippets", [])
        if isinstance(s, list):
            s = " ".join(s)
        if s:
            snippet_lines.append(f"- {s[:600]} (source: {u})")
        if u:
            urls.append(u)
    context = "\n".join(snippet_lines)
    synth_prompt = (
        "Using the snippets below, answer the user's question clearly with numbers where possible. "
        "Cite 3–5 URLs at the end. No ASCII art/graphs. Keep it concise.\n\n"
        f"Company: {company}\nDepartment: {dept or 'not specified'}\nUser question: {user_q}\n\nSnippets:\n{context}"
    )
    # Lower temperature for speed
    answer = call_gemini(SYSTEM_BASE, synth_prompt, temperature=0.1)
    return {"answer": answer, "sources": urls[:5]}

def _exploratory_followups(user_q: str) -> str:
    """
    Short, next-step suggestions tailored to research/account planning.
    """
    follow_prompt = (
        "You are assisting with research & account planning. Based on the user's question, "
        "produce 1–2 SHORT, targeted follow-up suggestions to improve the analysis and help reach their goal. "
        "Examples: 'Would you like me to dig into reasons for X?', 'Should I suggest next steps based on these findings?'. "
        "Keep each suggestion one line. If none are useful, reply exactly 'NO_FOLLOW_UP'.\n\n"
        f"Question: {user_q}"
    )
    fu = call_gemini(SYSTEM_BASE, follow_prompt, temperature=0.1)
    return fu.strip()

# ---------------- Tabs ----------------
tab_chat, tab_report = st.tabs(["💬 Chat", "📄 Report"])

# ---------------- 💬 Chat tab ----------------
with tab_chat:
    if st.button("🔍 Deep Analysis (download PDFs / build KB)"):
        try:
            res = agent.deep_collect(ttl_days=CACHE_TTL_DAYS)
            st.session_state["pdfs"] = res.get("downloaded", [])
            st.session_state["kb_ready"] = True
            st.success(f"KB populated with {len(st.session_state['pdfs'])} PDF(s).")
        except Exception as e:
            st.session_state["last_error"] = f"{type(e).__name__}: {e}"
            st.error("Deep Analysis failed.")
            st.code(st.session_state["last_error"])

    st.subheader("Conversation")
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state["messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(_normalize_md(msg["content"]))
        prompt = st.chat_input("Type your question…")
        if prompt:
            # Record user
            st.session_state["messages"].append({"role": "user", "content": prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(_normalize_md(prompt))
            # Try agent first
            try:
                resp = agent.answer_multi(prompt, kb_ready=st.session_state["kb_ready"])
                answer_text = resp.get("answer") or ""
                urls: List[str] = resp.get("sources", [])
                # If answer empty or no sources -> fast fallback
                if not answer_text.strip() or not urls:
                    fallback = _chat_fallback_answer(prompt, st.session_state["messages"][-2]["content"] if len(st.session_state["messages"]) >= 2 else "")
                    answer_text = fallback["answer"]
                    urls = fallback["sources"]
                # Exploratory follow-ups
                fu = _exploratory_followups(prompt)
                if fu and "NO_FOLLOW_UP" not in fu.upper():
                    answer_text = answer_text + "\n\n**Next steps:**\n" + _normalize_md(fu)
                st.session_state["messages"].append({"role": "assistant", "content": answer_text})
                with chat_container:
                    with st.chat_message("assistant"):
                        st.markdown(_normalize_md(answer_text))
                if urls:
                    st.markdown("\n\n**Sources:**")
                    for u in urls:
                        st.markdown(f"- {u}")
            except Exception as e:
                st.session_state["last_error"] = f"{type(e).__name__}: {e}"
                with chat_container:
                    with st.chat_message("assistant"):
                        st.error("Something went wrong answering your question.")
                        st.code(st.session_state["last_error"])

# ---------------- 📄 Report tab ----------------
with tab_report:
    st.subheader("Generate Account Plan (Full Report)")
    directive = st.text_area(
        "Report directive",
        (
            "Focus on financials and competitors. Include an overview, competitors, market position, "
            "financial summary, and SWOT. Update the existing Revenue Graph and Top Products/Segments table in place. "
            "If multiple years, include a line chart with labels; if a single year, skip the chart. "
            "If any segment/product values are missing and not publicly available, state 'Not publicly available'. "
            "Append References."
        ),
        height=140
    )

    if st.button("🧾 Generate Full Report (.docx)"):
        try:
            sections: Dict[str, str] = agent.generate_report_multi(directive)
            st.session_state["report_sections"] = sections

            # Show all previews inline
            st.markdown("### Section Previews")
            for label in [
                # ▼ NEW: include Directive Response in previews
                "Directive Response",
                "Overview", "Competitors", "Market Position", "Financial Summary",
                "SWOT", "Strategy", "Structured Insights", "TOP PRODUCTS TABLE", "Revenue Graph"
            ]:
                tx = sections.get(label, "")
                if tx and tx.strip():
                    st.markdown(f"#### {label}")
                    st.markdown(_normalize_md(tx))

            # Prefill editable box
            st.session_state["editable_report_md"] = _compose_sections_markdown(sections)

            # Build improved docx (updates existing graph/table without duplicates)
            paths = build_full_report(
                company=company,
                directive=directive,
                sections_dict=sections,
                years_back=years,
                currency="EUR"
            )
            st.session_state["financial_paths"] = paths
            st.success("Full report generated.")
        except Exception as e:
            st.session_state["last_error"] = f"{type(e).__name__}: {e}"
            st.error("Failed to generate the full report.")
            st.code(st.session_state["last_error"])

    # Edit box
    st.markdown("---")
    st.markdown("### Edit Report Content (optional)")
    st.session_state["editable_report_md"] = st.text_area(
        "You can edit the generated report content here before saving.",
        st.session_state.get("editable_report_md", ""),
        height=400
    )

    # Save edited docx
    if st.button("💾 Save Edited Report (.docx)"):
        try:
            edited_md = st.session_state.get("editable_report_md", "").strip()
            if not edited_md:
                st.warning("No edited content to save. Generate the report first, or paste content here.")
            else:
                paths = build_full_report_from_markdown(
                    company=company,
                    directive=directive,
                    sections_markdown=edited_md,
                    years_back=years,
                    currency="EUR"
                )
                st.session_state["financial_paths"] = paths
                st.success("Edited report saved.")
        except Exception as e:
            st.session_state["last_error"] = f"{type(e).__name__}: {e}"
            st.error("Failed to save the edited report.")
            st.code(st.session_state["last_error"])

    # Download (bytes)
    out_docx = st.session_state["financial_paths"].get("docx_path")
    if out_docx and os.path.exists(str(out_docx)):
        try:
            with open(str(out_docx), "rb") as f:
                data_bytes = f.read()
            st.download_button(
                "⬇️ Download Account Plan (.docx)",
                data=data_bytes,
                file_name=os.path.basename(str(out_docx)),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.session_state["last_error"] = f"{type(e).__name__}: {e}"
            st.error("Could not offer the download.")
            st.code(st.session_state["last_error"])
    else:
        st.caption("Run 'Generate Full Report' or 'Save Edited Report' to produce the .docx.")

    # Chart preview (if multiple years)
    chart_path = st.session_state["financial_paths"].get("chart_path")
    if chart_path and os.path.exists(str(chart_path)):
        st.image(str(chart_path), caption="Figure: Annual net sales (EUR). Sources in caption & references.")
