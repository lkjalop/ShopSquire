"""Checkout recommendation HTTP surface.

Product selection remains in ``services.checkout_upsell``. This router owns
request validation, security inspection, bundle projection, and audit output;
it has no dependency on the legacy ``suggest`` implementation.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, text

from src.app.config import get_settings, load_feature_flags
from src.app.deps import hash_uid
from src.app.models.db import get_db
from src.app.security.commerce_request_guard import inspect_commerce_request
from src.app.services.bundle_pricing import evaluate_bundle_savings
from src.app.services.checkout_upsell import recommend_checkout_upsell
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.price_conversion import cents_to_dollars


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/recommend", tags=["recommendation-checkout"])


def _trace_meta(policy_version: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "bitemporal": {
            "valid_from": now,
            "valid_to": "infinity",
            "system_from": now,
            "system_to": "infinity",
        },
        "recorded_at": now,
        "context_ids": ["cart_skus", "upsell_factors"],
        "policy_version": policy_version,
    }


@router.get("/checkout_upsell")
def checkout_upsell(
    uid: str,
    cart_skus: str,
    limit: int = 3,
    query: str | None = None,
    persona: str | None = None,
    use_case: str | None = None,
    db=Depends(get_db),
) -> Dict[str, Any]:
    skus = [value.strip() for value in str(cart_skus or "").split(",") if value.strip()]
    if not skus:
        raise HTTPException(status_code=400, detail="cart_skus is required")

    trace_id = str(uuid.uuid4())
    guard = inspect_commerce_request(
        surface="recommend.checkout_upsell",
        texts=[uid, query, persona, use_case, skus],
        sku_values=skus,
        uid=uid,
        quantity_values=[1 for _ in skus],
    )
    log_trace_event(
        trace_id=trace_id,
        event_type="security_scan",
        source_type="gate",
        source_id="checkout_upsell_guard",
        target_type="decision_trace",
        target_id=trace_id,
        payload={
            "summary": f"checkout_upsell input {guard.get('verdict')}",
            "severity": guard.get("severity"),
            "risk": guard.get("risk"),
            "mitre_atlas": guard.get("mitre_atlas") or [],
            "mitre_attack": guard.get("mitre_attack") or [],
            "signals": guard.get("reasons") or [],
            "mitigations": guard.get("mitigations") or [],
            "surface": guard.get("surface"),
            "verdict": guard.get("verdict"),
        },
    )
    if guard.get("verdict") == "block":
        reasons = ", ".join(guard.get("reasons") or ["invalid_payload"])
        raise HTTPException(status_code=400, detail=f"blocked_checkout_upsell: {reasons}")

    try:
        recommendations = recommend_checkout_upsell(
            db,
            cart_skus=skus,
            limit=max(1, min(int(limit or 3), 8)),
            uid_hash=uid,
            query=query,
            persona=persona,
            use_case=use_case,
            trace_id=trace_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"checkout_upsell_failed: {exc}") from exc

    bundle_savings: Dict[str, Any] = {}
    try:
        rows = db.execute(
            text(
                """
                SELECT sku, name, price_cents, specs
                FROM products
                WHERE sku IN :skus
                """
            ).bindparams(bindparam("skus", expanding=True)),
            {"skus": skus},
        ).fetchall()
        bundle_items = []
        for row in rows or []:
            raw_specs = row[3] if isinstance(row, (list, tuple)) else None
            specs: Dict[str, Any] = {}
            if isinstance(raw_specs, str) and raw_specs.strip():
                try:
                    parsed = json.loads(raw_specs)
                    specs = parsed if isinstance(parsed, dict) else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    specs = {}
            elif isinstance(raw_specs, dict):
                specs = raw_specs
            bundle_items.append(
                {
                    "sku": row[0],
                    "name": row[1],
                    "quantity": 1,
                    "price_cents": int(row[2] or 0),
                    "specs": specs,
                }
            )
        bundle_savings = evaluate_bundle_savings(bundle_items)
    except Exception as exc:
        logger.warning("checkout bundle projection unavailable trace=%s: %s", trace_id, exc)

    try:
        policy_version = load_feature_flags(
            os.getenv("FEATURE_FLAGS_PATH") or get_settings().feature_flags_path
        ).get("POLICY_VERSION", "v1")
    except Exception as exc:
        logger.warning("checkout policy version unavailable trace=%s: %s", trace_id, exc)
        policy_version = "v1"

    promoted = [
        {
            "sku": row.get("sku"),
            "name": row.get("name"),
            "price_cents": row.get("price_cents"),
            "price": (
                cents_to_dollars(row.get("price_cents"))
                if isinstance(row.get("price_cents"), (int, float))
                else row.get("price")
            ),
            "reasons": (row.get("reasons") or [])[:3],
            "reason_codes": (row.get("reason_codes") or [])[:5],
            "reason_confidence": row.get("reason_confidence"),
            "score": row.get("score"),
            "score_norm": row.get("score_norm"),
            "model_source": row.get("model_source"),
        }
        for row in (recommendations or [])
        if isinstance(row, dict)
    ]
    try:
        log_decision(
            agent_name="Checkout_Upsell_Agent",
            input_data={
                "uid_hash": hash_uid(uid),
                "cart_skus": skus,
                "limit": limit,
                "query": query,
                "persona": persona,
                "use_case": use_case,
            },
            retrieved_context={
                "upsell_candidates": promoted,
                "surface": "checkout_upsell",
            },
            proposed_action={
                "results": promoted,
                "decision_mode": "rules_plus_model",
                "surface": "checkout_upsell",
            },
            policy_version=policy_version,
            approval_required=False,
            execution_status="executed",
            decision_id=trace_id,
            event_type="upsell_promotion_selected",
        )
        log_trace_event(
            trace_id=trace_id,
            event_type="upsell_promotion_selected",
            source_type="stage",
            source_id="checkout_upsell",
            target_type="user",
            target_id=uid,
            payload={
                "surface": "checkout_upsell",
                "cart_skus": skus,
                "query": query,
                "persona": persona,
                "use_case": use_case,
                "promoted": promoted,
                "products_summary": promoted,
                "right_panel_contract": {
                    "mode": "cart_upsell",
                    "summary": "Checkout upsell suggestions selected for current cart.",
                },
                "bundle_savings": bundle_savings,
                **_trace_meta(str(policy_version)),
            },
        )
    except Exception as exc:
        logger.warning("checkout trace persistence unavailable trace=%s: %s", trace_id, exc)

    return {
        "results": recommendations,
        "count": len(recommendations),
        "cart_skus": skus,
        "uid_hash": hash_uid(uid),
        "trace_id": trace_id,
        "decision_trace_id": trace_id,
        "policy_version": policy_version,
        "bundle_savings": bundle_savings,
    }
