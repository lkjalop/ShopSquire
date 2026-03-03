from typing import Dict, Optional
import os
import httpx

from fastapi import APIRouter, HTTPException, Depends, Request

from src.app.security.pci import contains_pci_data
from src.app.config import load_feature_flags, get_settings
from src.app.observability.tracing import get_tracer
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.transaction_firewall import evaluate_transaction_firewall

router = APIRouter(prefix="/api/v1/payments/revolut", tags=["payments-revolut"])
tracer = get_tracer("payments-revolut")


@router.post("/intent")
def create_intent(
    request: Request,
    uid: str,
    amount_cents: int,
    idempotency_key: Optional[str] = None,
    description: Optional[str] = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    with tracer.start_as_current_span("revolut.create_intent"):
        flags = load_feature_flags(get_settings().feature_flags_path)
        cap = flags.get("CAPABILITIES", {}).get("revolut", {"enabled": False})
        if not cap.get("enabled"):
            raise HTTPException(status_code=503, detail="Revolut disabled by feature flags")
        if contains_pci_data(description or ""):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        risk = evaluate_transaction_firewall(
            provider="revolut",
            uid=uid,
            amount_cents=amount_cents,
            currency="USD",
            description=description,
            request_ip=(request.client.host if request and request.client else None),
            idempotency_key=idempotency_key,
            tenant_id=None,
            trace_id=None,
        )
        if risk.get("action") == "hard_block":
            raise HTTPException(status_code=403, detail={"message": "Payment request blocked by security policy", "security": risk})
        if risk.get("action") in ("step_up_mfa", "manual_review"):
            code = 401 if risk.get("action") == "step_up_mfa" else 202
            detail = "mfa_stepup_required" if code == 401 else "manual_review_required"
            raise HTTPException(status_code=code, detail={"message": detail, "security": risk})
        base_url = os.getenv("REVOLUT_API_BASE_URL", "").strip()
        api_key = os.getenv("REVOLUT_API_KEY", "").strip()
        if not (base_url and api_key):
            raise HTTPException(status_code=503, detail="Revolut provider not configured")
        payload = {
            "uid": uid,
            "amount_cents": int(amount_cents),
            "currency": "USD",
            "description": description,
            "idempotency_key": idempotency_key,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{base_url.rstrip('/')}/intents",
                    json=payload,
                    headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
                )
                data = resp.json() if resp.content else {}
            if resp.status_code >= 300:
                raise HTTPException(status_code=502, detail={"message": "Revolut request failed", "provider_status": resp.status_code})
            return {
                "provider": "revolut",
                "intent_id": data.get("id"),
                "idempotency_key": idempotency_key,
                "status": data.get("status") or "created",
                "security": risk,
                "pci_scope": "tokenized_provider_managed",
                "card_data_stored": ["token", "last4", "provider_ref"],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Revolut provider unavailable: {exc}")
