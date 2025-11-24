
# -*- coding: utf-8 -*-
"""
PDF Parser for Nokia filings (additive):
- Attempts to fetch official PDFs online:
    * Q4 & full-year 2024 results: 'nokia_results_2024_q4.pdf'
    * Annual report 2024: 'nokia-annual-report-2024_1.pdf'
- Extracts business group net sales (EUR million) and converts to EUR bn.

If no PDF is found or parsing fails, return [] and let report_builder fall back to web search.
"""

import re
from typing import List, Dict, Optional

import fitz  # pymupdf
import requests

# Candidate URLs (stable newsroom patterns)
CANDIDATE_PDFS = [
    # Earnings release (Jan 30, 2025)
    "https://www.nokia.com/system/files/2025-01/nokia_results_2024_q4.pdf",
    # Annual report (Mar/Apr 2025)
    "https://www.nokia.com/system/files/?file=2025-04/nokia-annual-report-2024_1.pdf",
    # Mirror candidates (if Nokia changes its path structure)
    "https://www.nokia.com/system/files/2025-03/nokia-annual-report-2024_1.pdf",
]

SEGMENT_LABELS = [
    "Network Infrastructure",
    "Mobile Networks",
    "Cloud and Network Services",
    "Nokia Technologies",
]

def _download_pdf(url: str, timeout: int = 20) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None

def _read_pdf_text(pdf_bytes: bytes) -> str:
    text = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text.append(page.get_text("text"))
    return "\n".join(text)

def _extract_segments_from_text(txt: str) -> List[Dict]:
    """
    Heuristic extraction:
    - Locate lines near segment names that include numbers like 'EUR 7,700 million' or '7,700' with 'EUR million'
    - Convert to EUR bn (divide by 1000)
    """
    rows: List[Dict] = []
    # Normalize whitespace
    t = re.sub(r"[ \t]+", " ", txt)
    # Build a window per segment
    for seg in SEGMENT_LABELS:
        # find segment occurrences
        matches = [m.start() for m in re.finditer(re.escape(seg), t)]
        val_bn: Optional[float] = None
        for pos in matches:
            window = t[max(0, pos-400): pos+400]  # around segment mention
            # EUR million patterns
            m1 = re.search(r"(?:EUR|€)\s?([0-9]{1,3}(?:[, ][0-9]{3})+|\d+(?:\.\d+)?)\s?(?:million|m)\b", window, re.I)
            if m1:
                raw = m1.group(1).replace(",", "").replace(" ", "")
                try:
                    val_m = float(raw)
                    val_bn = round(val_m / 1000.0, 3)
                    break
                except Exception:
                    pass
            # bn patterns (rare)
            m2 = re.search(r"(?:EUR|€)\s?([0-9]+(?:\.[0-9]+)?)\s?(?:billion|bn)\b", window, re.I)
            if m2:
                try:
                    val_bn = round(float(m2.group(1)), 3)
                    break
                except Exception:
                    pass
        rows.append({
            "Product": seg,
            "FY": 2024,
            "Revenue_EUR_bn": val_bn,
            "Source": ""  # filled by caller
        })
    return rows

def fetch_and_parse_nokia_segments(company: str, year: int = 2024) -> List[Dict]:
    """
    Returns list of rows: {"Product","FY","Revenue_EUR_bn","Source"} using official PDFs.
    If company != 'Nokia', returns [] (scope limited to Nokia for now).
    """
    if company.lower() != "nokia":
        return []

    # Try candidate URLs first
    for url in CANDIDATE_PDFS:
        pdf = _download_pdf(url)
        if pdf:
            txt = _read_pdf_text(pdf)
            rows = _extract_segments_from_text(txt)
            # attach source URL
            for r in rows:
                r["FY"] = year
                r["Source"] = url
            # only accept if at least one value found
            if any(isinstance(r["Revenue_EUR_bn"], (int, float)) for r in rows):
                return rows

    # As a fallback: try newsroom page to locate a PDF link (requires user-side search util)
    try:
        from src.services.search import web_search
        rs = web_search("Nokia Corporation Financial Report for Q4 and full year 2024 PDF", count=5) or []
        pdf_url = next((r["url"] for r in rs if r.get("url","").lower().endswith(".pdf")), None)
        if pdf_url:
            pdf = _download_pdf(pdf_url)
            if pdf:
                txt = _read_pdf_text(pdf)
                rows = _extract_segments_from_text(txt)
                for r in rows:
                    r["FY"] = year
                    r["Source"] = pdf_url
                if any(isinstance(r["Revenue_EUR_bn"], (int, float)) for r in rows):
                    return rows
    except Exception:
        pass

    # If nothing found
    return []
