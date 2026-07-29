"""Qualified-alternative comparison and supplier communication drafts.

This module never dispatches a message or authorizes a purchase. Qualification
comes only from the evidence sealed with a grounded hypothesis.
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import text

from src.app.services.currency_authority import (
    convert_minor_units,
    latest_fx_authority,
)
from src.app.services.product_identity import governed_convert_uom
from src.app.services.supplier_communication import draft_supplier_message
from src.app.services.supply_hypothesis_workflow import get_grounded_hypothesis


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _connects(edge: dict[str, Any], left: str, right: str) -> bool:
    return {
        str(edge.get("from_node_id") or ""),
        str(edge.get("to_node_id") or ""),
    } == {left, right}


def _qualified_candidates(
    *, target_node_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    target = str(target_node_id)
    node_by_id = {str(row.get("id")): row for row in nodes}
    qualification_edges = [
        row for row in edges
        if str(row.get("relationship_type")) == "qualified_substitute_for"
        and target in {
            str(row.get("from_node_id") or ""),
            str(row.get("to_node_id") or ""),
        }
    ]
    candidates: dict[str, dict[str, Any]] = {}
    for qualification in qualification_edges:
        candidate_id = (
            str(qualification["to_node_id"])
            if str(qualification["from_node_id"]) == target
            else str(qualification["from_node_id"])
        )
        certification = next(
            (
                row for row in edges
                if str(row.get("relationship_type")) == "certified_for"
                and _connects(row, candidate_id, target)
            ),
            None,
        )
        if certification is None:
            continue
        compatibility = [
            row for row in edges
            if str(row.get("relationship_type")) == "compatible_with"
            and _connects(row, candidate_id, target)
        ]
        candidates[candidate_id] = {
            "candidate_node": node_by_id.get(candidate_id, {"id": candidate_id}),
            "qualification_edge": qualification,
            "certification_edge": certification,
            "compatibility_edges": compatibility,
        }
    return candidates


def _supplier_for_candidate(
    *,
    candidate_id: str,
    supplier_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    node = next(
        (
            row for row in nodes
            if str(row.get("id")) == supplier_id
            and str(row.get("node_type")) == "supplier"
        ),
        None,
    )
    if node is None:
        return None
    linked = any(
        str(row.get("relationship_type")) == "supplied_by"
        and str(row.get("from_node_id")) == candidate_id
        and str(row.get("to_node_id")) == supplier_id
        for row in edges
    )
    return node if linked else None


def _compare_quote(
    *,
    tenant_id: str,
    quote: dict[str, Any],
    target_currency: str,
    target_uom: str,
    decision_time: str,
) -> dict[str, Any]:
    quote_id = str(quote.get("quote_id") or "").strip()
    if not quote_id:
        raise ValueError("quote_identity_required")
    if not isinstance(quote.get("provenance"), dict) or not quote["provenance"]:
        raise ValueError("quote_provenance_required")
    source_uom = str(quote.get("quote_uom") or "").strip().upper()
    conversion = governed_convert_uom(
        tenant_id=tenant_id,
        value=Decimal(1),
        from_code=source_uom,
        to_code=target_uom,
        at_time=decision_time,
    )
    if conversion.status != "comparable" or conversion.value is None:
        raise ValueError(f"uom_incomparable:{conversion.reason}")
    amount = (
        int(quote["purchase_unit_cost_minor"])
        + int(quote.get("freight_unit_minor") or 0)
        + int(quote.get("duty_unit_minor") or 0)
        + int(quote.get("handling_unit_minor") or 0)
    )
    quantity = int(quote.get("quantity") or 1)
    breaks = sorted(
        [
            item for item in quote.get("price_breaks") or []
            if isinstance(item, dict)
        ],
        key=lambda item: int(item.get("min_qty") or 0),
    )
    applicable = [
        item for item in breaks if int(item.get("min_qty") or 0) <= quantity
    ]
    selected_break = applicable[-1] if applicable else None
    discount = Decimal(str((selected_break or {}).get("discount_pct") or 0))
    amount = int(
        (Decimal(amount) * (Decimal(1) - discount / Decimal(100))).quantize(
            Decimal(1), rounding=ROUND_HALF_EVEN
        )
    )
    source_currency = str(quote.get("currency") or "").strip().upper()
    authority = (
        latest_fx_authority(
            tenant_id=tenant_id,
            base_currency=source_currency,
            quote_currency=target_currency,
            at_time=decision_time,
        )
        if source_currency != target_currency
        else None
    )
    converted = convert_minor_units(
        amount,
        from_currency=source_currency,
        to_currency=target_currency,
        authority=authority,
        at_time=decision_time,
    )
    unit_minor = (
        Decimal(int(converted["amount_minor"])) / conversion.value
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    return {
        "quote_id": quote_id,
        "candidate_node_id": str(quote.get("candidate_node_id") or ""),
        "supplier_node_id": str(quote.get("supplier_node_id") or ""),
        "comparable_landed_unit_minor": str(unit_minor),
        "currency": target_currency,
        "uom": target_uom,
        "quote_uom": source_uom,
        "uom_authority_id": conversion.authority_id,
        "uom_authority_source": conversion.source,
        "fx_authority": converted.get("fx_authority"),
        "selected_price_break": selected_break,
        "provenance": quote["provenance"],
    }


def propose_qualified_alternatives(
    db,
    *,
    tenant_id: str,
    hypothesis_id: str,
    target_currency: str,
    target_uom: str,
    quotes: list[dict[str, Any]],
    created_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    actor = str(created_by or "").strip()
    currency = str(target_currency or "").strip().upper()
    uom = str(target_uom or "").strip().upper()
    if not all((tenant, hypothesis_id, currency, uom, actor)):
        raise ValueError("qualified_alternative_scope_required")
    grounded = get_grounded_hypothesis(
        db, tenant_id=tenant, hypothesis_id=hypothesis_id
    )
    bundle = grounded["evidence_bundle"]
    nodes = list(bundle.get("nodes") or [])
    edges = list(bundle.get("edges") or [])
    target = grounded["target_node_id"]
    decision_time = str(grounded["hypothesis"].get("decision_time"))
    candidates = _qualified_candidates(
        target_node_id=target, nodes=nodes, edges=edges
    )
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    node_by_id = {str(row.get("id")): row for row in nodes}
    for quote in quotes[:100]:
        quote_id = str(quote.get("quote_id") or "")
        candidate_id = str(quote.get("candidate_node_id") or "")
        supplier_id = str(quote.get("supplier_node_id") or "")
        candidate = candidates.get(candidate_id)
        if candidate is None:
            has_qualification = any(
                str(row.get("relationship_type")) == "qualified_substitute_for"
                and _connects(row, candidate_id, target)
                for row in edges
            )
            excluded.append({
                "quote_id": quote_id,
                "candidate_node_id": candidate_id,
                "reason": (
                    "active_certification_required"
                    if has_qualification else "alternative_not_qualified"
                ),
            })
            continue
        supplier = _supplier_for_candidate(
            candidate_id=candidate_id,
            supplier_id=supplier_id,
            nodes=nodes,
            edges=edges,
        )
        if supplier is None:
            excluded.append({
                "quote_id": quote_id,
                "candidate_node_id": candidate_id,
                "reason": "active_candidate_supplier_link_required",
            })
            continue
        try:
            compared = _compare_quote(
                tenant_id=tenant,
                quote=quote,
                target_currency=currency,
                target_uom=uom,
                decision_time=decision_time,
            )
            compared["qualification"] = {
                "qualification_edge_id": candidate["qualification_edge"].get("id"),
                "certification_edge_id": candidate["certification_edge"].get("id"),
                "compatibility_edge_ids": [
                    row.get("id") for row in candidate["compatibility_edges"]
                ],
            }
            ranked.append(compared)
        except (KeyError, TypeError, ValueError) as exc:
            excluded.append({
                "quote_id": quote_id,
                "candidate_node_id": candidate_id,
                "reason": str(exc),
            })
        supplier_attributes = dict(supplier.get("attributes") or {})
        candidate_node = node_by_id.get(candidate_id) or {}
        draft = draft_supplier_message(
            kind="rfq_confirmation",
            supplier_name=str(supplier.get("label") or supplier_id),
            supplier_email=str(supplier_attributes.get("contact_email") or ""),
            item=str(candidate_node.get("label") or candidate_id),
            details=(
                f"Reference hypothesis {hypothesis_id}. Please confirm current "
                f"qualification, certification, price validity, lead time, MOQ, "
                f"pack/UoM and landed-cost components for quote {quote_id}."
            ),
        ).to_dict()
        drafts.append({
            **draft,
            "quote_id": quote_id,
            "candidate_node_id": candidate_id,
            "supplier_node_id": supplier_id,
            "status": "awaiting_human_approval",
            "authority": "draft_only",
            "delivery_enqueued": False,
            "human_approval_required": True,
            "recipient_status": (
                "resolved_from_governed_supplier_node"
                if draft["supplier_email"] else "contact_missing"
            ),
        })
    ranked.sort(
        key=lambda row: (
            Decimal(row["comparable_landed_unit_minor"]),
            row["quote_id"],
        )
    )
    comparison = {
        "status": "observed" if ranked else "undefined",
        "ranked": ranked,
        "recommended": ranked[0] if ranked else None,
        "excluded": excluded,
        "target_currency": currency,
        "target_uom": uom,
        "authority": "comparison_only",
        "can_authorize_purchase": False,
    }
    proposal_payload = {
        "proposal_type": "qualified_alternative_rfq_confirmation",
        "hypothesis_id": hypothesis_id,
        "comparison": comparison,
        "communication_drafts": drafts,
        "authority": "proposal_only",
        "execution_allowed": False,
        "delivery_enqueued": False,
        "human_approval_required": True,
    }
    proposal_id = hashlib.sha256(
        f"{tenant}|{hypothesis_id}|alternatives|{_json(proposal_payload)}".encode()
    ).hexdigest()
    exists = db.execute(
        text(
            "SELECT 1 FROM procurement_option_proposal "
            "WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant, "id": proposal_id},
    ).first()
    if not exists:
        db.execute(
            text(
                """
                INSERT INTO procurement_option_proposal
                (id,tenant_id,hypothesis_id,case_id,options_json,status,
                 authority,created_by)
                VALUES
                (:id,:tenant,:hypothesis,:case_id,:payload,
                 'awaiting_human_approval','proposal_only',:actor)
                """
            ),
            {
                "id": proposal_id, "tenant": tenant,
                "hypothesis": hypothesis_id,
                "case_id": grounded.get("case_id"),
                "payload": _json(proposal_payload), "actor": actor,
            },
        )
        db.commit()
    return {
        "proposal_id": proposal_id,
        **proposal_payload,
        "idempotent_replay": bool(exists),
    }
