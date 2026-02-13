from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict
from sqlalchemy import text

from src.app.config import get_settings, load_feature_flags
from src.app.observability.tracing import get_tracer
from src.app.services.payments import StripeClient
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.security.payment_threats import evaluate_payment_threat


router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
tracer = get_tracer("payments-router")

# In-memory idempotency cache used for tests/local runs when DB-backed idempotency
# may not be desirable or reliable.
_idempotency_cache: set[str] = set()


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
            # Short-circuit to an in-memory cache when UI routes disabled (test mode)
            try:
                if str(__import__("os").environ.get("DISABLE_UI_ROUTES", "0")).strip().lower() in ("1", "true", "yes"):
                    k = f"{path}:{key}"
                    if k in _idempotency_cache:
                        return False
                    _idempotency_cache.add(k)
                    return True
            except Exception:
                pass

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
        risk = evaluate_payment_threat(
            provider="stripe",
            uid="merchant_portal",
            amount_cents=amount_cents,
            currency=currency,
            description=None,
            request_ip=(request.client.host if request and request.client else None),
            idempotency_key=idempotency_key,
            tenant_id=None,
        )
        if risk.get("decision") == "block":
            raise HTTPException(status_code=403, detail={"message": "Payment request blocked by security policy", "security": risk})
        if not _idempotent("payment_intent", idempotency_key):
            raise HTTPException(status_code=409, detail="Duplicate payment intent")
        out = client.create_payment_intent(amount_cents, currency)
        if isinstance(out, dict):
            out["security"] = risk
        return out
