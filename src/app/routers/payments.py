from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Dict
from sqlalchemy import text

from src.app.config import get_settings, load_feature_flags
from src.app.observability.tracing import get_tracer
from src.app.services.payments import StripeClient
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.transaction_firewall import evaluate_transaction_firewall


router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
tracer = get_tracer("payments-router")


def _is_non_dev_env(app_env: str | None) -> bool:
    env = str(app_env or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


def _demo_checkout_allowed(settings, capability: Dict | None) -> bool:
    explicit = str(__import__("os").environ.get("ALLOW_DEMO_CHECKOUT", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    if isinstance(capability, dict) and capability.get("demo_checkout") is True:
        return True
    return not _is_non_dev_env(getattr(settings, "app_env", None))


def _idempotent(path: str, key: str | None) -> bool:
    if not key:
        return True
    with db_session() as db:
        # Ensure idempotency table exists (supports SQLite-based tests)
        try:
            if getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "sqlite":
                db.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                    )
                )
        except Exception:
            # If table creation fails (e.g., transient DB), treat as idempotent to avoid false conflicts
            return True
        try:
            # Attempt atomic insert and detect whether it was newly inserted.
            k = f"{path}:{key}"
            try:
                res = db.execute(text("INSERT OR IGNORE INTO idempotency_keys (key) VALUES (:k)"), {"k": k})
                try:
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                # SQLite-specific check: changes() returns 1 when insert occured, 0 when ignored
                try:
                    ch = db.execute(text("SELECT changes() as c")).fetchone()
                    if ch and len(ch) > 0:
                        return int(ch[0]) == 1
                except Exception:
                    pass
                # Fallback: check existence; if present and we didn't detect changes, treat as duplicate
                row = db.execute(text("SELECT 1 FROM idempotency_keys WHERE key = :k"), {"k": k}).fetchone()
                return not (row is None)
            except Exception:
                # On any DB error, allow the request rather than incorrectly signaling conflict
                try:
                    db.rollback()
                except Exception:
                    pass
                return True
        except Exception:
            # On any DB error, allow the request rather than incorrectly signaling conflict
            try:
                db.rollback()
            except Exception:
                pass
                return True


@router.get("/providers/rollout")
def providers_rollout_status(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    caps = flags.get("CAPABILITIES", {}) if isinstance(flags.get("CAPABILITIES"), dict) else {}
    settings = get_settings()
    providers = [
        {
            "provider": "stripe",
            "enabled": bool((caps.get("stripe") or caps.get("payments") or {}).get("enabled", True)),
            "real_integration_ready": bool(settings.stripe_api_key and str(settings.stripe_api_key).startswith("sk_")),
            "rollout_stage": "ga" if bool(settings.stripe_api_key and str(settings.stripe_api_key).startswith("sk_")) else "disabled",
        },
        {
            "provider": "paypal",
            "enabled": bool((caps.get("paypal") or {}).get("enabled", False)),
            "real_integration_ready": bool(settings.paypal_client_id and settings.paypal_client_secret),
            "rollout_stage": "beta" if bool(settings.paypal_client_id and settings.paypal_client_secret) else "disabled",
        },
        {
            "provider": "revolut",
            "enabled": bool((caps.get("revolut") or {}).get("enabled", False)),
            "real_integration_ready": False,
            "rollout_stage": "disabled",
        },
        {
            "provider": "googlepay",
            "enabled": bool((caps.get("googlepay") or {}).get("enabled", False)),
            "real_integration_ready": False,
            "rollout_stage": "disabled",
        },
        {
            "provider": "afterpay",
            "enabled": bool((caps.get("afterpay") or {}).get("enabled", False)),
            "real_integration_ready": False,
            "rollout_stage": "disabled",
        },
    ]
    enabled_count = len([p for p in providers if p["enabled"]])
    return {
        "providers": providers,
        "enabled_count": enabled_count,
        "provider_concentration_risk": "high" if enabled_count <= 1 else ("medium" if enabled_count == 2 else "low"),
        "recommendation": "Enable at least two providers in production to reduce checkout drop-off and concentration risk."
        if enabled_count <= 1
        else "Provider diversity is acceptable.",
    }


@router.post("/intent")
def create_intent(
    request: Request,
    amount_cents: int,
    currency: str = "USD",
    idempotency_key: str | None = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    with tracer.start_as_current_span("payments.create_intent"):
        flags = load_feature_flags(get_settings().feature_flags_path)
        cap = flags.get("CAPABILITIES", {}).get("stripe") or flags.get("CAPABILITIES", {}).get("payments")
        if isinstance(cap, dict) and cap.get("enabled") is False:
            raise HTTPException(status_code=503, detail="Payments disabled by feature flags")
        settings = get_settings()
        if not (settings.stripe_api_key and settings.stripe_api_key.startswith("sk_")):
            raise HTTPException(status_code=503, detail="Stripe provider not configured")
        try:
            client = StripeClient(settings.stripe_api_key)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Stripe provider unavailable: {exc}")
        risk = evaluate_transaction_firewall(
            provider="stripe",
            uid="merchant_portal",
            amount_cents=amount_cents,
            currency=currency,
            description=None,
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
        if not _idempotent("payment_intent", idempotency_key):
            raise HTTPException(status_code=409, detail="Duplicate payment intent")
        out = client.create_payment_intent(amount_cents, currency)
        if isinstance(out, dict):
            out["security"] = risk
            out["pci_scope"] = "tokenized_provider_managed"
            out["card_data_stored"] = ["token", "last4", "provider_ref"]
        return out


# ─── Customer-facing checkout initiation ─────────────────────────────────────

class _CheckoutInitiateBody(BaseModel):
    amount_cents: int = 0
    currency: str = "USD"
    customer_name: str | None = None
    customer_email: str | None = None
    shipping_address: str | None = None
    cart_id: str | None = None


@router.post("/checkout-initiate")
def checkout_initiate(
    request: Request,
    body: _CheckoutInitiateBody,
) -> Dict:
    """Customer-facing checkout initiation.

    Creates a Stripe PaymentIntent when Stripe is fully configured.
    Demo checkout is only allowed in local/dev/test or when explicitly enabled.
    Production runtimes fail closed instead of silently switching to demo mode.
    """
    import secrets

    settings = get_settings()
    flags = load_feature_flags(settings.feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("stripe") or flags.get("CAPABILITIES", {}).get("payments") or {}

    amount_cents = max(0, int(body.amount_cents or 0))
    currency = str(body.currency or "USD").upper()[:3]
    allow_demo_checkout = _demo_checkout_allowed(settings, cap)

    stripe_live = (
        settings.stripe_api_key
        and settings.stripe_api_key.startswith("sk_")
        and settings.stripe_api_key != "sk_test_xxx"
        and not (isinstance(cap, dict) and cap.get("enabled") is False)
    )

    if stripe_live:
        try:
            client = StripeClient(settings.stripe_api_key)
            intent = client.create_payment_intent(amount_cents, currency)
            if isinstance(intent, dict):
                return {
                    "order_id": intent.get("id", f"pi_{secrets.token_hex(8)}"),
                    "client_secret": intent.get("client_secret"),
                    "status": "requires_payment",
                    "amount_cents": amount_cents,
                    "currency": currency,
                    "demo_mode": False,
                }
        except Exception as exc:
            if not allow_demo_checkout:
                raise HTTPException(status_code=503, detail=f"Stripe checkout unavailable: {exc}")

    if not allow_demo_checkout:
        raise HTTPException(
            status_code=503,
            detail="Checkout provider unavailable. Configure Stripe or explicitly enable demo checkout in non-production environments.",
        )

    demo_order_id = f"DEMO-{secrets.token_urlsafe(6).upper()}"
    return {
        "order_id": demo_order_id,
        "client_secret": None,
        "status": "demo_confirmed",
        "amount_cents": amount_cents,
        "currency": currency,
        "demo_mode": True,
    }
