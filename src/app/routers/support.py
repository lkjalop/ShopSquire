from fastapi import APIRouter, Depends, HTTPException, Request
import time
from typing import Dict

from src.app.config import load_feature_flags, get_settings
from src.app.deps import get_redis
from src.app.observability.tracing import get_tracer
from src.app.observability.metrics import record_cb_state
from src.app.security.observer import analyze_payload, emit_security_event
from src.app.services.degradation import cb_is_open, cb_record
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.safety.policies import get_policy, apply_post_policy
from src.app.safety.redaction import redact_payload
from src.app.services.faq_bank import match_faq
from src.app.services.faq_v2 import semantic_match_faq
from src.app.security.model_theft import enforce_model_theft_rate_limit, enforce_model_theft_policy_gate


router = APIRouter(prefix="/api/v1/support", tags=["support"])
tracer = get_tracer("support-router")


def _answer_from_faq(question: str) -> Dict:
    item2, score2, _intent = semantic_match_faq(question or "", role="buyer")
    if item2 and score2 >= 0.2:
        return {
            "answer": str(item2.get("a") or ""),
            "source": "faq_v2",
            "confidence": float(score2),
        }
    item, score = match_faq(question or "")
    if item and score >= 1.0:
        return {
            "answer": str(item.get("a") or ""),
            "source": "faq",
            "confidence": min(1.0, 0.5 + 0.1 * score),
        }
    q = (question or "").lower()
    if any(k in q for k in ("refund", "return", "exchange")):
        return {
            "answer": "For returns and refunds, open your order and submit a return request with evidence if needed.",
            "source": "rules",
            "confidence": 0.62,
        }
    if any(k in q for k in ("shipping", "track", "delivery")):
        return {
            "answer": "Use the Orders page tracking link for live shipment status and delivery updates.",
            "source": "rules",
            "confidence": 0.62,
        }
    if any(k in q for k in ("payment", "card", "paypal", "wallet")):
        return {
            "answer": "Use checkout to choose a supported payment method. If payment fails, retry once and contact support.",
            "source": "rules",
            "confidence": 0.62,
        }
    return {
        "answer": "I could not find a high-confidence match. I can route this to a human support agent.",
        "source": "fallback",
        "confidence": 0.4,
    }


@router.post("/answer")
def answer(question: str, request: Request, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("support.answer") as span:
        span.set_attribute("support.question_len", len(question or ""))
        gate_ok, gate_reason = enforce_model_theft_policy_gate(
            query=question,
            uid=None,
            source_ip=(request.client.host if request and request.client else None),
            api_key_id=(request.headers.get("x-api-key") if request else None),
        )
        if not gate_ok:
            raise HTTPException(status_code=429, detail={"message": "model_theft_policy_gate", "reason": gate_reason})
        allow_model, reason = enforce_model_theft_rate_limit(
            redis_client=redis,
            uid=None,
            source_ip=None,
            api_key_id=(request.headers.get("x-api-key") if request else None),
            query=question,
        )
        if not allow_model:
            raise HTTPException(status_code=429, detail={"message": "model_theft_guard", "reason": reason})
        flags = load_feature_flags(get_settings().feature_flags_path)
        if flags.get("KILL_SWITCH"):
            raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
        degradation_cfg = flags.get("DEGRADATION", {"enabled": True})
        now_ts = int(time.time())
        cb_open = cb_is_open(redis, "support", now_ts) if degradation_cfg.get("enabled", True) else False
        record_cb_state("support", cb_open)
        with tracer.start_as_current_span("support.security_analyze_input"):
            analysis = analyze_payload({"question": question})
        sev = analysis.get("severity", "info")
        if sev in ("high", "critical"):
            try:
                emit_security_event("/api/v1/support/answer", {"payload": {"question": question}, "analysis": analysis.get("details")}, request=None)
            except Exception:
                pass
            return {
                "answer": "Request queued for security review. A human support agent will follow up.",
                "degraded": True,
                "notice": "Queued for security review.",
            }

        use_rules = bool(degradation_cfg.get("force_rules", False) or cb_open)
        try:
            if use_rules:
                resp = {
                    "answer": "Support is in degraded mode. Your request will be queued for a human follow-up.",
                    "degraded": True,
                    "source": "degraded_policy",
                    "confidence": 0.2,
                }
            else:
                qa = _answer_from_faq(question or "")
                resp = {
                    "answer": qa.get("answer") or "Support request received.",
                    "degraded": False,
                    "source": qa.get("source") or "rules",
                    "confidence": qa.get("confidence") or 0.0,
                }

            resp["persona_tone"] = "helpful-short"
            resp["learn_more_url"] = "/ui/status"
            policy = get_policy("support")
            resp["policy_version"] = policy.get("version", "v1")
            resp_policy, deltas = apply_post_policy("support", resp)
            redacted, _changes, _pci = redact_payload(resp_policy)

            out = analyze_payload({"answer": redacted.get("answer"), "question": question})
            try:
                emit_security_event(
                    "/api/v1/support/answer:output",
                    {"payload": redacted, "analysis": {**out.get("details", {}), "critique_deltas": deltas}},
                    request=None,
                )
            except Exception:
                pass
            cb_record(redis, "support", True, degradation_cfg)
            return redacted
        except Exception:
            cb_record(redis, "support", False, degradation_cfg)
            return {
                "answer": "Support is temporarily degraded. A human agent will follow up.",
                "degraded": True,
                "source": "error_fallback",
                "confidence": 0.0,
            }


@router.post("/intents")
def intents(text: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("support.intents") as span:
        span.set_attribute("support.text_len", len(text or ""))
        flags = load_feature_flags(get_settings().feature_flags_path)
        if flags.get("KILL_SWITCH"):
            raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
        lower = text.lower()
        degradation_cfg = flags.get("DEGRADATION", {"enabled": True})
        now_ts = int(time.time())
        cb_open = cb_is_open(redis, "support", now_ts) if degradation_cfg.get("enabled", True) else False
        if degradation_cfg.get("force_rules", False) or cb_open:
            return {"intent": "degraded_mode", "confidence": 0.0}
        rules = [
            ("refund", "refund_request", 0.9),
            ("price", "pricing", 0.8),
            ("discount", "pricing", 0.8),
            ("order", "order_status", 0.85),
            ("help", "general_support", 0.7),
            ("support", "general_support", 0.7),
        ]
        for kw, intent, conf in rules:
            if kw in lower:
                return {"intent": intent, "confidence": conf}
        return {"intent": "unknown", "confidence": 0.3}
