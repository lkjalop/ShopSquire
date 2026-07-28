"""Immutable procurement context and shadow replenishment/quote decisions."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from statistics import NormalDist
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.currency_authority import FxAuthority, convert_minor_units
from src.app.services.product_identity import convert_uom


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}_required") from exc
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"{name}_invalid")
    return parsed


def _case_version(db, *, tenant_id: str, case_id: str) -> str:
    row = db.execute(
        text(
            """
            SELECT v.id
            FROM fulfillment_case c
            JOIN fulfillment_case_version v ON v.case_id=c.id
            WHERE c.id=:case_id AND c.tenant_id=:tenant
            ORDER BY CASE WHEN v.valid_to IS NULL THEN 0 ELSE 1 END,
                     v.valid_from DESC, v.created_at DESC
            LIMIT 1
            """
        ),
        {"case_id": case_id, "tenant": tenant_id},
    ).fetchone()
    if not row:
        raise ValueError("procurement_case_not_found")
    return str(row[0])


def _validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    demand = dict(facts.get("demand") or {})
    lead = dict(facts.get("supplier_lead_time") or {})
    inventory = dict(facts.get("inventory") or {})
    commercial = dict(facts.get("commercial") or {})
    uom = dict(facts.get("uom") or {})
    authority = str(facts.get("source_authority") or "").strip()
    if authority not in {"authoritative", "simulation"}:
        raise ValueError("source_authority_required")
    normalized = {
        "demand": {
            "mean_daily": _number(demand.get("mean_daily"), "demand_mean"),
            "variance_daily": _number(demand.get("variance_daily"), "demand_variance"),
            "distribution": str(demand.get("distribution") or "empirical"),
            "forecast_evaluation_id": str(demand.get("forecast_evaluation_id") or ""),
        },
        "supplier_lead_time": {
            "mean_days": _number(lead.get("mean_days"), "lead_time_mean", minimum=0.01),
            "variance_days2": _number(lead.get("variance_days2", 0), "lead_time_variance"),
        },
        "service_level": _number(facts.get("service_level"), "service_level", minimum=0.5),
        "inventory": {
            "current_atp": _number(inventory.get("current_atp"), "current_atp"),
            "incoming_supply": _number(inventory.get("incoming_supply", 0), "incoming_supply"),
        },
        "commercial": {
            "moq": int(_number(commercial.get("moq", 0), "moq")),
            "pack_size": int(_number(commercial.get("pack_size", 1), "pack_size", minimum=1)),
            "price_breaks": sorted(
                [
                    {
                        "min_qty": int(_number(item.get("min_qty"), "price_break_min", minimum=1)),
                        "discount_pct": _number(item.get("discount_pct", 0), "discount_pct"),
                    }
                    for item in (commercial.get("price_breaks") or [])
                    if isinstance(item, dict)
                ],
                key=lambda item: item["min_qty"],
            ),
        },
        "uom": {
            "base_uom": str(uom.get("base_uom") or "").strip(),
            "order_uom": str(uom.get("order_uom") or "").strip(),
            "factor_to_base": _number(uom.get("factor_to_base"), "uom_factor", minimum=0.000001),
        },
        "source_authority": authority,
        "provenance": dict(facts.get("provenance") or {}),
    }
    if normalized["service_level"] >= 1:
        raise ValueError("service_level_invalid")
    if not normalized["uom"]["base_uom"] or not normalized["uom"]["order_uom"]:
        raise ValueError("uom_identity_required")
    if not normalized["provenance"]:
        raise ValueError("decision_context_provenance_required")
    return normalized


def create_case_context_snapshot(
    *,
    tenant_id: str,
    case_id: str,
    facts: dict[str, Any],
    created_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    case = str(case_id or "").strip()
    actor = str(created_by or "").strip()
    if not tenant or not case or not actor:
        raise ValueError("decision_context_scope_required")
    normalized = _validate_facts(facts)
    facts_hash = _hash(normalized)
    now = datetime.now(timezone.utc).isoformat()
    with db_session() as db:
        version_id = _case_version(db, tenant_id=tenant, case_id=case)
        snapshot_id = _hash(
            {
                "tenant_id": tenant,
                "case_id": case,
                "case_version_id": version_id,
                "facts_hash": facts_hash,
            }
        )
        existing = db.execute(
            text("SELECT 1 FROM procurement_case_context_snapshot WHERE id=:id"),
            {"id": snapshot_id},
        ).fetchone()
        if not existing:
            db.execute(
                text(
                    """
                    INSERT INTO procurement_case_context_snapshot
                    (id, tenant_id, case_id, case_version_id, facts_json,
                     facts_hash, source_authority, provenance_json,
                     created_by, created_at)
                    VALUES
                    (:id, :tenant, :case_id, :version, :facts, :facts_hash,
                     :authority, :provenance, :actor, :created)
                    """
                ),
                {
                    "id": snapshot_id,
                    "tenant": tenant,
                    "case_id": case,
                    "version": version_id,
                    "facts": _json(normalized),
                    "facts_hash": facts_hash,
                    "authority": normalized["source_authority"],
                    "provenance": _json(normalized["provenance"]),
                    "actor": actor,
                    "created": now,
                },
            )
            db.commit()
    return {
        "snapshot_id": snapshot_id,
        "case_id": case,
        "case_version_id": version_id,
        "facts_hash": facts_hash,
        "facts": normalized,
        "source_authority": normalized["source_authority"],
        "duplicate": bool(existing),
        "immutable": True,
    }


def calculate_replenishment(facts: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_facts(facts)
    demand = normalized["demand"]
    lead = normalized["supplier_lead_time"]
    inventory = normalized["inventory"]
    commercial = normalized["commercial"]
    z_score = NormalDist().inv_cdf(normalized["service_level"])
    safety_variance = (
        lead["mean_days"] * demand["variance_daily"]
        + (demand["mean_daily"] ** 2) * lead["variance_days2"]
    )
    safety_stock = z_score * math.sqrt(max(0.0, safety_variance))
    reorder_point = demand["mean_daily"] * lead["mean_days"] + safety_stock
    net_requirement = max(
        0.0,
        reorder_point - inventory["current_atp"] - inventory["incoming_supply"],
    )
    suggested = int(math.ceil(net_requirement))
    if suggested > 0:
        suggested = max(suggested, commercial["moq"])
        suggested = int(
            math.ceil(suggested / commercial["pack_size"]) * commercial["pack_size"]
        )
    applicable_breaks = [
        item for item in commercial["price_breaks"] if item["min_qty"] <= suggested
    ]
    selected_break = applicable_breaks[-1] if applicable_breaks else None
    return {
        "formula": "normal_demand_variable_lead_time_v1",
        "z_score": round(z_score, 6),
        "safety_stock_units": round(safety_stock, 4),
        "reorder_point_units": round(reorder_point, 4),
        "net_requirement_units": round(net_requirement, 4),
        "suggested_order_units": suggested,
        "moq_units": commercial["moq"],
        "pack_size_units": commercial["pack_size"],
        "selected_price_break": selected_break,
        "current_atp": inventory["current_atp"],
        "incoming_supply": inventory["incoming_supply"],
        "service_level": normalized["service_level"],
        "source_authority": normalized["source_authority"],
        "can_execute": False,
        "human_approval_required": True,
    }


def create_replenishment_proposal(
    *,
    tenant_id: str,
    case_id: str,
    context_snapshot_id: str,
    created_by: str,
) -> dict[str, Any]:
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT facts_json, source_authority
                FROM procurement_case_context_snapshot
                WHERE id=:snapshot AND tenant_id=:tenant AND case_id=:case_id
                """
            ),
            {
                "snapshot": context_snapshot_id,
                "tenant": tenant_id,
                "case_id": case_id,
            },
        ).fetchone()
        if not row:
            raise ValueError("decision_context_snapshot_not_found")
        facts = json.loads(str(row[0]))
        result = calculate_replenishment(facts)
        blocked = (
            ["non_authoritative_inputs"]
            if str(row[1]) != "authoritative"
            else ["human_approval_required"]
        )
        status = "simulation_only" if str(row[1]) != "authoritative" else "human_review_required"
        proposal_id = _hash(
            {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "context_snapshot_id": context_snapshot_id,
                "result": result,
            }
        )
        existing = db.execute(
            text("SELECT 1 FROM replenishment_decision_proposal WHERE id=:id"),
            {"id": proposal_id},
        ).fetchone()
        if not existing:
            db.execute(
                text(
                    """
                    INSERT INTO replenishment_decision_proposal
                    (id, tenant_id, case_id, context_snapshot_id, result_json,
                     status, blocked_reasons_json, authority, created_by, created_at)
                    VALUES
                    (:id, :tenant, :case_id, :snapshot, :result, :status,
                     :blocked, 'proposal_only', :actor, :created)
                    """
                ),
                {
                    "id": proposal_id,
                    "tenant": tenant_id,
                    "case_id": case_id,
                    "snapshot": context_snapshot_id,
                    "result": _json(result),
                    "status": status,
                    "blocked": _json(blocked),
                    "actor": created_by,
                    "created": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.commit()
    return {
        "proposal_id": proposal_id,
        "context_snapshot_id": context_snapshot_id,
        "status": status,
        "blocked_reasons": blocked,
        "authority": "proposal_only",
        "result": result,
        "duplicate": bool(existing),
    }


def compare_landed_cost_quotes(
    *,
    tenant_id: str,
    case_id: str,
    context_snapshot_id: str,
    target_currency: str,
    target_uom: str,
    quotes: list[dict[str, Any]],
    created_by: str,
    at_time: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    case = str(case_id or "").strip()
    target_currency = str(target_currency or "").strip().upper()
    target_uom = str(target_uom or "").strip().upper()
    if not tenant or not case or not target_currency or not target_uom:
        raise ValueError("landed_cost_comparison_scope_required")
    decision_time = at_time or datetime.now(timezone.utc).isoformat()
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for quote in quotes:
        quote_id = str(quote.get("quote_id") or quote.get("supplier_id") or "")
        try:
            if not quote_id:
                raise ValueError("quote_identity_required")
            if not isinstance(quote.get("provenance"), dict) or not quote["provenance"]:
                raise ValueError("quote_provenance_required")
            quote_uom = str(quote.get("quote_uom") or "").strip().upper()
            factor = convert_uom(
                tenant_id=tenant,
                value=Decimal(1),
                from_code=quote_uom,
                to_code=target_uom,
            )
            if factor <= 0:
                raise ValueError("uom_factor_invalid")
            amount = int(quote["purchase_unit_cost_minor"])
            amount += int(quote.get("freight_unit_minor") or 0)
            amount += int(quote.get("duty_unit_minor") or 0)
            amount += int(quote.get("handling_unit_minor") or 0)
            quantity = int(quote.get("quantity") or 1)
            breaks = sorted(
                [item for item in (quote.get("price_breaks") or []) if isinstance(item, dict)],
                key=lambda item: int(item.get("min_qty") or 0),
            )
            applicable = [item for item in breaks if int(item.get("min_qty") or 0) <= quantity]
            discount = Decimal(str((applicable[-1] if applicable else {}).get("discount_pct") or 0))
            amount = int(
                (Decimal(amount) * (Decimal(1) - discount / Decimal(100))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_EVEN
                )
            )
            fx_payload = quote.get("fx_authority")
            authority = FxAuthority(**fx_payload) if isinstance(fx_payload, dict) else None
            converted = convert_minor_units(
                amount,
                from_currency=str(quote.get("currency") or ""),
                to_currency=target_currency,
                authority=authority,
                at_time=decision_time,
            )
            per_base = (Decimal(int(converted["amount_minor"])) / factor).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_EVEN
            )
            ranked.append(
                {
                    "quote_id": quote_id,
                    "supplier_id": quote.get("supplier_id"),
                    "comparable_landed_unit_minor": str(per_base),
                    "currency": target_currency,
                    "uom": target_uom,
                    "quote_uom": quote_uom,
                    "factor_to_base": str(factor),
                    "uom_authority": "tenant_uom_registry",
                    "fx": converted.get("fx_authority"),
                    "selected_price_break": applicable[-1] if applicable else None,
                    "provenance": quote.get("provenance"),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            excluded.append({"quote_id": quote_id, "reason": str(exc)})
    ranked.sort(key=lambda item: (Decimal(item["comparable_landed_unit_minor"]), item["quote_id"]))
    result = {
        "ranked": ranked,
        "recommended": ranked[0] if ranked else None,
        "excluded": excluded,
        "status": "observed" if ranked else "undefined",
        "authority": "comparison_only",
        "can_authorize_purchase": False,
    }
    comparison_id = _hash(
        {
            "tenant_id": tenant,
            "case_id": case,
            "context_snapshot_id": context_snapshot_id,
            "target_currency": target_currency,
            "target_uom": target_uom,
            "quotes": quotes,
        }
    )
    with db_session() as db:
        snapshot = db.execute(
            text(
                "SELECT 1 FROM procurement_case_context_snapshot "
                "WHERE id=:snapshot AND tenant_id=:tenant AND case_id=:case_id"
            ),
            {"snapshot": context_snapshot_id, "tenant": tenant, "case_id": case},
        ).fetchone()
        if not snapshot:
            raise ValueError("decision_context_snapshot_not_found")
        if not db.execute(
            text("SELECT 1 FROM landed_cost_quote_comparison WHERE id=:id"),
            {"id": comparison_id},
        ).fetchone():
            db.execute(
                text(
                    """
                    INSERT INTO landed_cost_quote_comparison
                    (id, tenant_id, case_id, context_snapshot_id, target_currency,
                     target_uom, comparison_json, status, authority, created_by, created_at)
                    VALUES
                    (:id, :tenant, :case_id, :snapshot, :currency, :uom,
                     :comparison, :status, 'comparison_only', :actor, :created)
                    """
                ),
                {
                    "id": comparison_id,
                    "tenant": tenant,
                    "case_id": case,
                    "snapshot": context_snapshot_id,
                    "currency": target_currency,
                    "uom": target_uom,
                    "comparison": _json(result),
                    "status": result["status"],
                    "actor": created_by,
                    "created": decision_time,
                },
            )
            db.commit()
    result["comparison_id"] = comparison_id
    return result


def latest_case_decision_intelligence(*, tenant_id: str, case_id: str) -> dict[str, Any]:
    with db_session() as db:
        context = db.execute(
            text(
                """
                SELECT id, case_version_id, facts_json, facts_hash, source_authority,
                       provenance_json, created_by, created_at
                FROM procurement_case_context_snapshot
                WHERE tenant_id=:tenant AND case_id=:case_id
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tenant": tenant_id, "case_id": case_id},
        ).fetchone()
        if not context:
            return {"status": "not_materialized", "context": None, "proposal": None, "comparison": None}
        proposal = db.execute(
            text(
                """
                SELECT id, result_json, status, blocked_reasons_json, authority, created_at
                FROM replenishment_decision_proposal
                WHERE tenant_id=:tenant AND case_id=:case_id AND context_snapshot_id=:snapshot
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tenant": tenant_id, "case_id": case_id, "snapshot": context[0]},
        ).fetchone()
        comparison = db.execute(
            text(
                """
                SELECT id, comparison_json, status, authority, created_at
                FROM landed_cost_quote_comparison
                WHERE tenant_id=:tenant AND case_id=:case_id AND context_snapshot_id=:snapshot
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tenant": tenant_id, "case_id": case_id, "snapshot": context[0]},
        ).fetchone()
    return {
        "status": "available",
        "context": {
            "snapshot_id": context[0],
            "case_version_id": context[1],
            "facts": json.loads(context[2]),
            "facts_hash": context[3],
            "source_authority": context[4],
            "provenance": json.loads(context[5]),
            "created_by": context[6],
            "created_at": str(context[7]),
            "immutable": True,
        },
        "proposal": (
            {
                "proposal_id": proposal[0],
                "result": json.loads(proposal[1]),
                "status": proposal[2],
                "blocked_reasons": json.loads(proposal[3]),
                "authority": proposal[4],
                "created_at": str(proposal[5]),
            }
            if proposal else None
        ),
        "comparison": (
            {
                "comparison_id": comparison[0],
                **json.loads(comparison[1]),
                "status": comparison[2],
                "authority": comparison[3],
                "created_at": str(comparison[4]),
            }
            if comparison else None
        ),
    }
