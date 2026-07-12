"""M1.2 shadow worker: drains the queue, runs V2, diffs against V1-from-trace, dead-letters
poison. Uses a fake redis + a grounded sqlite so V2 actually produces a real decision."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.workers import recommendation_shadow_worker as W


class _Redis:
    """Minimal list-backed fake with brpop/lpush semantics."""
    def __init__(self): self.q = {}
    def lpush(self, k, v): self.q.setdefault(k, []).insert(0, v)
    def brpop(self, k, timeout=0):
        lst = self.q.get(k) or []
        return (k, lst.pop()) if lst else None


def _grounded_db():
    s = sessionmaker(bind=create_engine("sqlite://", connect_args={"check_same_thread": False}))()
    s.execute(text("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE, name TEXT, "
                   "price_cents INT, currency TEXT DEFAULT 'USD', image_url TEXT, specs TEXT, "
                   "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, "
                   "active INTEGER DEFAULT 1, updated_at TEXT)"))
    s.execute(text("INSERT INTO products (id,sku,name,price_cents,specs) VALUES "
                   "('p1','LAP-1','Dell Laptop',120000,:specs)"),
              {"specs": json.dumps({"ram_gb": 16})})
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(s, node_handle="el-6-6")
    upsert_classification(s, sku="LAP-1", node_handle="el-6-6", source="test", status="approved")
    # a V1 trace to diff against
    s.execute(text("CREATE TABLE decision_trace_events (id INTEGER PRIMARY KEY, trace_id TEXT, "
                   "event_type TEXT, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text("INSERT INTO decision_trace_events (trace_id,event_type,payload) VALUES "
                   "('tr-1','recommendation_result', :p)"),
              {"p": json.dumps({"products_summary": [{"sku": "LAP-1", "name": "Dell Laptop"}]})})
    s.commit()
    return s


def test_worker_drains_runs_and_diffs():
    db = _grounded_db()
    r = _Redis()
    r.lpush(W.QUEUE_KEY, json.dumps({"query": "laptop", "uid": "u", "tenant_id": "default",
                                     "trace_id": "tr-1"}))
    stats = W.run(r, lambda: db, once=True, max_jobs=1)
    assert stats["processed"] == 1 and stats["dead_lettered"] == 0
    # a job whose trace exists is diffed against V1
    assert stats["diffed"] == 1


def test_worker_intrinsic_only_when_no_trace():
    db = _grounded_db()
    r = _Redis()
    r.lpush(W.QUEUE_KEY, json.dumps({"query": "laptop", "uid": "u", "tenant_id": "default",
                                     "trace_id": "no-such-trace"}))
    stats = W.run(r, lambda: db, once=True, max_jobs=1)
    assert stats["processed"] == 1 and stats["diffed"] == 0   # no V1 → intrinsic-only, still processed


def test_poison_job_is_dead_lettered():
    r = _Redis()
    r.lpush(W.QUEUE_KEY, "{not valid json")
    stats = W.run(r, lambda: None, once=True, max_jobs=1)
    assert stats["dead_lettered"] == 1 and len(r.q.get(W.DEADLETTER_KEY) or []) == 1


def test_db_error_retries_then_dead_letters():
    r = _Redis()
    r.lpush(W.QUEUE_KEY, json.dumps({"query": "x", "uid": "u", "trace_id": "t"}))
    def boom():
        raise RuntimeError("db down")
    stats = W.run(r, boom, once=True, max_jobs=1)
    assert stats["errors"] == 1 and stats["dead_lettered"] == 1  # retried _MAX_RETRIES then DLQ


def test_v1_products_from_trace():
    db = _grounded_db()
    prods = W._v1_products_from_trace(db, "tr-1")
    assert prods == [{"sku": "LAP-1", "name": "Dell Laptop"}]
    assert W._v1_products_from_trace(db, "missing") is None


# ── C0 resolve-only cart shadow: plans resolved OFFLINE, never executed ──────────

_CART = [{"sku": "LAP-1", "name": "Dell Laptop", "quantity": 2}]


def _cart_llm(obj):
    return lambda _p, _t: json.dumps(obj)


def test_cart_only_job_resolves_plan_without_search_diff():
    db = _grounded_db()
    row = W.process_job(
        db, {"query": "clear my cart", "uid": "u", "tenant_id": "default",
             "trace_id": "tr-cart-1", "cart": _CART, "cart_only": True},
        cart_llm_fn=_cart_llm({"ops": [{"action": "clear_all"}], "confidence": 0.9}))
    assert row["kind"] == "cart_shadow_plan"
    assert row["outcome"] == "ops"
    assert row["plan"]["ops"] == [{"action": "clear_all", "target_skus": []}]
    assert row.get("diffed") is not True     # no search diff on a cart-only job


def test_cart_only_job_non_cart_query_scores_empty():
    db = _grounded_db()
    row = W.process_job(
        db, {"query": "show me gaming laptops", "uid": "u", "tenant_id": "default",
             "trace_id": "tr-cart-2", "cart": _CART, "cart_only": True},
        cart_llm_fn=_cart_llm({"ops": []}))
    assert row["outcome"] == "empty"         # the measurement: this turn was NOT a cart edit


def test_cart_job_with_search_shadow_does_both():
    db = _grounded_db()
    row = W.process_job(
        db, {"query": "laptop", "uid": "u", "tenant_id": "default",
             "trace_id": "tr-1", "cart": _CART},
        cart_llm_fn=_cart_llm({"ops": [], "confidence": 0.0}))
    # search diff still runs (tr-1 has a V1 trace) — cart resolution rides alongside
    assert row["diffed"] is True
