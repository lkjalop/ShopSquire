from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from typing import Dict, Any
import base64
import hashlib
import json
import logging
import time

from src.app.services.returns import capture_evidence, compute_return_score
from src.app.services.returns import mark_evidence_as_fraud
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.nlp_contract import is_contract_like_text, run_contract_assist, evaluate_quality_gate
from src.app.security.auth import (
    OperatorSubject,
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    operator_subject,
    require_role,
)
from src.app.policy.vertical_pack import load_vertical_pack, resolve_pack_id
from src.app.rules.tier0_gate import run_tier0_gate
from src.app.services.cases import create_case
from src.app.models.db import db_session
from src.app.policy.route_enforcement import enforce_action_authority
from sqlalchemy import text as _text
from src.app.cv.evidence_writer import EvidenceWriter
from src.app.rules.config_defaults import escalation_triggers_defaults
from src.app.services.fusion_scorer import compute_and_persist as compute_and_persist_fusion
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.buyer_principal import resolve_buyer_principal
from src.app.services.return_claims import (
    assess_return_claim_abuse,
    create_claim,
    find_idempotent_claim,
    get_claim,
    list_claims,
    load_encrypted_artifact,
    queue_evidence_job,
    set_evidence_legal_hold,
    store_encrypted_artifacts,
    transition_claim,
    verify_owned_order,
)

router = APIRouter(prefix="/api/v1/returns", tags=["returns"])
logger = logging.getLogger(__name__)


def _operator_actor(subject: OperatorSubject, role: str) -> str:
    return str(subject.user_id or subject.email or f"key:{role}")


def _strict_return_files(body: Dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("images") or body.get("files") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="return_evidence_required")
    if len(rows) > 8:
        raise HTTPException(status_code=413, detail="return_evidence_file_count_exceeded")
    out: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(status_code=422, detail="invalid_return_evidence_file")
        encoded = str(row.get("b64") or row.get("content_b64") or "")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid_return_evidence_base64") from exc
        if not raw:
            raise HTTPException(status_code=422, detail="return_evidence_file_empty")
        total += len(raw)
        if len(raw) > 12 * 1024 * 1024 or total > 30 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="return_evidence_size_exceeded")
        out.append({
            "filename": row.get("filename") or row.get("name") or "upload.bin",
            "content_type": row.get("content_type") or "application/octet-stream",
            "bytes": raw,
        })
    return out


@router.post("/claims", status_code=202)
def create_return_claim(body: Dict[str, Any], request: Request):
    """Fast, authenticated intake; raw files are encrypted before durable queuing."""
    started = time.perf_counter()
    principal = resolve_buyer_principal(request, supplied_uid=body.get("uid"))
    if principal is None or not principal.verified:
        raise HTTPException(status_code=401, detail="verified_buyer_identity_required")
    sku = str(body.get("sku") or "").strip()
    if not sku:
        raise HTTPException(status_code=422, detail="sku_required")
    idempotency_key = str(request.headers.get("idempotency-key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=428, detail="valid_idempotency_key_required")
    files = _strict_return_files(body)
    with db_session() as db:
        existing = find_idempotent_claim(
            db, tenant_id=principal.tenant_id, claimant_id=principal.subject,
            idempotency_key=idempotency_key,
        )
        if existing:
            return JSONResponse(status_code=202, content={**existing, "idempotent_replay": True})
        verification = verify_owned_order(
            db,
            tenant_id=principal.tenant_id,
            claimant_id=principal.subject,
            sku=sku,
            order_id=(str(body.get("order_id")) if body.get("order_id") else None),
        )
        try:
            abuse = assess_return_claim_abuse(
                db,
                tenant_id=principal.tenant_id,
                claimant_id=principal.subject,
                order_id=verification.order_id,
                evidence_digests=[hashlib.sha256(item["bytes"]).hexdigest() for item in files],
            )
        except PermissionError as exc:
            try:
                from src.app.observability.return_metrics import RETURN_AUTHORIZATION_BLOCKS

                RETURN_AUTHORIZATION_BLOCKS.labels(reason="claim_velocity_limit").inc()
            except Exception as metric_exc:
                logger.debug("return authorization metric emission failed: %s", metric_exc)
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        claim = create_claim(
            db,
            tenant_id=principal.tenant_id,
            claimant_id=principal.subject,
            sku=sku,
            description=str(body.get("description") or ""),
            order_verification=verification,
            abuse_assessment=abuse,
            idempotency_key=idempotency_key,
        )
        evidence = store_encrypted_artifacts(
            db,
            tenant_id=principal.tenant_id,
            claim_id=claim["claim_id"],
            files=files,
            actor_id=principal.subject,
        )
        job_id = queue_evidence_job(
            db, tenant_id=principal.tenant_id, claim_id=claim["claim_id"]
        )
        try:
            from src.app.services.search_demand_authority import append_lifecycle_transition

            with db.begin_nested():
                lifecycle_attribution = append_lifecycle_transition(
                    db,
                    tenant_id=principal.tenant_id,
                    case_id=str(verification.order_id or ""),
                    trace_id=str(claim.get("trace_id") or ""),
                    lifecycle_stage="return",
                    resolved_sku=sku,
                )
        except Exception as exc:
            logger.warning(
                "return lifecycle attribution degraded claim=%s error=%s",
                claim["claim_id"], type(exc).__name__,
            )
            lifecycle_attribution = {"status": "degraded", "reason": type(exc).__name__}
        db.commit()
    try:
        from src.app.tasks.return_evidence_tasks import process_return_evidence

        process_return_evidence.delay(principal.tenant_id, job_id)
    except Exception as exc:
        # Durable queued state remains for the dispatcher/beat recovery path.
        logger.warning("return evidence dispatch deferred claim=%s: %s", claim["claim_id"], exc)
    try:
        log_trace_event(
            trace_id=claim["trace_id"],
            event_type="return_claim_evidence_pending",
            source_type="buyer",
            source_id=principal.subject,
            target_type="workflow",
            target_id=claim["claim_id"],
            payload={
                "claim_id": claim["claim_id"], "status": claim["status"],
                "order_verification_status": verification.status,
                "abuse_status": abuse.status,
                "abuse_reasons": list(abuse.reasons),
                "evidence_count": len(evidence), "authority": "observation_only",
                "state_changed": True, "commercial_action_prevented": True,
            },
        )
    except Exception as exc:
        # The canonical claim transaction is authoritative; trace projection is retryable.
        logger.warning("return claim trace projection deferred claim=%s: %s", claim["claim_id"], exc)
    payload = {
        **claim,
        "job_id": job_id,
        "evidence": evidence,
        "order_verification": {
            "status": verification.status,
            "order_id": verification.order_id,
            "detail": verification.detail,
        },
        "abuse_assessment": {
            "status": abuse.status,
            "reasons": list(abuse.reasons),
            "claimant_window_count": abuse.claimant_window_count,
            "order_window_count": abuse.order_window_count,
        },
        "search_demand_attribution": lifecycle_attribution,
        "message": (
            "Evidence accepted for bounded review. No refund, replacement, or repair was authorized."
        ),
    }
    try:
        from src.app.observability.return_metrics import RETURN_RESPONSE_SECONDS

        RETURN_RESPONSE_SECONDS.labels(
            milestone="first_useful_response", status=claim["status"]
        ).observe(time.perf_counter() - started)
    except Exception as exc:
        logger.debug("return response metric emission failed: %s", exc)
    return JSONResponse(status_code=202, content=payload)


@router.get("/claims/{claim_id}")
def read_return_claim(claim_id: str, request: Request):
    principal = resolve_buyer_principal(request)
    if principal is None or not principal.verified:
        raise HTTPException(status_code=401, detail="verified_buyer_identity_required")
    try:
        with db_session() as db:
            return get_claim(
                db,
                tenant_id=principal.tenant_id,
                claim_id=claim_id,
                claimant_id=principal.subject,
            )
    except LookupError as exc:
        # Do not disclose whether the identifier exists for another buyer or tenant.
        raise HTTPException(status_code=404, detail="return_claim_not_found") from exc


@router.get("/operator/claims")
def operator_return_queue(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER])),
):
    try:
        with db_session() as db:
            return {
                "claims": list_claims(
                    db,
                    tenant_id=str(current_tenant_id() or "default"),
                    status=status,
                    limit=limit,
                )
            }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/operator/claims/{claim_id}")
def operator_return_claim(
    claim_id: str,
    _role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER])),
):
    try:
        with db_session() as db:
            return get_claim(
                db,
                tenant_id=str(current_tenant_id() or "default"),
                claim_id=claim_id,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="return_claim_not_found") from exc


@router.post("/claims/{claim_id}/transition")
def update_return_claim(
    claim_id: str,
    body: Dict[str, Any],
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER])),
    subject: OperatorSubject = Depends(operator_subject),
):
    actor_id = _operator_actor(subject, role)
    try:
        with db_session() as db:
            result = transition_claim(
                db,
                tenant_id=str(current_tenant_id() or "default"),
                claim_id=claim_id,
                to_status=str(body.get("status") or ""),
                actor_type="operator",
                actor_id=actor_id,
                metadata={"reason": str(body.get("reason") or "")[:500]},
            )
            projection = get_claim(
                db,
                tenant_id=str(current_tenant_id() or "default"),
                claim_id=claim_id,
            )
            db.commit()
        try:
            log_trace_event(
                trace_id=str(projection.get("trace_id")),
                event_type="return_claim_status_changed",
                source_type="operator",
                source_id=actor_id,
                target_type="workflow",
                target_id=claim_id,
                payload={
                    **result,
                    "claim_id": claim_id,
                    "authority": "operator_authorized",
                    "state_changed": True,
                    "recorded_at": projection.get("updated_at"),
                },
            )
        except Exception:
            pass
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="return_claim_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/claims/{claim_id}/evidence/{evidence_id}/legal-hold")
def update_return_evidence_legal_hold(
    claim_id: str,
    evidence_id: str,
    body: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER])),
    subject: OperatorSubject = Depends(operator_subject),
):
    purpose = str(body.get("purpose") or "").strip()
    if not purpose:
        raise HTTPException(status_code=422, detail="legal_hold_purpose_required")
    try:
        with db_session() as db:
            set_evidence_legal_hold(
                db,
                tenant_id=str(current_tenant_id() or "default"),
                claim_id=claim_id,
                evidence_id=evidence_id,
                enabled=bool(body.get("enabled")),
                actor_id=_operator_actor(subject, role),
                purpose=purpose[:500],
            )
            db.commit()
        return {"claim_id": claim_id, "evidence_id": evidence_id, "legal_hold": bool(body.get("enabled"))}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="return_evidence_not_found") from exc


@router.get("/claims/{claim_id}/evidence/{evidence_id}/content")
def access_return_evidence(
    claim_id: str,
    evidence_id: str,
    purpose: str = Query(min_length=3, max_length=500),
    role: str = Depends(require_role([ROLE_OWNER])),
    subject: OperatorSubject = Depends(operator_subject),
):
    """Audited break-glass access; browsers receive bytes without inline rendering."""
    try:
        with db_session() as db:
            raw = load_encrypted_artifact(
                db,
                tenant_id=str(current_tenant_id() or "default"),
                claim_id=claim_id,
                evidence_id=evidence_id,
                actor_id=_operator_actor(subject, role),
                purpose=purpose,
            )
            db.commit()
        return Response(
            content=raw,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="return-evidence-{evidence_id}.bin"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="return_evidence_not_found") from exc


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


def _corroborate_order(
    uid: str | None,
    sku: str,
    pkg: dict,
    *,
    tenant_id: str | None = None,
) -> dict:
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
    tenant = str(tenant_id or current_tenant_id() or "default")
    try:
        with db_session() as db:
            rows = db.execute(
                _text(
                    "SELECT o.id, o.status, o.created_at, o.total_cents, o.currency, d.line_items "
                    "FROM orders o LEFT JOIN draft_orders d ON d.id = o.draft_order_id "
                    "AND (d.tenant_id = :tenant OR (:tenant = 'default' AND d.tenant_id IS NULL)) "
                    "WHERE o.customer_id = :uid AND "
                    "(o.tenant_id = :tenant OR (:tenant = 'default' AND o.tenant_id IS NULL)) "
                    "ORDER BY o.created_at DESC LIMIT 50"
                ),
                {"uid": uid, "tenant": tenant},
            ).fetchall()
    except Exception as exc:
        if tenant != "default":
            return {
                **_not_found, "fraud_score_delta": 0, "mismatch": False,
                "detail": "order_source_unavailable", "source_error": type(exc).__name__,
            }
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
                prow = db.execute(
                    _text(
                        "SELECT name FROM products WHERE sku = :s AND "
                        "(tenant_id = :tenant OR (:tenant = 'default' AND tenant_id IS NULL)) LIMIT 1"
                    ),
                    {"s": sku, "tenant": tenant},
                ).fetchone()
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
    if tenant != "default":
        return {
            **_not_found, "fraud_score_delta": 15, "mismatch": True,
            "detail": "order_not_found",
        }
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
    import os

    app_env = str(os.getenv("APP_ENV") or "dev").strip().lower()
    legacy_enabled = str(os.getenv("RETURN_LEGACY_SYNC_ENABLED") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if app_env in {"prod", "production", "staging"} and not legacy_enabled:
        raise HTTPException(
            status_code=410,
            detail="legacy_return_intake_disabled_use_api_v1_returns_claims",
        )
    sku = body.get("sku")
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")
    principal = resolve_buyer_principal(request, supplied_uid=body.get("uid")) if request is not None else None
    uid = principal.subject if principal is not None else body.get("uid")
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

    # Body/header tenant claims are data, never authority. Middleware and the
    # verified buyer principal resolve the active tenant before this handler.
    tenant_id = str((principal.tenant_id if principal is not None else current_tenant_id()) or "default")

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
        corroboration = _corroborate_order(uid, sku, pkg, tenant_id=tenant_id)
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
            images=images,
        )
        for sig in policy_signals:
            score["score"] = float(score.get("score") or 0) + float(sig.get("delta") or 0)
            score.setdefault("signals", []).append(sig)
        if policy_signals:
            pkg["claim_policy_signals"] = policy_signals
    except Exception:
        pass

    # ── Claim grounding + ACL failure severity (R3 2026-07-07): claim_grounding.ground_claim was
    # designed for exactly this and sat UNWIRED — evidence-reliability verdicts influenced nothing.
    # A contradicted claim (text says X, CV evidence says otherwise) now raises the score toward
    # human review; severity classifies major/minor so the LAWFUL remedy options render (major →
    # consumer chooses refund/replacement/repair; minor → repair). Proposes only — humans confirm.
    grounding = None
    failure_severity = None
    try:
        from src.app.services.claim_grounding import ground_claim
        from src.app.services.claim_policy import classify_failure_severity
        _cvres = (pkg.get("cv_result") or pkg.get("triage") or {}) if isinstance(pkg, dict) else {}
        _corr = pkg.get("order_corroboration") or {}
        grounding = ground_claim(
            str(body.get("description") or ""),
            cv_evidence=({"damage_type": _cvres.get("damage_type"),
                          "confidence": float(_cvres.get("confidence") or _cvres.get("damage_confidence") or 0.0)}
                         if _cvres.get("damage_type") else None),
            receipt_evidence={"verified": bool(_corr.get("order_found")),
                              "confidence": 0.9 if _corr.get("order_id") else 0.5},
        ).to_dict()
        pkg["claim_grounding"] = grounding
        if grounding.get("verdict") == "contradicted":
            from src.app.rules.config_defaults import returns_policy_defaults as _rpd
            _delta = int((_rpd(tenant_id=tenant_id) or {}).get("claim_contradicted_delta", 25) or 25)
            score["score"] = float(score.get("score") or 0) + _delta
            score.setdefault("signals", []).append(
                {"signal": "claim_contradicted_by_evidence", "delta": _delta,
                 "detail": f"grounding verdict=contradicted ({', '.join(grounding.get('evidence_sources') or [])})"})
        failure_severity = classify_failure_severity(
            description=str(body.get("description") or ""),
            damage_type=str(_cvres.get("damage_type") or ""), tenant_id=tenant_id)
        pkg["failure_severity"] = failure_severity
    except Exception as _exc:
        import logging as _lg
        _lg.getLogger(__name__).warning("claim grounding/severity skipped: %s", _exc)

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
                    # R3: the reviewer opens the room already knowing the grounding verdict and which
                    # remedies are LAWFUL to offer (major → buyer chooses; minor → repair path).
                    "grounding_verdict": (grounding or {}).get("verdict"),
                    "failure_severity": (failure_severity or {}).get("severity"),
                    "remedy_options": (failure_severity or {}).get("remedy_options"),
                    "safety_risk": (failure_severity or {}).get("safety_risk"),
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
        "grounding": grounding,
        "failure_severity": failure_severity,
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
    try:
        decoded = json.loads(data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc
    evidence_tenant = str(decoded.get("tenant_id") or "default")
    if evidence_tenant != str(current_tenant_id() or "default"):
        raise HTTPException(status_code=404, detail="evidence not found")
    return {"evidence": data}


@router.post("/{eid}/confirm_fraud")
def confirm_fraud(eid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Mark an evidence package as confirmed fraud (persist phashes)."""
    import os

    package_path = os.path.join("tmp", "returns", eid, "package.json")
    try:
        with open(package_path, "r", encoding="utf-8") as handle:
            package = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc
    if str(package.get("tenant_id") or "default") != str(current_tenant_id() or "default"):
        raise HTTPException(status_code=404, detail="evidence not found")
    cnt = mark_evidence_as_fraud(eid)
    if cnt == 0:
        raise HTTPException(status_code=404, detail="evidence not found or no images")
    return {"inserted_phashes": cnt}
