"""Question-time measurement matching, independent of product vocabulary.

Only producer-declared finding types establish the measured facet. Summary
text and graph labels are not evidence that a different quantity was measured.
Temporal/provenance admission remains a separate mandatory check.
"""

import math
import re


_QUESTION_PATTERNS = {
    "lead_time": (
        r"\b(?:lead[ -]?times?|how\s+(?:soon|long)|delivery\s+(?:times?|dates?|windows?)"
        r"|arrival|restock|turnaround|eta|estimated\s+delivery|(?:shipping|delivery)\s+delays?)\b"
        r"|\bwhen\b[^?.!]{0,100}\b(?:deliver|arrive|ship|restock)\b"
        r"|\b(?:arrive|delivered|shipped|get\s+here)\b[^?.!]{0,40}\b(?:by|before|after|within)\b"
    ),
    "demand": r"\b(?:demand|trending|trends?|popular|best[ -]?sellers?|sales\s+(?:growth|volume))\b",
    "price": r"\b(?:prices?|pricing|costs?|cheaper|expensive|price[ -]?match)\b",
    "stock": r"\b(?:stock|inventory|availability|available\s+units?|supply\s+levels?)\b",
    "competition": r"\b(?:competitors?|competition|elsewhere|undercut)\b",
    "forecast": r"\b(?:forecasts?|predict(?:ions?|ed)?|will\b[^?.!]{0,100}\b(?:rise|fall|drop|increase|decrease))\b",
    "causality": r"\b(?:why|causes?|caused|causing|driving)\b",
}
_FINDING_FACETS = {
    "supplier_lead_time": {"lead_time"},
    "lead_time": {"lead_time"},
    "lead_time_change": {"lead_time"},
    "delivery_delay": {"lead_time"},
    "demand_shift": {"demand"},
    "segment_shift": {"demand"},
    # Unmet catalogue searches are a demand proxy, not a physical stock count.
    "inventory_demand_mismatch": {"demand"},
    "inventory_snapshot": {"stock"},
    "supplier_stock": {"stock"},
    "stock_availability": {"stock"},
    "price_change": {"price"},
    "supplier_price": {"price"},
    "competitor_undercut": {"price", "competition"},
    "competitor_price": {"price", "competition"},
}


def requested_facets(query, *, market_request=False):
    facets = {
        name
        for name, pattern in _QUESTION_PATTERNS.items()
        if re.search(pattern, str(query or ""), re.I)
    }
    if not (
        market_request
        or facets.difference({"forecast", "causality"})
        or re.search(r"\bmarket\b", str(query or ""), re.I)
    ):
        facets.difference_update({"forecast", "causality"})
    if facets.intersection({"price", "demand", "stock", "competition"}) and re.search(
        r"\bnext\s+(?:day|week|month|quarter|year)\b", str(query or ""), re.I
    ):
        facets.add("forecast")
    return sorted(facets)


def finding_facets(finding):
    return _FINDING_FACETS.get(str(finding.get("finding_type") or ""), set())


def finite_measurement(value):
    """Keep numeric observations; do not coerce booleans or prose into measurements."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _time_measurement(finding, kinds, *, signed=False):
    low = finite_measurement(finding.get("magnitude_low"))
    high = finite_measurement(finding.get("magnitude_high"))
    return bool(
        finding.get("finding_type") in kinds
        and finding.get("measurement_definition")
        and str(finding.get("uom") or "").strip().lower()
        in {"day", "days", "calendar days", "business days", "hour", "hours", "week", "weeks"}
        and low is not None and high is not None and low <= high
        and (signed or low >= 0)
    )


def answer_coverage(findings, requested, *, query=None):
    supported = set().union(*(finding_facets(item) for item in findings))
    if "lead_time" in requested:
        text = str(query or "")
        change = bool(re.search(
            r"\b(?:changed|changes|increas(?:ed|ing)|decreas(?:ed|ing)|longer|shorter)\b", text, re.I,
        ))
        delay = bool(re.search(r"\b(?:delays?|late|lateness)\b", text, re.I))
        level = not (change or delay) or bool(re.search(
            r"\b(?:eta|when|how\s+(?:long|soon)|delivery\s+(?:date|window))\b", text, re.I,
        ))
        requirements = []
        if level:
            requirements.append(({"supplier_lead_time", "lead_time"}, False))
        if change:
            requirements.append(({"lead_time_change"}, True))
        if delay:
            requirements.append(({"delivery_delay"}, False))
        # A level, a change from a baseline and a delay against a promise are
        # different measurements. Neither topic labels nor summary prose can
        # substitute for any requested measurement.
        if not all(any(_time_measurement(item, kinds, signed=signed) for item in findings)
                   for kinds, signed in requirements):
            supported.discard("lead_time")
    return sorted(set(requested) & supported), sorted(set(requested) - supported)
