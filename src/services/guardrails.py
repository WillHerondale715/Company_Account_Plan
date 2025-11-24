
import re

BLOCKLIST = [
    # Keep generic policy categories minimal & neutral
    "sexual", "porn", "violent", "hate", "terror", "extremist"
]

def apply_guardrails(prompt: str) -> str:
    """
    Lightweight guardrail to sanitize user/system prompts.
    - Blocks obviously unsafe keywords.
    - Trims excessively long inputs and removes control chars.
    """
    if not prompt:
        return prompt

    p = prompt
    # Remove control characters
    p = re.sub(r"[\x00-\x1f\x7f]", " ", p)

    # Hard block simple keywords
    lower = p.lower()
    if any(kw in lower for kw in BLOCKLIST):
        return "(Input blocked due to policy violation.)"

    # Limit to a sane length
    if len(p) > 6000:
        p = p[:6000] + "\n(…truncated for safety…)"

    return p
