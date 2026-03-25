"""Catalog and FAQ indexing script.

Usage:
    python scripts/index_catalog.py [--faq] [--catalog] [--batch-size N]

Indexes product catalog and/or FAQ entries into pgvector for semantic search.
Designed to be run as a one-shot CLI or called from a Celery task.

Environment:
    DATABASE_URL  — postgres connection string (required)
    EMBEDDING_PROVIDER — 'openai' | 'ollama' | 'local' (default: local)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any, Dict, Iterable, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("index_catalog")

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _fetch_products(batch_size: int, *, delta_only: bool = False) -> Iterable[Dict[str, Any]]:
    from src.app.models.db import db_session
    from sqlalchemy import text

    offset = 0
    while True:
        with db_session() as db:
            try:
                sql = (
                    "SELECT p.id, p.sku, p.name, p.brand, p.price_cents, p.specs "
                    "FROM products p "
                    + (
                        "LEFT JOIN product_embeddings pe ON pe.product_id = CAST(p.id AS TEXT) "
                        "WHERE pe.product_id IS NULL OR pe.updated_at IS NULL "
                        "OR COALESCE(p.updated_at, p.created_at) > pe.updated_at "
                        if delta_only
                        else ""
                    )
                    + " ORDER BY p.sku LIMIT :lim OFFSET :off"
                )
                rows = db.execute(text(sql), {"lim": batch_size, "off": offset}).fetchall()
            except Exception as exc:
                if delta_only:
                    try:
                        rows = db.execute(
                            text(
                                "SELECT p.id, p.sku, p.name, p.brand, p.price_cents, p.specs "
                                "FROM products p ORDER BY p.sku LIMIT :lim OFFSET :off"
                            ),
                            {"lim": batch_size, "off": offset},
                        ).fetchall()
                    except Exception as inner_exc:
                        log.error("Failed to fetch products at offset %d: %s", offset, inner_exc)
                        break
                else:
                    log.error("Failed to fetch products at offset %d: %s", offset, exc)
                    break
        if not rows:
            break
        for r in rows:
            specs: dict = {}
            if r[5]:
                try:
                    specs = json.loads(r[5]) if isinstance(r[5], str) else r[5]
                except Exception:
                    pass
            spec_text = " ".join(f"{k}:{v}" for k, v in (specs or {}).items() if k and v)
            text_body = " ".join(filter(None, [str(r[2] or ""), str(r[3] or ""), spec_text]))
            yield {
                "product_id": str(r[0] or ""),
                "sku": str(r[1] or ""),
                "text": text_body,
                "payload": {
                    "sku": str(r[1] or ""),
                    "name": str(r[2] or ""),
                    "brand": str(r[3] or ""),
                    "price_cents": int(r[4] or 0),
                    "type": "product",
                },
            }
        offset += batch_size
        log.info("Fetched products offset=%d batch=%d", offset, batch_size)
        if len(rows) < batch_size:
            break


def _fetch_faq_items() -> Iterable[Dict[str, Any]]:
    from src.app.services.faq_bank import FAQ_BANK

    for i, item in enumerate(FAQ_BANK or []):
        q = str(item.get("q") or "")
        a = str(item.get("a") or "")
        tags = " ".join(str(t) for t in (item.get("tags") or []))
        text_body = " ".join(filter(None, [q, tags]))
        yield {
            "id": f"faq:{i}",
            "text": text_body,
            "payload": {
                "q": q,
                "a": a,
                "tags": item.get("tags") or [],
                "type": "faq",
            },
        }


def run_index(
    *,
    index_catalog: bool = True,
    index_faq: bool = True,
    batch_size: int = 500,
    delta_only: bool = False,
) -> Dict[str, Any]:
    from src.app.services.embedding_pipeline import EmbeddingPipeline
    from src.app.services.vector_store import PgVectorStore, ensure_vector_table
    from src.app.models.db import db_session
    from src.app.repositories.embeddings import upsert_product_embeddings

    results: Dict[str, Any] = {}

    if index_catalog:
        pipeline = EmbeddingPipeline()
        t0 = time.time()
        total = 0
        errors = 0
        batch: List[Dict[str, Any]] = []
        for doc in _fetch_products(batch_size, delta_only=delta_only):
            batch.append(doc)
            if len(batch) >= batch_size:
                items = []
                for row in batch:
                    text_body = str(row.get("text") or "").strip()
                    product_id = str(row.get("product_id") or "").strip()
                    if not product_id or not text_body:
                        continue
                    items.append({"product_id": product_id, "embedding": pipeline.embed_text(text_body)})
                with db_session() as db:
                    r = upsert_product_embeddings(db, items)
                total += int(r.get("indexed") or 0)
                errors += int(r.get("errors") or 0)
                log.info("Catalog indexed %d (+%d errors)", total, errors)
                batch = []
        if batch:
            items = []
            for row in batch:
                text_body = str(row.get("text") or "").strip()
                product_id = str(row.get("product_id") or "").strip()
                if not product_id or not text_body:
                    continue
                items.append({"product_id": product_id, "embedding": pipeline.embed_text(text_body)})
            with db_session() as db:
                r = upsert_product_embeddings(db, items)
            total += int(r.get("indexed") or 0)
            errors += int(r.get("errors") or 0)
        elapsed = round(time.time() - t0, 2)
        results["catalog"] = {"indexed": total, "errors": errors, "elapsed_s": elapsed, "delta_only": bool(delta_only)}
        log.info("Catalog indexing done: %d indexed, %d errors in %.1fs", total, errors, elapsed)

    if index_faq:
        ensure_vector_table("faq_embeddings")
        faq_store = PgVectorStore("faq_embeddings")
        faq_pipeline = EmbeddingPipeline(store=faq_store)
        t0 = time.time()
        faq_docs = list(_fetch_faq_items())
        r = faq_pipeline.index_documents(faq_docs)
        elapsed = round(time.time() - t0, 2)
        results["faq"] = {
            "indexed": r.get("indexed") or 0,
            "errors": r.get("errors") or 0,
            "elapsed_s": elapsed,
        }
        log.info(
            "FAQ indexing done: %d indexed, %d errors in %.1fs",
            results["faq"]["indexed"],
            results["faq"]["errors"],
            elapsed,
        )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index product catalog and FAQ into pgvector")
    parser.add_argument("--catalog", action="store_true", default=False, help="Index product catalog (default: both)")
    parser.add_argument("--faq", action="store_true", default=False, help="Index FAQ entries (default: both)")
    parser.add_argument("--batch-size", type=int, default=500, help="Products per embedding batch")
    parser.add_argument("--delta-only", action="store_true", default=False, help="Only index products missing/staler than embeddings")
    args = parser.parse_args()

    do_catalog = args.catalog or (not args.catalog and not args.faq)
    do_faq = args.faq or (not args.catalog and not args.faq)

    result = run_index(index_catalog=do_catalog, index_faq=do_faq, batch_size=args.batch_size, delta_only=args.delta_only)
    print(json.dumps(result, indent=2))
    has_errors = any((v.get("errors") or 0) > 0 for v in result.values() if isinstance(v, dict))
    sys.exit(1 if has_errors else 0)
