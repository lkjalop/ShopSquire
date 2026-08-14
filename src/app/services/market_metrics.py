"""Read-only, tenant-scoped commerce metrics over canonical marketing facts.

These metrics inform operators and experiments. They never authorize pricing,
ranking, inventory, or supplier actions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from sqlalchemy import text

from src.app.services.behavioral_signal_projection import project_behavioral_signals


_ENTRY_EVENTS = {"impression", "view", "view_item", "view_item_list"}
_CART_EVENTS = {"add_to_cart"}
_PURCHASE_EVENTS = {"purchase"}
_RETURN_EVENTS = {"refund", "return"}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _session_sets(rows: Iterable[Dict[str, Any]]) -> Dict[str, set[str]]:
    stages = {"entered": set(), "clicked": set(), "carted": set(), "purchased": set(), "returned": set()}
    for row in rows:
        session = str(row.get("session_id") or "").strip()
        if not session:
            continue
        event = str(row.get("event_type") or "").lower()
        if event in _ENTRY_EVENTS:
            stages["entered"].add(session)
        elif event == "click" or event == "select_item":
            stages["clicked"].add(session)
        elif event in _CART_EVENTS:
            stages["carted"].add(session)
        elif event in _PURCHASE_EVENTS:
            stages["purchased"].add(session)
        elif event in _RETURN_EVENTS:
            stages["returned"].add(session)
    return stages


def summarize_marketing_facts(db, *, tenant_id: str, min_action_sample: int = 10) -> Dict[str, Any]:
    """Return a BI-safe summary for one tenant; no cross-tenant or raw PII output."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    records = db.execute(text("""
        SELECT event_type, session_id, sku, campaign_id, channel, value, currency,
               quantity, consent_state, source_system, source_record_id, provenance_json,
               confidence, occurred_at, ingested_at, status
        FROM marketing_event_fact
        WHERE tenant_id=:tenant AND status='active'
        ORDER BY occurred_at, id
    """), {"tenant": tenant}).mappings().all()
    rows = [dict(row) for row in records]
    behavioral = project_behavioral_signals(rows)
    counts = Counter(str(row.get("event_type") or "unknown").lower() for row in rows)
    stages = _session_sets(rows)
    total = len(rows)
    sessions = {str(row.get("session_id")) for row in rows if row.get("session_id")}
    source_complete = sum(bool(row.get("source_system") and row.get("source_record_id")) for row in rows)
    provenance_complete = sum(bool(row.get("provenance_json") and row.get("occurred_at") and row.get("ingested_at")) for row in rows)
    consent_known = sum(str(row.get("consent_state") or "").lower() in {"granted", "denied", "not_required"} for row in rows)
    monetary = [row for row in rows if row.get("value") is not None]
    currency_complete = sum(bool(row.get("currency")) for row in monetary)

    by_sku: Dict[str, Counter] = defaultdict(Counter)
    by_campaign: Dict[str, Counter] = defaultdict(Counter)
    by_month: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event = str(row.get("event_type") or "unknown").lower()
        if row.get("sku"):
            by_sku[str(row["sku"])][event] += 1
        if row.get("campaign_id"):
            by_campaign[str(row["campaign_id"])][event] += 1
        occurred = str(row.get("occurred_at") or "")
        month = occurred[:7] if len(occurred) >= 7 else "unknown"
        cohort = by_month.setdefault(month, {
            "events": Counter(), "sessions": set(), "purchase_value_cents_by_currency": Counter(),
        })
        cohort["events"][event] += 1
        if row.get("session_id"):
            cohort["sessions"].add(str(row["session_id"]))
        if event == "purchase" and row.get("value") is not None and row.get("currency"):
            cohort["purchase_value_cents_by_currency"][str(row["currency"])] += int(row["value"])

    entered = len(stages["entered"])
    carted = len(stages["carted"])
    purchased = len(stages["purchased"])
    returned = len(stages["returned"])
    insights: List[Dict[str, Any]] = []
    abandonment = next(
        (item for item in behavioral.measurements if item.metric == "cart_abandonment_rate"),
        None,
    )
    if (
        abandonment is not None
        and abandonment.value is not None
        and int(abandonment.denominator or 0) >= min_action_sample
    ):
        rate = float(abandonment.value)
        if rate >= 0.35:
            insights.append({
                "type": "cart_abandonment", "sample": abandonment.denominator,
                "rate": round(rate, 4),
                "confidence": "eligible", "action": "inspect checkout friction by stage and device",
                "authority": "operator_advisory",
            })
    for sku, sku_counts in sorted(by_sku.items()):
        interest = sku_counts["click"] + sku_counts["select_item"]
        buys = sku_counts["purchase"]
        if interest >= min_action_sample and buys / interest < 0.1:
            insights.append({
                "type": "high_interest_low_conversion", "sku": sku, "sample": interest,
                "rate": round(buys / interest, 4), "confidence": "eligible",
                "action": "review price, availability, content quality, and compatibility evidence",
                "authority": "operator_advisory",
            })

    return {
        "tenant_id": tenant,
        "event_count": total,
        "unique_sessions": len(sessions),
        "events": dict(sorted(counts.items())),
        "funnel": {
            "entered_sessions": entered,
            "carted_sessions": carted,
            "purchased_sessions": purchased,
            "returned_sessions": returned,
            "entry_to_purchase_rate": _rate(purchased, entered),
            "cart_to_purchase_rate": _rate(purchased, carted),
            "return_to_purchase_rate": _rate(returned, purchased),
        },
        "data_quality": {
            "source_identity_rate": _rate(source_complete, total),
            "provenance_time_rate": _rate(provenance_complete, total),
            "consent_state_rate": _rate(consent_known, total),
            "monetary_currency_rate": _rate(currency_complete, len(monetary)),
            "right_censored_sessions": behavioral.right_censored_sessions,
            "withheld_sessions": behavioral.withheld_sessions,
        },
        "behavioral_signal_truth": behavioral.model_dump(mode="json"),
        "sku_cohorts": {sku: dict(sorted(values.items())) for sku, values in sorted(by_sku.items())},
        "campaign_cohorts": {key: dict(sorted(values.items())) for key, values in sorted(by_campaign.items())},
        "month_cohorts": {
            month: {
                "event_count": sum(cohort["events"].values()),
                "unique_sessions": len(cohort["sessions"]),
                "events": dict(sorted(cohort["events"].items())),
                "purchase_value_cents_by_currency": dict(
                    sorted(cohort["purchase_value_cents_by_currency"].items())
                ),
            }
            for month, cohort in sorted(by_month.items())
        },
        "insights": insights,
        "authority": "read_only_operator_advisory",
    }


def cohort_safe_behavior_projection(
    db, *, tenant_id: str, minimum_sessions: int = 5,
) -> Dict[str, Any]:
    """Return aggregate behavior truth without session, user, or case identifiers."""
    report = summarize_marketing_facts(db, tenant_id=tenant_id)
    sample = int(report.get("unique_sessions") or 0)
    base = {
        "schema_version": "cohort-behavior-trace-v1",
        "cohort_scope": "tenant_aggregate",
        "minimum_sessions": minimum_sessions,
        "individual_behavior_hidden": True,
        "authority": "read_only_advisory",
    }
    if sample < max(1, int(minimum_sessions)):
        return {**base, "status": "suppressed_small_cohort", "sample_size": None,
                "measurements": []}
    behavioral = dict(report.get("behavioral_signal_truth") or {})
    allowed_metrics = {"hover_to_click_rate", "click_to_cart_rate", "cart_abandonment_rate"}
    measurements = [item for item in behavioral.get("measurements", [])
                    if str(item.get("metric")) in allowed_metrics]
    return {
        **base, "status": "aggregated", "sample_size": sample,
        "measurements": measurements,
        "right_censored_sessions": behavioral.get("right_censored_sessions", 0),
        "withheld_sessions": behavioral.get("withheld_sessions", 0),
    }
