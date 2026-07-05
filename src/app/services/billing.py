from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text

from src.app.models.db import db_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dialect(db) -> str:
    try:
        return str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
    except Exception:
        return ""


_billing_tables_ready = False


def _ensure_billing_tables() -> None:
    # Once per process: this runs on EVERY request's billing-meter write, and re-issuing 4 DDL
    # statements against a contended live DB was a measurable chunk of the post-payload latency.
    global _billing_tables_ready
    if _billing_tables_ready:
        return
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tenant_billing_accounts (
                        tenant_id TEXT PRIMARY KEY,
                        stripe_customer_id TEXT,
                        stripe_subscription_item_id TEXT,
                        meter_key TEXT,
                        xero_tenant_id TEXT,
                        status TEXT DEFAULT 'active',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS billing_meter_events (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        source TEXT,
                        metadata_json TEXT,
                        stripe_event_id TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS pilot_tenants (
                        tenant_id TEXT PRIMARY KEY,
                        company_name TEXT,
                        contact_email TEXT,
                        vertical TEXT,
                        status TEXT DEFAULT 'pilot',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS tenant_provisioning (
                        tenant_id TEXT PRIMARY KEY,
                        plan_id TEXT NOT NULL,
                        home_region TEXT NOT NULL,
                        status TEXT DEFAULT 'provisioned',
                        limits_json TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.commit()
        _billing_tables_ready = True
    except Exception:
        pass


def link_tenant_stripe(
    *,
    tenant_id: str,
    customer_id: str,
    subscription_item_id: str,
    meter_key: str | None = None,
) -> Dict[str, Any]:
    _ensure_billing_tables()
    with db_session() as db:
        d = _dialect(db)
        if d == "sqlite":
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO tenant_billing_accounts
                    (tenant_id, stripe_customer_id, stripe_subscription_item_id, meter_key, updated_at)
                    VALUES (:tenant_id, :customer_id, :subscription_item_id, :meter_key, :updated_at)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "subscription_item_id": subscription_item_id,
                    "meter_key": meter_key,
                    "updated_at": _now(),
                },
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO tenant_billing_accounts
                    (tenant_id, stripe_customer_id, stripe_subscription_item_id, meter_key, updated_at)
                    VALUES (:tenant_id, :customer_id, :subscription_item_id, :meter_key, :updated_at)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      stripe_customer_id=EXCLUDED.stripe_customer_id,
                      stripe_subscription_item_id=EXCLUDED.stripe_subscription_item_id,
                      meter_key=EXCLUDED.meter_key,
                      updated_at=EXCLUDED.updated_at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "subscription_item_id": subscription_item_id,
                    "meter_key": meter_key,
                    "updated_at": _now(),
                },
            )
        db.commit()
    return {"ok": True, "tenant_id": tenant_id}


def onboard_pilot_tenant(*, tenant_id: str, company_name: str, contact_email: str, vertical: str | None = None) -> Dict[str, Any]:
    _ensure_billing_tables()
    with db_session() as db:
        d = _dialect(db)
        if d == "sqlite":
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO pilot_tenants (tenant_id, company_name, contact_email, vertical, status)
                    VALUES (:tenant_id, :company_name, :contact_email, :vertical, 'pilot')
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "company_name": company_name,
                    "contact_email": contact_email,
                    "vertical": vertical,
                },
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO pilot_tenants (tenant_id, company_name, contact_email, vertical, status)
                    VALUES (:tenant_id, :company_name, :contact_email, :vertical, 'pilot')
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      company_name=EXCLUDED.company_name,
                      contact_email=EXCLUDED.contact_email,
                      vertical=EXCLUDED.vertical,
                      status='pilot'
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "company_name": company_name,
                    "contact_email": contact_email,
                    "vertical": vertical,
                },
            )
        db.commit()
    return {"ok": True, "tenant_id": tenant_id, "status": "pilot"}


def _send_stripe_meter_event(*, subscription_item_id: str, quantity: float, ts_unix: int) -> str | None:
    if str(os.getenv("STRIPE_BILLING_ENABLED", "0")).lower() not in ("1", "true", "yes"):
        return None
    try:
        import stripe  # type: ignore

        stripe.api_key = str(os.getenv("STRIPE_API_KEY", "") or "")
        # Legacy usage records (works for metered subscription items).
        res = stripe.SubscriptionItem.create_usage_record(
            subscription_item_id,
            quantity=quantity,
            timestamp=ts_unix,
            action="increment",
        )
        return str((res or {}).get("id") or "")
    except Exception:
        return None


def record_meter_event(
    *,
    tenant_id: str,
    metric: str,
    quantity: float,
    source: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    _ensure_billing_tables()
    stripe_event_id = None
    now_unix = int(datetime.now(timezone.utc).timestamp())

    with db_session() as db:
        acct = db.execute(
            text(
                """
                SELECT stripe_subscription_item_id
                FROM tenant_billing_accounts
                WHERE tenant_id = :tenant_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).fetchone()
        sub_item = str(acct[0] or "") if acct else ""
        if sub_item:
            stripe_event_id = _send_stripe_meter_event(
                subscription_item_id=sub_item,
                quantity=float(quantity),
                ts_unix=now_unix,
            )

        event_id = f"meter-{uuid.uuid4().hex[:16]}"
        db.execute(
            text(
                """
                INSERT INTO billing_meter_events
                (id, tenant_id, metric, quantity, source, metadata_json, stripe_event_id, created_at)
                VALUES (:id, :tenant_id, :metric, :quantity, :source, :metadata_json, :stripe_event_id, :created_at)
                """
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "metric": metric,
                "quantity": float(quantity),
                "source": source,
                "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
                "stripe_event_id": stripe_event_id,
                "created_at": _now(),
            },
        )
        db.commit()
    return {"ok": True, "event_id": event_id, "stripe_event_id": stripe_event_id}


def usage_summary(*, tenant_id: str | None = None, days: int = 30) -> Dict[str, Any]:
    _ensure_billing_tables()
    days = max(1, min(int(days or 30), 365))
    with db_session() as db:
        d = _dialect(db)
        params: Dict[str, Any] = {}
        if d == "sqlite":
            params["window_expr"] = f"-{days} days"
            where = "WHERE datetime(created_at) >= datetime('now', :window_expr)"
        else:
            params["days"] = int(days)
            where = "WHERE created_at >= (NOW() - (:days * INTERVAL '1 day'))"
        if tenant_id:
            where += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        rows = db.execute(
            text(
                f"""
                SELECT tenant_id, metric, SUM(quantity) as qty, COUNT(*) as events
                FROM billing_meter_events
                {where}
                GROUP BY tenant_id, metric
                ORDER BY tenant_id, metric
                """
            ),
            params,
        ).fetchall()
    items = [
        {"tenant_id": r[0], "metric": r[1], "quantity": float(r[2] or 0.0), "events": int(r[3] or 0)}
        for r in (rows or [])
    ]
    return {"ok": True, "days": days, "items": items}


def list_billing_plans() -> Dict[str, Any]:
    return {
        "ok": True,
        "plans": [
            {"id": "starter", "name": "Starter", "monthly_usd": 199, "included_recommend_requests": 10000},
            {"id": "growth", "name": "Growth", "monthly_usd": 699, "included_recommend_requests": 100000},
            {"id": "enterprise", "name": "Enterprise", "monthly_usd": 2499, "included_recommend_requests": 1000000},
        ],
    }


def provision_tenant_core(
    *,
    tenant_id: str,
    plan_id: str,
    home_region: str,
    limits: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    _ensure_billing_tables()
    limits_json = json.dumps(limits or {}, ensure_ascii=False)
    with db_session() as db:
        d = _dialect(db)
        if d == "sqlite":
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO tenant_provisioning
                    (tenant_id, plan_id, home_region, status, limits_json, updated_at)
                    VALUES (:tenant_id, :plan_id, :home_region, 'provisioned', :limits_json, :updated_at)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "plan_id": plan_id,
                    "home_region": home_region,
                    "limits_json": limits_json,
                    "updated_at": _now(),
                },
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO tenant_provisioning
                    (tenant_id, plan_id, home_region, status, limits_json, updated_at)
                    VALUES (:tenant_id, :plan_id, :home_region, 'provisioned', :limits_json, :updated_at)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      plan_id=EXCLUDED.plan_id,
                      home_region=EXCLUDED.home_region,
                      status='provisioned',
                      limits_json=EXCLUDED.limits_json,
                      updated_at=EXCLUDED.updated_at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "plan_id": plan_id,
                    "home_region": home_region,
                    "limits_json": limits_json,
                    "updated_at": _now(),
                },
            )
        db.commit()
    return {"ok": True, "tenant_id": tenant_id, "plan_id": plan_id, "home_region": home_region, "status": "provisioned"}

