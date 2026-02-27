from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role_or_oidc
from src.app.erp.jobs import run_netsuite_delta_sync, enqueue_netsuite_outbound, run_netsuite_outbound_sync, _SnapshotConnector
from src.app.erp.sync import sync_inventory
from src.app.erp.provider_registry import load_provider


router = APIRouter(prefix="/api/v1/admin/inventory", tags=["admin-inventory"])


def _load_csv_connector(path: str | None = None):
    from src.app.erp.connectors.csv_inventory import CSVInventoryConnector

    return CSVInventoryConnector(path=path)

def _load_shopify_connector():
    from src.app.erp.connectors.shopify_inventory import ShopifyInventoryConnector

    return ShopifyInventoryConnector()


def _load_external_connector(connector_id: str):
    cid = str(connector_id or "").strip().lower()
    # Deep provider connectors (delta cursors + outbound maps).
    if cid in ("netsuite", "sap", "dynamics", "quickbooks", "coupa", "ariba", "salesforce", "hubspot"):
        from src.app.erp.provider_registry import load_provider

        return load_provider(cid)
    raise ValueError("unsupported connector")


def _json_load(raw: Any, default: Any):
    try:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        return json.loads(raw)
    except Exception:
        return default


@router.get("/connectors")
def connectors(role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    csv_path = os.getenv("CSV_INVENTORY_PATH") or ""
    c = _load_csv_connector(csv_path if csv_path else None)
    s = _load_shopify_connector()
    items = [{"id": "csv", "name": c.name(), "health": c.health()}, {"id": "shopify", "name": s.name(), "health": s.health()}]
    for cid in ("netsuite", "sap", "dynamics", "quickbooks", "coupa", "ariba", "salesforce", "hubspot"):
        try:
            ec = _load_external_connector(cid)
            items.append({"id": cid, "name": ec.name(), "health": ec.health()})
        except Exception as exc:
            items.append({"id": cid, "name": cid, "health": {"ok": False, "error": str(exc)}})
    return {"items": items}

@router.get("/connectors/summary")
def connectors_summary(
    limit_samples: int = 5,
    tenant_id: str | None = None,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Return per-connector health plus last sync run and sample snapshot rows."""
    lim = max(0, min(int(limit_samples or 5), 25))
    csv_path = os.getenv("CSV_INVENTORY_PATH") or ""
    connectors = [
        {"id": "csv", "connector": _load_csv_connector(csv_path if csv_path else None)},
        {"id": "shopify", "connector": _load_shopify_connector()},
    ]
    for cid in ("netsuite", "sap", "dynamics", "quickbooks", "coupa", "ariba", "salesforce", "hubspot"):
        try:
            connectors.append({"id": cid, "connector": _load_external_connector(cid)})
        except Exception:
            continue

    items = []
    for entry in connectors:
        cid = entry["id"]
        c = entry["connector"]
        health = {}
        try:
            health = c.health()
        except Exception as exc:
            health = {"ok": False, "error": str(exc)}

        last_run = None
        prev_run = None
        sample = []
        try:
            where = "WHERE source = :source"
            params: Dict[str, Any] = {"source": cid}
            if tenant_id:
                where += " AND tenant_id = :tenant_id"
                params["tenant_id"] = str(tenant_id)
            with db_session() as db:
                runs = db.execute(
                    text(
                        "SELECT id, tenant_id, source, status, started_at, finished_at, records_seen, records_applied, error "
                        "FROM inventory_sync_runs "
                        "WHERE source = :source "
                        "AND (:tenant_id IS NULL OR tenant_id = :tenant_id) "
                        "ORDER BY started_at DESC LIMIT 2"
                    ),
                    {"source": cid, "tenant_id": (str(tenant_id) if tenant_id else None)},
                ).fetchall()
                if runs:
                    r = runs[0]
                    last_run = {
                        "id": r[0],
                        "tenant_id": r[1],
                        "source": r[2],
                        "status": r[3],
                        "started_at": r[4],
                        "finished_at": r[5],
                        "records_seen": r[6],
                        "records_applied": r[7],
                        "error": r[8],
                    }
                if runs and len(runs) > 1:
                    r = runs[1]
                    prev_run = {
                        "id": r[0],
                        "tenant_id": r[1],
                        "source": r[2],
                        "status": r[3],
                        "started_at": r[4],
                        "finished_at": r[5],
                        "records_seen": r[6],
                        "records_applied": r[7],
                        "error": r[8],
                    }

                if lim > 0:
                    sample = db.execute(
                        text(
                            "SELECT sku, warehouse, stock, observed_at "
                            "FROM inventory_external_stock "
                            "WHERE source = :source "
                            "ORDER BY observed_at DESC LIMIT :lim"
                        ),
                        {"source": cid, "lim": lim},
                    ).fetchall()
        except Exception:
            last_run = None
            prev_run = None
            sample = []

        delta_applied = None
        try:
            if last_run and prev_run:
                delta_applied = (int(last_run.get("records_applied") or 0) - int(prev_run.get("records_applied") or 0))
            elif last_run:
                delta_applied = int(last_run.get("records_applied") or 0)
        except Exception:
            delta_applied = None

        items.append(
            {
                "id": cid,
                "name": getattr(c, "name", lambda: cid)(),
                "health": health,
                "last_run": last_run,
                "delta_applied": delta_applied,
                "sample": [{"sku": r[0], "warehouse": r[1], "stock": r[2], "observed_at": r[3]} for r in (sample or [])],
            }
        )

    return {"items": items, "tenant_id": tenant_id, "limit_samples": lim}


@router.get("/sync/runs")
def sync_runs(
    limit: int = 50,
    tenant_id: str | None = None,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 50), 500))
    rows = []
    try:
        with db_session() as db:
            if tenant_id:
                rows = db.execute(
                    text(
                        "SELECT id, tenant_id, source, status, started_at, finished_at, records_seen, records_applied, error "
                        "FROM inventory_sync_runs WHERE tenant_id = :tid ORDER BY started_at DESC LIMIT :lim"
                    ),
                    {"tid": str(tenant_id), "lim": lim},
                ).fetchall()
            else:
                rows = db.execute(
                    text(
                        "SELECT id, tenant_id, source, status, started_at, finished_at, records_seen, records_applied, error "
                        "FROM inventory_sync_runs ORDER BY started_at DESC LIMIT :lim"
                    ),
                    {"lim": lim},
                ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        items.append(
            {
                "id": r[0],
                "tenant_id": r[1],
                "source": r[2],
                "status": r[3],
                "started_at": r[4],
                "finished_at": r[5],
                "records_seen": r[6],
                "records_applied": r[7],
                "error": r[8],
            }
        )
    return {"items": items, "limit": lim, "tenant_id": tenant_id}


@router.post("/sync")
def sync(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    connector_id = str(body.get("connector") or "csv").strip().lower()
    tenant_id = body.get("tenant_id")
    dry_run = bool(body.get("dry_run", True))
    upsert_products = bool(body.get("upsert_products", False))
    csv_path = body.get("csv_path")

    if connector_id == "csv":
        c = _load_csv_connector(path=str(csv_path) if csv_path else None)
    elif connector_id == "shopify":
        c = _load_shopify_connector()
    elif connector_id in ("netsuite", "sap", "dynamics", "quickbooks", "coupa", "ariba", "salesforce", "hubspot"):
        c = _load_external_connector(connector_id)
    else:
        raise HTTPException(status_code=400, detail="unsupported connector")
    h = c.health()
    if not h.get("ok"):
        raise HTTPException(status_code=400, detail=f"connector unhealthy: {h.get('error')}")

    from src.app.erp.sync import sync_inventory
    from src.app.observability.metrics import record_inventory_sync

    out = sync_inventory(connector=c, tenant_id=str(tenant_id) if tenant_id is not None else None, dry_run=dry_run, upsert_products=upsert_products)
    try:
        record_inventory_sync(
            str(out.get("source") or connector_id),
            str(out.get("status") or "unknown"),
            records_seen=int(out.get("records_seen") or 0) if out.get("records_seen") is not None else None,
            records_applied=int(out.get("records_applied") or 0) if out.get("records_applied") is not None else None,
        )
    except Exception:
        pass
    return out


@router.post("/sync/netsuite/delta")
def sync_netsuite_delta(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = body.get("tenant_id")
    dry_run = bool(body.get("dry_run", True))
    upsert_products = bool(body.get("upsert_products", False))
    limit = int(body.get("limit", 2000) or 2000)
    return run_netsuite_delta_sync(
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        dry_run=dry_run,
        upsert_products=upsert_products,
        limit=limit,
    )


@router.post("/sync/netsuite/outbound/enqueue")
def enqueue_netsuite(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = body.get("tenant_id")
    entity_type = str(body.get("entity_type") or "").strip().lower()
    if entity_type not in {"customer", "sales_order", "order"}:
        raise HTTPException(status_code=400, detail="unsupported_entity_type")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    max_attempts = int(body.get("max_attempts", 3) or 3)
    return enqueue_netsuite_outbound(
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        entity_type=entity_type,
        payload=payload,
        max_attempts=max_attempts,
    )


@router.post("/sync/netsuite/outbound/run")
def run_netsuite_outbound(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = body.get("tenant_id")
    limit = int(body.get("limit", 100) or 100)
    return run_netsuite_outbound_sync(tenant_id=str(tenant_id) if tenant_id is not None else None, limit=limit)


@router.post("/sync/erp/delta")
def sync_erp_delta(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    provider = str(body.get("provider") or "").strip().lower()
    tenant_id = body.get("tenant_id")
    dry_run = bool(body.get("dry_run", True))
    upsert_products = bool(body.get("upsert_products", False))
    limit = int(body.get("limit", 2000) or 2000)
    if provider == "netsuite":
        return run_netsuite_delta_sync(
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            dry_run=dry_run,
            upsert_products=upsert_products,
            limit=limit,
        )
    c = load_provider(provider)
    prev_cursor = None
    next_cursor = None
    rows = []
    try:
        prev_cursor = getattr(c, "get_cursor")(tenant_id=str(tenant_id) if tenant_id is not None else None, entity_type="inventory")
        rows, next_cursor = getattr(c, "fetch_inventory_delta")(cursor=prev_cursor, tenant_id=str(tenant_id) if tenant_id is not None else None, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"delta_fetch_failed:{exc}")
    from src.app.erp.jobs import _SnapshotConnector  # local helper
    out = sync_inventory(
        connector=_SnapshotConnector(rows=rows, name=provider),
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        dry_run=dry_run,
        upsert_products=upsert_products,
    )
    if not dry_run and not out.get("error") and next_cursor is not None and prev_cursor != next_cursor:
        try:
            getattr(c, "set_cursor")(tenant_id=str(tenant_id) if tenant_id is not None else None, entity_type="inventory", cursor_value=next_cursor)
        except Exception:
            pass
    out["cursor"] = {"previous": prev_cursor, "next": (next_cursor if not dry_run else prev_cursor)}
    out["delta_count"] = len(rows or [])
    return out


@router.post("/sync/erp/outbound/enqueue")
def enqueue_erp_outbound(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    provider = str(body.get("provider") or "").strip().lower()
    tenant_id = body.get("tenant_id")
    entity_type = str(body.get("entity_type") or "").strip().lower()
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    max_attempts = int(body.get("max_attempts", 3) or 3)
    if provider == "netsuite":
        return enqueue_netsuite_outbound(
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            entity_type=entity_type,
            payload=payload,
            max_attempts=max_attempts,
        )
    from src.app.erp.jobs_generic import enqueue_outbound
    return enqueue_outbound(provider=provider, tenant_id=str(tenant_id) if tenant_id is not None else None, entity_type=entity_type, payload=payload, max_attempts=max_attempts)


@router.post("/sync/erp/outbound/run")
def run_erp_outbound(
    body: Dict[str, Any],
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    provider = str(body.get("provider") or "").strip().lower()
    tenant_id = body.get("tenant_id")
    limit = int(body.get("limit", 100) or 100)
    if provider == "netsuite":
        return run_netsuite_outbound_sync(tenant_id=str(tenant_id) if tenant_id is not None else None, limit=limit)
    from src.app.erp.jobs_generic import run_outbound
    return run_outbound(provider=provider, tenant_id=str(tenant_id) if tenant_id is not None else None, limit=limit)


@router.get("/external_stock/recent")
def external_stock_recent(
    limit: int = 200,
    tenant_id: str | None = None,
    source: str | None = None,
    sku: str | None = None,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 200), 1000))
    params: Dict[str, Any] = {
        "lim": lim,
        "tenant_id": (str(tenant_id) if tenant_id else None),
        "source": (str(source) if source else None),
        "sku": (str(sku) if sku else None),
    }

    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    "SELECT id, tenant_id, source, sku, warehouse, stock, observed_at, raw_json "
                    "FROM inventory_external_stock "
                    "WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id) "
                    "AND (:source IS NULL OR source = :source) "
                    "AND (:sku IS NULL OR sku = :sku) "
                    "ORDER BY observed_at DESC LIMIT :lim"
                ),
                params,
            ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        raw = r[7]
        try:
            raw = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            raw = raw
        items.append(
            {
                "id": r[0],
                "tenant_id": r[1],
                "source": r[2],
                "sku": r[3],
                "warehouse": r[4],
                "stock": r[5],
                "observed_at": r[6],
                "raw": raw,
            }
        )
    return {"items": items, "limit": lim}


@router.get("/analysis/summary")
def analysis_summary(
    max_transfers: int = 10,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Operational snapshot for inventory automation readiness and transfer balancing."""
    try:
        from src.app.data_readiness.report import compute_inventory_readiness
        from src.app.services.inventory_agent import InventoryAgent

        readiness = compute_inventory_readiness()
        agent = InventoryAgent()
        transfers = agent.suggest_rebalancing_transfers(max_suggestions=max(1, min(int(max_transfers or 10), 50)))
        return {
            "readiness": {
                "score": readiness.score,
                "level": readiness.level,
                "summary": readiness.summary,
                "checks": readiness.checks,
            },
            "transfer_suggestions": transfers,
            "transfer_count": len(transfers),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}")


@router.get("/ops/readiness")
def ops_readiness(
    hours: int = 24 * 7,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Operational readiness metrics for inventory autonomy."""
    window_h = max(1, min(int(hours or 24), 24 * 365))
    metrics: Dict[str, Any] = {
        "reorder_approvals_required": 0,
        "reorder_approvals_completed": 0,
        "approval_completion_rate": 0.0,
        "po_created_count": 0,
        "po_creation_rate_per_day": 0.0,
        "forecast_mape_avg": 0.0,
        "forecast_mape_count": 0,
        "transfer_suggestions_count": 0,
        "supplier_score_audits_count": 0,
        "decision_trace_write_failures": 0,
    }
    try:
        with db_session() as db:
            try:
                rows = db.execute(
                    text(
                        """
                        SELECT approval_required, execution_status
                        FROM decision_logs
                        WHERE agent_name = 'inventory_agent'
                          AND datetime(valid_from) >= datetime('now', :window_expr)
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchall()
            except Exception:
                rows = []
            for r in rows or []:
                required = bool(r[0])
                status = str(r[1] or "").lower()
                if required:
                    metrics["reorder_approvals_required"] += 1
                if required and status in ("executed", "approved", "completed", "po_created"):
                    metrics["reorder_approvals_completed"] += 1

            try:
                po_rows = db.execute(
                    text(
                        """
                        SELECT COUNT(1)
                        FROM purchase_orders
                        WHERE datetime(created_at) >= datetime('now', :window_expr)
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchone()
                metrics["po_created_count"] = int((po_rows[0] if po_rows else 0) or 0)
            except Exception:
                metrics["po_created_count"] = 0

            try:
                mape_rows = db.execute(
                    text(
                        """
                        SELECT retrieved_context
                        FROM decision_logs
                        WHERE agent_name = 'inventory_agent'
                          AND datetime(valid_from) >= datetime('now', :window_expr)
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchall()
            except Exception:
                mape_rows = []
            mape_vals = []
            for r in mape_rows or []:
                rc = _json_load(r[0], {})
                if isinstance(rc, dict):
                    fc = rc.get("forecast") if isinstance(rc.get("forecast"), dict) else {}
                    try:
                        mv = fc.get("mape")
                        if mv is not None:
                            mape_vals.append(float(mv))
                    except Exception:
                        pass
            metrics["forecast_mape_count"] = len(mape_vals)
            metrics["forecast_mape_avg"] = round(sum(mape_vals) / len(mape_vals), 4) if mape_vals else 0.0

            try:
                t_rows = db.execute(
                    text(
                        """
                        SELECT COUNT(1)
                        FROM decision_trace_events
                        WHERE event_type = 'inventory_rebalance_suggestion'
                          AND datetime(created_at) >= datetime('now', :window_expr)
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchone()
                metrics["transfer_suggestions_count"] = int((t_rows[0] if t_rows else 0) or 0)
            except Exception:
                metrics["transfer_suggestions_count"] = 0

            try:
                s_rows = db.execute(
                    text(
                        """
                        SELECT COUNT(1)
                        FROM supplier_score_audits
                        WHERE datetime(created_at) >= datetime('now', :window_expr)
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchone()
                metrics["supplier_score_audits_count"] = int((s_rows[0] if s_rows else 0) or 0)
            except Exception:
                metrics["supplier_score_audits_count"] = 0

            try:
                f_rows = db.execute(
                    text(
                        """
                        SELECT COUNT(1)
                        FROM decision_logs
                        WHERE agent_name = 'inventory_agent'
                          AND datetime(valid_from) >= datetime('now', :window_expr)
                          AND (id IS NULL OR TRIM(COALESCE(id, '')) = '')
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchone()
                metrics["decision_trace_write_failures"] = int((f_rows[0] if f_rows else 0) or 0)
            except Exception:
                metrics["decision_trace_write_failures"] = 0
    except Exception:
        pass

    req = int(metrics["reorder_approvals_required"] or 0)
    done = int(metrics["reorder_approvals_completed"] or 0)
    metrics["approval_completion_rate"] = round(float(done) / float(max(1, req)), 4)
    metrics["po_creation_rate_per_day"] = round(float(metrics["po_created_count"] or 0) * 24.0 / float(window_h), 4)

    alerts = {
        "approval_backlog_high": req > 0 and (done / float(max(1, req))) < 0.6,
        "po_creation_stalled": int(metrics["po_created_count"] or 0) == 0 and req > 0,
        "forecast_quality_low": float(metrics["forecast_mape_avg"] or 0.0) > 0.35,
        "transfer_automation_idle": int(metrics["transfer_suggestions_count"] or 0) == 0,
        "supplier_scoring_missing": int(metrics["supplier_score_audits_count"] or 0) == 0,
        "decision_trace_write_failures": int(metrics["decision_trace_write_failures"] or 0) > 0,
    }
    return {"window_hours": window_h, "metrics": metrics, "alerts": alerts}


@router.get("/supplier-risk")
def supplier_risk_summary(
    hours: int = 24 * 7,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    window_h = max(1, min(int(hours or 24), 24 * 90))
    out: Dict[str, Any] = {
        "window_hours": window_h,
        "quarantined_updates": 0,
        "avg_risk_score": 0.0,
        "source_risk": [],
        "recent_quarantines": [],
    }
    scores: list[float] = []
    try:
        with db_session() as db:
            try:
                q_rows = db.execute(
                    text(
                        """
                        SELECT id, source, sku, warehouse, stock, risk_score, reasons_json, created_at
                        FROM supplier_feed_quarantine
                        WHERE datetime(created_at) >= datetime('now', :window_expr)
                        ORDER BY created_at DESC
                        LIMIT 100
                        """
                    ),
                    {"window_expr": f"-{window_h} hours"},
                ).fetchall()
            except Exception:
                q_rows = []
            out["quarantined_updates"] = len(q_rows or [])
            src_acc: Dict[str, Dict[str, Any]] = {}
            for r in q_rows or []:
                sid = str(r[1] or "unknown")
                risk = float(r[5] or 0.0)
                scores.append(risk)
                bucket = src_acc.setdefault(sid, {"source": sid, "quarantined": 0, "risk_sum": 0.0, "risk_avg": 0.0})
                bucket["quarantined"] = int(bucket["quarantined"]) + 1
                bucket["risk_sum"] = float(bucket["risk_sum"]) + risk
                if len(out["recent_quarantines"]) < 20:
                    try:
                        reasons = json.loads(r[6]) if isinstance(r[6], str) and r[6] else []
                    except Exception:
                        reasons = []
                    out["recent_quarantines"].append(
                        {
                            "id": r[0],
                            "source": sid,
                            "sku": r[2],
                            "warehouse": r[3],
                            "stock": r[4],
                            "risk_score": round(risk, 4),
                            "reasons": reasons,
                            "created_at": r[7],
                        }
                    )
            source_risk = []
            for _, v in src_acc.items():
                q = max(1, int(v["quarantined"]))
                source_risk.append(
                    {
                        "source": v["source"],
                        "quarantined": int(v["quarantined"]),
                        "risk_avg": round(float(v["risk_sum"]) / float(q), 4),
                        "trust_score": round(max(0.0, 1.0 - (float(v["risk_sum"]) / float(q))), 4),
                    }
                )
            out["source_risk"] = sorted(source_risk, key=lambda x: (x["quarantined"], x["risk_avg"]), reverse=True)
    except Exception:
        pass
    out["avg_risk_score"] = round(sum(scores) / len(scores), 4) if scores else 0.0
    return out


@router.get("/drift/check")
def inventory_drift_check(
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    out = {
        "missing_inventory_products": 0,
        "orphan_inventory_rows": 0,
        "unknown_order_line_skus": 0,
        "negative_stock_rows": 0,
        "status": "ok",
    }
    try:
        with db_session() as db:
            try:
                out["missing_inventory_products"] = int(
                    db.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM products p
                            LEFT JOIN inventory i ON i.product_id = p.id
                            WHERE i.id IS NULL AND COALESCE(p.active, 1) = 1
                            """
                        )
                    ).scalar()
                    or 0
                )
            except Exception:
                pass
            try:
                out["orphan_inventory_rows"] = int(
                    db.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM inventory i
                            LEFT JOIN products p ON p.id = i.product_id
                            WHERE p.id IS NULL
                            """
                        )
                    ).scalar()
                    or 0
                )
            except Exception:
                pass
            try:
                out["negative_stock_rows"] = int(
                    db.execute(text("SELECT COUNT(*) FROM inventory WHERE stock < 0")).scalar() or 0
                )
            except Exception:
                pass
            try:
                rows = db.execute(text("SELECT line_items FROM draft_orders ORDER BY created_at DESC LIMIT 800")).fetchall()
                unknown = 0
                for r in rows or []:
                    raw = r[0] if isinstance(r, (list, tuple)) else r[0]
                    items = _json_load(raw, [])
                    if not isinstance(items, list):
                        continue
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        sku = str(it.get("sku") or "").strip()
                        if not sku:
                            continue
                        exists = db.execute(text("SELECT 1 FROM products WHERE sku = :sku LIMIT 1"), {"sku": sku}).fetchone()
                        if not exists:
                            unknown += 1
                out["unknown_order_line_skus"] = int(unknown)
            except Exception:
                pass
    except Exception:
        pass
    if any(int(out.get(k) or 0) > 0 for k in ("missing_inventory_products", "orphan_inventory_rows", "unknown_order_line_skus", "negative_stock_rows")):
        out["status"] = "attention"
    return out
