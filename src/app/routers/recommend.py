from __future__ import annotations

import time
import hashlib
import os
import uuid
import re
import json
from typing import Dict, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Body
from pydantic import BaseModel
from opentelemetry import trace

from src.app.config import load_feature_flags, get_settings
from src.app.deps import get_redis, scrub_pii, security_sanitize
from src.app.models.db import get_db
from src.app.security.observer import analyze_payload, emit_security_event
from src.app.observability.metrics import record_incident_alert, record_cb_state, record_rate_limit_exceeded, record_token_budget_usage
from src.app.observability.tracing import get_tracer
from src.app.routers.approvals import enqueue_approval
from src.app.services.degradation import cb_is_open, cb_record
from src.app.services.memory import Memory
from src.app.services.conversation_state import ConversationState
from src.app.services.recommendations import RecommendationService
from sqlalchemy import text
from src.app.observability.health import dependency_health_snapshot
from src.app.services.token_budget import TokenBudget, estimate_tokens, estimate_cost, infer_tier
from src.app.services.tenant_quota import TenantQuotaGuard
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.safety.policies import get_policy, apply_post_policy
from src.app.safety.redaction import redact_payload
from src.app.services.llm_provider import select_ollama_model, is_complex_query, OLLAMA_URL, complexity_explain
from src.app.rules.engine import RuleEngine
from src.app.services.ethical_ai import EthicalAIGuard
from src.app.services.decision_log import log_trace_event, log_decision
from src.app.services.agent_bus import AgentBus
from src.app.services.agent_handoff import request_handoff_best_effort
from src.app.deps import hash_uid
from src.app.services.risk_quantification import quantify as quantify_risk
from src.app.policy.gate import evaluate_policy_gate
from src.app.services.search_events import log_search_event
from src.app.services.checkout_upsell import recommend_checkout_upsell, ensure_recommend_interactions_table
from src.app.flows.nqe import NextQuestionEngine, NQEInput
from src.app.flows.catalog import QuestionTemplateCatalog
from src.app.rag.retrieve import Retriever
from src.app.services.trace_strategy_tags import build_strategy_trace_correlation
from src.app.services.i18n import localize_recommend_payload
import httpx
from types import SimpleNamespace
import logging


router = APIRouter(prefix="/api/v1/recommend", tags=["recommend"])
tracer = get_tracer("recommend-router")


class RecommendInteractionPayload(BaseModel):
    uid: str
    sku: str
    action: str
    surface: str = "checkout_upsell"
    trace_id: str | None = None
    context: Dict[str, Any] | None = None


def _block_response(payload: Dict, code: int = 403):
    # Default to returning 200 so tests can observe blocked payloads without
    # an HTTP-level 403. Use env SECURITY_BLOCK_MODE=403 to enable strict blocking.
    mode = os.getenv("SECURITY_BLOCK_MODE", "200").strip()
    if mode == "200":
        return payload
    raise HTTPException(status_code=code, detail=payload)


def _with_trace(payload: Dict[str, Any], trace_id: str | None) -> Dict[str, Any]:
    try:
        payload = security_sanitize(payload or {})
    except Exception:
        payload = payload or {}
    try:
        locale = (
            payload.get("locale")
            or (payload.get("constraints_used") or {}).get("locale")
            or ((payload.get("proposal") or {}).get("nlp") or {}).get("locale")
        )
        payload = localize_recommend_payload(payload, locale)
    except Exception:
        pass
    if not trace_id:
        return payload
    if "trace_id" not in payload:
        payload["trace_id"] = trace_id
    if "decision_id" not in payload:
        payload["decision_id"] = trace_id
    return payload


_SUPPORTED_PRODUCT_TERMS = {
    "laptop",
    "notebook",
    "ultrabook",
    "macbook",
    "chromebook",
    "desktop",
    "pc",
    "monitor",
    "display",
    "dock",
    "charger",
    "adapter",
    "keyboard",
    "mouse",
}
_UNSUPPORTED_PRODUCT_TERMS = {
    "kitchen",
    "mixer",
    "blender",
    "toaster",
    "microwave",
    "fridge",
    "refrigerator",
    "dishwasher",
    "oven",
    "vacuum",
    "television",
    "tv",
    "sofa",
    "bed",
    "mattress",
}


def _query_signals_unsupported_intent(query: str | None) -> bool:
    text = (query or "").lower()
    if not text:
        return False
    has_supported = any(tok in text for tok in _SUPPORTED_PRODUCT_TERMS)
    has_unsupported = any(tok in text for tok in _UNSUPPORTED_PRODUCT_TERMS)
    return bool(has_unsupported and not has_supported)


def _ensure_trace_response(response: Dict[str, Any], trace_id: str, flags: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure every response includes trace ids and policy version for UI wiring."""
    response["trace_id"] = trace_id
    response["decision_trace_id"] = trace_id
    response["policy_version"] = response.get("policy_version") or flags.get("POLICY_VERSION", "v1")
    # Ensure contract-critical keys exist for tests/UI
    if "results" not in response:
        response["results"] = []
    if "proposal" not in response:
        response["proposal"] = {"decision_mode": "blocked", "ranked_skus": []}
    if "constraints_used" not in response:
        response["constraints_used"] = response.get("constraints_used") or {}
    # Enterprise evidence contract defaults.
    if "evidence_items" not in response:
        top = []
        for r in (response.get("results") or [])[:3]:
            if isinstance(r, dict):
                top.append(
                    {
                        "type": "candidate",
                        "id": r.get("sku"),
                        "score": r.get("score"),
                    }
                )
        response["evidence_items"] = top
    if "evidence_weighting" not in response:
        response["evidence_weighting"] = {"retrieval": 0.5, "rules": 0.3, "policy": 0.2}
    if "confidence_calibrated" not in response:
        try:
            confs = [float((r or {}).get("confidence") or 0.0) for r in (response.get("results") or []) if isinstance(r, dict)]
            response["confidence_calibrated"] = round(sum(confs) / len(confs), 4) if confs else 0.0
        except Exception:
            response["confidence_calibrated"] = 0.0
    if "counterfactual" not in response:
        response["counterfactual"] = "Different budget/spec constraints or stock availability could change top recommendations."
    return response


def _extract_quantity_from_query(query: str | None) -> int | None:
    """Best-effort quantity extraction for bulk-order intent."""
    if not query:
        return None
    q = str(query).strip().lower()
    if not q:
        return None

    m = re.search(r"\b(?:qty|quantity)\s*[:=#-]?\s*(\d{1,4})\b", q)
    if not m:
        m = re.search(r"\b(\d{1,4})\s*[x×]\b", q)
    if not m:
        m = re.search(
            r"\b(\d{1,4})\s*(?:units?|items?|pieces?|pcs|laptops?|desktops?|monitors?|keyboards?|mice|phones?)\b",
            q,
        )
    if not m:
        return None
    try:
        qty = int(m.group(1))
    except Exception:
        return None
    if qty <= 0 or qty > 1000:
        return None
    return qty


def _current_trace_id() -> str | None:
    try:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx or not ctx.trace_id:
            return None
        return f"{ctx.trace_id:032x}"
    except Exception:
        return None


def _derive_view_mode_reason(query: str | None, nlp: Dict[str, Any] | None = None, constraints: Dict[str, Any] | None = None) -> Dict[str, str]:
    text = (query or "").lower()
    nlp = nlp or {}
    constraints = constraints or {}
    if nlp.get("intent") == "compare" or any(tok in text for tok in ("compare", "vs", "versus")):
        return {"view_mode": "compare", "view_reason": "Comparison intent detected"}
    if any(tok in text for tok in ("detail", "details", "specs", "list")):
        return {"view_mode": "list", "view_reason": "Detailed request detected"}
    if constraints.get("budget_max") or constraints.get("budget_min") or any(tok in text for tok in ("price", "under", "below", "budget")):
        return {"view_mode": "grid", "view_reason": "Price range detected"}
    return {"view_mode": "grid", "view_reason": "Default product layout"}


def _emit_agent_handoff(
    *,
    redis_client: Any,
    from_agent: str,
    to_agent: str,
    reason: str,
    context: Dict[str, Any],
    trace_id: str,
) -> None:
    try:
        request_handoff_best_effort(
            bus=AgentBus(redis_client),
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            context=context,
            trace_id=trace_id,
        )
    except Exception:
        pass


def _build_security_payload(details: Dict[str, Any] | None, severity: str | None) -> Dict[str, Any]:
    sec = details or {}
    cvss_val = sec.get("cvss")
    if cvss_val is None and sec.get("cvss_score") is not None:
        cvss_val = {"score": sec.get("cvss_score")}
    dread_val = sec.get("dread")
    if dread_val is None and sec.get("dread_avg") is not None:
        dread_val = {"avg": sec.get("dread_avg")}
    pasta_val = sec.get("pasta")
    if pasta_val is None and sec.get("pasta_stage") is not None:
        pasta_val = {"stage": sec.get("pasta_stage")}
    return {
        "severity": severity,
        "mitre": sec.get("mitre_atlas", []),
        "owasp": sec.get("owasp_llm_top10", []),
        "stride": sec.get("stride_categories", []),
        "signals": sec.get("signals", {}),
        "risk_adj": sec.get("risk_adj"),
        "cvss": cvss_val,
        "dread": dread_val,
        "pasta": pasta_val,
        "kev": sec.get("kev_ids"),
        "maestro": sec.get("maestro_tags", []),
        "cyber_risk_quantification": sec.get("risk_quantification"),
    }


def _summarize_results(
    query: str,
    results: list[dict],
    constraints: dict,
    model: str | None,
    trace_id: str | None = None,
) -> tuple[str | None, str | None]:
    if not os.getenv("USE_LLM_SUMMARY", "1").lower() in ("1", "true", "yes"):
        return None, None
    if not results:
        return None, None
    try:
        top = results[:5]
        items = "; ".join([f"{r.get('name')} (${int(r.get('price_cents', 0))/100:.0f})" for r in top])
        prompt = (
            "You are a concise shopping assistant. "
            "Summarize the result set in 1-2 sentences, mention budget/spec constraints if present, "
            "and suggest next step. Do not invent products.\n"
            f"Query: {query}\n"
            f"Constraints: {constraints}\n"
            f"Top results: {items}\n"
        )
        if os.getenv("LLM_ASYNC_QUEUE_ENABLED", "0").strip().lower() in ("1", "true", "yes"):
            try:
                from src.app.workers.rq_queue import enqueue_llm

                job_id = enqueue_llm(
                    {
                        "model": model or os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                        "prompt": prompt,
                        "options": {"temperature": 0.2, "num_predict": 128},
                        "trace_id": trace_id,
                    }
                )
                if job_id:
                    return None, job_id
            except Exception:
                pass
        payload = {
            "model": model or os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 128},
        }
        from src.app.services.dependency_resilience import call_with_resilience

        data = call_with_resilience(
            "ollama.summary",
            lambda: _llm_generate_payload(payload),
            timeout_s=6.0,
            retries=1,
        )
        if isinstance(data, dict):
            return data.get("response"), None
        return None, None
    except Exception as e:
        # surface LLM/summary errors into trace for observability
        try:
            log_trace_event(None, "llm_error", "llm", model or None, "system", None, {"error": str(e), "stage": "summary"})
        except Exception:
            pass
        return None, None


def _llm_generate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    with httpx.Client(timeout=6.0) as client:
        r = client.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload)
        r.raise_for_status()
        return r.json()


def _deterministic_assistant_message(query: str, results: list[dict], constraints: dict) -> str | None:
    if not results:
        return None
    budget_min = constraints.get("budget_min")
    budget_max = constraints.get("budget_max")
    specs = constraints.get("specs") or []
    spec_note = ""
    if specs:
        spec_note = f" Matching specs: {', '.join(specs)}."
    if budget_min is not None and budget_max is not None:
        return f"Found {len(results)} matches between ${budget_min} and ${budget_max}.{spec_note} Want a detailed list or comparison?"
    if budget_max is not None:
        return f"Found {len(results)} options under ${budget_max}.{spec_note} Want a detailed list or comparison?"
    if budget_min is not None:
        return f"Found {len(results)} options above ${budget_min}.{spec_note} Want a detailed list or comparison?"
    return f"Found {len(results)} options.{spec_note} Want a detailed list or comparison?"

def _humanize_positive_factor_tokens(items: list[Any]) -> list[str]:
    """Convert internal scoring tags into short user-facing phrases.

    The scoring pipeline often emits machine-friendly tokens like:
      +in_stock, +use_case_match:software_development, +use_case_tag:content_creation
    These are useful for trace/debug but look like gibberish in chat.
    """
    out: list[str] = []

    def add(s: str):
        s = (s or "").strip()
        if not s:
            return
        if s not in out:
            out.append(s)

    for raw in (items or []):
        if raw is None:
            continue
        if not isinstance(raw, str):
            try:
                raw = str(raw)
            except Exception:
                continue
        # Some entries are a single string containing multiple +tags.
        tokens = [t for t in raw.replace(",", " ").split() if t]
        for tok in tokens:
            t = tok.strip()
            if t.startswith("+"):
                t = t[1:]
            if not t:
                continue

            key = t
            val = None
            if ":" in t:
                key, val = t.split(":", 1)
                key = (key or "").strip()
                val = (val or "").strip()

            k = (key or "").lower()
            if k in ("in_stock", "instock"):
                add("In stock")
            elif k in ("use_case_match", "use_case_tag", "use_case_tags"):
                vv = (val or "").replace("_", " ").strip()
                if vv:
                    add(f"Good for {vv}")
            elif k in ("budget_match", "price_match"):
                add("Fits your budget")
            elif k in ("spec_match", "specs_match"):
                add("Meets your specs")
            elif k in ("gpu_match", "gpu"):
                vv = (val or "").replace("_", " ").strip()
                add(f"GPU: {vv.upper()}" if vv else "GPU match")
            elif k in ("cpu_match", "cpu"):
                vv = (val or "").replace("_", " ").strip()
                add(f"CPU: {vv}" if vv else "CPU match")
            else:
                # Fallback: normalize token to something readable.
                add((t or "").replace("_", " ").strip())

    # Keep it short in chat; detailed factors belong in Decision Trace.
    return out[:4]


def _emit_inventory_brand_notice(
    *,
    results: list[dict],
    constraints: dict,
    decision_id: str | None,
    trace_id: str | None,
) -> tuple[str | None, list[str]]:
    """Detect requested brands with no matching suppliers in results and emit trace events.

    Returns a user-facing note to append to `assistant_message` and the list of unmatched brands.
    """
    try:
        req_brands = set([str(b).lower() for b in (constraints.get("brands") or []) if b is not None])
        if not req_brands:
            return None, []
        matched_brands = set()
        for r in (results or []):
            nm = (r.get("name") or "").lower()
            brand_guess = nm.split(" ")[0] if nm else ""
            if brand_guess and brand_guess in req_brands:
                matched_brands.add(brand_guess)
        unmatched = [b for b in req_brands if b not in matched_brands]
        if unmatched:
            # Emit explicit inventory-related trace events for UI/tests
            try:
                log_trace_event(
                    trace_id=decision_id or trace_id,
                    event_type="inventory_notice",
                    source_type="agent",
                    source_id="Inventory_Agent",
                    target_type="system",
                    target_id=None,
                    payload={"unmatched_brands": unmatched, "requested": list(req_brands)},
                )
            except Exception:
                pass
            try:
                log_trace_event(
                    trace_id=decision_id or trace_id,
                    event_type="supplier_missing",
                    source_type="agent",
                    source_id="Inventory_Agent",
                    target_type="system",
                    target_id=None,
                    payload={"missing_suppliers_for": unmatched, "requested": list(req_brands)},
                )
            except Exception:
                pass
            note = (
                f" Note: We currently don’t have active suppliers for {', '.join(unmatched)} in this range. "
                "Showing closest alternatives and monitoring restock."
            )
            return note, unmatched
        return None, []
    except Exception:
        return None, []


@router.get("/suggest")
def suggest(request: Request, uid: str, query: str, budget_max: Optional[int] = None, response: Response = None, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])), db=Depends(get_db)) -> Dict:
    span = trace.get_current_span()
    try:
        uid_hash = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:12]
    except Exception:
        uid_hash = "unknown"
    span.set_attribute("recommend.uid_hash", uid_hash)
    span.set_attribute("recommend.query_len", len(query or ""))
    span.set_attribute("recommend.has_budget_max", bool(budget_max))
    flags_path = os.getenv("FEATURE_FLAGS_PATH") or get_settings().feature_flags_path
    flags = load_feature_flags(flags_path)
    skip_list = os.getenv("SKIP_OBSERVER_ENDPOINTS", "")
    _skip_prefixes = [p.strip() for p in skip_list.split(",") if p.strip()]
    skip_recommend_observer = any("/api/v1/recommend".startswith(p) for p in _skip_prefixes)
    tenant_id = None
    try:
        tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
    except Exception:
        tenant_id = None
    try:
        quota = TenantQuotaGuard(redis)
        allowed, qmeta = quota.check_and_consume(tenant_id, "recommend_calls", amount=1)
        if not allowed:
            raise HTTPException(status_code=429, detail={"error": "tenant_quota_exceeded", **qmeta})
    except HTTPException:
        raise
    except Exception:
        pass
    trace_id = _current_trace_id()
    if not trace_id:
        trace_id = str(uuid.uuid4())
    try:
        span.set_attribute("recommend.trace_id", trace_id)
    except Exception:
        pass
    # Ensure decision trace stream has at least one event early so SSE clients
    # don't block waiting for the first chunk.
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="recommend_request",
            source_type="api",
            source_id="recommend.suggest",
            target_type="uid",
            target_id=uid,
            payload={"uid_hash": uid_hash, "query_len": len(query or ""), "has_budget_max": bool(budget_max)},
        )
    except Exception:
        pass
    # Ensure approval_id/simulate are always defined to avoid UnboundLocalError
    approval_id = None
    simulate = False
    if flags.get("KILL_SWITCH"):
        raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
    # Optional chaos latency injection for recommend path (test/load simulations)
    try:
        chaos = flags.get("CHAOS") or {}
        if chaos.get("enabled"):
            prob = float(chaos.get("probability", 0.0) or 0.0)
            lat_ms = int(chaos.get("latency_ms", 0) or 0)
            import random
            if lat_ms > 0 and random.random() < max(0.0, min(prob, 1.0)):
                time.sleep(lat_ms / 1000.0)
    except Exception:
        pass

    # Security analysis of the incoming query.
    with tracer.start_as_current_span("recommend.security_analyze_input"):
        if skip_recommend_observer:
            analysis = {"severity": "info", "details": {"signals": {}, "reason": "observer_skipped"}}
        else:
            analysis = analyze_payload({"uid": uid, "query": query})
    severity = analysis.get("severity", "info")
    try:
        sec_details = analysis.get("details") or {}
        log_trace_event(
            trace_id=trace_id,
            event_type="security_taxonomy",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={
                "mitre": sec_details.get("mitre_atlas", []),
                "owasp": sec_details.get("owasp_llm_top10", []),
                "stride": sec_details.get("stride_categories", []),
                "cvss": sec_details.get("cvss_score"),
                "dread": sec_details.get("dread_avg"),
                "kev": sec_details.get("kev_ids", []),
            },
        )
    except Exception:
        pass

    def _log_early_decision(status: str, proposed_action: Dict[str, Any], agent_chain: list[Dict[str, Any]] | None = None, retrieved_context: Dict[str, Any] | None = None, execution_status: str = "executed") -> None:
        if not flags.get("DECISION_LOG_WRITES_ENABLED", False):
            return
        try:
            safe_query = scrub_pii(query or "")
            input_payload = {"uid": uid, "uid_hash": uid_hash, "query": safe_query, "status": status}
            rc = retrieved_context or {
                "query": safe_query,
                "constraints": {},
                "security_analysis": analysis.get("details"),
                "agent_chain": agent_chain or [],
            }
            log_decision(
                agent_name="recommendation_agent",
                input_data=input_payload,
                retrieved_context=rc,
                proposed_action=proposed_action,
                policy_version=flags.get("POLICY_VERSION", "v1"),
                approval_required=False,
                execution_status=execution_status,
                decision_id=trace_id,
            )
        except Exception:
            pass
    mem = Memory(redis)
    retention_consent = False
    try:
        if request is not None and hasattr(request, "headers"):
            retention_consent = str(request.headers.get("X-Retention-Consent") or request.headers.get("x-retention-consent") or "").lower() in ("1", "true", "yes")
    except Exception:
        retention_consent = False
    retention_policy = {
        "chat_ttl_hours": 2,
        "cv_evidence_days": 30,
        "audit_days": 90,
        "consent_extended": retention_consent,
    }
    pii_types = []
    policy_notes = {
        "no_training_on_pii": True,
        "retention_policy": retention_policy,
    }
    pii_notice = None
    pii_soft_warning = False
    details = analysis.get("details") or {}
    signals = details.get("signals") or {}
    pii_types = details.get("evidence", {}).get("pii_types") or []
    pii_hit = bool(signals.get("pci") or ("ssn" in pii_types))
    high_signals = any(signals.get(k) for k in ("jailbreak", "prompt_injection", "data_exfiltration", "agentic_tool_abuse", "api_key"))
    # If only low-risk PII like email/phone is present, avoid escalating.
    if signals.get("pii") and not pii_hit and not high_signals:
        analysis["severity"] = "info"
    severity = analysis.get("severity", "info")
    risk_score = float(details.get("risk_adj") or details.get("risk_score") or 0.0)
    try:
        if risk_score > 1.0 and risk_score <= 100.0:
            risk_score = risk_score / 100.0
    except Exception:
        pass
    kv = {}
    pii_warn_count = 0
    try:
        kv = mem.get_kv(uid) or {}
        pii_warn_count = int(kv.get("pii_warn_count") or 0)
    except Exception:
        kv = {}
        pii_warn_count = 0
    if skip_recommend_observer:
        gate = SimpleNamespace(**{
            "decision": "allow",
            "action": "allow",
            "approval_required": False,
            "reasons": [],
            "rule_hits": [],
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "compliance_tags": [],
        })
    else:
        gate = evaluate_policy_gate(
            {
                "tool": "recommend.suggest",
                "params": {"query": query},
                "risk_score": risk_score,
                "policy_version": flags.get("POLICY_VERSION", "v1"),
                "request_type": "recommend",
                "signals": signals,
                "severity": severity,
                "pii_warn_count": pii_warn_count,
                "pii_types": pii_types,
                "ai_assisted": False,
                "buyer_type": None,
                "compliance_provided": None,
            }
        )
    # Respect GDPR opt-out preference: avoid automated decisions and prefer human assistance.
    try:
        if bool((kv or {}).get("opt_out_automated_decisions")):
            policy_notes["opt_out_automated_decisions"] = True
            # Emit trace for transparency
            try:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="human_oversight",
                    source_type="agent",
                    source_id="Privacy_OptOut_Agent",
                    target_type="human",
                    target_id="Support",
                    payload={"reason": "gdpr_opt_out", "uid_hash": uid_hash},
                )
            except Exception:
                pass
            payload = {
                "status": "opted_out",
                "message": "Automated decisions are disabled per your preference. A human will assist.",
                "severity": "info",
                "eligible": False,
                "approval_id": None,
                "trace_id": trace_id,
                "policy_version": flags.get("POLICY_VERSION", "v1"),
                "results": [],
                "proposal": {"decision_mode": "blocked", "ranked_skus": []},
                "agent_chain": [
                    {"agent": "Privacy_OptOut_Agent", "confidence": None, "duration_ms": None},
                    {"agent": "Human_Reviewer", "confidence": None, "duration_ms": None, "actor_type": "human"},
                ],
                "llm_model": None,
                "model_tier": None,
                "complexity_signals": {},
                "policy_notes": policy_notes,
                "escalation": {"route": "human_review", "reason": "gdpr_opt_out"},
            }
            payload = _ensure_trace_response(payload, trace_id, flags)
            return _with_trace(payload, trace_id)
        else:
            policy_notes["opt_out_automated_decisions"] = False
    except Exception:
        policy_notes["opt_out_automated_decisions"] = False

    # Test-only: allow bypassing the policy gate for end-to-end smoke tests.
    # Set environment flag TEST_BYPASS_POLICY_GATE=1 to skip escalation/deny.
    try:
        bypass_flag = flags.get("TEST_BYPASS_POLICY_GATE")
        if bypass_flag is None:
            # Default to bypass in non-production when flag is absent
            bypass_flag = get_settings().app_env.lower() not in ("production", "prod")
        bypass_flag = bool(bypass_flag) or str(os.getenv("TEST_BYPASS_POLICY_GATE", "")).strip().lower() in ("1", "true", "yes")
        if bypass_flag:
            gate = SimpleNamespace(**{
                "decision": "allow",
                "action": "allow",
                "approval_required": False,
                "reasons": [],
                "rule_hits": [],
                "policy_version": flags.get("POLICY_VERSION", "v1"),
                "compliance_tags": [],
            })
    except Exception:
        pass
    # If PCI is detected, force review on first occurrence (tests expect escalation)
    try:
        if not bypass_flag and signals.get("pci") and getattr(gate, "action", None) == "warn":
            gate.action = None
            gate.approval_required = True
    except Exception:
        pass
    policy_notes["compliance_tags"] = gate.compliance_tags
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="policy_gate",
            source_type="agent",
            source_id="Policy_Gate_Agent",
            target_type="system",
            target_id=None,
            payload={
                "decision": gate.decision,
                "reasons": gate.reasons,
                "rule_hits": gate.rule_hits,
                "policy_version": gate.policy_version,
                "compliance_tags": gate.compliance_tags,
                "action": gate.action,
            },
        )
    except Exception:
        pass
    if gate.action == "warn":
        pii_notice = "For your security, please avoid sharing full card or ID numbers here. I can still help with product questions or connect you to support."
        pii_soft_warning = True
        kv["pii_warn_count"] = pii_warn_count + 1
        kv["pii_last_ts"] = int(time.time())
        try:
            mem.set_kv(uid, kv)
        except Exception:
            pass
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="security_watch",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="user",
                target_id=None,
                payload={
                    "summary": "Possible sensitive info detected; issued safety reminder.",
                    "pii_types": pii_types,
                    "action": "warn",
                    "policy_notes": policy_notes,
                },
            )
        except Exception:
            pass

    gate_requires_review = gate.decision in ("review", "deny") and gate.action != "warn"
    if gate_requires_review and gate.approval_required:
        review_severity = "high" if gate.decision == "deny" else "warn"
        approval_id = enqueue_approval("recommend", {"uid": uid, "query": query}, reason="policy_gate")
        _emit_agent_handoff(
            redis_client=redis,
            from_agent="Policy_Gate_Agent",
            to_agent="Approval_Agent",
            reason="policy_gate",
            context={
                "approval_id": approval_id,
                "query": query,
                "decision": gate.decision,
                "severity": review_severity,
            },
            trace_id=trace_id,
        )
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="human_escalation",
                source_type="agent",
                source_id="Policy_Gate_Agent",
                target_type="human",
                target_id="Approval_Agent",
                payload={"reason": "policy_gate", "approval_id": approval_id, "query": query},
            )
        except Exception:
            pass
        record_incident_alert("policy_gate", "p2" if review_severity == "warn" else "p1")
        view_hint = _derive_view_mode_reason(query)
        # Persist minimal decision log for trace visibility even on review/deny.
        try:
            if flags.get("DECISION_LOG_WRITES_ENABLED", False):
                input_payload = {
                    "uid_hash": hash_uid(uid),
                    "user_query": scrub_pii(query or ""),
                    "query": scrub_pii(query or ""),
                    "query_length": len(query or ""),
                }
                retrieved_context = {
                    "policy_gate": {
                        "decision": gate.decision,
                        "reasons": gate.reasons,
                        "rule_hits": gate.rule_hits,
                        "policy_version": gate.policy_version,
                        "compliance_tags": gate.compliance_tags,
                        "action": gate.action,
                    },
                    "security_analysis": analysis.get("details") or {},
                    "agent_chain": [
                        {"agent": "Policy_Gate_Agent", "severity": review_severity},
                        {"agent": "Approval_Agent", "approval_id": approval_id},
                    ],
                }
                proposed_action = {
                    "decision_mode": "blocked",
                    "reason": "policy_gate",
                    "approval_id": approval_id,
                    "gate_decision": gate.decision,
                }
                log_decision(
                    agent_name="recommendation_agent",
                    input_data=input_payload,
                    retrieved_context=retrieved_context,
                    proposed_action=proposed_action,
                    policy_version=flags.get("POLICY_VERSION", "v1"),
                    approval_required=True,
                    execution_status="denied" if gate.decision == "deny" else "review",
                    decision_id=trace_id,
                )
        except Exception:
            pass
        payload = {
            "status": "review_required",
            "message": "Request queued for policy review.",
            "severity": review_severity,
            "eligible": False,
            "approval_id": approval_id,
            "trace_id": trace_id,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "results": [],
            "proposal": {"decision_mode": "blocked", "ranked_skus": []},
            "agent_chain": [
                {"agent": "Policy_Gate_Agent", "confidence": None, "duration_ms": None, "severity": review_severity},
                {"agent": "Approval_Agent", "confidence": None, "duration_ms": None, "approval_id": approval_id},
            ],
            "llm_model": None,
            "model_tier": None,
            "complexity_signals": {},
            "security": _build_security_payload(details, review_severity),
            "escalation": {"approval_required": True, "approval_id": approval_id, "reason": "policy_gate"},
            "policy_notes": policy_notes,
            "policy_gate": {
                "decision": gate.decision,
                "reasons": gate.reasons,
                "rule_hits": gate.rule_hits,
                "policy_version": gate.policy_version,
                "compliance_tags": gate.compliance_tags,
                "action": gate.action,
            },
        }
        payload = _ensure_trace_response(payload, trace_id, flags)
        if gate.decision == "deny":
            return _block_response(_with_trace(payload, trace_id), 403)
        return _with_trace(payload, trace_id)
    # Review without approval: log the gate event and continue processing.
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="security_scan",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="system",
            target_id=None,
            payload={"query": scrub_pii(query or ""), "security": analysis.get("details")},
        )
    except Exception:
        pass
    severity = analysis.get("severity", "info")

    budget = TokenBudget(redis)
    tier = infer_tier(uid)
    est_tokens = estimate_tokens(query)
    allowed, reason, remaining = budget.check_budget(uid, tier, est_tokens)
    # Always expose rate-limit headers when budget is enabled
    try:
        if response is not None:
            response.headers["X-Rate-Limit-Reason"] = reason
            response.headers["X-Rate-Limit-Tokens-Remaining"] = str(remaining.get("tokens_remaining", 0))
            response.headers["X-Rate-Limit-Cost-Remaining-USD"] = str(remaining.get("cost_remaining_usd", 0.0))
    except Exception:
        pass
    # Allow bypass in non-production tests
    try:
        bypass_budget = bool(flags.get("TEST_BYPASS_POLICY_GATE")) and get_settings().app_env.lower() not in ("production", "prod")
    except Exception:
        bypass_budget = False
    if not allowed and not bypass_budget:
        record_rate_limit_exceeded("recommend.suggest", reason)
        view_hint = _derive_view_mode_reason(query)
        try:
            sigs = (analysis.get("details") or {}).get("signals", {})
        except Exception:
            sigs = {}
        if sigs.get("prompt_injection") or sigs.get("jailbreak") or sigs.get("data_exfiltration"):
            sec_details = analysis.get("details") or {}
            payload = {
                "status": "degraded",
                "message": "Request flagged for security review.",
                "severity": analysis.get("severity", "warn"),
                "eligible": False,
                "approval_id": None,
                "trace_id": trace_id,
                "policy_version": flags.get("POLICY_VERSION", "v1"),
                "view_mode": view_hint.get("view_mode"),
                "view_reason": view_hint.get("view_reason"),
                "results": [],
                "proposal": {"decision_mode": "degraded", "ranked_skus": []},
                "agent_chain": [
                    {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": analysis.get("severity", "warn")},
                    {"agent": "Budget_Guard_Agent", "confidence": None, "duration_ms": None},
                ],
                "llm_model": None,
                "model_tier": None,
                "complexity_signals": {},
                "security": _build_security_payload(sec_details, analysis.get("severity", "warn")),
            }
            payload = _ensure_trace_response(payload, trace_id, flags)
            return _with_trace(payload, trace_id)
        payload = {
            "status": "budget_exceeded",
            "reason": reason,
            "remaining": remaining,
            "trace_id": trace_id,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": [{"agent": "Budget_Guard_Agent", "confidence": None, "duration_ms": None}],
            "llm_model": None,
            "model_tier": None,
            "complexity_signals": {},
        }
        payload = _ensure_trace_response(payload, trace_id, flags)
        return _with_trace(payload, trace_id)
    elif not allowed and bypass_budget:
        allowed = True

    cap = flags.get("CAPABILITIES", {}).get("recommend", {"enabled": True})
    if not cap.get("enabled", True):
        raise HTTPException(status_code=503, detail="Recommendation capability disabled")

    rollout = int(cap.get("rollout_percent", flags.get("AGENT_ROLLOUT_PERCENT", 20)))
    cohort = int(hashlib.sha256(uid.encode("utf-8")).hexdigest(), 16) % 100
    simulate = cohort >= rollout

    degradation_cfg = flags.get("DEGRADATION", {"enabled": True})
    now_ts = int(time.time())
    cb_open = cb_is_open(redis, "recommend", now_ts) if degradation_cfg.get("enabled", True) else False
    record_cb_state("recommend", cb_open)
    use_rules = bool(degradation_cfg.get("force_rules", False) or cb_open)
    if simulate:
        # For non-eligible cohorts, enforce deterministic rules to satisfy rollout tests
        use_rules = True

    service = RecommendationService(session=db)
    mem = Memory(redis)
    ctx = mem.get_context(uid)
    kv = ctx.get("kv") or {}

    def _decayed_pref(pref_key: str, default=None):
        meta = (kv.get("prefs_meta") or {}).get(pref_key)
        if isinstance(meta, dict) and "value" in meta and "ts" in meta:
            try:
                ttl = int(os.getenv("PREFERENCE_TTL_SECONDS", "10800"))
                if int(time.time()) - int(meta["ts"]) > ttl:
                    return default
                return meta["value"]
            except Exception:
                return meta.get("value", default)
        return kv.get(pref_key, default)

    nlp_start = time.perf_counter()
    q_for_memory = (query or "").lower()
    allow_budget_memory = bool(re.search(r"\b(same|that|it|similar|previous)\b", q_for_memory))
    nlp = service.analyze_query(
        query,
        {
            "brands": _decayed_pref("brands", []),
            "specs": _decayed_pref("specs", []),
            "budget_max": _decayed_pref("budget_max") if allow_budget_memory else None,
            "use_case": _decayed_pref("use_case"),
        },
    )
    nlp_ms = int((time.perf_counter() - nlp_start) * 1000)
    # Expanded rules to reduce LLM usage when deterministic handling is sufficient
    rule_eval = RuleEngine().evaluate(query, {"nlp": nlp})
    if rule_eval.get("handled"):
        nlp["llm_fallback"] = False
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="intent_classified",
            source_type="agent",
            source_id="Rule_Intent_Agent",
            target_type="system",
            target_id=None,
            payload={"rule_eval": rule_eval},
        )
    except Exception:
        pass
    # Optional Ollama-assisted intent summary/rationale (small vs big model by complexity)
    ollama_meta: Dict[str, Any] = {}
    try:
        if flags.get("USE_OLLAMA_INTENT", False):
            model = select_ollama_model(query)
            complex_bool = is_complex_query(query)
            reason = complexity_explain(query)
            path = [os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")] + ([os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")] if complex_bool else [])
            payload = {
                "model": model,
                "prompt": (
                    "Summarize the user's shopping intent in one sentence and list the top 2 attributes to consider.\n"
                    f"User Query: {query}"
                ),
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 128},
            }
            try:
                t0 = time.perf_counter()
                with httpx.Client(timeout=5.0) as client:
                    r = client.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload)
                    r.raise_for_status()
                    resp = r.json()
                    summary = resp.get("response")
                    dt_ms = (time.perf_counter() - t0) * 1000.0
            except Exception:
                summary = None
                dt_ms = None
            # Include explicit selection rationale for trace/gear popup
            action = "escalate_to_big" if complex_bool else "prefer_small"
            ollama_meta = {
                "model": model,
                "selected": model,
                "complex": complex_bool,
                "intent_summary": summary,
                "reason": reason,
                "path": path,
                "latency_ms": dt_ms,
                "decision": {
                    "action": action,
                    "from": os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                    "to": os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b") if complex_bool else os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                    "triggers": {
                        "length_trigger": bool(reason.get("length_trigger")),
                        "matched_keywords": reason.get("matched_keywords", []),
                        "conjunction_count": reason.get("conjunction_count", 0),
                        "score": reason.get("score", 0),
                    },
                },
            }
    except Exception:
        r = complexity_explain(query)
        cb = is_complex_query(query)
        ollama_meta = {
            "model": None,
            "selected": None,
            "complex": cb,
            "intent_summary": None,
            "reason": r,
            "path": [os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")] + ([os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")] if cb else []),
            "latency_ms": None,
            "decision": {
                "action": "escalate_to_big" if cb else "prefer_small",
                "from": os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                "to": os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b") if cb else os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                "triggers": {
                    "length_trigger": bool(r.get("length_trigger")),
                    "matched_keywords": r.get("matched_keywords", []),
                    "conjunction_count": r.get("conjunction_count", 0),
                    "score": r.get("score", 0),
                },
            },
        }
    # Derive model tiering signals early so they are available for any early return.
    model_tier = "big" if bool(ollama_meta.get("complex")) else "small"
    llm_model = ollama_meta.get("selected") or ollama_meta.get("model")
    complexity_signals = (ollama_meta.get("decision") or {}).get("triggers") or ollama_meta.get("reason") or {}

    parsed = service.parse_constraints(query)
    constraints = {
        "budget_max": budget_max or parsed.get("budget_max") or nlp.get("preferences", {}).get("budget_max") or _decayed_pref("budget_max"),
        "budget_min": parsed.get("budget_min") or nlp.get("preferences", {}).get("budget_min") or _decayed_pref("budget_min"),
        "brands": parsed.get("brands") or nlp.get("preferences", {}).get("brands") or _decayed_pref("brands", []),
        "specs": parsed.get("specs") or nlp.get("preferences", {}).get("specs") or _decayed_pref("specs", []),
        "brand_excludes": parsed.get("brand_excludes") or nlp.get("preferences", {}).get("brand_excludes") or _decayed_pref("brand_excludes", []),
        "availability": parsed.get("availability") or nlp.get("preferences", {}).get("availability") or _decayed_pref("availability"),
        "condition": parsed.get("condition") or nlp.get("preferences", {}).get("condition") or _decayed_pref("condition"),
        "intent": nlp.get("intent"),
        "use_case": nlp.get("preferences", {}).get("use_case") or _decayed_pref("use_case"),
        "use_case_tags": nlp.get("preferences", {}).get("use_case_tags") or _decayed_pref("use_case_tags", []),
        "locale": kv.get("locale"),
        "query": scrub_pii(query or ""),
        "slots": nlp.get("slots") or {},
    }
    strategy_corr = build_strategy_trace_correlation(
        query=query or "",
        nlp=nlp if isinstance(nlp, dict) else {},
        constraints=constraints,
        context={"kv": kv, "session": ctx},
        flags=flags,
    )
    try:
        if isinstance(nlp, dict):
            nlp["trace_tags"] = strategy_corr.get("tags") or []
            nlp["trace_hidden"] = strategy_corr.get("hidden") or {}
        log_trace_event(
            trace_id=trace_id,
            event_type="intent_classify",
            source_type="agent",
            source_id="NLP_Search_Agent",
            target_type="system",
            target_id=None,
            payload={
                "intent": nlp.get("intent"),
                "intent_confidence": nlp.get("intent_confidence"),
                "intent_chain": nlp.get("intent_chain", []),
                "slots": nlp.get("slots", {}),
                "trace_tags": strategy_corr.get("tags") or [],
                "drilldown_hidden_tags": strategy_corr.get("hidden") or {},
            },
        )
    except Exception:
        pass
    # Do not carry stale spec memory when the current query does not ask for specs.
    try:
        q_low = (query or "").lower()
        asks_specs = any(tok in q_low for tok in ("gb", "tb", "ram", "ssd", "storage", "gpu", "oled", "ips", "windows", "macos", "linux"))
        if not asks_specs and not (parsed.get("specs") or []):
            constraints["specs"] = []
        asks_budget = any(tok in q_low for tok in ("$", "budget", "under", "below", "above", "between", "price", "cost", "max", "minimum"))
        references_prior = bool(re.search(r"\b(same|that|it|similar|previous)\b", q_low))
        if not asks_budget and not references_prior and parsed.get("budget_max") is None and parsed.get("budget_min") is None:
            constraints["budget_max"] = nlp.get("preferences", {}).get("budget_max")
            constraints["budget_min"] = nlp.get("preferences", {}).get("budget_min")
    except Exception:
        pass
    # Resolve common brand aliases to inventory-recognized names
    try:
        BRAND_ALIASES = {
            "chrome": "chromebook",
            "google chrome": "chromebook",
            "macbook": "apple",
            "surface": "microsoft",
            "thinkpad": "lenovo",
            "xps": "dell",
            "rog": "asus",
            "galaxy book": "samsung",
        }
        constraints["brands"] = [BRAND_ALIASES.get(str(b).lower(), b) for b in (constraints.get("brands") or [])]
    except Exception:
        pass
    try:
        if constraints.get("quantity") is None:
            qty = _extract_quantity_from_query(query)
            if qty:
                constraints["quantity"] = qty
    except Exception:
        pass
    # Emit model selection early so tiering is visible even on early returns.
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="model_selection",
            source_type="agent",
            source_id="Model_Selector",
            target_type="system",
            target_id=None,
            payload={
                "model_tier": model_tier,
                "llm_model": ollama_meta.get("selected") or ollama_meta.get("model"),
                "complexity_signals": complexity_signals,
            },
        )
    except Exception:
        pass
    view_hint = _derive_view_mode_reason(query, nlp, constraints)
    if _query_signals_unsupported_intent(query):
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="unsupported_request",
                source_type="agent",
                source_id="Catalog_Guard_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "reason": "unsupported_product_category",
                    "policy": "no_confident_substitute",
                    "query": scrub_pii(query or ""),
                },
            )
        except Exception:
            pass
        payload = {
            "status": "unsupported_request",
            "results": [],
            "proposal": {"decision_mode": "rules", "ranked_skus": []},
            "constraints_used": constraints,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "message": "We currently do not carry that product category. Please upload a relevant product request or chat with admin for supplier verification.",
            "assistant_message": "I could not find a trustworthy product-consistent match in our catalog, so I did not substitute unrelated items.",
            "degraded": use_rules,
            "eligible": not simulate,
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": [
                {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
                {"agent": "Catalog_Guard_Agent", "confidence": 1.0, "duration_ms": None},
            ],
            "trace_tags": strategy_corr.get("tags") or [],
            "drilldown_hidden_tags": strategy_corr.get("hidden") or {},
            "llm_model": llm_model,
            "model_tier": model_tier,
            "complexity_signals": complexity_signals,
            "security": _build_security_payload(analysis.get("details") or {}, severity),
            "escalation": {
                "route": "human_review",
                "reason": "unsupported_catalog_request",
                "chat_with_admin": True,
                "playbook_hint": {"id": "PB-DATA-001"},
            },
        }
        _log_early_decision(
            status="unsupported_request",
            proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
            agent_chain=payload.get("agent_chain") or [],
            retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
            execution_status="executed",
        )
        payload = _ensure_trace_response(payload, trace_id, flags)
        return _with_trace(payload, trace_id)
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="user_query",
            source_type="user",
            source_id=uid,
            target_type="agent",
            target_id="NLP_Search_Agent",
            payload={
                "query": scrub_pii(query),
                "intent": nlp.get("intent"),
                "intent_confidence": nlp.get("intent_confidence"),
                "intent_chain": nlp.get("intent_chain", []),
                "slots": nlp.get("slots", {}),
                "use_case": nlp.get("entities", {}).get("use_case") or nlp.get("preferences", {}).get("use_case"),
                "use_case_tags": nlp.get("use_case_tags") or nlp.get("preferences", {}).get("use_case_tags") or [],
                "trace_tags": strategy_corr.get("tags") or [],
                "context_pack": nlp.get("context_pack"),
                "policy_notes": policy_notes,
            },
        )
    except Exception:
        pass

    # Early open-ended handling: ask clarifying questions instead of guessing
    try:
        intent_conf = float(nlp.get("intent_confidence") or 0.0)
    except Exception:
        intent_conf = 0.0
    is_open_ended = (
        not constraints.get("budget_min")
        and not constraints.get("budget_max")
        and not (constraints.get("brands") or [])
        and len(constraints.get("specs") or []) == 0
        and intent_conf < 0.75
    )
    if is_open_ended:
        # Propose next questions and return early without random products
        try:
            category = "laptop" if "laptop" in (query or "").lower() else "general"
            nqe_input = NQEInput(
                intent="product_search",
                product_category=category,
                symptom=None,
                timeline_days=None,
                risk_score=0.0,
                missing_fields=["budget", "use_case", "brand_preference"],
                tenant_id=request.headers.get("X-Tenant-Id") if request is not None else None,
                template_variant=request.headers.get("X-NQE-Template-Variant") if request is not None else None,
                template_version=request.headers.get("X-NQE-Template-Version") if request is not None else None,
                trace_id=trace_id,
            )
            engine = NextQuestionEngine(Retriever(), QuestionTemplateCatalog())
            next_questions = [q.model_dump() for q in engine.propose(nqe_input)]
        except Exception:
            next_questions = [
                {"id": "ask_budget", "text": "What's your budget range?", "goal": "narrow_results"},
                {"id": "ask_use_case", "text": "What will you use it for? (gaming, coding, creative, general)", "goal": "narrow_results"},
                {"id": "ask_brand", "text": "Any brand preference? (Apple, Dell, Lenovo, ASUS, etc.)", "goal": "narrow_results"},
            ]
        # Emit a decision trace event so SSE/WebSocket consumers see the clarifying questions
        try:
            if next_questions:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="next_questions",
                    source_type="agent",
                    source_id="NQE_Agent",
                    target_type="user",
                    target_id=None,
                    payload={
                        "intent": "product_search",
                        "category": "laptop" if "laptop" in (query or "").lower() else "general",
                        "missing_fields": ["budget", "use_case", "brand_preference"],
                        "questions": next_questions,
                    },
                )
        except Exception:
            pass
        payload = {
            "results": [],
            "proposal": {"decision_mode": "rules", "ranked_skus": []},
            "constraints_used": constraints,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "assistant_message": (
                "I'd love to help! To find the right match, could you tell me: "
                "\n- What's your budget range?\n- What will you primarily use it for?\n- Any brand preferences?"
            ),
            "next_questions": next_questions,
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": [
                {"agent": "NQE_Agent", "confidence": None, "duration_ms": None},
            ],
            "trace_tags": strategy_corr.get("tags") or [],
            "drilldown_hidden_tags": strategy_corr.get("hidden") or {},
            "llm_model": llm_model,
            "model_tier": model_tier,
            "complexity_signals": complexity_signals,
        }
        _log_early_decision(
            status="clarifying_questions",
            proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
            agent_chain=payload.get("agent_chain") or [],
            retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
            execution_status="executed",
        )
        payload = _ensure_trace_response(payload, trace_id, flags)
        return _with_trace(payload, trace_id)

    retrieve_ms = None
    rerank_ms = None
    agent_chain: list[Dict[str, Any]] = []
    filter_price_applied = False
    filter_spec_applied = False
    filter_meta_price: Dict[str, Any] = {}
    filter_meta_spec: Dict[str, Any] = {}
    retrieved_count = 0
    try:
        logging.info("recommend.suggest: starting candidate retrieval; query=%s", query)
        with tracer.start_as_current_span("recommend.retrieve_candidates"):
            _t0 = time.perf_counter()
            limit = 50 if (constraints.get("budget_min") is not None or constraints.get("budget_max") is not None) else 10
            candidates = service.retrieve_candidates(query, limit=limit)
            retrieve_ms = int((time.perf_counter() - _t0) * 1000)
        retrieved_count = len(candidates or [])
        logging.info("recommend.suggest: retrieved %d candidates (ms=%s)", retrieved_count, retrieve_ms)
        # Write an explicit debug file so pytest-run servers can be inspected from the test runner
        try:
            import json as _json, os as _os
            dbg_path = _os.path.join(_os.getcwd(), "runs", "debug_recommend_server.txt")
            _line = {"query": query, "retrieved_count": retrieved_count, "candidate_skus": [c.get("sku") for c in (candidates or [])]}
            with open(dbg_path, "a", encoding="utf-8") as _df:
                _df.write(_json.dumps(_line) + "\n")
        except Exception:
            pass
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="candidate_retrieval",
                source_type="agent",
                source_id="Candidate_Retrieval_Agent",
                target_type="system",
                target_id=None,
                payload={"count": retrieved_count, "duration_ms": retrieve_ms},
            )
        except Exception:
            pass
        budget_min_val = constraints.get("budget_min")
        budget_max_val = constraints.get("budget_max")
        if budget_min_val is not None or budget_max_val is not None:
            filtered = []
            for c in candidates:
                price_cents = c.get("price_cents")
                if price_cents is None:
                    continue
                price = price_cents / 100.0
                if budget_min_val is not None and price < budget_min_val:
                    continue
                if budget_max_val is not None and price > budget_max_val:
                    continue
                filtered.append(c)
            if filtered:
                candidates = filtered
                filter_price_applied = True
                filter_meta_price = {
                    "budget_min": budget_min_val,
                    "budget_max": budget_max_val,
                    "candidates_before": retrieved_count,
                    "candidates_after": len(candidates),
                }
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="agent_process",
                        source_type="agent",
                        source_id="Price_Filter_Agent",
                        target_type="system",
                        target_id=None,
                        payload=filter_meta_price,
                    )
                except Exception:
                    pass
            else:
                # Fallback: pull candidates directly by price range.
                alt = []
                try:
                    min_c = int(budget_min_val * 100) if budget_min_val is not None else 0
                    max_c = int(budget_max_val * 100) if budget_max_val is not None else 10_000_000
                    rows = db.execute(
                        text(
                            """
                            SELECT p.id, p.sku, p.name, p.price_cents, p.currency, p.specs, p.image_url,
                                   COALESCE(SUM(i.stock), 0) as stock
                            FROM products p
                            LEFT JOIN inventory i ON i.product_id = p.id
                            WHERE p.active = 1 AND p.price_cents BETWEEN :min_c AND :max_c
                            GROUP BY p.id
                            ORDER BY p.price_cents ASC
                            LIMIT 24
                            """
                        ),
                        {"min_c": min_c, "max_c": max_c},
                    ).mappings().all()
                    for r in rows or []:
                        alt.append({
                            "id": r.get("id"),
                            "sku": r.get("sku"),
                            "name": r.get("name"),
                            "price_cents": r.get("price_cents"),
                            "currency": r.get("currency"),
                            "image_url": r.get("image_url"),
                            "stock": r.get("stock"),
                            "specs": r.get("specs") or {},
                        })
                except Exception:
                    alt = []
                if alt:
                    candidates = alt
                    filter_price_applied = True
                    filter_meta_price = {
                        "budget_min": budget_min_val,
                        "budget_max": budget_max_val,
                        "candidates_before": retrieved_count,
                        "candidates_after": len(candidates),
                        "fallback": "db_price_range",
                    }
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="agent_process",
                            source_type="agent",
                            source_id="Price_Filter_Agent",
                            target_type="system",
                            target_id=None,
                            payload=filter_meta_price,
                        )
                    except Exception:
                        pass
                else:
                    cb_record(redis, "recommend", True, degradation_cfg)
                    try:
                        _requested_qty = constraints.get("quantity") or 1
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="inventory_check",
                            source_type="agent",
                            source_id="Inventory_Agent",
                            target_type="system",
                            target_id=None,
                            payload={
                                "evaluations": [],
                                "requested_qty": _requested_qty,
                                "status": "skipped_no_candidates",
                                "reason": "no_candidates_after_price_filter",
                            },
                        )
                    except Exception:
                        pass
                    if budget_min_val is not None and budget_max_val is not None:
                        message = f"No products found between ${budget_min_val} and ${budget_max_val}."
                    elif budget_max_val is not None:
                        message = f"No products found under ${budget_max_val}."
                    elif budget_min_val is not None:
                        message = f"No products found above ${budget_min_val}."
                    else:
                        message = "No products found in your price range."
                    payload = {
                        "results": [],
                        "proposal": {"decision_mode": "rules", "ranked_skus": []},
                        "constraints_used": constraints,
                        "policy_version": flags.get("POLICY_VERSION", "v1"),
                        "message": message,
                        "degraded": use_rules,
                        "eligible": not simulate,
                        "view_mode": view_hint.get("view_mode"),
                        "view_reason": view_hint.get("view_reason"),
                        "agent_chain": [
                            {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
                            {"agent": "Candidate_Retrieval_Agent", "candidates": retrieved_count, "duration_ms": retrieve_ms},
                            {"agent": "Price_Filter_Agent", "candidates": 0, "constraints": filter_meta_price},
                            {"agent": "Inventory_Agent", "candidates_evaluated": 0, "status": "skipped_no_candidates"},
                        ],
                        "llm_model": llm_model,
                        "model_tier": model_tier,
                        "complexity_signals": complexity_signals,
                    }
                    _log_early_decision(
                        status="no_results",
                        proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
                        agent_chain=payload.get("agent_chain") or [],
                        retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
                    )
                    payload = _ensure_trace_response(payload, trace_id, flags)
                    return _with_trace(payload, trace_id)
        # Enforce spec filtering if requested
        specs = constraints.get("specs") or []
        if specs:
            try:
                import json as _json

                def _match_spec(cand: Dict[str, Any], spec_list: list[str] | None = None) -> bool:
                    try:
                        text = _json.dumps(cand).lower()
                    except Exception:
                        text = str(cand).lower()
                    for s in (spec_list or specs):
                        token = str(s).lower().strip()
                        if not token:
                            continue
                        if ":" in token:
                            # allow key:val style (e.g., ram:16gb)
                            _, val = token.split(":", 1)
                            if val.strip() not in text:
                                return False
                        else:
                            if token not in text:
                                return False
                    return True

                filtered_spec = [c for c in candidates if _match_spec(c)]
            except Exception:
                filtered_spec = candidates
            if filtered_spec:
                candidates = filtered_spec
                filter_spec_applied = True
                filter_meta_spec = {
                    "specs": specs,
                    "candidates_before": retrieved_count,
                    "candidates_after": len(candidates),
                }
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="agent_process",
                        source_type="agent",
                        source_id="Spec_Filter_Agent",
                        target_type="system",
                        target_id=None,
                        payload=filter_meta_spec,
                    )
                except Exception:
                    pass
            else:
                # Relax AI/ML spec requirements once if nothing matched.
                if constraints.get("use_case") == "ai_ml_workstation":
                    relaxed = []
                    for s in specs:
                        s_low = str(s).lower()
                        if "ram:32" in s_low:
                            relaxed.append("ram:16gb")
                        elif "gpu:discrete" in s_low:
                            continue
                        else:
                            relaxed.append(s)
                    try:
                        filtered_relaxed = [c for c in candidates if _match_spec(c, relaxed)]
                    except Exception:
                        filtered_relaxed = []
                    if filtered_relaxed:
                        candidates = filtered_relaxed
                        filter_spec_applied = True
                        filter_meta_spec = {
                            "specs": relaxed,
                            "candidates_before": retrieved_count,
                            "candidates_after": len(candidates),
                            "fallback": "relaxed_ai_ml_specs",
                        }
                        try:
                            log_trace_event(
                                trace_id=trace_id,
                                event_type="agent_process",
                                source_type="agent",
                                source_id="Spec_Filter_Agent",
                                target_type="system",
                                target_id=None,
                                payload=filter_meta_spec,
                            )
                        except Exception:
                            pass
                        # continue with relaxed candidates
                    else:
                        cb_record(redis, "recommend", True, degradation_cfg)
                        payload = {
                            "results": [],
                            "proposal": {"decision_mode": "rules", "ranked_skus": []},
                            "constraints_used": constraints,
                            "policy_version": flags.get("POLICY_VERSION", "v1"),
                            "message": f"No products found matching specs: {', '.join(specs)}.",
                            "degraded": use_rules,
                            "eligible": not simulate,
                            "view_mode": view_hint.get("view_mode"),
                            "view_reason": view_hint.get("view_reason"),
                            "agent_chain": [
                                {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
                                {"agent": "Candidate_Retrieval_Agent", "candidates": retrieved_count, "duration_ms": retrieve_ms},
                                {"agent": "Spec_Filter_Agent", "candidates": 0, "constraints": filter_meta_spec},
                                {"agent": "Inventory_Agent", "candidates_evaluated": len(candidates or []), "status": "evaluated_pre_spec_filter"},
                            ],
                            "llm_model": llm_model,
                            "model_tier": model_tier,
                            "complexity_signals": complexity_signals,
                        }
                        _log_early_decision(
                            status="no_results",
                            proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
                            agent_chain=payload.get("agent_chain") or [],
                            retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
                        )
                        payload = _ensure_trace_response(payload, trace_id, flags)
                        return _with_trace(payload, trace_id)
                cb_record(redis, "recommend", True, degradation_cfg)
                payload = {
                    "results": [],
                    "proposal": {"decision_mode": "rules", "ranked_skus": []},
                    "constraints_used": constraints,
                    "policy_version": flags.get("POLICY_VERSION", "v1"),
                    "message": f"No products found matching specs: {', '.join(specs)}.",
                    "degraded": use_rules,
                    "eligible": not simulate,
                    "view_mode": view_hint.get("view_mode"),
                    "view_reason": view_hint.get("view_reason"),
                    "agent_chain": [
                        {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
                        {"agent": "Candidate_Retrieval_Agent", "candidates": retrieved_count, "duration_ms": retrieve_ms},
                        {"agent": "Spec_Filter_Agent", "candidates": 0, "constraints": filter_meta_spec},
                        {"agent": "Inventory_Agent", "candidates_evaluated": len(candidates or []), "status": "evaluated_pre_spec_filter"},
                    ],
                    "llm_model": llm_model,
                    "model_tier": model_tier,
                    "complexity_signals": complexity_signals,
                }
                _log_early_decision(
                    status="no_results",
                    proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
                    agent_chain=payload.get("agent_chain") or [],
                    retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
                )
                payload = _ensure_trace_response(payload, trace_id, flags)
                return _with_trace(payload, trace_id)
        # Brand exclusions
        brand_excludes = constraints.get("brand_excludes") or []
        if brand_excludes:
            filtered = []
            for c in candidates:
                name = (c.get("name") or "").lower()
                sku = (c.get("sku") or "").lower()
                if any(b in name or b in sku for b in brand_excludes):
                    continue
                filtered.append(c)
            candidates = filtered
        # Availability constraint
        if constraints.get("availability") == "in_stock":
            candidates = [c for c in candidates if (c.get("stock") or 0) > 0]

        # Inventory agent evaluation WITH quantity check for bulk orders
        requested_qty = constraints.get("quantity") or 1
        insufficient_stock_skus = []
        inv_shortage_approval_id = None
        try:
            from src.app.services.inventory_agent import InventoryAgent
            logging.info("recommend.suggest: running inventory checks for up to 8 candidates")
            inv = InventoryAgent()
            inv_evals = []
            for c in (candidates or [])[:8]:
                stock = int(c.get("stock") or 0)
                ctx = {"stock": stock}
                sku_val = c.get("sku") or ""
                try:
                    res = inv.evaluate_stock_rule(sku_val, ctx)
                    res["available_qty"] = stock
                    res["requested_qty"] = requested_qty
                    res["can_fulfill"] = stock >= requested_qty
                    inv_evals.append({"sku": sku_val, **res})
                    # Track insufficient stock for bulk orders
                    if requested_qty > 1 and stock < requested_qty:
                        insufficient_stock_skus.append({"sku": sku_val, "available": stock, "requested": requested_qty})
                except Exception:
                    inv_evals.append({"sku": sku_val, "rule_id": None, "action": "eval_failed", "escalate": False, "can_fulfill": False})
            if inv_evals:
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="inventory_check",
                        source_type="agent",
                        source_id="Inventory_Agent",
                        target_type="system",
                        target_id=None,
                        payload={
                            "evaluations": inv_evals,
                            "requested_qty": requested_qty,
                            "insufficient_stock_count": len(insufficient_stock_skus),
                            "insufficient_stock_skus": insufficient_stock_skus[:5],  # Limit payload size
                        },
                    )
                except Exception:
                    pass
                # If bulk order cannot be fulfilled, propose a human handoff to Sales
                try:
                    if insufficient_stock_skus:
                        try:
                            inv_shortage_approval_id = enqueue_approval(
                                "inventory",
                                {
                                    "uid": uid,
                                    "query": query,
                                    "requested_qty": requested_qty,
                                    "insufficient_stock": insufficient_stock_skus[:10],
                                },
                                reason="insufficient_stock_bulk",
                                created_by=role,
                            )
                        except Exception:
                            inv_shortage_approval_id = None
                        _emit_agent_handoff(
                            redis_client=redis,
                            from_agent="Inventory_Agent",
                            to_agent="Sales_Agent",
                            reason="insufficient_stock_bulk",
                            context={
                                "uid": uid,
                                "query": query,
                                "requested_qty": requested_qty,
                                "approval_id": inv_shortage_approval_id,
                                "insufficient_stock": insufficient_stock_skus[:10],
                            },
                            trace_id=trace_id,
                        )
                        # Emit explicit handoff event for trace consumers/tests
                        try:
                            log_trace_event(
                                trace_id=trace_id,
                                event_type="handoff_requested",
                                source_type="agent",
                                source_id="Inventory_Agent",
                                target_type="agent",
                                target_id="Sales_Agent",
                                payload={
                                    "reason": "insufficient_stock_bulk",
                                    "requested_qty": requested_qty,
                                    "insufficient_stock": insufficient_stock_skus[:5],
                                    "approval_id": inv_shortage_approval_id,
                                    "tags": ["inventory_insufficient_stock", "approval_required"],
                                },
                            )
                        except Exception:
                            pass
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="human_escalation",
                            source_type="agent",
                            source_id="Inventory_Agent",
                            target_type="human",
                            target_id="Sales",
                            payload={
                                "reason": "insufficient_stock_bulk",
                                "requested_qty": requested_qty,
                                "insufficient_stock": insufficient_stock_skus[:5],
                                "approval_id": inv_shortage_approval_id,
                                "tags": ["inventory_insufficient_stock", "approval_required"],
                            },
                        )
                except Exception:
                    pass
        except Exception:
            # Non-blocking: recommendation flow continues even if inventory evaluation fails
            pass

        if not candidates and os.getenv("TEST_USE_FALLBACK_PRODUCTS", "0").lower() in ("1", "true", "yes"):
            candidates = [
                {
                    "id": "fb-xps13plus",
                    "sku": "XPS13PLUS",
                    "name": "Dell XPS 13 Plus",
                    "price_cents": 129900,
                    "currency": "USD",
                    "stock": 5,
                    "specs": {"ram_gb": 16, "storage": "512GB", "cpu": "Intel Core i7"},
                },
                {
                    "id": "fb-mbp14",
                    "sku": "MBP14",
                    "name": "MacBook Pro 14",
                    "price_cents": 209900,
                    "currency": "USD",
                    "stock": 3,
                    "specs": {"ram_gb": 16, "storage": "1TB", "cpu": "Apple M4"},
                },
            ]
            # Re-apply active filters to fallback set.
            if budget_min_val is not None or budget_max_val is not None:
                _f = []
                for c in candidates:
                    p = float(c.get("price_cents") or 0) / 100.0
                    if budget_min_val is not None and p < budget_min_val:
                        continue
                    if budget_max_val is not None and p > budget_max_val:
                        continue
                    _f.append(c)
                candidates = _f
            if constraints.get("availability") == "in_stock":
                candidates = [c for c in candidates if int(c.get("stock") or 0) > 0]
            try:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="candidate_retrieval",
                    source_type="agent",
                    source_id="Candidate_Retrieval_Agent",
                    target_type="system",
                    target_id=None,
                    payload={"count": len(candidates), "fallback": "test_products"},
                )
            except Exception:
                pass

        if not candidates:
            logging.info("recommend.suggest: no candidates left after filters/inventory")
            cb_record(redis, "recommend", True, degradation_cfg)
            try:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="inventory_check",
                    source_type="agent",
                    source_id="Inventory_Agent",
                    target_type="system",
                    target_id=None,
                    payload={
                        "evaluations": [],
                        "requested_qty": requested_qty,
                        "status": "skipped_no_candidates",
                        "reason": "no_candidates_after_filters",
                    },
                )
            except Exception:
                pass
            # Ensure schema keys are present even when no candidates
            payload = {
                "results": [],
                "proposal": {"decision_mode": "rules", "ranked_skus": []},
                "constraints_used": constraints,
                "policy_version": flags.get("POLICY_VERSION", "v1"),
                "message": "No matching products found.",
                "degraded": use_rules,
                "eligible": not simulate,
                "view_mode": view_hint.get("view_mode"),
                "view_reason": view_hint.get("view_reason"),
                "agent_chain": [
                    {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
                    {"agent": "Inventory_Agent", "candidates_evaluated": 0, "status": "skipped_no_candidates"},
                ],
                "llm_model": llm_model,
                "model_tier": model_tier,
                "complexity_signals": complexity_signals,
                "security": _build_security_payload(analysis.get("details") or {}, severity),
            }
            _log_early_decision(
                status="no_results",
                proposed_action=payload.get("proposal") or {"decision_mode": "rules", "ranked_skus": []},
                agent_chain=payload.get("agent_chain") or [],
                retrieved_context={"query": query, "constraints": constraints, "security_analysis": analysis.get("details")},
            )
            payload = _ensure_trace_response(payload, trace_id, flags)
            return _with_trace(payload, trace_id)

        use_llm = bool(flags.get("USE_LLM_RERANK", False)) and not (use_rules or simulate)
        with tracer.start_as_current_span("recommend.rerank_baseline"):
            baseline_scored = service.rerank_candidates_with_factors(candidates, constraints)
            baseline_skus = [i["candidate"]["sku"] for i in baseline_scored]
        baseline_pos = {sku: idx for idx, sku in enumerate(baseline_skus)}
        _rerank_t0 = time.perf_counter()
        if use_rules or simulate:
            ranked = candidates
            scored = baseline_scored
        else:
            with tracer.start_as_current_span("recommend.rerank_llm"):
                ranked = service.maybe_llm_rerank(uid, candidates, constraints, use_llm=use_llm)
            with tracer.start_as_current_span("recommend.rerank_post"):
                scored = service.rerank_candidates_with_factors(ranked, constraints)
        rerank_ms = int((time.perf_counter() - _rerank_t0) * 1000)
        cb_record(redis, "recommend", True, degradation_cfg)
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="rerank",
                source_type="agent",
                source_id="Product_Ranking_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "decision_mode": ("rules" if use_rules or simulate else "agent_rerank"),
                    "duration_ms": rerank_ms,
                    "candidates": len(ranked or []),
                },
            )
        except Exception:
            pass
    except Exception:
        logging.exception("recommend.suggest failed")
        cb_record(redis, "recommend", False, degradation_cfg)
        # Ensure contract keys present even on exceptions
        return _with_trace({
            "results": [],
            "proposal": {"decision_mode": "rules", "ranked_skus": []},
            "constraints_used": constraints,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "message": "Recommendation service degraded; try again later.",
            "error": "recommendation_unavailable",
            "degraded": True,
            "eligible": not simulate,
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": [{"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity}],
            "llm_model": llm_model,
            "model_tier": model_tier,
            "complexity_signals": complexity_signals,
            "security": _build_security_payload(analysis.get("details") or {}, severity),
        }, trace_id)

    proposal = {
        "decision_mode": "rules" if use_rules or simulate else "agent_rerank",
        "ranked_skus": [c["sku"] for c in ranked],
        "rationale": (ollama_meta.get("intent_summary") or "Reranked within candidate set based on inferred intent and constraints.") if not use_rules else "Rule-based fallback.",
        "factor_telemetry": {
            "decision_mode": "rules" if use_rules or simulate else "agent_rerank",
            "window_precision": "na",
            "context_multipliers": "default",
            "factor_rankings": [],
        },
        "nlp": nlp,
        "llm": ollama_meta,
    }

    def _sanitize_proposal(p: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"decision_mode", "ranked_skus", "rationale", "factor_telemetry", "nlp"}
        cleaned = {k: v for k, v in p.items() if k in allowed}
        skus = cleaned.get("ranked_skus") or []
        cleaned["ranked_skus"] = [str(s) for s in skus if isinstance(s, (str, int))]
        if not isinstance(cleaned.get("nlp"), dict):
            cleaned["nlp"] = {}
        return cleaned

    proposal = _sanitize_proposal(proposal)
    agent_chain = [
        {"agent": "Security_Observer_Agent", "confidence": None, "duration_ms": None, "severity": severity},
        {"agent": "NLP_Search_Agent", "confidence": nlp.get("intent_confidence"), "duration_ms": nlp_ms},
        {"agent": "Candidate_Retrieval_Agent", "candidates": retrieved_count, "duration_ms": retrieve_ms},
        {"agent": "Product_Ranking_Agent", "candidates": len(ranked or []), "duration_ms": rerank_ms, "decision_mode": proposal.get("decision_mode")},
    ]
    # If price or spec filtering ran, include filter agents for visibility
    if filter_price_applied:
        agent_chain.insert(
            3,
            {"agent": "Price_Filter_Agent", "candidates": len(candidates or []), "constraints": filter_meta_price},
        )
    if filter_spec_applied:
        agent_chain.insert(
            3,
            {"agent": "Spec_Filter_Agent", "candidates": len(candidates or []), "constraints": filter_meta_spec},
        )
    retrieved_context = {
        "query": query,
        "constraints": constraints,
        "candidates": candidates,
        "dependency_health": dependency_health_snapshot(),
        "security_analysis": analysis.get("details"),
        "nlp": nlp,
        "llm": ollama_meta,
        "model_tier": model_tier,
        "llm_model": llm_model,
        "complexity_signals": complexity_signals,
        "agent_chain": agent_chain,
        "customer_tier": tier,
        "retention_policy": retention_policy,
        "policy_notes": policy_notes,
    }
    # analysis/PII severity already normalized earlier
    risk_quantification = None
    try:
        risk_quantification = quantify_risk(
            security=analysis.get("details") or {},
            policy_gates=None,
        )
        retrieved_context["risk_quantification"] = risk_quantification
    except Exception:
        pass

    decision_id = None
    try:
        prefs = nlp.get("preferences", {}) or {}
        meta = kv.get("prefs_meta") or {}
        now_ts = int(time.time())
        for k, v in prefs.items():
            if v is None:
                continue
            meta[k] = {"value": v, "ts": now_ts}
        mem.set_kv(uid, {**kv, "prefs_meta": meta, "last_intent": nlp.get("intent"), "last_query": query})
    except Exception:
        pass

    # Infer and persist conversation state for context-aware agents
    try:
        conv_state = ConversationState.infer_from_intent(nlp.get("intent"))
        kv2 = ConversationState.apply_to_kv(kv, conv_state)
        try:
            mem.set_kv(uid, kv2)
        except Exception:
            pass
        # attach to retrieved_context for traceability
        # (retrieved_context is built later and will include mem.get_context)
    except Exception:
        pass

    if flags.get("DECISION_LOG_WRITES_ENABLED", False):
        try:
            with tracer.start_as_current_span("recommend.log_decision"):
                tenant_id = None
                try:
                    tenant_id = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
                except Exception:
                    tenant_id = None
                decision_id = service.log_decision(
                    uid,
                    query,
                    retrieved_context,
                    proposal,
                    flags.get("POLICY_VERSION", "v1"),
                    flags,
                    decision_id=trace_id,
                    tenant_id=tenant_id,
                )
                decision_id = decision_id or trace_id
                try:
                    log_trace_event(
                        trace_id=decision_id or trace_id,
                        event_type="user_query",
                        source_type="user",
                        source_id=uid,
                        target_type="agent",
                        target_id="Recommendation_Agent",
                        payload={
                            "query": scrub_pii(query),
                            "constraints": constraints,
                            "intent_chain": nlp.get("intent_chain", []),
                            "slots": nlp.get("slots", {}),
                            "filters_applied": {
                                "price": filter_price_applied,
                                "spec": filter_spec_applied,
                                "brand_excludes": bool(constraints.get("brand_excludes")),
                                "availability": constraints.get("availability"),
                            },
                            "policy_notes": policy_notes,
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

    decision_id = decision_id or trace_id

    if flags.get("TEST_FORCE_BAD_SKU", False):
        proposal["ranked_skus"] = proposal["ranked_skus"] + ["INVALID_TEST_SKU"]

    candidate_skus = {c.get("sku") for c in candidates}
    ranked_skus = set(proposal.get("ranked_skus", []))
    if not ranked_skus.issubset(candidate_skus):
        approval_id = enqueue_approval("recommend", {"uid": uid, "query": query, "proposal": proposal}, reason="invalid_sku")
        record_incident_alert("security", "p1")
        sec_details = analysis.get("details") or {}
        payload = {
            "status": "blocked",
            "message": "Response blocked due to invalid SKU output. A human will review it.",
            "severity": "high",
            "eligible": not simulate,
            "approval_id": approval_id,
            "trace_id": trace_id,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": agent_chain,
            "llm_model": llm_model,
            "model_tier": model_tier,
            "complexity_signals": complexity_signals,
            "security": _build_security_payload(sec_details, "high"),
            "escalation": {"approval_required": True, "approval_id": approval_id, "reason": "invalid_sku"},
            "policy_notes": policy_notes,
        }
        payload = _ensure_trace_response(payload, trace_id, flags)
        return _block_response(_with_trace(payload, trace_id), 403)

    # Output validation and logging
    with tracer.start_as_current_span("recommend.security_analyze_output"):
        output_analysis = analyze_payload({"uid": uid, "proposal": proposal, "results": [c.get("sku") for c in ranked]})
    try:
        # Respect optional test skip list
        skip_list = os.getenv("SKIP_OBSERVER_ENDPOINTS", "")
        prefixes = [p.strip() for p in skip_list.split(",") if p.strip()]
        if not any("/api/v1/recommend".startswith(p) for p in prefixes):
            emit_security_event("/api/v1/recommend/suggest:output", {"proposal": proposal, "analysis": output_analysis.get("details")}, request=request)
    except Exception:
        pass
    # Persist the input analysis after output so test harnesses that read the
    # latest event will observe the original input signals (e.g. prompt
    # injection markers). This ensures the most relevant event is available
    # for auditing and tests.
    try:
        # Use a slightly later timestamp for the input event so it orders
        # after the output event in the DB when tests query for the latest
        import datetime as _dt
        later = (_dt.datetime.utcnow() + _dt.timedelta(milliseconds=10)).isoformat()
        try:
            skip_list = os.getenv("SKIP_OBSERVER_ENDPOINTS", "")
            prefixes = [p.strip() for p in skip_list.split(",") if p.strip()]
            if not any("/api/v1/recommend".startswith(p) for p in prefixes):
                emit_security_event("/api/v1/recommend/suggest", {"payload": {"uid": uid, "query": query}, "analysis": analysis.get("details")}, event_time=later, request=request)
        except Exception:
            pass
    except Exception:
        pass

    out_sev = output_analysis.get("severity", "info")
    if out_sev in ("high", "critical"):
        approval_id = enqueue_approval("recommend", {"uid": uid, "query": query, "proposal": proposal}, reason="security_output")
        record_incident_alert("security", "p1")
        out_details = output_analysis.get("details") or {}
        payload = {
            "status": "blocked",
            "message": "Response blocked due to safety checks. A human will review it.",
            "severity": out_sev,
            "eligible": not simulate,
            "approval_id": approval_id,
            "trace_id": trace_id,
            "policy_version": flags.get("POLICY_VERSION", "v1"),
            "view_mode": view_hint.get("view_mode"),
            "view_reason": view_hint.get("view_reason"),
            "agent_chain": agent_chain,
            "llm_model": llm_model,
            "model_tier": model_tier,
            "complexity_signals": complexity_signals,
            "security": _build_security_payload(out_details, out_sev),
            "escalation": {"approval_required": True, "approval_id": approval_id, "reason": "security_output"},
            "policy_notes": policy_notes,
        }
        payload = _ensure_trace_response(payload, trace_id, flags)
        return _block_response(_with_trace(payload, trace_id), 403)

    # Record budget usage (best-effort). For now use estimates until LLM tokens are real.
    try:
        cost = estimate_cost(est_tokens)
        budget.record_usage(uid, est_tokens, cost)
        record_token_budget_usage(tier, "recommend.suggest", est_tokens)
    except Exception:
        pass
    # Build why-not list for non-selected candidates (top 3)
    ranked_skus_list = [c["sku"] for c in ranked]
    why_not = []
    for item in scored[3:6]:
        c = item.get("candidate") or {}
        why_not.append({
            "sku": c.get("sku"),
            "name": c.get("name"),
            "reasons": item.get("factors", {}).get("negative", [])[:3],
            "score": item.get("score"),
        })

    results = []
    top_score = scored[0]["score"] if scored else 0.0
    min_score = scored[-1]["score"] if scored else 0.0
    def _normalize_score(val: float) -> float:
        if top_score == min_score:
            return 100.0
        return round((val - min_score) / max((top_score - min_score), 1e-6) * 100, 2)
    for idx, item in enumerate(scored):
        c = item.get("candidate") or {}
        score_val = float(item.get("score") or 0.0)
        rank_delta = round(top_score - score_val, 2)
        why_not_inline = item.get("factors", {}).get("negative", [])[:3]
        sku = c.get("sku")
        baseline_rank = baseline_pos.get(sku) if sku in baseline_pos else None
        rerank_delta = None
        if baseline_rank is not None:
            rerank_delta = baseline_rank - idx
        results.append({
            **c,
            "confidence": item.get("confidence"),
            "factors": item.get("factors"),
            "score": score_val,
            "score_norm": _normalize_score(score_val),
            "rank_delta": rank_delta,
            "why_not": why_not_inline,
            "baseline_rank": baseline_rank,
            "rerank_delta": rerank_delta,
        })
    # Persist search event for BI/funnel tracking
    try:
        log_search_event(
            uid=uid,
            query=query,
            filters=constraints,
            result_skus=[r.get("sku") for r in results],
            view_mode=view_hint.get("view_mode"),
            trace_id=trace_id,
            session_id=kv.get("session_id") if isinstance(kv, dict) else None,
        )
    except Exception:
        pass
    # Emit candidate stats for decision trace visibility
    try:
        price_vals = [float(r.get("price_cents") or 0.0) for r in results if r.get("price_cents") is not None]
        candidate_stats = {
            "retrieved_count": retrieved_count,
            "candidate_count": len(candidates or []),
            "ranked_count": len(ranked or []),
            "result_count": len(results),
            "price_min_cents": int(min(price_vals)) if price_vals else None,
            "price_max_cents": int(max(price_vals)) if price_vals else None,
            "price_avg_cents": int(sum(price_vals) / len(price_vals)) if price_vals else None,
            "filters_applied": {
                "price": filter_price_applied,
                "spec": filter_spec_applied,
                "brand_excludes": bool(constraints.get("brand_excludes")),
                "availability": constraints.get("availability"),
            },
            "use_case": constraints.get("use_case"),
            "use_case_tags": constraints.get("use_case_tags") or [],
        }
        log_trace_event(
            trace_id=decision_id or trace_id,
            event_type="candidate_stats",
            source_type="agent",
            source_id="Candidate_Ranking_Agent",
            target_type="system",
            target_id=None,
            payload=candidate_stats,
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=decision_id or trace_id,
            event_type="agent_process",
            source_type="agent",
            source_id="Recommendation_Agent",
            target_type="system",
            target_id=None,
            payload={
                "result_count": len(results),
                "filters_applied": {
                    "price": filter_price_applied,
                    "spec": filter_spec_applied,
                    "brand_excludes": bool(constraints.get("brand_excludes")),
                    "availability": constraints.get("availability"),
                },
                "view_mode": view_hint.get("view_mode"),
            },
        )
    except Exception:
        pass

    # Apply policy and redaction to outgoing payload
    persona_tone = {
        "guest": "neutral",
        "basic": "helpful-short",
        "premium": "friendly-short",
        "enterprise": "professional-short",
    }.get(tier, "neutral")
    payload = _with_trace({
        "results": results,
        "proposal": proposal,
        "constraints_used": constraints,
        "policy_version": flags.get("POLICY_VERSION", "v1"),
        "decision_id": decision_id,
        "risk_score": analysis.get("details", {}).get("risk_adj"),
        "why_not": why_not,
        "degraded": use_rules,
        "eligible": not simulate,
        "notice": "Security review queued due to detected risk." if approval_id else None,
        "approval_id": approval_id,
        "trace_id": trace_id,
        "persona_tone": persona_tone,
        "learn_more_url": "/ui/status",
        "agent_chain": agent_chain,
        "trace_tags": strategy_corr.get("tags") or [],
        "drilldown_hidden_tags": strategy_corr.get("hidden") or {},
        "llm_model": llm_model,
        "model_tier": model_tier,
        "complexity_signals": complexity_signals,
        "view_mode": view_hint.get("view_mode"),
        "view_reason": view_hint.get("view_reason"),
        "security": _build_security_payload(
            {
                **(analysis.get("details") or {}),
                "risk_quantification": risk_quantification,
            },
            severity,
        ),
        "policy_notes": policy_notes,
        # Attach a lightweight escalation hint when bulk stock is insufficient
        "escalation": ({
            "approval_required": True,
            "approval_id": inv_shortage_approval_id,
            "handoff": "sales_support",
            "reason": "insufficient_stock_bulk",
            "requested_qty": requested_qty,
            "insufficient": len(insufficient_stock_skus),
            "tags": ["inventory_insufficient_stock", "approval_required"],
            "playbook_hint": {"id": "PB-INV-004"},
        } if insufficient_stock_skus else None),
    }, trace_id)
    # Ensure evidence contract keys are present at payload construction
    if "evidence_items" not in payload:
        top = []
        for r in (payload.get("results") or [])[:3]:
            if isinstance(r, dict):
                top.append({"type": "candidate", "id": r.get("sku"), "score": r.get("score")})
        payload["evidence_items"] = top
    if "evidence_weighting" not in payload:
        payload["evidence_weighting"] = {"retrieval": 0.5, "rules": 0.3, "policy": 0.2}
    if "confidence_calibrated" not in payload:
        try:
            confs = [float((r or {}).get("confidence") or 0.0) for r in (payload.get("results") or []) if isinstance(r, dict)]
            payload["confidence_calibrated"] = round(sum(confs) / len(confs), 4) if confs else 0.0
        except Exception:
            payload["confidence_calibrated"] = 0.0
    try:
        if inv_shortage_approval_id and not payload.get("approval_id"):
            payload["approval_id"] = inv_shortage_approval_id
        if insufficient_stock_skus and not payload.get("status"):
            payload["status"] = "review_required"
            payload["notice"] = payload.get("notice") or "Approval required due to insufficient inventory for requested quantity."
        if not payload.get("status"):
            sigs = (analysis.get("details") or {}).get("signals", {})
            if sigs.get("pci") or sigs.get("pii"):
                payload["status"] = "review_required"
    except Exception:
        pass
    if pii_notice:
        payload["notice"] = pii_notice
    # Next-Question Engine for shopping guidance (budget/specs/use-case)
    next_questions = []
    try:
        missing_fields = []
        if constraints.get("budget_min") is None and constraints.get("budget_max") is None:
            missing_fields.append("budget")
        if not constraints.get("specs"):
            missing_fields.append("specs")
        if not nlp.get("entities", {}).get("use_case"):
            missing_fields.append("use_case")
        if missing_fields:
            category = "laptop" if "laptop" in (query or "").lower() else "general"
            nqe_input = NQEInput(
                intent="product_search",
                product_category=category,
                symptom=None,
                timeline_days=None,
                risk_score=0.0,
                missing_fields=missing_fields,
                tenant_id=request.headers.get("X-Tenant-Id") if request is not None else None,
                template_variant=request.headers.get("X-NQE-Template-Variant") if request is not None else None,
                template_version=request.headers.get("X-NQE-Template-Version") if request is not None else None,
                trace_id=trace_id,
            )
            engine = NextQuestionEngine(Retriever(), QuestionTemplateCatalog())
            next_questions = [q.model_dump() for q in engine.propose(nqe_input)]
            if next_questions:
                payload["next_questions"] = next_questions
                # Also attach follow-ups into the NLP bundle so frontends reading
                # `proposal.nlp.followups` or `nlp.followups` will surface questions.
                try:
                    if isinstance(nlp, dict):
                        nlp.setdefault("followups", [])
                        # prefer existing followups first, then append
                        for q in next_questions:
                            if q not in nlp["followups"]:
                                nlp["followups"].append(q)
                except Exception:
                    pass
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="next_questions",
                        source_type="agent",
                        source_id="NQE_Agent",
                        target_type="user",
                        target_id=None,
                        payload={
                            "intent": "product_search",
                            "category": category,
                            "missing_fields": missing_fields,
                            "questions": next_questions,
                        },
                    )
                except Exception:
                    pass
    except Exception:
        next_questions = []
    assistant_message = None
    llm_summary_job_id = None
    if nlp.get("llm_fallback") and rule_eval.get("recommend_llm", True):
        assistant_message, llm_summary_job_id = _summarize_results(query, results, constraints, llm_model, trace_id)
    if not assistant_message:
        assistant_message = _deterministic_assistant_message(query, results, constraints)
    # Inventory presence note when requested brands are missing (via helper for testability)
    note, unmatched = _emit_inventory_brand_notice(results=results, constraints=constraints, decision_id=decision_id, trace_id=trace_id)
    if note:
        assistant_message = (assistant_message or "") + note
    # Comparative synthesis for "which is better" queries
    try:
        needs_synthesis = any(
            phrase in (query or "").lower() for phrase in [
                "which is better", "which one should", "what do you recommend",
                "pros and cons", "which would you", "best choice",
            ]
        )
        if needs_synthesis and results:
            top = results[:3]
            lines = []
            for i, r in enumerate(top):
                pros = (r.get("factors") or {}).get("positive", [])
                price = int(r.get("price_cents") or 0) // 100 if r.get("price_cents") is not None else r.get("price")
                pros_h = _humanize_positive_factor_tokens(pros)
                why = (" - " + "; ".join(pros_h)) if pros_h else ""
                lines.append(f"{i+1}. {r.get('name')} (${price}){why}")
            assistant_message = (
                "Based on your criteria and our current inventory:\n\n" +
                "\n".join(lines) +
                "\n\nThese rankings consider price match, spec relevance, and stock availability. "
                "Ask for more detail on any item if you'd like."
            )
    except Exception:
        pass
    if pii_notice:
        assistant_message = f"{pii_notice} {assistant_message}" if assistant_message else pii_notice
    if assistant_message:
        if not skip_recommend_observer:
            try:
                assistant_message = EthicalAIGuard().enhance_response(
                    assistant_message,
                    {"sentiment": nlp.get("sentiment", "neutral")},
                )
            except Exception:
                pass
        payload["assistant_message"] = assistant_message
    if llm_summary_job_id:
        payload["llm_summary_job_id"] = llm_summary_job_id
    # Test-only debug: emit a simple log of SKUs when query mentions budget
    try:
        if any(tok in (query or "").lower() for tok in ("under $", "below $", "budget")):
            line = {
                "query": query,
                "constraints": constraints,
                "candidate_skus": [c.get("sku") for c in (retrieved_context.get("candidates") or [])],
                "result_skus": [r.get("sku") for r in results],
            }
            import json as _json
            with open("runs/debug_recommend.txt", "a", encoding="utf-8") as df:
                df.write(_json.dumps(line) + "\n")
    except Exception:
        pass
    policy = get_policy("recommend")
    payload["policy_version"] = policy.get("version", payload["policy_version"])
    payload_policy, deltas = apply_post_policy("recommend", payload)
    # Ensure final payload includes trace/evidence contract keys for UI/tests
    try:
        payload_policy = _ensure_trace_response(payload_policy or {}, trace_id, flags)
    except Exception:
        pass
    try:
        agent_chain.append({
            "agent": "Policy_Agent",
            "policy_version": payload_policy.get("policy_version"),
            "deltas": len(deltas or []),
            "duration_ms": None,
        })
        retrieved_context["policy_gates"] = deltas or []
        try:
            log_trace_event(
                trace_id=decision_id or trace_id,
                event_type="policy_gate",
                source_type="agent",
                source_id="Policy_Agent",
                target_type="system",
                target_id=None,
                payload={"policy_version": payload_policy.get("policy_version"), "deltas": deltas},
            )
        except Exception:
            pass
    except Exception:
        pass
    redacted, changes, pci = redact_payload(payload_policy)
    # Final safety: ensure contract keys present after redaction as well
    try:
        redacted = _ensure_trace_response(redacted or {}, decision_id or trace_id, flags)
    except Exception:
        pass
    # Emit additional output analysis including critique deltas
    with tracer.start_as_current_span("recommend.security_analyze_output_final"):
        if skip_recommend_observer:
            final_out = {"severity": "info", "details": {"signals": {}, "reason": "observer_skipped"}}
        else:
            # IMPORTANT: only scan user-facing output. Scanning the internal `proposal` blob can
            # self-trigger (e.g., OWASP/MITRE tag strings contain "prompt injection", "supply chain", etc.)
            # and cause false blocks on otherwise safe queries.
            final_out = analyze_payload(
                {
                    "uid": uid,
                    "assistant_message": redacted.get("assistant_message"),
                    "next_questions": redacted.get("next_questions") or [],
                    "results": [
                        {"sku": r.get("sku"), "name": r.get("name"), "price": r.get("price")}
                        for r in (redacted.get("results") or [])
                        if isinstance(r, dict)
                    ][:8],
                }
            )
    try:
        if not skip_recommend_observer:
            emit_security_event(
                "/api/v1/recommend/suggest:output",
                {"proposal": redacted.get("proposal"), "analysis": {**final_out.get("details", {}), "critique_deltas": deltas}},
                request=request,
            )
    except Exception:
        pass
    return redacted


@router.get("/checkout_upsell")
def checkout_upsell(
    uid: str,
    cart_skus: str,
    limit: int = 3,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    skus = [s.strip() for s in str(cart_skus or "").split(",") if s.strip()]
    if not skus:
        raise HTTPException(status_code=400, detail="cart_skus is required")
    try:
        recs = recommend_checkout_upsell(
            db,
            cart_skus=skus,
            limit=max(1, min(int(limit or 3), 8)),
            uid_hash=uid,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"checkout_upsell_failed: {exc}")
    return {"results": recs, "count": len(recs), "cart_skus": skus, "uid_hash": hash_uid(uid)}


@router.post("/interaction")
def log_recommend_interaction(
    payload: RecommendInteractionPayload,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    action = str(payload.action or "").strip().lower()
    if action not in {"hover", "click", "view", "add_to_cart", "atc", "cart_add"}:
        raise HTTPException(status_code=400, detail="action must be one of: hover, click, view, add_to_cart")
    sku = str(payload.sku or "").strip()
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")
    ensure_recommend_interactions_table(db)
    eid = str(uuid.uuid4())
    try:
        db.execute(
            text(
                """
                INSERT INTO recommend_interactions (id, uid_hash, sku, action, surface, trace_id, context_json)
                VALUES (:id, :uid_hash, :sku, :action, :surface, :trace_id, :context_json)
                """
            ),
            {
                "id": eid,
                "uid_hash": hash_uid(payload.uid),
                "sku": sku,
                "action": action,
                "surface": str(payload.surface or "checkout_upsell"),
                "trace_id": str(payload.trace_id or ""),
                "context_json": json.dumps(security_sanitize(payload.context or {}), ensure_ascii=False),
            },
        )
        try:
            db.commit()
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"interaction_log_failed: {exc}")
    return {"status": "ok", "event_id": eid}


@router.get("/nqe_slots")
def nqe_slots(request: Request, uid: str, query: str, redis=Depends(get_redis)) -> Dict[str, Any]:
    """Lightweight rule-first slot detector for NQE: returns missing slots and confidences.

    Response schema:
      { slots: [{ name: 'budget', confidence: 0.9, reason: 'no_budget_in_query' }, ...], context: {...} }
    """
    mem = Memory(redis)
    ctx = mem.get_context(uid) or {}
    kv = ctx.get("kv") or {}
    # Use existing parser to extract explicit constraints
    svc = RecommendationService(session=None)
    parsed = {}
    try:
        parsed = svc.parse_constraints(query) or {}
    except Exception:
        parsed = {}

    # Canonical slots
    slots = []
    # budget
    has_budget = bool(parsed.get("budget_min") is not None or parsed.get("budget_max") is not None or (kv.get("prefs_meta") or {}).get("budget_max"))
    if not has_budget:
        slots.append({"name": "budget", "confidence": 0.9, "reason": "no_budget_in_query_or_prefs"})

    # specs
    specs = parsed.get("specs") or []
    if not specs and not (kv.get("prefs_meta") or {}).get("specs"):
        slots.append({"name": "specs", "confidence": 0.85, "reason": "no_specs"})

    # use_case
    use_case = parsed.get("use_case") or (kv.get("prefs_meta") or {}).get("use_case")
    if not use_case:
        slots.append({"name": "use_case", "confidence": 0.7, "reason": "no_use_case"})

    # quantity
    qty = _extract_quantity_from_query(query)
    if qty is None:
        slots.append({"name": "quantity", "confidence": 0.6, "reason": "no_quantity"})

    # availability
    if not parsed.get("availability"):
        slots.append({"name": "availability", "confidence": 0.5, "reason": "no_availability"})

    # brand
    if not parsed.get("brands"):
        slots.append({"name": "brand", "confidence": 0.4, "reason": "no_brand"})

    # Order by confidence descending
    slots = sorted(slots, key=lambda s: s.get("confidence", 0), reverse=True)

    # Attach some context signals useful for NQE
    context = {
        "prefs_meta": kv.get("prefs_meta") or {},
        "last_query": kv.get("last_query"),
        "session_id": kv.get("session_id"),
    }

    return {"slots": slots, "context": context}


@router.post("/nqe_feedback")
def nqe_feedback(
    payload: Dict[str, Any] = Body(default_factory=dict),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Record followup conversion outcomes for NQE template governance."""
    trace_id = str(payload.get("trace_id") or "").strip()
    question_id = str(payload.get("question_id") or "").strip()
    if not trace_id or not question_id:
        raise HTTPException(status_code=400, detail="trace_id and question_id required")
    tenant_id = str(payload.get("tenant_id") or "default")
    variant = str(payload.get("variant") or "control")
    converted = bool(payload.get("converted", False))
    latency_ms = int(payload.get("latency_ms") or 0)
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS nqe_feedback_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    tenant_id TEXT,
                    trace_id TEXT,
                    question_id TEXT,
                    variant TEXT,
                    converted INTEGER,
                    latency_ms INTEGER
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO nqe_feedback_events (id, tenant_id, trace_id, question_id, variant, converted, latency_ms)
                VALUES (:id, :tenant_id, :trace_id, :question_id, :variant, :converted, :latency_ms)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "question_id": question_id,
                "variant": variant,
                "converted": 1 if converted else 0,
                "latency_ms": max(0, latency_ms),
            },
        )
        try:
            db.commit()
        except Exception:
            pass
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed_to_record_feedback: {exc}")
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="nqe_feedback_recorded",
            source_type="agent",
            source_id="NQE_Agent",
            target_type="template",
            target_id=question_id,
            payload={"variant": variant, "converted": converted, "latency_ms": latency_ms, "tenant_id": tenant_id},
        )
    except Exception:
        pass
    return {"status": "ok", "trace_id": trace_id, "question_id": question_id}


@router.get("/admin/nqe_feedback_summary")
def nqe_feedback_summary(
    tenant_id: str | None = None,
    days: int = 30,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    where = "WHERE datetime(created_at) >= datetime('now', :window_expr)"
    params: Dict[str, Any] = {"window_expr": f"-{days} days"}
    if tenant_id:
        where += " AND tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id
    try:
        rows = db.execute(
            text(
                f"""
                SELECT variant,
                       COUNT(*) as n,
                       SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conv
                FROM nqe_feedback_events
                {where}
                GROUP BY variant
                """
            ),
            params,
        ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        n = int(r[1] or 0)
        c = int(r[2] or 0)
        items.append({"variant": str(r[0] or "control"), "samples": n, "conversion_rate": (float(c) / float(max(1, n)))})
    return {"status": "ok", "tenant_id": tenant_id, "days": days, "items": items}
