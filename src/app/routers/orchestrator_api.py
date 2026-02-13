from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.memory import Memory
from src.app.security.firewall import TransactionFirewall
from src.app.config import load_feature_flags, get_settings
from src.app.services.orchestrator import Orchestrator
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


class OrchestrateRequest(BaseModel):
    uid: str
    cart_total_cents: int
    sku: str | None = None
    query: str | None = None
    images: list[str] | None = None
    image_urls: list[str] | None = None
    complaint_intent: bool | None = None
    tenant_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    idempotency_key: str | None = None
    use_rules: bool = False
    simulate_only: bool = False


@router.post("/orchestrate")
def orchestrate(req: OrchestrateRequest, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Primary agent orchestrator endpoint.

    Runs pricing/decision flow with guardrails and persists decisions.
    """
    try:
        flags = load_feature_flags(get_settings().feature_flags_path)
    except Exception:
        flags = {}
    try:
        # Create a Memory instance; if Redis isn't available, use a noop shim
        try:
            from src.app.deps import get_redis
            redis_client = None
            try:
                redis_client = get_redis()
            except Exception:
                redis_client = None
        except Exception:
            redis_client = None
        if redis_client is None:
            class _DummyRedis:
                def get(self, *_a, **_kw):
                    return None

                def setex(self, *_a, **_kw):
                    return None

            memory = Memory(_DummyRedis())
        else:
            memory = Memory(redis_client)
        firewall = TransactionFirewall(flags)
        orch = Orchestrator(memory=memory, firewall=firewall, flags=flags)
        payload: Dict[str, Any] = {
            "cart_total_cents": req.cart_total_cents,
            "sku": req.sku,
            "query": req.query,
            "images": req.images,
            "image_urls": req.image_urls,
            "complaint_intent": req.complaint_intent,
            "tenant_id": req.tenant_id,
            "actor_id": req.actor_id,
            "actor_role": req.actor_role,
            "idempotency_key": req.idempotency_key,
        }
        use_nlp_cv = bool(req.images or req.image_urls or req.complaint_intent)
        if not use_nlp_cv and req.query:
            try:
                use_nlp_cv = orch.detect_complaint_intent(req.query, {})
            except Exception:
                use_nlp_cv = False

        if use_nlp_cv:
            res = orch.run_nlp_cv(uid=req.uid, payload=payload, simulate_only=req.simulate_only, use_rules=req.use_rules)
            if res is None:
                # Defensive fallback: some intermediate NLP/CV branches may short-circuit without a result.
                try:
                    log_trace_event(
                        trace_id=payload.get("trace_id"),
                        event_type="orchestrate_fallback",
                        source_type="orchestrator",
                        source_id="run_nlp_cv",
                        target_type="orchestrator",
                        target_id="run",
                        payload={"reason": "run_nlp_cv_returned_none"},
                    )
                except Exception:
                    pass
                res = orch.run(uid=req.uid, payload=payload, simulate_only=req.simulate_only, use_rules=req.use_rules)
        else:
            res = orch.run(uid=req.uid, payload=payload, simulate_only=req.simulate_only, use_rules=req.use_rules)

        if res is None:
            raise RuntimeError("orchestrator_returned_none")

        # Attach a decision trace event best-effort
        try:
            trace_id = res.proposal.get("proposal_id") if isinstance(res.proposal, dict) else None
            log_trace_event(
                trace_id=trace_id,
                event_type="orchestrate",
                source_type="agent",
                source_id="orchestrator",
                target_type="policy",
                target_id="pricing",
                payload={
                    "firewall": res.firewall,
                    "executed": res.executed,
                    "timings": res.timings or {},
                },
            )
        except Exception:
            pass
        return {
            "status": "ok",
            "proposal": res.proposal,
            "firewall": res.firewall,
            "executed": res.executed,
            "timings": res.timings,
            "trace_id": res.proposal.get("trace_id") if isinstance(res.proposal, dict) else None,
            "decision_trace_id": res.proposal.get("trace_id") if isinstance(res.proposal, dict) else None,
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        raise HTTPException(status_code=500, detail="orchestrate failed")
