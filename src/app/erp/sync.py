from __future__ import annotations

import json
import os
import uuid
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.models.db import db_session
from src.app.services.embeddings import VectorStoreEmbeddings
from src.app.services.catalog_profile import invalidate_catalog_profile_cache
from src.app.repositories.embeddings import upsert_product_embedding


def _now_iso() -> str:
    return __import__("datetime").datetime.utcnow().isoformat()


def _ensure_supplier_risk_tables(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS supplier_feed_quarantine (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    source TEXT,
                    sku TEXT,
                    warehouse TEXT,
                    stock INTEGER,
                    risk_score REAL,
                    reasons_json TEXT,
                    raw_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    except Exception:
        pass


def _score_supplier_record(db, *, source: str, sku: str, incoming_stock: int, raw_payload: Dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    prev_stock = None
    try:
        row = db.execute(
            text(
                """
                SELECT stock
                FROM inventory_external_stock
                WHERE source = :source AND sku = :sku
                ORDER BY observed_at DESC
                LIMIT 1
                """
            ),
            {"source": source, "sku": sku},
        ).fetchone()
        if row:
            prev_stock = int(row[0] or 0)
    except Exception:
        prev_stock = None

    if incoming_stock < 0:
        score += 1.0
        reasons.append("negative_stock")

    if prev_stock is not None:
        delta = abs(int(incoming_stock) - int(prev_stock))
        ratio = float(delta) / float(max(1, abs(int(prev_stock))))
        if delta >= int(os.getenv("SUPPLIER_SPIKE_MIN_ABS", "20") or 20) and ratio >= float(
            os.getenv("SUPPLIER_SPIKE_RATIO_THRESHOLD", "2.0") or 2.0
        ):
            score += min(1.0, 0.35 + ratio * 0.2)
            reasons.append("stock_spike_delta")

    try:
        price_cents = raw_payload.get("price_cents")
        if price_cents is not None:
            rowp = db.execute(text("SELECT price_cents FROM products WHERE sku = :sku"), {"sku": sku}).fetchone()
            if rowp and rowp[0] is not None:
                p0 = int(rowp[0] or 0)
                p1 = int(price_cents or 0)
                if p0 > 0:
                    pd = abs(p1 - p0) / float(p0)
                    if pd >= float(os.getenv("SUPPLIER_PRICE_SPIKE_RATIO_THRESHOLD", "0.6") or 0.6):
                        score += min(1.0, 0.25 + pd * 0.4)
                        reasons.append("price_spike_delta")
    except Exception:
        pass
    return min(1.0, score), reasons


def sync_inventory(
    *,
    connector: InventoryConnector,
    tenant_id: str | None = None,
    dry_run: bool = True,
    upsert_products: bool = False,
) -> Dict[str, Any]:
    """Sync external inventory snapshot into canonical tables.

    Phase 5 MVP:
      - record a sync run in `inventory_sync_runs`
      - store a point-in-time snapshot in `inventory_external_stock`
      - optionally upsert into the app's `products` and `inventory` tables (off by default)
    """
    run_id = str(uuid.uuid4())
    started = _now_iso()
    source = getattr(connector, "name", lambda: "unknown")()

    recs = connector.fetch_inventory(tenant_id=tenant_id) or []
    seen = len(recs)
    applied = 0
    quarantined = 0
    supplier_risk_samples: list[float] = []
    err = None

    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO inventory_sync_runs (id, tenant_id, source, status, started_at, records_seen, records_applied)
                VALUES (:id, :tenant_id, :source, :status, :started_at, :seen, 0)
                """
            ),
            {"id": run_id, "tenant_id": tenant_id, "source": source, "status": "started", "started_at": started, "seen": seen},
        )
        db.commit()

    try:
        if not dry_run:
            with db_session() as db:
                _ensure_supplier_risk_tables(db)
                dialect = ""
                try:
                    bind = getattr(db, "get_bind", lambda: None)()
                    dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
                except Exception:
                    dialect = ""
                for r in recs:
                    payload = {"sku": r.sku, "warehouse": r.warehouse, "stock": r.stock, "updated_at": r.updated_at, "source": r.source}
                    risk_score, risk_reasons = _score_supplier_record(
                        db, source=source, sku=str(r.sku), incoming_stock=int(r.stock or 0), raw_payload=payload
                    )
                    supplier_risk_samples.append(float(risk_score))
                    quarantine_threshold = float(os.getenv("SUPPLIER_QUARANTINE_RISK_THRESHOLD", "0.7") or 0.7)
                    is_quarantined = bool(risk_score >= quarantine_threshold and len(risk_reasons) > 0)
                    if is_quarantined:
                        try:
                            db.execute(
                                text(
                                    """
                                    INSERT INTO supplier_feed_quarantine (id, tenant_id, source, sku, warehouse, stock, risk_score, reasons_json, raw_json, created_at)
                                    VALUES (:id, :tenant_id, :source, :sku, :warehouse, :stock, :risk_score, :reasons_json, :raw_json, :created_at)
                                    """
                                ),
                                {
                                    "id": str(uuid.uuid4()),
                                    "tenant_id": tenant_id,
                                    "source": source,
                                    "sku": r.sku,
                                    "warehouse": r.warehouse,
                                    "stock": int(r.stock or 0),
                                    "risk_score": float(risk_score),
                                    "reasons_json": json.dumps(risk_reasons, ensure_ascii=False),
                                    "raw_json": json.dumps(payload, ensure_ascii=False),
                                    "created_at": _now_iso(),
                                },
                            )
                            quarantined += 1
                        except Exception:
                            pass
                    obs = r.updated_at or started
                    # Deterministic id gives basic idempotency when a connector provides stable `updated_at`.
                    # (For CSV, include an updated_at column in the file for best results.)
                    hid = hashlib.sha256(f"{tenant_id or 'global'}|{source}|{r.sku}|{r.warehouse}|{obs}".encode("utf-8")).hexdigest()
                    params = {
                        "id": hid,
                        "tenant_id": tenant_id,
                        "source": source,
                        "sku": r.sku,
                        "warehouse": r.warehouse,
                        "stock": int(r.stock or 0),
                        "obs": obs,
                        "raw": json.dumps(payload, ensure_ascii=False),
                    }
                    try:
                        if dialect == "sqlite":
                            db.execute(
                                text(
                                    """
                                    INSERT OR IGNORE INTO inventory_external_stock (id, tenant_id, source, sku, warehouse, stock, observed_at, raw_json)
                                    VALUES (:id, :tenant_id, :source, :sku, :warehouse, :stock, :obs, :raw)
                                    """
                                ),
                                params,
                            )
                            # sqlite rowcount is unreliable; treat as applied for MVP.
                            applied += 1
                        elif dialect == "postgresql":
                            db.execute(
                                text(
                                    """
                                    INSERT INTO inventory_external_stock (id, tenant_id, source, sku, warehouse, stock, observed_at, raw_json)
                                    VALUES (:id, :tenant_id, :source, :sku, :warehouse, :stock, :obs, :raw)
                                    ON CONFLICT (id) DO NOTHING
                                    """
                                ),
                                params,
                            )
                            applied += 1
                        else:
                            db.execute(
                                text(
                                    """
                                    INSERT INTO inventory_external_stock (id, tenant_id, source, sku, warehouse, stock, observed_at, raw_json)
                                    VALUES (:id, :tenant_id, :source, :sku, :warehouse, :stock, :obs, :raw)
                                    """
                                ),
                                params,
                            )
                            applied += 1
                    except Exception:
                        # Duplicate or DB error; continue best-effort.
                        continue

                    if upsert_products and not is_quarantined:
                        # Race-safe product upsert: use INSERT … ON CONFLICT DO NOTHING so
                        # concurrent sync workers do not race to insert the same SKU.
                        pid = str(uuid.uuid4())
                        try:
                            dialect = str(getattr(getattr(db.bind, "dialect", None), "name", "")).lower()
                        except Exception:
                            dialect = ""
                        if "postgres" in dialect:
                            db.execute(
                                text(
                                    "INSERT INTO products (id, sku, name, active, updated_at) "
                                    "VALUES (:id, :sku, :name, 1, :ts) "
                                    "ON CONFLICT (sku) DO NOTHING"
                                ),
                                {"id": pid, "sku": r.sku, "name": r.sku, "ts": _now_iso()},
                            )
                            # Re-fetch the actual id (might be a pre-existing row)
                            row = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": r.sku}).fetchone()
                            if row:
                                pid = row[0]
                        else:
                            # SQLite: INSERT OR IGNORE then fetch
                            db.execute(
                                text(
                                    "INSERT OR IGNORE INTO products (id, sku, name, active, updated_at) "
                                    "VALUES (:id, :sku, :name, 1, :ts)"
                                ),
                                {"id": pid, "sku": r.sku, "name": r.sku, "ts": _now_iso()},
                            )
                            row = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": r.sku}).fetchone()
                            if row:
                                pid = row[0]
                        # Upsert inventory row for product/warehouse — dialect-aware
                        inv_id = str(uuid.uuid4())
                        try:
                            if "postgres" in dialect:
                                db.execute(
                                    text(
                                        "INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) "
                                        "VALUES (:id, :pid, :stock, :wh, :ts) "
                                        "ON CONFLICT (product_id, warehouse) DO UPDATE "
                                        "SET stock = EXCLUDED.stock, updated_at = EXCLUDED.updated_at"
                                    ),
                                    {"id": inv_id, "pid": pid, "stock": int(r.stock or 0), "wh": r.warehouse, "ts": _now_iso()},
                                )
                            else:
                                db.execute(
                                    text(
                                        "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse, updated_at) "
                                        "VALUES (:id, :pid, :stock, :wh, :ts)"
                                    ),
                                    {"id": inv_id, "pid": pid, "stock": int(r.stock or 0), "wh": r.warehouse, "ts": _now_iso()},
                                )
                        except Exception:
                            db.execute(
                                text(
                                    "UPDATE inventory SET stock = :stock, updated_at = :ts WHERE product_id = :pid AND warehouse = :wh"
                                ),
                                {"pid": pid, "wh": r.warehouse, "stock": int(r.stock or 0), "ts": _now_iso()},
                            )
                        # Best-effort: upsert product embedding (name/specs unknown here, use sku)
                        try:
                            provider = (os.getenv("EMBEDDINGS_PROVIDER") or "bow").strip().lower()
                        except Exception:
                            provider = "bow"
                        if provider in ("openai", "vector", "pgvector"):
                            try:
                                emb_svc = VectorStoreEmbeddings()
                                # Minimal text using SKU; richer text will be indexed elsewhere when product details are available
                                vec = emb_svc.embed_text_vector(r.sku or "")
                                upsert_product_embedding(db, pid, vec)
                            except Exception:
                                pass
                db.commit()
                if upsert_products and applied > 0:
                    invalidate_catalog_profile_cache(tenant_id=tenant_id)
    except Exception as exc:
        err = str(exc)

    finished = _now_iso()
    with db_session() as db:
        db.execute(
            text(
                "UPDATE inventory_sync_runs SET status=:status, finished_at=:fin, records_applied=:applied, error=:err WHERE id=:id"
            ),
            {
                "id": run_id,
                "status": "failed" if err else ("dry_run" if dry_run else "completed"),
                "fin": finished,
                "applied": applied,
                "err": err,
            },
        )
        db.commit()

    return {
        "id": run_id,
        "source": source,
        "status": "failed" if err else ("dry_run" if dry_run else "completed"),
        "records_seen": seen,
        "records_applied": applied,
        "records_quarantined": quarantined,
        "supplier_risk_avg": (round(sum(supplier_risk_samples) / len(supplier_risk_samples), 4) if supplier_risk_samples else 0.0),
        "error": err,
    }
