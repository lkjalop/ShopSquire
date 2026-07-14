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
        idempotency_key = (
            str(idempotency_key or request.headers.get("Idempotency-Key") or "").strip() or None
        )
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required for payment intents")
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
        # pass the key to Stripe too (P0-1d): provider-level guard so even a retry that slips past
        # the server dedup can't mint a second intent.
        out = client.create_payment_intent(amount_cents, currency, idempotency_key=idempotency_key)
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
    checkout_attempt_id: str | None = None
    # P0-A bridge: the checkout page sends the cart lines so a REAL order row is created
    # server-side (server-priced), making the webhook's created→paid transition reachable.
    uid: str | None = None
    items: list[dict] | None = None


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
    # Address validation: reject an UNUSABLE shipping address (empty/gibberish → an order that can
    # never ship + a dispatch that dead-letters at the carrier); a weak-but-plausible one warns and
    # is stamped on the response. Only enforced when an address is provided (guest/direct flows omit it).
    _addr_verdict = None
    if body.shipping_address is not None:
        from src.app.services.address_validation import validate_address
        _addr_verdict = validate_address(body.shipping_address)
        if _addr_verdict.get("severity") == "reject":
            raise HTTPException(status_code=422, detail={"message": "invalid_shipping_address",
                                                         "reason": _addr_verdict.get("reason")})
    assert_autonomy_allowed(
        "payments",
        flags=flags,
        source_id="Payments_Autonomy_Governance_Agent",
        context={"amount_cents": amount_cents, "currency": currency},
    )
    cap = flags.get("CAPABILITIES", {}).get("stripe") or flags.get("CAPABILITIES", {}).get("payments") or {}

    allow_demo_checkout = _demo_checkout_allowed(settings, cap)

    # P0-B gate parity: the PUBLIC route gets the same transaction firewall + idempotency the
    # merchant /intent enforces (it previously had the LEAST protection of any payment route).
    _request_idempotency_key = str(
        request.headers.get("Idempotency-Key") or body.checkout_attempt_id or ""
    ).strip() or None
    risk = evaluate_transaction_firewall(
        provider="stripe",
        uid=str(body.uid or "public_checkout"),
        amount_cents=amount_cents,
        currency=currency,
        description=None,
        request_ip=(request.client.host if request and request.client else None),
        idempotency_key=_request_idempotency_key,
        tenant_id=None,
        trace_id=None,
    )
    if risk.get("action") == "hard_block":
        raise HTTPException(status_code=403, detail={"message": "Payment request blocked by security policy", "security": risk})
    if risk.get("action") in ("step_up_mfa", "manual_review"):
        code = 401 if risk.get("action") == "step_up_mfa" else 202
        raise HTTPException(status_code=code, detail={
            "message": "mfa_stepup_required" if code == 401 else "manual_review_required", "security": risk})

    # IDEMPOTENCY FIRST (P0-1b): reserve BEFORE creating the order/intent — otherwise a duplicate
    # submit leaves a second order row + double-reserved inventory behind before the (previously
    # post-order) check could fire. Key precedence: explicit client Idempotency-Key header → the
    # passed-in order_id → a stable, WINDOWED signature of the cart (uid+items+amount) so a
    # header-less double-submit dedups while a genuine later re-purchase of the same cart is not
    # permanently blocked. _idempotent fails CLOSED on DB error (409, no order, no charge).
    # A checkout attempt must have a stable client or order identity. Time windows and client
    # prices are intentionally excluded from idempotency keys.
    order_id = (body.order_id or "").strip() or None
    _hdr_key = (request.headers.get("Idempotency-Key") or "").strip()
    _body_key = str(body.checkout_attempt_id or "").strip()
    if _hdr_key:
        _idem_key = _hdr_key
    elif _body_key:
        _idem_key = _body_key
    elif order_id:
        _idem_key = f"co:{order_id}"
    elif body.items:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key or checkout_attempt_id is required when creating an order from cart items",
        )
    else:
        _idem_key = None    # bare-amount path (no order/items/key) — allowed only for DEMO confirm;
        #                     the REAL-provider guard below (#7) blocks an un-keyed live Stripe intent.
    if _idem_key and not _idempotent("checkout_initiate", _idem_key):
        raise HTTPException(status_code=409, detail="Duplicate checkout initiation")

    # P0-A: no order_id but cart lines present → create the REAL order row server-side.
    # The server-priced total wins over the client-sent amount (never trust client pricing).
    if order_id is None and body.items:
        from src.app.routers.orders import create_order_core
        with db_session() as _odb:
            created = create_order_core(
                _odb,
                uid=str(body.uid or f"guest-{secrets.token_hex(4)}"),
                items=list(body.items or []),
                guest_email=(body.customer_email or None),
            )
        order_id = created.get("order_id")
        if created.get("total_cents"):
            amount_cents = int(created["total_cents"])

    stripe_live = (
        settings.stripe_api_key
        and settings.stripe_api_key.startswith("sk_")
        and settings.stripe_api_key != "sk_test_xxx"
        and not (isinstance(cap, dict) and cap.get("enabled") is False)
    )

    if stripe_live:
        # #7 (GPT-5.6): never create a REAL Stripe intent without an idempotency key — a retry would
        # mint a second charge. The demo/no-provider path is exempt (no real money). A bare-amount
        # checkout that reaches live Stripe must carry a header or checkout_attempt_id.
        if not _idem_key:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key or checkout_attempt_id is required for a live payment")
        try:
            client = StripeClient(settings.stripe_api_key)
            # P0-1d: provider-level idempotency — reuse the same key the server dedup reserved, so a
            # retry that reaches Stripe returns the same intent instead of a second charge.
            intent = client.create_payment_intent(amount_cents, currency, idempotency_key=_idem_key)
            if isinstance(intent, dict):
                stripe_intent_id = intent.get("id") or f"pi_{secrets.token_hex(8)}"
                # Link the Stripe intent to the internal order so the webhook can
                # transition pending → paid without guessing the association.
                if order_id:
                    try:
                        with db_session() as _db:
                            _db.execute(
                                text(
                                    "UPDATE orders SET stripe_intent_id = :iid, "
                                    "updated_at = CURRENT_TIMESTAMP "
                                    "WHERE id = :oid"
                                ),
                                {"iid": stripe_intent_id, "oid": order_id},
                            )
                            _db.commit()
                    except Exception as _db_exc:
                        _log.warning("checkout_initiate: failed to store stripe_intent_id: %s", _db_exc)
                    try:
                        from src.app.services.payment_ledger import KIND_INTENT_CREATED, record_txn
                        with db_session() as _ldb:
                            record_txn(_ldb, order_id=order_id, kind=KIND_INTENT_CREATED,
                                       intent_id=stripe_intent_id, amount_cents=amount_cents,
                                       currency=currency, provider="stripe", commit=True)
                    except Exception as _l_exc:
                        _log.warning("checkout_initiate: ledger write failed: %s", _l_exc)
                return {
                    "order_id": order_id or stripe_intent_id,
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
    # Demo mode with a REAL order row: stamp a demo intent id so the (dev-only, unsigned) webhook
    # can drive the SAME created→paid→dispatch chain the production Stripe path uses.
    demo_intent_id = None
    if order_id:
        demo_intent_id = f"pi_demo_{secrets.token_hex(8)}"
        try:
            with db_session() as _db:
                _db.execute(
                    text("UPDATE orders SET stripe_intent_id = :iid, updated_at = CURRENT_TIMESTAMP WHERE id = :oid"),
                    {"iid": demo_intent_id, "oid": order_id},
                )
                _db.commit()
        except Exception as _db_exc:
            _log.warning("checkout_initiate: failed to store demo intent id: %s", _db_exc)
        try:
            from src.app.services.payment_ledger import KIND_INTENT_CREATED, record_txn
            with db_session() as _ldb:
                record_txn(_ldb, order_id=order_id, kind=KIND_INTENT_CREATED, intent_id=demo_intent_id,
                           amount_cents=amount_cents, currency=currency, provider="demo", commit=True)
        except Exception as _l_exc:
            _log.warning("checkout_initiate: ledger write failed: %s", _l_exc)
    return {
        "order_id": order_id or f"DEMO-{secrets.token_urlsafe(6).upper()}",
        "stripe_intent_id": demo_intent_id,
        "client_secret": None,
        "status": "demo_confirmed",
        "amount_cents": amount_cents,
        "currency": currency,
        "demo_mode": True,
        "address_warning": (_addr_verdict.get("reason") if _addr_verdict and _addr_verdict.get("severity") == "warn" else None),
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
        if getattr(result, "rowcount", 0):
            _ledger_txn_for_intent(intent_id, "payment_succeeded")
            try:
                _dispatch_paid_order(intent_id)
            except Exception as exc:
                _log.warning("stripe_webhook: dispatch after paid failed for %s: %s", intent_id, exc)

    elif event_type == "payment_intent.payment_failed" and intent_id:
        with db_session() as _db:
            _res = _db.execute(
                text(
                    "UPDATE orders SET status = 'payment_failed', updated_at = CURRENT_TIMESTAMP "
                    "WHERE stripe_intent_id = :iid AND status = 'created'"
                ),
                {"iid": intent_id},
            )
            _won = int(getattr(_res, "rowcount", 0) or 0) > 0
            # #4: a failed payment must RELEASE the inventory the order reserved at creation — else
            # stock stays locked forever (phantom stockout). Atomic with the status flip; only on the
            # winning transition (idempotent anyway — release CAS-claims the reservations).
            if _won:
                _oid = _db.execute(
                    text("SELECT id FROM orders WHERE stripe_intent_id = :iid LIMIT 1"),
                    {"iid": intent_id}).scalar()
                if _oid:
                    try:
                        from src.app.services.inventory_guard import release_inventory_for_order
                        release_inventory_for_order(_db, order_id=str(_oid))
                    except Exception as _rex:
                        _log.warning("stripe_webhook: inventory release after failed payment %s: %s",
                                     intent_id, _rex)
            _db.commit()
        # #5 (this path): record the failure ONCE — the created→payment_failed CAS updates 0 rows on
        # a DUPLICATE webhook delivery, so gating the ledger append on the win dedups repeat delivery
        # (a repeated append would corrupt the refund/settlement fold).
        if _won:
            _log.warning("stripe_webhook: payment_failed for intent %s", intent_id)
            _ledger_txn_for_intent(intent_id, "payment_failed")

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
        # Reconcile settlement against the governed ledger: a provider refund with NO approved
        # request on file is recorded but flagged loudly — money moved outside the approval flow.
        try:
            from src.app.services.payment_ledger import refund_state
            _amt = data_obj.get("amount_refunded")
            _oid = _ledger_txn_for_intent(pi_id, "refund_settled",
                                          amount_cents=(int(_amt) if _amt is not None else None))
            if _oid:
                with db_session() as _rdb:
                    state = refund_state(_rdb, _oid)
                if int(state.get("approved_cents") or 0) < int(state.get("settled_cents") or 0):
                    _log.critical(
                        "stripe_webhook: refund SETTLED WITHOUT MATCHING APPROVAL for order %s "
                        "(approved=%s settled=%s) — reconcile with the provider dashboard.",
                        _oid, state.get("approved_cents"), state.get("settled_cents"))
        except Exception as exc:
            _log.warning("stripe_webhook: refund reconciliation failed for %s: %s", pi_id, exc)

    return {"received": True, "type": event_type}


# ─── Governed refunds (GATE-2 mold: propose → human approve → provider settles) ──────────────
# Refunds were previously OBSERVED only (charge.refunded flips status); nothing could INITIATE
# one and nothing reconciled. Now: a merchant REQUESTS (append refund_requested), a human owner
# APPROVES (append refund_approved — the authorization to execute at the provider), and the
# charge.refunded webhook SETTLES + reconciles against these events, screaming on any refund
# that settled without an approval on file. One open request per order at a time.

class _RefundRequestBody(BaseModel):
    order_id: str
    amount_cents: int | None = None  # default: full remaining refundable amount
    reason: str = ""


@router.post("/refunds/request")
def refund_request(
    body: _RefundRequestBody,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    # Core extracted to services/refund_requests.py so the returns/claims pipeline can open a request on
    # the SAME governed rail programmatically. This endpoint keeps its exact HTTP semantics.
    from src.app.services.refund_requests import create_refund_request
    with db_session() as db:
        result = create_refund_request(db, order_id=body.order_id, amount_cents=body.amount_cents,
                                       reason=body.reason, actor_type="role", actor_id=role)
    if not result.get("ok"):
        err = result.get("error")
        if err == "order_not_found":
            raise HTTPException(status_code=404, detail="order_not_found")
        if err == "order_not_refundable":
            raise HTTPException(status_code=409, detail={"message": "order_not_refundable",
                                                         "status": result.get("order_status")})
        if err == "refund_request_already_open":
            raise HTTPException(status_code=409, detail="refund_request_already_open")
        raise HTTPException(status_code=422, detail={"message": "invalid_refund_amount",
                                                     "refundable_cents": result.get("refundable_cents")})
    return {"order_id": result["order_id"], "status": "refund_requested",
            "amount_cents": result["amount_cents"], "approval_required": True,
            "approve_via": result["approve_via"]}


@router.post("/refunds/{order_id}/approve")
def refund_approve(
    order_id: str,
    role: str = Depends(require_role([ROLE_OWNER])),  # HUMAN owner only — the GATE-2 invariant
) -> Dict:
    from src.app.services.payment_ledger import (KIND_REFUND_APPROVED, KIND_REFUND_REQUESTED,
                                                 ledger_for_order, record_txn, reserve_refund_slot)
    with db_session() as db:
        events = ledger_for_order(db, order_id)
        requests = [e for e in events if e["kind"] == KIND_REFUND_REQUESTED]
        approvals = [e for e in events if e["kind"] == KIND_REFUND_APPROVED]
        if len(requests) <= len(approvals):
            raise HTTPException(status_code=409, detail="no_open_refund_request")
        # ATOMIC slot lock (P0-1f): the count check above is check-then-act — two concurrent
        # approvals of the same open request both pass and both append REFUND_APPROVED (double
        # refund authorization). Reserve the (order, approval-index) slot; rides this transaction
        # so a failed ledger write releases it. The live-Stripe path is also key-guarded below.
        if not reserve_refund_slot(db, f"refund:appr:{order_id}:{len(approvals)}"):
            raise HTTPException(status_code=409, detail="refund_approval_in_progress")
        open_req = requests[len(approvals)]
        _amount = open_req.get("amount_cents")
        _currency = open_req.get("currency") or "USD"
        _intent_id = db.execute(text("SELECT stripe_intent_id FROM orders WHERE id = :o LIMIT 1"),
                                {"o": order_id}).scalar()
        record_txn(db, order_id=order_id, kind=KIND_REFUND_APPROVED,
                   amount_cents=_amount, currency=_currency,
                   actor_type="role", actor_id=role, reason="approved", commit=True)
    _log.info("refund approved for order %s (%s cents) by role=%s", order_id, _amount, role)

    # EXECUTE the refund at the provider when Stripe is live AND the order carries a real intent
    # (demo intents pi_demo_* have no provider-side charge). The approval above is the authorization;
    # this is the execution. charge.refunded still reconciles the ledger when the webhook lands.
    settings = get_settings()
    _intent = str(_intent_id or "")
    if _stripe_key_live(settings.stripe_api_key) and _intent and not _intent.startswith("pi_demo_"):
        try:
            client = StripeClient(settings.stripe_api_key)
            refund = client.create_refund(
                payment_intent_id=_intent, amount_cents=(int(_amount) if _amount is not None else None),
                reason="requested_by_customer", idempotency_key=f"refund:{order_id}:{len(approvals)}")
            return {"order_id": order_id, "status": "refund_executed",
                    "amount_cents": _amount, "provider_execution": "stripe",
                    "provider_refund_id": refund.get("id"), "provider_status": refund.get("status"),
                    "settled_by": "charge.refunded webhook"}
        except Exception as exc:
            # Approval is recorded; execution failed — surface it so an operator retries. The ledger
            # shows an approved-but-unsettled refund (refund_state.approved > settled) until resolved.
            _log.warning("refund execution failed for order %s: %s", order_id, exc)
            raise HTTPException(status_code=502, detail={"message": "refund_provider_execution_failed",
                                                         "error": str(exc)[:160], "order_id": order_id})
    # No live Stripe / demo intent → the approval AUTHORIZES a manual/dashboard refund; the webhook
    # settles + reconciles it here when it lands.
    return {"order_id": order_id, "status": "refund_approved",
            "amount_cents": _amount,
            "provider_execution": "manual_or_webhook", "settled_by": "charge.refunded webhook"}


@router.get("/refunds/{order_id}")
def refund_ledger(
    order_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    from src.app.services.payment_ledger import ledger_for_order, refund_state
    with db_session() as db:
        return {"order_id": order_id, "state": refund_state(db, order_id),
                "ledger": ledger_for_order(db, order_id)}


def _ledger_txn_for_intent(intent_id: str, kind: str, amount_cents: int | None = None) -> str | None:
    """Resolve the order behind an intent and append a ledger event (amount defaults to the order
    total). Returns the order_id, or None. Best-effort — webhook processing never fails on this."""
    try:
        from src.app.services.payment_ledger import record_txn
        with db_session() as db:
            row = db.execute(
                text("SELECT id, total_cents, currency FROM orders WHERE stripe_intent_id = :iid LIMIT 1"),
                {"iid": intent_id},
            ).fetchone()
            if not row:
                return None
            record_txn(db, order_id=str(row[0]), kind=kind, intent_id=intent_id,
                       amount_cents=(amount_cents if amount_cents is not None else row[1]),
                       currency=str(row[2] or "USD"),
                       provider=("demo" if intent_id.startswith("pi_demo_") else "stripe"), commit=True)
            return str(row[0])
    except Exception as exc:
        _log.warning("payment ledger write (%s) failed for intent %s: %s", kind, intent_id, exc)
        return None


def _dispatch_paid_order(intent_id: str) -> None:
    """P0-C, now GOVERNED: paid → Dispatch_Agent. Proposes carrier/service from the profile
    delivery_policy + provider readiness; auto-executes under the approval threshold and HOLDS
    above it for a human owner (POST /dispatch/{order_id}/approve) — the RFQ bounded-autonomy
    mold applied to buyer-facing dispatch."""
    from src.app.services.dispatch_agent import dispatch_for_paid_order, log_dispatch_decision
    with db_session() as db:
        row = db.execute(
            text("SELECT id, total_cents FROM orders WHERE stripe_intent_id = :iid LIMIT 1"),
            {"iid": intent_id},
        ).fetchone()
        if not row:
            return
        out = dispatch_for_paid_order(db, order_id=str(row[0]), intent_id=intent_id,
                                      total_cents=int(row[1] or 0))
        db.commit()
    # trace event AFTER commit — inside the transaction it self-deadlocks on the SQLite lock
    log_dispatch_decision(out, status=("pending" if out.get("outcome") == "held_for_approval" else "executed"))
    _log.info("stripe_webhook: dispatch %s for order %s (carrier=%s)",
              out.get("outcome"), row[0], out.get("carrier"))


@router.post("/dispatch/{order_id}/approve")
def dispatch_approve(
    order_id: str,
    role: str = Depends(require_role([ROLE_OWNER])),  # HUMAN owner only — GATE-2 invariant
) -> Dict:
    """Approve + execute a HELD dispatch (order total met the approval threshold)."""
    from src.app.services.dispatch_agent import (execute_dispatch, log_dispatch_decision,
                                                 pending_dispatch, propose_dispatch)
    with db_session() as db:
        held = pending_dispatch(db, order_id)
        if not held:
            raise HTTPException(status_code=409, detail="no_dispatch_pending_approval")
        row = db.execute(text("SELECT total_cents, stripe_intent_id FROM orders WHERE id = :o LIMIT 1"),
                         {"o": order_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="order_not_found")
        proposal = propose_dispatch(order_id=order_id, total_cents=int(row[0] or 0))
        out = execute_dispatch(db, order_id=order_id, intent_id=(str(row[1]) if row[1] else None),
                               proposal=proposal, actor=role)
        db.commit()
    log_dispatch_decision(proposal, status="executed", actor=role)  # after commit — see agent note
    return {"order_id": order_id, "status": "dispatch_approved", **out}

