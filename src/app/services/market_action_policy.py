"""Governed authorization for replenishment advice.

Models and detectors may propose an action. This policy authorizes only when independent,
fresh evidence proves demand, ATP deficit, lead-time exposure, and viable economics.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _is_upward(fact: Dict[str, Any]) -> bool:
    direction = str(fact.get("direction") or "").lower()
    summary = str(fact.get("summary") or "").lower()
    return direction in {"up", "rising", "growth", "increase"} or any(
        token in summary for token in ("spike", "growth", "trending up", "increased", "rising"))


def authorize_replenishment(
    *, demand_facts: Iterable[Dict[str, Any]], atp: Dict[str, Any], economics: Dict[str, Any],
    now: datetime | None = None, min_confidence: float = 0.7,
    max_demand_age_seconds: int = 7 * 86400, min_source_diversity: int = 2,
) -> Dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    eligible = []
    for fact in demand_facts or []:
        observed = _time(fact.get("observed_at") or fact.get("detected_at"))
        scope = str(fact.get("scope") or "").lower()
        if scope not in {"this_item", "this_product", "taxonomy"}:
            continue
        if float(fact.get("confidence") or 0.0) < min_confidence or not _is_upward(fact):
            continue
        if observed is None or (current - observed).total_seconds() > max_demand_age_seconds:
            continue
        if not fact.get("source_system") or not fact.get("provenance_chain"):
            continue
        eligible.append(fact)

    sources = {str(f.get("source_system")) for f in eligible}
    shortfall = max(0, int(atp.get("shortfall") or 0))
    lead_time = float(atp.get("lead_time_days") or 0.0)
    margin_authoritative = (
        bool(economics.get("available")) and bool(economics.get("clears_floor"))
        and str(economics.get("cost_basis") or "")
        == "validated_landed_supplier_quote"
    )
    reasons = []
    if len(sources) < int(min_source_diversity):
        reasons.append("insufficient_independent_demand_sources")
    if shortfall <= 0:
        reasons.append("no_atp_deficit")
    if lead_time <= 0:
        reasons.append("missing_supplier_lead_time")
    if not margin_authoritative:
        reasons.append("unverified_or_unprofitable_cost_basis")
    return {
        "allowed": not reasons,
        "decision": "replenish_advisory" if not reasons else "insufficient_evidence",
        "reasons": reasons,
        "demand_source_count": len(sources),
        "qualified_demand_facts": len(eligible),
        "shortfall": shortfall,
        "lead_time_days": lead_time or None,
        "authority": "operator_advisory_only",
    }
