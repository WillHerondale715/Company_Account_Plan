
# -*- coding: utf-8 -*-
import os
import json
import logging
from dotenv import load_dotenv
from google import generativeai as genai
from google.api_core.exceptions import ResourceExhausted, NotFound

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger("llm-service")
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

FLASH_CANDIDATES = (
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-flash-latest",
)

ALLOWED_TOPICS = [
    "revenue","growth","financial","market","competitors",
    "products","swot","account plan","strategy","stakeholders",
    "profit","margin","ebitda","forecast","pricing","sales","customer"
]

def validate_question(text: str) -> bool:
    t = (text or "").lower()
    if "structured account plan sections" in t or "create structured account plan" in t:
        return True
    return any(k in t for k in ALLOWED_TOPICS)

SYSTEM_BASE = (
    "You are a research-driven, context-aware assistant for company analysis and account planning. "
    "Your goals: (1) retrieve facts from reliable sources, (2) synthesize concise, useful analysis aligned with user intent, "
    "(3) ask short, targeted follow-ups or next-step suggestions when they materially improve outcomes. "
    "Be conversational, constructive, and natural; prioritize clarity over verbosity. "
    "When citing data, include URLs. Never output ASCII graphs; use plain text or references only. "
    "Remove odd escapes (\\\\#, \\\\*, \\\\- ) and keep clean Markdown. Insert spaces between units and numbers (e.g., 'EUR 19.22B'). "
    "Handle different user types—confused, efficient, chatty, and edge cases—by adapting tone and structure. "
    "If data is not publicly available, say exactly 'Not publicly available'."
)

def _available_generate_models() -> list[str]:
    try:
        names = []
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods:
                names.append(m.name)
        return names
    except Exception as e:
        logger.warning(f"Could not list models: {e}")
        return []

def _normalize_model_name(name: str) -> str:
    return name.replace("models/", "")

def _pick_valid_model(preferred: str) -> str:
    available = _available_generate_models()
    normalized = [_normalize_model_name(n) for n in available]
    if preferred in normalized:
        logger.info(f"Preferred model '{preferred}' available.")
        return f"models/{preferred}"
    for fb in FLASH_CANDIDATES:
        if fb in normalized:
            logger.info(f"Using Flash fallback: {fb}")
            return f"models/{fb}"
    if available:
        logger.info(f"No preferred/Flash; using first available: {available[0]}")
        return available[0]
    logger.warning("No models listed; returning preferred alias.")
    return f"models/{preferred}"

_VALID_MODEL = _pick_valid_model(GEMINI_MODEL)
logger.info(f"Selected model: {_VALID_MODEL}")

def call_gemini(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
    if not validate_question(user_prompt):
        return "(Your question seems unrelated to account planning. Please ask relevant questions.)"
    def _invoke(model_name: str) -> str:
        model = genai.GenerativeModel(model_name=model_name, system_instruction=system_prompt)
        resp = model.generate_content(user_prompt, generation_config={"temperature": temperature})
        text = resp.text or ""
        text = text.replace("\\(", "(").replace("\\)", ")").replace("\\*", "*").replace("\\-", "-").replace("\\#", "#")
        return text
    try:
        return _invoke(_VALID_MODEL)
    except ResourceExhausted as e:
        for fb in FLASH_CANDIDATES:
            try:
                return _invoke(f"models/{fb}")
            except Exception:
                continue
        return f"(LLM 429: quota exceeded. Details: {e})"
    except NotFound as e:
        alt = _pick_valid_model(GEMINI_MODEL)
        try:
            return _invoke(alt)
        except Exception as e2:
            return f"(LLM 404: {_VALID_MODEL} not found; fallback {alt} failed: {e2})"
    except Exception as e:
        return f"(LLM error on {_VALID_MODEL}: {e})"

# ---------- NEW: Directive-aware structured JSON generation ----------
EXPECTED_KEYS = [
    "Directive Response", "Overview", "Competitors", "Market Position",
    "Financial Summary", "SWOT", "Strategy", "TOP PRODUCTS TABLE", "Revenue Graph", "Structured Insights"
]

def structured_sections_prompt(company: str, years: int, dept: str, directive: str) -> str:
    return (
        "Return ONLY a JSON object with keys: " + str(EXPECTED_KEYS) + ". "
        "Each value should be plain text (no markdown fences). "
        "Directive Response MUST explicitly address the user's directive (comparisons, reasons, next steps). "
        f"Context: company={company}, years={years}, dept={dept or 'not specified'}. "
        f"User directive: {directive}"
    )

def _parse_json(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                pass
    return {}

def coerce_sections(raw: dict) -> dict:
    return {k: (str(raw.get(k, "")).strip()) for k in EXPECTED_KEYS}

def call_gemini_json(company: str, years: int, dept: str, directive: str) -> dict:
    prompt = structured_sections_prompt(company, years, dept, directive)
    model = genai.GenerativeModel(model_name=_VALID_MODEL, system_instruction=SYSTEM_BASE)
    resp = model.generate_content(prompt, generation_config={"temperature": 0.2})
    parsed = _parse_json(resp.text or "")
    return coerce_sections(parsed)

# Prompt utilities (unchanged)
def clarify_questions(company: str, years: int, dept: str = None) -> str:
    return (
        f"Before we begin deep research on {company}, ask 2–4 clarifying questions ONLY if they improve outcomes. "
        f"User already provided: years={years}, department={dept or 'not specified'}. "
        "Do NOT ask for these again. Keep questions short and relevant."
    )

def overview_summarizer_prompt(snippets: str) -> str:
    return (
        "Summarize these search snippets into a neutral 3–6 bullet overview. "
        "Call out uncertainties or conflicts.\n\n" + (snippets or "")
    )

def evidence_card_prompt(claim: str, sources: str) -> str:
    if (sources or "").strip() == "[]":
        return (
            "No sources were provided. Output a placeholder Evidence Card:\n"
            "- one-line claim\n- sources: None\n- evidence snippet: Not available\n- confidence: 0"
        )
    return (
        f"Given the claim: '{claim}' and sources: {sources}. "
        "Output a compact Evidence Card with:\n"
        "- one-line claim\n- 1–2 source URLs\n- 1–2 sentence evidence snippet\n- confidence (0–1)"
    )
