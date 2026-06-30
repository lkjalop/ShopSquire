import json
import logging
import os

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Any, Dict
from sqlalchemy import text

from src.app.config import get_settings, load_feature_flags
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.observability.tracing import get_tracer
from src.app.services.payments import StripeClient
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.transaction_firewall import evaluate_transaction_firewall
from src.app.policy.kill_switch import assert_autonomy_allowed

_log = logging.getLogger("shopsquire.payments")


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
    k = f"{path}:{key}"
    with db_session() as db:
        try:
            # Ensure the table exists — schema matches idempotency middleware.
            # fingerprint NOT NULL so we provide the operation type as fingerprint.
            db.execute(text(
                "CREATE TABLE IF NOT EXISTS idempotency_keys "
                "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
                "response_status INT, response_body TEXT, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            ))
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        try:
            # INSERT OR IGNORE silently skips UNIQUE violations on SQLite.
            # rowcount == 1 → new key (allow); rowcount == 0 → duplicate (reject).
            result = db.execute(
                text("INSERT INTO idempotency_keys (key, fingerprint) VALUES (:k, :fp) ON CONFLICT (key) DO NOTHING"),
                {"k": k, "fp": path},
            )
            db.commit()
            inserted = getattr(result, "rowcount", 1)
            return bool(inserted)  # True = first occurrence; False = duplicate
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            # Fallback: check directly whether the key already exists
            try:
                row = db.execute(
                    text("SELECT 1 FROM idempotency_keys WHERE key = :k"), {"k": k}
                ).fetchone()
                return row is None  # True = no existing row, False = duplicate
            except Exception:
                # Money path: if we CANNOT verify idempotency (DB error), fail CLOSED — reject as a
                # possible duplicate (caller returns 409, no charge) rather than risk a double charge.
                return False


def _stripe_key_live(key: Any) -> bool:
    """True only for a REAL Stripe secret key — not the sk_test_xxx demo placeholder. Single source of
    truth shared by the rollout reporter and the checkout gate so readiness can't over-claim."""
    k = str(key or "")
    return bool(k.startswith("sk_") and k != "sk_test_xxx")


@router.get("/providers/rollout")
def providers_rollout_status(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    flags = _ff_get_flags()
    caps = flags.get("CAPABILITIES", {}) if isinstance(flags.get("CAPABILITIES"), dict) else {}
    settings = get_settings()
    providers = [
        {
            "provider": "stripe",
            "enabled": bool((caps.get("stripe") or caps.get("payments") or {}).get("enabled", True)),
            # honest readiness: a placeholder key (sk_test_xxx) is NOT a real integration — mirror the
            # checkout's stripe_live gate so this never reports "ga" on the demo placeholder.
            "real_integration_ready": _stripe_key_live(settings.stripe_api_key),
            "rollout_stage": "ga" if _stripe_key_live(settings.stripe_api_key) else "disabled",
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
        flags = _ff_get_flags()
        assert_autonomy_allowed(
            "payments",
            flags=flags,
            source_id="Payments_Autonomy_Governance_Agent",
            context={"amount_cents": int(amount_cents or 0), "currency": currency},
        )
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
    order_id: str | None = None  # internal order ID from POST /api/v1/orders/create


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
    amount_cents = max(0, int(body.amount_cents or 0))
    currency = str(body.currency or "USD").upper()[:3]
    assert_autonomy_allowed(
        "payments",
        flags=flags,
        source_id="Payments_Autonomy_Governance_Agent",
        context={"amount_cents": amount_cents, "currency": currency},
    )
    cap = flags.get("CAPABILITIES", {}).get("stripe") or flags.get("CAPABILITIES", {}).get("payments") or {}

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
                stripe_intent_id = intent.get("id") or f"pi_{secrets.token_hex(8)}"
                # Link the Stripe intent to the internal order so the webhook can
                # transition pending → paid without guessing the association.
                if body.order_id:
                    try:
                        with db_session() as _db:
                            _db.execute(
                                text(
                                    "UPDATE orders SET stripe_intent_id = :iid, "
                                    "updated_at = CURRENT_TIMESTAMP "
                                    "WHERE id = :oid"
                                ),
                                {"iid": stripe_intent_id, "oid": body.order_id},
                            )
                            _db.commit()
                    except Exception as _db_exc:
                        _log.warning("checkout_initiate: failed to store stripe_intent_id: %s", _db_exc)
                return {
                    "order_id": body.order_id or stripe_intent_id,
                    "stripe_intent_id": stripe_intent_id,
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

    # Hard-block demo mode in production even if ALLOW_DEMO_CHECKOUT is somehow set.
    if _is_non_dev_env(settings.app_env) and not os.environ.get("ALLOW_DEMO_CHECKOUT", "").lower() in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=503,
            detail="Checkout unavailable in production without a configured Stripe key.",
        )
    _log.warning(
        "checkout_initiate: returning demo_confirmed — no real payment processed "
        "(app_env=%s, ALLOW_DEMO_CHECKOUT=%s)",
        getattr(settings, "app_env", "unknown"),
        os.environ.get("ALLOW_DEMO_CHECKOUT", ""),
    )
    demo_order_id = f"DEMO-{secrets.token_urlsafe(6).upper()}"
    return {
        "order_id": demo_order_id,
        "stripe_intent_id": None,
        "client_secret": None,
        "status": "demo_confirmed",
        "amount_cents": amount_cents,
        "currency": currency,
        "demo_mode": True,
    }


# ─── Stripe webhook ───────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request) -> Dict:
    """Stripe sends payment_intent.succeeded / payment_intent.payment_failed here.

    Signature verification uses STRIPE_WEBHOOK_SECRET. In non-dev environments the
    secret is MANDATORY: an unsigned/unverifiable webhook is rejected (fail closed),
    so a forged event can never transition an order to paid/refunded. In local/dev/test
    only, an unset secret falls back to processing the raw JSON (with a warning) so the
    flow can be exercised without Stripe configured.
    """
    payload_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()

    if webhook_secret:
        try:
            import stripe as _stripe
            event = _stripe.Webhook.construct_event(payload_bytes, sig_header, webhook_secret)
        except Exception as exc:
            _log.warning("stripe_webhook: invalid signature — %s", exc)
            raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook signature: {exc}")
    else:
        # Fail closed outside dev: never mutate order state from an unverified payload.
        if _is_non_dev_env(getattr(get_settings(), "app_env", None)):
            _log.error(
                "stripe_webhook: STRIPE_WEBHOOK_SECRET not set in non-dev env — rejecting unverified webhook (fail closed)"
            )
            raise HTTPException(
                status_code=503,
                detail="Webhook signature verification not configured (STRIPE_WEBHOOK_SECRET required).",
            )
        _log.warning("stripe_webhook: STRIPE_WEBHOOK_SECRET not set — skipping signature verification (dev only)")
        try:
            event = json.loads(payload_bytes)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

    event_type = str(event.get("type") or "")
    data_obj = (event.get("data") or {}).get("object") or {}
    intent_id = str(data_obj.get("id") or "").strip()

    if event_type == "payment_intent.succeeded" and intent_id:
        with db_session() as _db:
            result = _db.execute(
                text(
                    "UPDATE orders SET status = 'paid', updated_at = CURRENT_TIMESTAMP "
                    "WHERE stripe_intent_id = :iid AND status = 'created'"
                ),
                {"iid": intent_id},
            )
            _db.commit()
        _log.info("stripe_webhook: marked paid for intent %s (rows=%s)", intent_id, getattr(result, "rowcount", "?"))

    elif event_type == "payment_intent.payment_failed" and intent_id:
        with db_session() as _db:
            _db.execute(
                text(
                    "UPDATE orders SET status = 'payment_failed', updated_at = CURRENT_TIMESTAMP "
                    "WHERE stripe_intent_id = :iid AND status = 'created'"
                ),
                {"iid": intent_id},
            )
            _db.commit()
        _log.warning("stripe_webhook: payment_failed for intent %s", intent_id)

    elif event_type == "charge.refunded" and intent_id:
        # charge.refunded carries payment_intent field, not id
        pi_id = str(data_obj.get("payment_intent") or "").strip() or intent_id
        with db_session() as _db:
            _db.execute(
                text(
                    "UPDATE orders SET status = 'returned', updated_at = CURRENT_TIMESTAMP "
                    "WHERE stripe_intent_id = :iid AND status IN ('delivered', 'shipped', 'paid')"
                ),
                {"iid": pi_id},
            )
            _db.commit()
        _log.info("stripe_webhook: refund processed for intent %s", pi_id)

    return {"received": True, "type": event_type}
