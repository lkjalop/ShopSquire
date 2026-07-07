from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any, List
import base64
import json

from src.app.services.returns import capture_evidence, compute_return_score
from src.app.services.returns import mark_evidence_as_fraud
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.nlp_contract import is_contract_like_text, run_contract_assist, evaluate_quality_gate
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.policy.vertical_pack import load_vertical_pack, resolve_pack_id
from src.app.rules.tier0_gate import run_tier0_gate
from src.app.services.cases import create_case
from src.app.models.db import db_session
from src.app.policy.route_enforcement import enforce_action_authority
from sqlalchemy import text as _text
from src.app.cv.evidence_writer import EvidenceWriter
from src.app.rules.config_defaults import escalation_triggers_defaults
from src.app.services.fusion_scorer import compute_and_persist as compute_and_persist_fusion

router = APIRouter(prefix="/api/v1/returns", tags=["returns"])


def _value_cents_from_body(body: Dict[str, Any]) -> int:
    for key in ("item_value_cents", "amount_cents", "refund_amount_cents", "item_price_cents"):
        value = body.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except Exception:
            continue
    for key in ("item_value", "amount", "refund_amount", "item_price"):
        value = body.get(key)
        if value is None:
            continue
        try:
            return max(0, int(round(float(value) * 100)))
        except Exception:
            continue
    return 0


def _cv_brand_mismatch(pkg: dict, expected: str) -> bool:
    """Does the CV evidence FAIL to mention the expected brand/product token? (best-effort, len-guarded)"""
    expected = str(expected or "").lower().strip()
    if not expected:
        return False
    cv_result = pkg.get("cv_result") or pkg.get("triage") or {}
    cv_labels = " ".join(cv_result.get("raw_labels") or pkg.get("labels") or []).lower()
    cv_text = (cv_result.get("extracted_text") or "").lower()
    cv_plain = (cv_result.get("plain_english") or "").lower()
    combined_cv = f"{cv_labels} {cv_text} {cv_plain}"
    return expected not in combined_cv and len(combined_cv.strip()) > 10


def _corroborate_order(uid: str | None, sku: str, pkg: dict) -> dict:
    """Check whether the submitted return matches an actual purchase for uid+sku.

    Queries the CANONICAL schema (orders JOIN draft_orders, scanning line_items JSON for the SKU) with the
    legacy order_items table as a fallback. The old code queried ONLY order_items — a table that does not
    exist in the live DB — so every production claim silently returned "db_unavailable"/delta 0 and
    purchase corroboration was a NO-OP (found in the 2026-07-07 audit).

    Returns {order_found, order_id, order_status, purchased_at, total_cents, currency,
             fraud_score_delta (0/15/20), mismatch, detail}.
    """
    _not_found = {"order_found": False, "order_id": None, "order_status": None, "purchased_at": None,
                  "total_cents": None, "currency": None}
    if not uid:
        return {**_not_found, "fraud_score_delta": 15, "mismatch": True, "detail": "no_uid_provided"}

    # ── Canonical: orders (paid/shipped/delivered preferred) joined to their draft's line_items ──
    try:
        with db_session() as db:
            rows = db.execute(
                _text(
                    "SELECT o.id, o.status, o.created_at, o.total_cents, o.currency, d.line_items "
                    "FROM orders o LEFT JOIN draft_orders d ON d.id = o.draft_order_id "
                    "WHERE o.customer_id = :uid ORDER BY o.created_at DESC LIMIT 50"
                ),
                {"uid": uid},
            ).fetchall()
    except Exception:
        rows = []
    best = None
    for r in rows or []:
        try:
            items = json.loads(r[5]) if r[5] else []
        except (json.JSONDecodeError, TypeError):
            items = []
        if any(str(it.get("sku") or "").strip().upper() == str(sku or "").strip().upper() for it in items if isinstance(it, dict)):
            best = r
            if str(r[1]) in ("paid", "shipped", "delivered"):
                break  # prefer the most recent REFUNDABLE order; keep scanning otherwise
    if best is not None:
        # Brand/product mismatch: compare CV evidence to the CATALOG name for this SKU (canonical rows
        # don't carry product_name/brand like the legacy table did).
        expected = ""
        try:
            with db_session() as db:
                prow = db.execute(_text("SELECT name FROM products WHERE sku = :s LIMIT 1"), {"s": sku}).fetchone()
            expected = (str(prow[0]).split() or [""])[0] if prow and prow[0] else ""
        except Exception:
            expected = ""
        mismatch = _cv_brand_mismatch(pkg, expected)
        return {
            "order_found": True, "order_id": str(best[0]), "order_status": str(best[1] or ""),
            "purchased_at": str(best[2] or "") or None, "total_cents": int(best[3] or 0),
            "currency": str(best[4] or "USD"),
            "fraud_score_delta": 20 if mismatch else 0, "mismatch": mismatch,
            "detail": (f"brand_mismatch: expected '{expected}' not in cv_output" if mismatch else "order_matched"),
        }

    # ── Legacy fallback: order_items (only exists in some environments) ──
    try:
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT id, product_name, brand, sku FROM order_items "
                    "WHERE user_id = :uid AND sku = :sku ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": uid, "sku": sku},
            ).fetchone()
    except Exception:
        row = None
        if not rows:
            # BOTH schemas unavailable — genuinely inconclusive (do not penalize the buyer for our outage)
            return {**_not_found, "fraud_score_delta": 0, "mismatch": False, "detail": "db_unavailable"}
    if not row:
        return {**_not_found, "fraud_score_delta": 15, "mismatch": True, "detail": "no_matching_order"}
    order_brand = str(row[2] or "").lower().strip() if len(row) > 2 else ""
    mismatch = _cv_brand_mismatch(pkg, order_brand)
    return {
        "order_found": True, "order_id": None, "order_status": None, "purchased_at": None,
        "total_cents": None, "currency": None,
        "fraud_score_delta": 20 if mismatch else 0, "mismatch": mismatch,
        "detail": (f"brand_mismatch: order_brand='{order_brand}' not found in cv_output" if mismatch else "order_matched"),
    }


@router.post("/submit")
def submit_return(body: Dict[str, Any], request: Request = None, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Submit a return/complaint with images.

    Expected body: { sku, uid (optional), images: [{filename, b64}], description }
    """
    sku = body.get("sku")
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")
    uid = body.get("uid")
    images_in = body.get("images") or []
    images = []
    for im in images_in:
        fname = im.get("filename") or "upload.jpg"
        b64 = im.get("b64") or ""
        try:
            b = base64.b64decode(b64)
        except Exception:
            b = b""
        images.append((fname, b))

    tenant_id = None
    try:
        tenant_id = body.get("tenant_id")
    except Exception:
        tenant_id = None
    if tenant_id is None:
        try:
            if request is not None and hasattr(request, "headers"):
                tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
        except Exception:
            tenant_id = None
    if tenant_id is not None:
        try:
            tenant_id = str(tenant_id)
        except Exception:
            tenant_id = None

    # Tier0 (rules-first) gate: avoid expensive CV/OCR work when images/policy fail.
    try:
        enabled = str((body.get("tier0_rules_enabled") or "")).strip().lower() in ("1", "true", "yes")
        if not enabled:
            enabled = str(__import__("os").getenv("TIER0_RULES_ENABLED", "0")).strip().lower() in ("1", "true", "yes")
    except Exception:
        enabled = False
    gate = None
    pack_id = None
    if enabled:
        try:
            pack_id = resolve_pack_id(getattr(request, "headers", None), body)
            pack = load_vertical_pack(pack_id)
            gate = run_tier0_gate(payload=body, images=images, pack=pack)
        except Exception:
            gate = None
    if gate is not None and gate.decision in ("ask_more_images", "deny"):
        mode = "need_more_images" if gate.decision == "ask_more_images" else "rejected"
        dec_id = None
        try:
            dec_id = log_decision(
                agent_name="returns.tier0_gate",
                input_data={"sku": sku, "uid": uid, "vertical_pack": (gate.details.get("vertical_pack") or {}).get("id")},
                retrieved_context={"tier0": gate.details},
                proposed_action={"action": mode, "missing_views": gate.missing_views, "reasons": gate.reasons},
                agent_reasoning="tier0_rules_gate",
                execution_status="executed",
            )
        except Exception:
            pass
        return {"evidence_id": None, "decision_id": dec_id, "mode": mode, "tier0": gate.details, "missing_views": gate.missing_views, "reasons": gate.reasons}

    # Create a lightweight ReturnCase so evidence can be linked consistently.
    # customer_id was previously None — the case never recorded WHO claimed (2026-07-07 audit), which
    # both lost the claimant from the audit trail and made serial-returner detection impossible.
    case_id = None
    try:
        case_id = create_case(order_id=None, issue_type="return", description=body.get("description") or "",
                              customer_id=uid, tenant_id=tenant_id)
    except Exception:
        case_id = None

    # Prefer the same vertical pack id used by Tier0 gate when present (helps OCR postprocess patterns).
    try:
        if not pack_id:
            pack_id = resolve_pack_id(getattr(request, "headers", None), body)
    except Exception:
        pack_id = None
    pack = None
    try:
        if pack_id:
            pack = load_vertical_pack(pack_id)
    except Exception:
        pack = None

    pkg = capture_evidence(sku=sku, uid=uid, images=images, description=body.get("description"), vertical_pack_id=pack_id, tenant_id=tenant_id)
    try:
        pkg["tenant_id"] = tenant_id
    except Exception:
        pass
    score = compute_return_score(pkg)

    # ── Order corroboration: verify uid+sku exists in orders; CV brand check ──
    try:
        corroboration = _corroborate_order(uid, sku, pkg)
        pkg["order_corroboration"] = corroboration
        if corroboration.get("fraud_score_delta", 0) > 0:
            score["score"] = float(score.get("score") or 0) + corroboration["fraud_score_delta"]
            score.setdefault("signals", []).append(
                {"signal": "order_corroboration", "delta": corroboration["fraud_score_delta"], "detail": corroboration["detail"]}
            )
    except Exception:
        pass

    # ── Claim-policy signals: return/warranty windows, price sanity, evidence relevance, serial
    # returner (config/rules/returns_policy.json; tenant-overridable). ACL posture: these raise the
    # score toward human review — they NEVER auto-deny. ──
    try:
        from src.app.services.claim_policy import evaluate_claim_policy
        _cvres = pkg.get("cv_result") or pkg.get("triage") or {}
        policy_signals = evaluate_claim_policy(
            corroboration=pkg.get("order_corroboration") or {},
            claimed_value_cents=_value_cents_from_body(body),
            labels=(_cvres.get("raw_labels") or pkg.get("labels") or []),
            ocr_text=str(_cvres.get("extracted_text") or ""),
            uid=uid,
            tenant_id=tenant_id,
            profile_id=pack_id,
            has_images=bool(images),
        )
        for sig in policy_signals:
            score["score"] = float(score.get("score") or 0) + float(sig.get("delta") or 0)
            score.setdefault("signals", []).append(sig)
        if policy_signals:
            pkg["claim_policy_signals"] = policy_signals
    except Exception:
        pass

    # ── Multi-image mismatch detection ──
    # submit_return is a sync def; asyncio.run() creates a fresh event loop
    # in the thread-pool worker — safe for sync FastAPI handlers under uvicorn.
    if images and len(images) >= 2:
        import asyncio
        import logging as _logging
        _mim_log = _logging.getLogger(__name__)
        try:
            from src.app.services.cv_triage_basic import BasicCVTriage
            triage = BasicCVTriage()
            img_dicts = [
                {"bytes": b, "mime": "image/jpeg", "labels": [], "text": "", "filename": fn}
                for fn, b in images
            ]
            _expected_pt = None
            try:
                _cat = str(pkg.get("category") or "").lower()
                if "laptop" in _cat or "notebook" in _cat:
                    _expected_pt = "laptop"
                elif "phone" in _cat or "mobile" in _cat:
                    _expected_pt = "phone"
            except Exception:
                pass
            batch = asyncio.run(
                triage.analyze_batch(img_dicts, expected_product_type=_expected_pt)
            )
            pkg["multi_image_analysis"] = batch
            if batch.get("mismatch_detected"):
                delta = int(batch.get("fraud_score_delta") or 0)
                score["score"] = float(score.get("score") or 0) + delta
                score.setdefault("signals", []).append(
                    {"signal": "multi_image_mismatch", "delta": delta, "detail": batch.get("mismatch_detail", "")}
                )
        except RuntimeError as exc:
            # asyncio.run() can raise if a loop is already running (rare in sync handlers).
            # Log and continue — do not silently discard fraud signal opportunity.
            _mim_log.warning("multi_image_mismatch: asyncio.run failed: %s", exc)
            score.setdefault("signals", []).append(
                {"signal": "multi_image_mismatch_skipped", "delta": 0, "detail": str(exc)}
            )
        except Exception as exc:
            _mim_log.warning("multi_image_mismatch: unexpected error: %s", exc)
    # Optional contract NLP assist on free-text description
    contract_nlp = None
    contract_quality = None
    try:
        desc = body.get("description") or ""
        # Respect feature flags when available via headers or global flags (best-effort)
        enabled = True
        try:
            from src.app.feature_flags import get_flags
            flags = get_flags() or {}
            enabled = bool(flags.get("CONTRACT_NLP_ASSIST_ENABLED", True))
        except Exception:
            enabled = True
        if enabled and is_contract_like_text(desc):
            contract_nlp = run_contract_assist(desc, enable_llm=False)
            try:
                contract_quality = evaluate_quality_gate(desc, contract_nlp or {})
            except Exception:
                contract_quality = None
    except Exception:
        contract_nlp = None
        contract_quality = None

    # Decision thresholds
    esc = escalation_triggers_defaults(tenant_id=tenant_id)
    default_thr = (esc.get("default") or {}) if isinstance(esc.get("default"), dict) else {}
    auto_approve_max = None
    human_review_max = None
    escalate_min = None
    try:
        if pack is not None and isinstance(getattr(pack, "thresholds", None), dict):
            auto_approve_max = pack.thresholds.get("auto_approve_max_score")
            human_review_max = pack.thresholds.get("human_review_max_score")
            escalate_min = pack.thresholds.get("escalate_security_min_score")
    except Exception:
        pass
    try:
        if auto_approve_max is None:
            auto_approve_max = default_thr.get("auto_approve_max_score", 30)
        if human_review_max is None:
            human_review_max = default_thr.get("human_review_max_score", 70)
        if escalate_min is None:
            escalate_min = default_thr.get("escalate_security_min_score", 70)
        auto_approve_max = float(auto_approve_max)
        human_review_max = float(human_review_max)
        escalate_min = float(escalate_min)
    except Exception:
        auto_approve_max = 30.0
        human_review_max = 70.0
        escalate_min = 70.0

    if score["score"] < auto_approve_max:
        mode = "auto_approve"
    elif score["score"] < human_review_max:
        mode = "require_human"
    else:
        mode = "escalate_security"

    # ── Close the loop to the GOVERNED refund rail (2026-07-07 audit: an auto-approved claim previously
    # went NOWHERE — no refund request was ever created; the claim and refund pipelines were disconnected).
    # auto_approve now (a) requires a corroborated, refundable order — no order, no auto-refund — and
    # (b) opens a refund REQUEST on the payment ledger. Human OWNER approval (GATE-2) still moves the money.
    corroboration = pkg.get("order_corroboration") or {}
    refund = None
    if mode == "auto_approve":
        _order_id = corroboration.get("order_id")
        if not corroboration.get("order_found") or not _order_id:
            mode = "require_human"
            score.setdefault("signals", []).append(
                {"signal": "auto_approve_downgraded", "delta": 0,
                 "detail": "no_corroborated_refundable_order — refund cannot be raised without a purchase record"}
            )
        else:
            enforce_action_authority(
                "refund",
                value_aud_cents=_value_cents_from_body(body),
                context={
                    "sku": sku,
                    "uid": uid,
                    "tenant_id": tenant_id,
                    "fraud_score": score.get("score"),
                    "decision_mode": mode,
                },
            )
            try:
                from src.app.services.refund_requests import create_refund_request
                with db_session() as db:
                    refund = create_refund_request(
                        db, order_id=_order_id,
                        amount_cents=(_value_cents_from_body(body) or None),
                        reason=f"return_claim:{case_id or ''}",
                        actor_type="agent", actor_id="returns.agent", clamp=True,
                    )
            except Exception as exc:
                refund = {"ok": False, "error": f"refund_request_failed: {exc}"}
            if not (refund or {}).get("ok"):
                mode = "require_human"
                score.setdefault("signals", []).append(
                    {"signal": "auto_approve_downgraded", "delta": 0,
                     "detail": str((refund or {}).get("error") or "refund_request_failed")}
                )

    # Persist decision log for audit
    customer_tier = None
    try:
        if request is not None and hasattr(request, "headers"):
            customer_tier = request.headers.get("X-User-Tier") or request.headers.get("x-user-tier")
    except Exception:
        customer_tier = None
    dec_id = log_decision(
        agent_name="returns.agent",
        input_data={"sku": sku, "uid": uid, "description": body.get("description")},
        retrieved_context={"evidence": pkg, "customer_tier": customer_tier, "contract_nlp": contract_nlp, "contract_quality": contract_quality},
        proposed_action={"action": mode, "score": score},
        agent_reasoning="returns_heuristic",
        execution_status="executed" if mode == "auto_approve" else "pending",
    )
    # Emit trace events for contract NLP when present
    try:
        if contract_nlp:
            log_trace_event(
                trace_id=dec_id,
                event_type="contract_nlp_analysis",
                source_type="agent",
                source_id="Contract_NLP_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "mode": contract_nlp.get("mode"),
                    "score": contract_nlp.get("score"),
                    "risks": contract_nlp.get("risks"),
                },
            )
        if contract_quality:
            log_trace_event(
                trace_id=dec_id,
                event_type="nlp_quality_gate",
                source_type="agent",
                source_id="Contract_NLP_Agent",
                target_type="system",
                target_id=None,
                payload=contract_quality,
            )
    except Exception:
        pass
    # Persist EvidenceBundle row for auditing when case_id exists
    try:
        if case_id:
            EvidenceWriter().write(case_id, pkg, evidence_id=pkg.get("evidence_id"))
    except Exception:
        pass

    fusion = None
    try:
        fusion = compute_and_persist_fusion(
            tenant_id=tenant_id,
            case_id=case_id,
            evidence_pkg=pkg,
            tier0_details=(gate.details if gate is not None else None),
            source="returns",
            model_version="fusion_v0",
        )
    except Exception:
        fusion = None
    # If human review is required, create a HumanReviewTask entry
    human_review = {"status": "not_required", "ticket_id": None}
    try:
        if mode in ("require_human", "escalate_security") and case_id:
            with db_session() as db:
                db.execute(
                    _text(
                        "INSERT INTO human_review_tasks (id, case_id, decision_id, ticket_id, status, created_at) VALUES (:id, :case_id, :decision_id, :ticket_id, :status, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": f"hr-{__import__('uuid').uuid4().hex}",
                        "case_id": case_id,
                        "decision_id": dec_id,
                        "ticket_id": None,
                        "status": "pending",
                    },
                )
                db.commit()
            human_review = {"status": "pending", "ticket_id": None}
    except Exception:
        pass
    # Escalation-room incident for anything a human must look at (2026-07-07 audit: the room accepted
    # warranty/damage context but returns NEVER invoked it — reviewers had a bare task row with no room).
    # Deliberately NOT gated on case_id (the task insert above is — a missing case must not silently
    # drop the escalation). Failure is recorded on the response, never swallowed.
    if mode in ("require_human", "escalate_security"):
        try:
            from src.app.routers.escalation_room import create_incident_record
            _cvres = (pkg.get("cv_result") or pkg.get("triage") or {}) if isinstance(pkg, dict) else {}
            _damage = _cvres.get("damage_types") or ([_cvres.get("damage_type")] if _cvres.get("damage_type") else [])
            incident = create_incident_record(
                case_id=case_id,
                trace_id=dec_id,
                reason="return_claim_review",
                context={
                    "issue_type": "return_claim",
                    "damage_types": _damage,
                    "warranty_candidate": bool(body.get("warranty_claim")) or None,
                    "fraud_score": score.get("score"),
                    "sku": sku,
                    "uid": uid,
                    "order_id": corroboration.get("order_id"),
                    "decision_mode": mode,
                },
                created_by="returns.agent",
                severity=("critical" if mode == "escalate_security" else "warn"),
            )
            human_review["incident_id"] = (incident or {}).get("incident_id") or (incident or {}).get("id")
        except Exception as exc:
            human_review["incident_error"] = str(exc)[:200]

    return {
        "case_id": case_id,
        "evidence_id": pkg.get("evidence_id"),
        "decision_id": dec_id,
        "mode": mode,
        "score": score,
        "refund": refund,
        "human_review": human_review,
        "fusion": fusion,
        "thresholds": {"auto_approve_max_score": auto_approve_max, "human_review_max_score": human_review_max, "escalate_security_min_score": escalate_min},
    }


@router.get("/evidence/{eid}/export")
def export_evidence(eid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    # Serve the package.json for the evidence id if exists
    import os
    base = os.path.join("tmp", "returns", eid)
    pkgf = os.path.join(base, "package.json")
    if not os.path.exists(pkgf):
        raise HTTPException(status_code=404, detail="evidence not found")
    with open(pkgf, "r", encoding="utf-8") as pf:
        data = pf.read()
    return {"evidence": data}


@router.post("/{eid}/confirm_fraud")
def confirm_fraud(eid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Mark an evidence package as confirmed fraud (persist phashes)."""
    cnt = mark_evidence_as_fraud(eid)
    if cnt == 0:
        raise HTTPException(status_code=404, detail="evidence not found or no images")
    return {"inserted_phashes": cnt}
