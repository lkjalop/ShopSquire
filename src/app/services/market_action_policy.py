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
    return direction in {"up", "rising", "growth", "increase", "spike"}


def authorize_replenishment(
    *, demand_facts: Iterable[Dict[str, Any]], atp: Dict[str, Any], economics: Dict[str, Any],
    now: datetime | None = None, min_confidence: float = 0.7,
    max_demand_age_seconds: int = 7 * 86400, max_atp_age_seconds: int = 86400,
    min_source_diversity: int = 2,
    tenant_id: str | None = None, sku: str | None = None,
    taxonomy_node: str | None = None, currency: str | None = None,
    forecast_quality: Dict[str, Any] | None = None,
    authority_readiness: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expected_tenant = str(tenant_id or "").strip()
    expected_sku = str(sku or "").strip()
    expected_taxonomy = str(taxonomy_node or "").strip()
    expected_currency = str(currency or "").strip().upper()

    def _same_tenant(fact: Dict[str, Any]) -> bool:
        return not expected_tenant or str(fact.get("tenant_id") or "").strip() == expected_tenant

    def _same_subject(fact: Dict[str, Any]) -> bool:
        if not expected_sku and not expected_taxonomy:
            return True
        fact_sku = str(fact.get("sku") or fact.get("subject_id") or "").strip()
        fact_taxonomy = str(fact.get("taxonomy_node") or "").strip()
        if expected_sku:
            return fact_sku == expected_sku
        return bool(expected_taxonomy and fact_taxonomy == expected_taxonomy)

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
        if not _same_tenant(fact) or not _same_subject(fact):
            continue
        eligible.append(fact)

    # Adapter names are not independent evidence when they derive from the same root event.
    sources = {
        str(f.get("lineage_root") or "").strip()
        for f in eligible
        if str(f.get("lineage_root") or "").strip()
    }
    shortfall = max(0, int(atp.get("shortfall") or 0))
    lead_time = float(atp.get("lead_time_days") or 0.0)
    atp_observed = _time(atp.get("observed_at"))
    atp_age = (current - atp_observed).total_seconds() if atp_observed else None
    atp_authoritative = (
        atp_observed is not None
        and -300 <= float(atp_age) <= float(max_atp_age_seconds)
        and float(atp.get("confidence") or 0.0) >= min_confidence
        and bool(atp.get("source_system"))
        and bool(atp.get("provenance_chain"))
        and _same_tenant(atp)
        and _same_subject(atp)
    )
    economics_currency = str(economics.get("currency") or "").strip().upper()
    margin_authoritative = (
        bool(economics.get("available")) and bool(economics.get("clears_floor"))
        and str(economics.get("cost_basis") or "")
        == "validated_landed_supplier_quote"
        and bool(economics.get("source_record_id"))
        and bool(economics.get("provenance_chain"))
        and _same_tenant(economics)
        and _same_subject(economics)
        and (not expected_currency or economics_currency == expected_currency)
    )
    reasons = []
    if len(sources) < int(min_source_diversity):
        reasons.append("insufficient_independent_demand_sources")
    if shortfall <= 0:
        reasons.append("no_atp_deficit")
    if lead_time <= 0:
        reasons.append("missing_supplier_lead_time")
    if not atp_authoritative:
        reasons.append("untrusted_or_stale_atp")
    if not margin_authoritative:
        reasons.append("unverified_or_unprofitable_cost_basis")
    quality = forecast_quality or {}
    quality_status = str(quality.get("status") or "unavailable")
    quality_wape = quality.get("wape")
    quality_coverage = float(quality.get("coverage") or 0.0)
    forecast_quality_shadow = {
        "mode": "shadow",
        "status": quality_status,
        "wape": quality_wape,
        "coverage": quality_coverage,
        "would_pass": bool(
            quality_status == "observed"
            and quality_wape is not None
            and float(quality_wape) <= 0.35
            and quality_coverage >= 0.5),
    }
    readiness = authority_readiness or {}
    autonomous_execution_allowed = bool(
        not reasons
        and readiness.get("forecast_outcome_calibrated")
        and readiness.get("supplier_score_outcome_calibrated")
        and readiness.get("market_source_licensed")
        and readiness.get("human_policy_approved")
    )
    return {
        "allowed": not reasons,
        "decision": "replenish_advisory" if not reasons else "insufficient_evidence",
        "reasons": reasons,
        "demand_source_count": len(sources),
        "qualified_demand_facts": len(eligible),
        "shortfall": shortfall,
        "lead_time_days": lead_time or None,
        "atp_authoritative": atp_authoritative,
        "economics_authoritative": margin_authoritative,
        "forecast_quality_shadow": forecast_quality_shadow,
        "autonomous_execution_allowed": autonomous_execution_allowed,
        "autonomy_blockers": (
            [] if autonomous_execution_allowed else [
                key for key in (
                    "forecast_outcome_calibrated",
                    "supplier_score_outcome_calibrated",
                    "market_source_licensed",
                    "human_policy_approved",
                ) if not readiness.get(key)
            ]
        ),
        "authority": "operator_advisory_only",
    }
