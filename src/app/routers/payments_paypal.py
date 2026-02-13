from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Depends, Request

from src.app.security.pci import contains_pci_data
from src.app.config import load_feature_flags, get_settings
from src.app.observability.tracing import get_tracer
from src.app.services.payments import PayPalClient
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.payment_threats import evaluate_payment_threat

router = APIRouter(prefix="/api/v1/payments/paypal", tags=["payments-paypal"])
tracer = get_tracer("payments-paypal")


@router.post("/intent")
def create_intent(
    request: Request,
    uid: str,
    amount_cents: int,
    idempotency_key: Optional[str] = None,
    description: Optional[str] = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    with tracer.start_as_current_span("paypal.create_intent"):
        flags = load_feature_flags(get_settings().feature_flags_path)
        cap = flags.get("CAPABILITIES", {}).get("paypal", {"enabled": False})
        if not cap.get("enabled"):
            raise HTTPException(status_code=503, detail="PayPal disabled by feature flags")
        if contains_pci_data(description or ""):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        risk = evaluate_payment_threat(
            provider="paypal",
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
        settings = get_settings()
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            raise HTTPException(status_code=503, detail="PayPal provider not configured")
        try:
            client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret)
            order = client.create_order(amount_cents=amount_cents, currency="USD", description=description)
            return {
                "provider": "paypal",
                "intent_id": order.get("id"),
                "idempotency_key": idempotency_key,
                "status": order.get("status"),
                "security": risk,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
