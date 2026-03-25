from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any, List
import base64

from src.app.services.returns import capture_evidence, compute_return_score
from src.app.services.returns import mark_evidence_as_fraud
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.nlp_contract import is_contract_like_text, run_contract_assist, evaluate_quality_gate
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.policy.vertical_pack import load_vertical_pack, resolve_pack_id
from src.app.rules.tier0_gate import run_tier0_gate
from src.app.services.cases import create_case
from src.app.models.db import db_session
from sqlalchemy import text as _text
from src.app.cv.evidence_writer import EvidenceWriter
from src.app.rules.config_defaults import escalation_triggers_defaults
from src.app.services.fusion_scorer import compute_and_persist as compute_and_persist_fusion

router = APIRouter(prefix="/api/v1/returns", tags=["returns"])


def _corroborate_order(uid: str | None, sku: str, pkg: dict) -> dict:
    """Check whether the submitted return matches an actual order for uid+sku.

    Returns::

        {
            "order_found": bool,
            "fraud_score_delta": int,   # 0 / 15 / 20
            "mismatch": bool,
            "detail": str,
        }
    """
    if not uid:
        return {"order_found": False, "fraud_score_delta": 15, "mismatch": True, "detail": "no_uid_provided"}
    try:
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT id, product_name, brand, sku FROM order_items "
                    "WHERE user_id = :uid AND sku = :sku "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": uid, "sku": sku},
            ).fetchone()
    except Exception:
        # Table may not exist in all environments — treat as inconclusive
        return {"order_found": False, "fraud_score_delta": 0, "mismatch": False, "detail": "db_unavailable"}

    if not row:
        return {"order_found": False, "fraud_score_delta": 15, "mismatch": True, "detail": "no_matching_order"}

    # Order found — compare CV-identified brand/product type against order record
    order_brand = str(row[2] or "").lower().strip() if len(row) > 2 else ""
    order_product = str(row[1] or "").lower().strip() if len(row) > 1 else ""
    cv_result = pkg.get("cv_result") or pkg.get("triage") or {}
    cv_labels = " ".join(cv_result.get("raw_labels") or pkg.get("labels") or []).lower()
    cv_text = (cv_result.get("extracted_text") or "").lower()
    cv_plain = (cv_result.get("plain_english") or "").lower()
    combined_cv = f"{cv_labels} {cv_text} {cv_plain}"

    mismatch = False
    delta = 0
    detail = "order_matched"

    if order_brand and order_brand not in combined_cv and len(combined_cv.strip()) > 10:
        # CV content doesn't mention the expected brand
        mismatch = True
        delta = 20
        detail = f"brand_mismatch: order_brand='{order_brand}' not found in cv_output"

    return {"order_found": True, "fraud_score_delta": delta, "mismatch": mismatch, "detail": detail}


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

    # Create a lightweight ReturnCase so evidence can be linked consistently
    case_id = None
    try:
        case_id = create_case(order_id=None, issue_type="return", description=body.get("description") or "", tenant_id=tenant_id)
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

    # ── Multi-image mismatch detection ──
    if images and len(images) >= 2:
        try:
            from src.app.services.cv_triage_basic import BasicCVTriage
            import asyncio
            triage = BasicCVTriage()
            img_dicts = [
                {"bytes": b, "mime": "image/jpeg", "labels": [], "text": "", "filename": fn}
                for fn, b in images
            ]
            # Derive expected product type from pkg SKU metadata if available
            _expected_pt = None
            try:
                _cat = str(pkg.get("category") or "").lower()
                if "laptop" in _cat or "notebook" in _cat:
                    _expected_pt = "laptop"
                elif "phone" in _cat or "mobile" in _cat:
                    _expected_pt = "phone"
            except Exception:
                pass
            batch = asyncio.get_event_loop().run_until_complete(
                triage.analyze_batch(img_dicts, expected_product_type=_expected_pt)
            )
            pkg["multi_image_analysis"] = batch
            if batch.get("mismatch_detected"):
                delta = int(batch.get("fraud_score_delta") or 0)
                score["score"] = float(score.get("score") or 0) + delta
                score.setdefault("signals", []).append(
                    {"signal": "multi_image_mismatch", "delta": delta, "detail": batch.get("mismatch_detail", "")}
                )
        except Exception:
            pass
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

    return {
        "case_id": case_id,
        "evidence_id": pkg.get("evidence_id"),
        "decision_id": dec_id,
        "mode": mode,
        "score": score,
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
