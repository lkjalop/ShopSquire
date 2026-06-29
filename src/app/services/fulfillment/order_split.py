"""Multi-line procurement split planning.

The fulfillment case/draft domain is currently one commercial scope per case:
``{item_ref, quantity}``. For mixed buyer requests, the safe behavior is therefore
to split the request into one sourcing line per SKU and group those lines by the
approved supplier that would receive the RFQ. This module is read-only planning:
it never contacts a supplier and never creates a PO.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _supplier_rows(db, sku: str, limit: int = 5) -> List[Dict[str, Any]]:
    if db is None or not sku:
        return []
    try:
        from src.app.services.supplier_catalog import ensure_tables
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT s.id, s.name, s.unit_cost, "
            "COALESCE(sp.lead_time_days, s.lead_time_days, 999) AS lead_time_days, "
            "COALESCE(sp.on_time_rate, s.on_time_rate, 0) AS on_time_rate, "
            "COALESCE(s.reliability_score, 0) AS reliability_score, "
            "COALESCE(sp.active,1) AS product_active, COALESCE(s.active,1) AS supplier_active "
            "FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
            "WHERE sp.sku = :sku AND COALESCE(sp.active,1)=1 AND COALESCE(s.active,1)=1 "
            "ORDER BY (COALESCE(sp.on_time_rate, s.on_time_rate, 0) * 0.45 "
            "       + COALESCE(s.reliability_score, 0) * 0.35 "
            "       - COALESCE(sp.lead_time_days, s.lead_time_days, 999) * 0.01 "
            "       - COALESCE(s.unit_cost, 0) * 0.00001) DESC "
            "LIMIT :limit"
        ), {"sku": str(sku), "limit": int(limit)}).fetchall()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({
            "supplier_id": str(r[0]),
            "supplier_name": str(r[1] or r[0]),
            "unit_cost": r[2],
            "lead_time_days": _int(r[3]),
            "on_time_rate": float(r[4] or 0.0),
            "reliability": float(r[5] or 0.0),
        })
    return out


def _contact_for_domain(domain: str, *, tenant_id: str = "default") -> Optional[str]:
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain
        v = lookup_vendor_by_domain(tenant_id=tenant_id, domain=domain) or {}
        email = str(v.get("contact_email") or "").strip()
        if email and email.lower().endswith(f"@{domain.lower()}"):
            return email
    except Exception:
        pass
    return None


def plan_order_split(db, *, lines: List[Dict[str, Any]], tenant_id: str = "default") -> Dict[str, Any]:
    """Plan a mixed procurement request into supplier groups.

    Input lines are vertical-blind dictionaries containing ``item_ref``,
    ``requested_qty`` and optional ``in_stock``. The output is buyer/admin safe:
    each sourcing line carries the approved supplier selected from the catalog
    and the terms the operator needs to judge MOQ/min-value/price-break risk.
    """
    from src.app.services import supplier_catalog

    groups: Dict[str, Dict[str, Any]] = {}
    line_out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(lines or []):
        item_ref = str(raw.get("item_ref") or raw.get("sku") or "").strip()
        requested = max(0, _int(raw.get("requested_qty", raw.get("quantity")), 0))
        in_stock = max(0, _int(raw.get("in_stock"), 0))
        shortfall = max(0, requested - in_stock)
        line = {
            "line_id": str(raw.get("line_id") or f"line-{idx + 1}"),
            "item_ref": item_ref,
            "requested_qty": requested,
            "in_stock": in_stock,
            "shortfall": shortfall,
            "status": "fillable_from_stock" if shortfall <= 0 else "needs_sourcing",
        }
        if shortfall <= 0 or not item_ref:
            line_out.append(line)
            continue

        ranked = _supplier_rows(db, item_ref, limit=3)
        if not ranked:
            line.update({"status": "no_approved_supplier", "supplier_candidates": []})
            line_out.append(line)
            continue

        best = ranked[0]
        sid = best["supplier_id"]
        domain = supplier_catalog.domain_for_supplier(db, sid)
        terms = supplier_catalog.supplier_terms(db, sid, item_ref, tenant_id=tenant_id)
        advisory = supplier_catalog.price_break_advisory(shortfall, terms)
        contact = _contact_for_domain(domain or "", tenant_id=tenant_id) if domain else None
        line.update({
            "supplier_ref": sid,
            "supplier_name": best["supplier_name"],
            "recipient_domain": domain,
            "recipient_email": contact,
            "supplier_terms": terms,
            "below_moq": bool(terms.get("moq") and shortfall < _int(terms.get("moq"))),
            "price_break_advisory": advisory,
            "supplier_candidates": ranked,
        })
        group_key = f"{sid}:{domain or ''}"
        group = groups.setdefault(group_key, {
            "group_id": group_key,
            "supplier_ref": sid,
            "supplier_name": best["supplier_name"],
            "recipient_domain": domain,
            "recipient_email": contact,
            "case_model": "one_case_per_sku",
            "lines": [],
            "total_shortfall": 0,
        })
        group["lines"].append(line)
        group["total_shortfall"] += shortfall
        line_out.append(line)

    return {
        "line_count": len(line_out),
        "sourcing_line_count": sum(1 for l in line_out if l.get("status") == "needs_sourcing"),
        "group_count": len(groups),
        "case_model": "one_case_per_sku_or_supplier_group",
        "groups": list(groups.values()),
        "lines": line_out,
    }


def emit_split_trace(trace_id: Optional[str], *, plan: Dict[str, Any]) -> None:
    if not trace_id:
        return
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=trace_id,
            event_type="procurement_order_split",
            source_type="agent",
            source_id="Procurement_Split_Agent",
            target_type="procurement_order",
            target_id=None,
            payload={
                "line_count": plan.get("line_count"),
                "sourcing_line_count": plan.get("sourcing_line_count"),
                "group_count": plan.get("group_count"),
                "groups": [
                    {
                        "supplier_ref": g.get("supplier_ref"),
                        "recipient_domain": g.get("recipient_domain"),
                        "line_count": len(g.get("lines") or []),
                        "total_shortfall": g.get("total_shortfall"),
                    }
                    for g in (plan.get("groups") or [])
                ],
            },
            durable=True,
        )
    except Exception:
        pass
