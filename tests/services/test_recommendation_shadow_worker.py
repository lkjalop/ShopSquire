"""M1.2 shadow worker: drains the queue, runs V2, diffs against V1-from-trace, dead-letters
poison. Uses a fake redis + a grounded sqlite so V2 actually produces a real decision."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.workers import recommendation_shadow_worker as W


class _Redis:
    """Minimal list-backed fake with brpop/rpop/lpush semantics (NO stream support — exercises
    the R10.4b fallback ladder: worker runs list-only, producer falls back to lpush)."""
    def __init__(self): self.q = {}
    def lpush(self, k, v): self.q.setdefault(k, []).insert(0, v)
    def rpop(self, k):
        lst = self.q.get(k) or []
        return lst.pop() if lst else None
    def brpop(self, k, timeout=0):
        lst = self.q.get(k) or []
        return (k, lst.pop()) if lst else None


class _StreamRedis(_Redis):
    """+ minimal consumer-group stream semantics (xadd/xgroup/xreadgroup/xack/xautoclaim/
    xpending_range) for the R10.4b durability proofs."""
    def __init__(self):
        super().__init__()
        self.stream = {}      # key -> [(msg_id, fields)]
        self.pending = {}     # key -> {msg_id: {"consumer","idle","deliveries"}}
        self.acked = set()
        self._seq = 0

    def xadd(self, key, fields, maxlen=None, approximate=True):
        self._seq += 1
        mid = f"{self._seq}-0"
        self.stream.setdefault(key, []).append((mid, dict(fields)))
        return mid

    def xgroup_create(self, key, group, id="0", mkstream=False):
        self.stream.setdefault(key, [])
        self.pending.setdefault(key, {})

    def xreadgroup(self, group, consumer, streams, count=1, block=0):
        out = []
        for key in streams:
            entries = []
            for mid, fields in self.stream.get(key, []):
                if mid in self.pending.get(key, {}) or mid in self.acked:
                    continue
                self.pending.setdefault(key, {})[mid] = {
                    "consumer": consumer, "idle": 0, "deliveries": 1}
                entries.append((mid, fields))
                if len(entries) >= count:
                    break
            if entries:
                out.append((key, entries))
        return out

    def xack(self, key, group, mid):
        self.pending.get(key, {}).pop(mid, None)
        self.acked.add(mid)

    def xautoclaim(self, key, group, consumer, min_idle_time=0, start_id="0-0", count=10):
        claimed = []
        for mid, meta in list(self.pending.get(key, {}).items()):
            if meta["idle"] >= min_idle_time:
                meta.update(consumer=consumer, idle=0, deliveries=meta["deliveries"] + 1)
                fields = next(f for m, f in self.stream[key] if m == mid)
                claimed.append((mid, fields))
                if len(claimed) >= count:
                    break
        return ("0-0", claimed, [])

    def xpending_range(self, key, group, min=None, max=None, count=1):
        meta = self.pending.get(key, {}).get(min)
        return [{"times_delivered": meta["deliveries"]}] if meta else []


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


# ── R10.4b — stream durability proofs ─────────────────────────────────────────────

_JOB = {"query": "laptop", "uid": "u", "tenant_id": "default", "trace_id": "tr-1"}


def test_stream_job_processed_and_acked():
    db = _grounded_db()
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    stats = W.run(r, lambda: db, once=True, max_jobs=1)
    assert stats["processed"] == 1 and stats["diffed"] == 1
    assert not r.pending.get(W.STREAM_KEY)            # ACKed after processing — nothing pending


def test_crash_before_ack_recovers_via_autoclaim():
    """THE loss mode the BRPOP list could not survive: a consumer pops a job and DIES before
    finishing. With the stream, the entry stays PENDING; after the idle window a live consumer
    XAUTOCLAIMs and processes it — zero loss."""
    db = _grounded_db()
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    r.xgroup_create(W.STREAM_KEY, W.GROUP)
    # consumer 'dead-worker' reads the entry and crashes (no ack)
    delivered = r.xreadgroup(W.GROUP, "dead-worker", {W.STREAM_KEY: ">"}, count=1)
    assert delivered and delivered[0][1]              # it was delivered...
    # ...time passes; the entry goes stale in PEL
    for meta in r.pending[W.STREAM_KEY].values():
        meta["idle"] = W._CLAIM_IDLE_MS + 1
    # a LIVE worker reclaims and completes it
    stats = W.run(r, lambda: db, once=True, max_jobs=1, consumer="live-worker")
    assert stats["processed"] == 1
    assert not r.pending.get(W.STREAM_KEY)            # recovered, processed, ACKed


def test_poison_redelivery_dead_letters_and_acks():
    """An entry redelivered past _MAX_DELIVERIES (crashes its consumer every time) is dead-
    lettered to the DLQ STREAM and ACKed — the group can never wedge on one poison job."""
    r = _StreamRedis()
    mid = r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    r.xgroup_create(W.STREAM_KEY, W.GROUP)
    r.xreadgroup(W.GROUP, "dead-worker", {W.STREAM_KEY: ">"}, count=1)
    r.pending[W.STREAM_KEY][mid].update(idle=W._CLAIM_IDLE_MS + 1,
                                        deliveries=W._MAX_DELIVERIES + 1)
    stats = W.run(r, lambda: None, once=True)
    assert stats["processed"] == 0                    # never re-processed
    assert r.stream.get(W.DEADLETTER_STREAM)          # dead-lettered to the DLQ stream
    assert mid in r.acked                             # and ACKed — group unwedged


def test_stream_and_legacy_list_both_drained():
    """Migration: jobs queued on the OLD list (or by stream-less clients) still process
    alongside stream jobs — nothing strands."""
    db = _grounded_db()
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    r.lpush(W.QUEUE_KEY, json.dumps({**_JOB, "trace_id": "no-such-trace"}))
    stats = W.run(r, lambda: db, once=True)
    assert stats["processed"] == 2


def test_producer_prefers_stream_falls_back_to_list():
    import src.app.services.recommendation_facade as F
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    env = TurnEnvelope.from_suggest_params(query="laptop", uid="u1")
    sr = _StreamRedis()
    F._enqueue_shadow(sr, envelope=env)
    assert sr.stream.get(F._SHADOW_STREAM_KEY) and not sr.q.get(F._SHADOW_QUEUE_KEY)
    lr = _Redis()                                     # no stream support
    F._enqueue_shadow(lr, envelope=env)
    assert lr.q.get(F._SHADOW_QUEUE_KEY)              # graceful fallback to the list
