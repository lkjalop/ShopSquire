"""Support-phrasing policy (agnostic CORE) — the M5 SUPPORT lane of David's deck.

Module-4 "Support Decisions": when a specific OBJECTION pattern is blocking conversion, shift the pre-sales
support phrasing to counter it — e.g. slide-7's rule "if support objections focus on price → shift scripts
to lifetime value". This module turns an objection THEME into a recommended response ANGLE + the guidance
line, deterministically. It RECOMMENDS the angle; the support runtime renders approved copy (never free-form,
never a privileged action).

Vertical-blind: objection themes and response angles are commerce-generic categories (price / capability /
trust / availability) — NO product vocabulary. Pure functions: no DB, no LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# objection THEME (what the buyer pushes back on) — opaque, commerce-generic
OBJECTION_PRICE, OBJECTION_CAPABILITY = "price", "capability"
OBJECTION_TRUST, OBJECTION_AVAILABILITY, OBJECTION_UNKNOWN = "trust", "availability", "unknown"

# response ANGLE (how support should reframe) — the approved-copy category the runtime renders
ANGLE_VALUE, ANGLE_CAPABILITY = "value", "capability"
ANGLE_ASSURANCE, ANGLE_AVAILABILITY, ANGLE_NEUTRAL = "assurance", "availability", "neutral"

# keyword → theme (commerce-generic cues; matched against an objection summary, never product literals)
_THEME_CUES = {
    OBJECTION_PRICE: ("price", "expensive", "cost", "cheaper", "budget", "afford", "too much", "pricey"),
    OBJECTION_CAPABILITY: ("slow", "spec", "performance", "power", "enough for", "capable", "handle", "fast enough"),
    OBJECTION_TRUST: ("warranty", "return", "refund", "reliable", "trust", "brand", "reviews", "guarantee"),
    OBJECTION_AVAILABILITY: ("stock", "delivery", "ship", "wait", "lead time", "available", "when will", "eta"),
}

_ANGLE_FOR_THEME = {
    OBJECTION_PRICE: (ANGLE_VALUE, "Objections centre on price — reframe to VALUE / total cost of ownership, not sticker price."),
    OBJECTION_CAPABILITY: (ANGLE_CAPABILITY, "Objections centre on capability — reframe to fit-for-use-case (the specs that matter here)."),
    OBJECTION_TRUST: (ANGLE_ASSURANCE, "Objections centre on trust — lead with ASSURANCE (warranty, returns, support)."),
    OBJECTION_AVAILABILITY: (ANGLE_AVAILABILITY, "Objections centre on availability — set honest delivery expectations / offer to source."),
    OBJECTION_UNKNOWN: (ANGLE_NEUTRAL, "No dominant objection theme — keep neutral, discovery-first phrasing."),
}


@dataclass(frozen=True)
class SupportResponse:
    objection_theme: str
    response_angle: str
    guidance: str
    rationale: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"objection_theme": self.objection_theme, "response_angle": self.response_angle,
                "guidance": self.guidance, "rationale": list(self.rationale)}


def classify_objection(objection: Any) -> str:
    """Map an objection SUMMARY (or an already-known theme token) to a theme. Accepts a MarketFinding-style
    dict/obj (reads .summary / .evidence['theme']), or a raw string. Keyword cues only — vertical-blind.
    Unrecognised → 'unknown'."""
    if objection is None:
        return OBJECTION_UNKNOWN
    # already a theme?
    tok = str(objection if isinstance(objection, str) else "").strip().lower()
    if tok in _ANGLE_FOR_THEME:
        return tok
    # a finding-like object: prefer an explicit evidence.theme, else scan the summary text
    text = tok
    if not text:
        ev = _attr(objection, "evidence")
        if isinstance(ev, dict):
            th = str(ev.get("theme") or "").strip().lower()
            if th in _ANGLE_FOR_THEME:
                return th
        text = str(_attr(objection, "summary") or "").strip().lower()
    if not text:
        return OBJECTION_UNKNOWN
    for theme, cues in _THEME_CUES.items():
        if any(re.search(r"\b" + re.escape(c) + r"\b", text) for c in cues):
            return theme
    return OBJECTION_UNKNOWN


def objection_response(objection: Any) -> SupportResponse:
    """The support-phrasing decision: objection → (theme, angle, guidance). Recommends only."""
    theme = classify_objection(objection)
    angle, guidance = _ANGLE_FOR_THEME.get(theme, _ANGLE_FOR_THEME[OBJECTION_UNKNOWN])
    return SupportResponse(objection_theme=theme, response_angle=angle, guidance=guidance,
                           rationale=[guidance])


def dominant_objection(findings: Optional[List[Any]]) -> str:
    """The strongest objection theme across recent objection findings (by severity then confidence). Reads
    objection_cluster findings; empty / none recognised → 'unknown'. Vertical-blind."""
    sev_w = {"critical": 2.0, "warn": 1.0, "info": 0.5}
    best_theme, best_weight = OBJECTION_UNKNOWN, 0.0
    for f in (findings or []):
        if str(_attr(f, "finding_type") or "") not in ("objection_cluster", "funnel_dropoff"):
            continue
        theme = classify_objection(f)
        if theme == OBJECTION_UNKNOWN:
            continue
        w = sev_w.get(str(_attr(f, "severity") or "warn").lower(), 1.0) * max(0.1, _to_float(_attr(f, "confidence"), 0.5))
        if w > best_weight:
            best_theme, best_weight = theme, w
    return best_theme


def _attr(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
