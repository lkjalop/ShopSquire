"""Single source of truth for prompt-injection markers across ALL guard surfaces (P1-3 dedup).

Previously three separate lists keyed on DIFFERENT tokens, so each surface admitted a different
attack string — the legacy commerce guard (security/commerce_request_guard.py) missed "do anything
now" / "system prompt", the V2 core gate (recommendation_core/gates.py) missed "override system" /
"developer mode", and the narration guard (product_claim_guard.py) missed "jailbreak" / "<script".
The guarantee depended on which path a request happened to traverse. This module is the UNION, so
every surface keys on the same markers and the lists can no longer drift.

Calibration: the ignore/disregard family REQUIRES an instruction-context word (instructions / rules /
prompt / the above) — the real injection shape ("ignore all previous instructions") — so a plain
shopping query ("ignore all the cheap ones") is NOT a false positive. This is a thin FIRST gate, not
a replacement for the full security battery (which also joins the image lane).
"""
from __future__ import annotations

import re

# Distinct attack FAMILIES (union of the historical three lists), each kept in its precise form.
_INJECTION_MARKERS = (
    r"ignore\s+(?:all\s+|previous\s+|prior\s+)*(?:instructions?|rules?|prompts?|the\s+above)",
    r"disregard\b.{0,20}\b(?:instruction|rule|prompt)",
    r"forget\s+(?:all\s+|everything\s+|previous\s+)*(?:instructions?|rules?|above)",
    r"override\s+system",
    r"developer\s+mode",
    r"system\s+prompt",
    r"you\s+are\s+now\b",
    r"do\s+anything\s+now",
    r"jailbreak",
    r"<\s*script",
)

INJECTION_RE = re.compile("|".join(_INJECTION_MARKERS), re.IGNORECASE)

# Tuple form for callers that iterate compiled patterns (e.g. the commerce guard's any(...) loop).
INJECTION_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in _INJECTION_MARKERS)


def is_injection(text: str) -> bool:
    """True iff the text carries a prompt-injection marker. The single predicate every guard uses."""
    return bool(INJECTION_RE.search(str(text or "")))
