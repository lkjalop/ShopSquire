"""Read-only stakeholder integrity gate over the currently configured tenant.

This does not manufacture ERP, WMS, accounting, or marketing evidence. Missing
feeds are reported as operational gaps; contradictory or under-proven metric
claims are failures.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session
from src.app.services.canonical_fact_adapters import canonical_source_health


def _scalar(db, sql: str, params: dict) -> int:
    try:
        return int(db.execute(text(sql), params).scalar() or 0)
    except Exception:
        return 0


def evaluate(*, tenant_id: str) -> dict:
    with db_session() as db:
        health = canonical_source_health(db, tenant_id=tenant_id)
        bad_gmroi = _scalar(db, """
            SELECT COUNT(*) FROM executive_metric_snapshot
            WHERE tenant_id=:tenant AND metric_name='gmroi'
              AND status IN ('observed','estimated')
              AND (source_count < 1 OR provenance_json IS NULL OR provenance_json IN ('','[]'))
        """, {"tenant": tenant_id})
        bad_ppv = _scalar(db, """
            SELECT COUNT(*) FROM executive_metric_snapshot
            WHERE tenant_id=:tenant AND metric_name='purchase_price_variance'
              AND status='observed' AND source_count < 3
        """, {"tenant": tenant_id})
        forecast_pairs = _scalar(db, """
            SELECT COUNT(*) FROM forecast_actual_pair
            WHERE tenant_id=:tenant AND status='active'
              AND sealed_by IS NOT NULL AND sealed_by <> ''
        """, {"tenant": tenant_id})
        marketing_total = _scalar(db, """
            SELECT COUNT(*) FROM marketing_event_fact
            WHERE tenant_id=:tenant AND status='active'
        """, {"tenant": tenant_id})
        marketing_consent = _scalar(db, """
            SELECT COUNT(*) FROM marketing_event_fact
            WHERE tenant_id=:tenant AND status='active'
              AND consent_state IS NOT NULL AND consent_state <> ''
        """, {"tenant": tenant_id})
        campaign_total = _scalar(db, """
            SELECT COUNT(*) FROM marketing_event_fact
            WHERE tenant_id=:tenant AND status='active'
              AND campaign_id IS NOT NULL AND campaign_id <> ''
        """, {"tenant": tenant_id})
        campaign_attributed = _scalar(db, """
            SELECT COUNT(*) FROM marketing_event_fact
            WHERE tenant_id=:tenant AND status='active'
              AND campaign_id IS NOT NULL AND campaign_id <> ''
              AND attribution_window IS NOT NULL AND attribution_window <> ''
        """, {"tenant": tenant_id})
        interaction_total = _scalar(db, """
            SELECT COUNT(*) FROM recommend_interactions
            WHERE context_json LIKE :tenant
        """, {"tenant": f'%\"tenant_id\": \"{tenant_id}\"%'})
        traced_interactions = _scalar(db, """
            SELECT COUNT(*) FROM recommend_interactions
            WHERE context_json LIKE :tenant
              AND trace_id IS NOT NULL AND trace_id <> ''
        """, {"tenant": f'%\"tenant_id\": \"{tenant_id}\"%'})

    sources = {row["family"]: row for row in health.get("onboarding") or []}
    gates = {
        "cfo_metric_integrity": {
            "pass": bad_gmroi == 0 and bad_ppv == 0,
            "ready": (
                sources.get("landed_inventory_valuation", {}).get("status") == "connected"
                and sources.get("matched_procurement_documents", {}).get("status") == "connected"
            ),
            "invalid_gmroi_claims": bad_gmroi,
            "invalid_ppv_claims": bad_ppv,
            "landed_valuation": sources.get("landed_inventory_valuation", {}).get("status"),
            "matched_documents": sources.get("matched_procurement_documents", {}).get("status"),
        },
        "operations_evidence": {
            "pass": sources.get("inventory_atp", {}).get("status") == "connected",
            "ready": (
                sources.get("inventory_atp", {}).get("status") == "connected"
                and forecast_pairs > 0
            ),
            "atp_status": sources.get("inventory_atp", {}).get("status"),
            "sealed_forecast_pairs": forecast_pairs,
            "forecast_autonomy_ready": forecast_pairs > 0,
        },
        "marketing_governance": {
            "pass": marketing_total == 0 or marketing_consent == marketing_total,
            "ready": (
                marketing_total > 0
                and marketing_consent == marketing_total
                and (campaign_total == 0 or campaign_attributed == campaign_total)
            ),
            "event_count": marketing_total,
            "consent_coverage": marketing_consent / max(1, marketing_total),
            "attribution_coverage": campaign_attributed / max(1, campaign_total),
        },
        "sales_opportunity_quality": {
            "pass": interaction_total == 0 or traced_interactions == interaction_total,
            "ready": interaction_total > 0 and traced_interactions == interaction_total,
            "interaction_count": interaction_total,
            "trace_coverage": traced_interactions / max(1, interaction_total),
            "note": "trace coverage is an integrity gate, not proof of opportunity relevance",
        },
    }
    integrity_pass = all(
        gates[name]["pass"]
        for name in ("cfo_metric_integrity", "marketing_governance",
                     "sales_opportunity_quality")
    )
    return {
        "tenant_id": tenant_id,
        "integrity_pass": integrity_pass,
        "operational_readiness_pass": all(item["ready"] for item in gates.values()),
        "gates": gates,
        "source_health": health,
        "synthetic_canary_equivalent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--output", default="tmp/synthetic_soak/stakeholder_metric_gates.json")
    args = parser.parse_args()
    report = evaluate(tenant_id=str(args.tenant))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "integrity_pass": report["integrity_pass"],
        "operational_readiness_pass": report["operational_readiness_pass"],
        "gates": report["gates"],
    }))
    return 0 if report["integrity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
