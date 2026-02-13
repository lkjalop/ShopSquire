from typing import Dict, Optional
import os
import httpx

from fastapi import APIRouter, HTTPException, Depends, Request

from src.app.security.pci import contains_pci_data
from src.app.config import load_feature_flags, get_settings
from src.app.observability.tracing import get_tracer
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.payment_threats import evaluate_payment_threat

router = APIRouter(prefix="/api/v1/payments/afterpay", tags=["payments-afterpay"])
tracer = get_tracer("payments-afterpay")


@router.post("/intent")
def create_intent(
    request: Request,
    uid: str,
    amount_cents: int,
    idempotency_key: Optional[str] = None,
    description: Optional[str] = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    with tracer.start_as_current_span("afterpay.create_intent"):
        flags = load_feature_flags(get_settings().feature_flags_path)
        cap = flags.get("CAPABILITIES", {}).get("afterpay", {"enabled": False})
        if not cap.get("enabled"):
            raise HTTPException(status_code=503, detail="Afterpay disabled by feature flags")
        if contains_pci_data(description or ""):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        risk = evaluate_payment_threat(
            provider="afterpay",
            uid=uid,
            amount_cents=amount_cents,
            currency="USD",
            description=description,
            request_ip=(request.client.host if request and request.client else None),
            idempotency_key=idempotency_key,
            tenant_id=None,
        )
        if risk.get("decision") == "block":
            raise HTTPException(status_code=403, detail={"message": "Payment request blocked by security policy", "security": risk})
        base_url = os.getenv("AFTERPAY_API_BASE_URL", "").strip()
        api_key = os.getenv("AFTERPAY_API_KEY", "").strip()
        if not (base_url and api_key):
            raise HTTPException(status_code=503, detail="Afterpay provider not configured")
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
                raise HTTPException(status_code=502, detail={"message": "Afterpay request failed", "provider_status": resp.status_code})
            return {
                "provider": "afterpay",
                "intent_id": data.get("id"),
                "idempotency_key": idempotency_key,
                "status": data.get("status") or "created",
                "security": risk,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Afterpay provider unavailable: {exc}")
