"""M1.2 shadow worker: drains the queue, runs V2, diffs against V1-from-trace, dead-letters
poison. Uses a fake redis + a grounded sqlite so V2 actually produces a real decision."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.workers import recommendation_shadow_worker as W


class _Redis:
    """Minimal list-backed fake with brpop/rpop/lpush + string ops (get/setex/incr/expire) so the
    idempotency + attempt-counter paths work on the LIST leg too. NO stream ops → exercises the
    R10.4b fallback ladder (worker list-only, producer lpush-fallback)."""
    def __init__(self):
        self.q = {}
        self.kv = {}
    def lpush(self, k, v): self.q.setdefault(k, []).insert(0, v)
    def rpop(self, k):
        lst = self.q.get(k) or []
        return lst.pop() if lst else None
    def brpop(self, k, timeout=0):
        lst = self.q.get(k) or []
        return (k, lst.pop()) if lst else None
    def get(self, k): return self.kv.get(k)
    def setex(self, k, ttl, v): self.kv[k] = v
    def expire(self, k, ttl): pass
    def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]


class _StreamRedis(_Redis):
    """+ consumer-group stream semantics (xadd/xgroup/xreadgroup/xack/xdel/xautoclaim). Faithful
    to the properties the worker depends on: XDEL removes an entry from the stream (so a
    reclaimed-but-deleted id is reported gone, not re-served); a NEW read never returns a pending
    or deleted id; xautoclaim returns entries idle >= min_idle_time, bounded by count."""
    def __init__(self):
        super().__init__()
        self.stream = {}      # key -> [(msg_id, fields)]
        self.pending = {}     # key -> {msg_id: {"consumer","idle"}}
        self.deleted = set()
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
                if mid in self.pending.get(key, {}) or mid in self.deleted:
                    continue
                self.pending.setdefault(key, {})[mid] = {"consumer": consumer, "idle": 0}
                entries.append((mid, fields))
                if len(entries) >= count:
                    break
            if entries:
                out.append((key, entries))
        return out

    def xack(self, key, group, mid):
        self.pending.get(key, {}).pop(mid, None)

    def xdel(self, key, mid):
        self.deleted.add(mid)
        self.stream[key] = [(m, f) for m, f in self.stream.get(key, []) if m != mid]

    def xautoclaim(self, key, group, consumer, min_idle_time=0, start_id="0-0", count=10):
        claimed = []
        for mid, meta in list(self.pending.get(key, {}).items())[:count]:
            if meta["idle"] >= min_idle_time:
                meta.update(consumer=consumer, idle=0)
                match = [f for m, f in self.stream.get(key, []) if m == mid]
                claimed.append((mid, match[0] if match else {}))   # {} = trimmed/deleted payload
        return ("0-0", claimed, [])


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
# These test QUEUE MECHANICS (ack / xdel / reclaim / poison / dedup), NOT the recommendation —
# so process_job is stubbed to a fast deterministic row (the real diff is covered by
# test_worker_drains_runs_and_diffs, which exercises the model path).

_JOB = {"query": "laptop", "uid": "u", "tenant_id": "default", "trace_id": "tr-1"}


@pytest.fixture()
def stub_pj(monkeypatch):
    calls = {"n": 0}
    def _fast(db, job, **k):
        calls["n"] += 1
        return {"diffed": True, "trace_id": job.get("trace_id")}
    monkeypatch.setattr(W, "process_job", _fast)
    return calls


def test_stream_job_processed_acked_and_deleted(stub_pj):
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    stats = W.run(r, lambda: object(), once=True, max_jobs=1)
    assert stats["processed"] == 1 and stats["diffed"] == 1
    assert not r.pending.get(W.STREAM_KEY)            # ACKed
    assert not r.stream.get(W.STREAM_KEY)             # XDELed — stream self-cleans (no MAXLEN, #1)


def test_crash_before_ack_recovers_via_autoclaim(stub_pj):
    """THE loss mode the BRPOP list could not survive: a consumer pops a job and DIES before
    finishing. The entry stays PENDING; after the idle window a live consumer XAUTOCLAIMs and
    completes it — zero loss on worker crash."""
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    r.xgroup_create(W.STREAM_KEY, W.GROUP)
    r.xreadgroup(W.GROUP, "dead-worker", {W.STREAM_KEY: ">"}, count=1)   # delivered, no ack
    for meta in r.pending[W.STREAM_KEY].values():
        meta["idle"] = W._CLAIM_IDLE_MS + 1                              # goes stale
    stats = W.run(r, lambda: object(), once=True, max_jobs=1, consumer="live-worker")
    assert stats["processed"] == 1
    assert not r.pending.get(W.STREAM_KEY) and not r.stream.get(W.STREAM_KEY)   # recovered + done


def test_poison_by_attempt_counter_dead_letters_and_acks():
    """review-9-followup #4: poison detection uses a Redis attempt COUNTER independent of
    XPENDING (which can be unreadable). A job whose attempt count has passed _MAX_DELIVERIES is
    dead-lettered to the DLQ stream + ACKed + XDELed — the group can never wedge, and this
    converges even when pending metadata is gone."""
    r = _StreamRedis()
    mid = r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    # simulate prior redeliveries: the counter is already at the threshold
    key = mid
    r.kv[W._ATTEMPT_PREFIX + key] = W._MAX_DELIVERIES
    stats = W.run(r, lambda: None, once=True)          # db_factory never called (poison first)
    assert stats["processed"] == 0 and stats["dead_lettered"] == 1
    assert r.stream.get(W.DEADLETTER_STREAM)           # durably dead-lettered
    assert not r.pending.get(W.STREAM_KEY) and mid in r.deleted   # acked + xdeled, unwedged


def test_malformed_entry_is_dead_lettered_not_eternally_pending():
    """review-9-followup #3: a stream entry with no `payload` field (or a trimmed pending entry
    whose payload is gone) is dead-lettered + acked, never skipped into an infinite reclaim loop."""
    r = _StreamRedis()
    r.xadd(W.STREAM_KEY, {"WRONG_FIELD": "x"})         # malformed
    stats = W.run(r, lambda: None, once=True)
    assert stats["dead_lettered"] == 1 and stats["processed"] == 0
    assert not r.pending.get(W.STREAM_KEY)             # not left pending forever


def test_dlq_write_failure_keeps_job_pending_for_retry():
    """review-9-followup #2: a job may be ACKed only after a DURABLE outcome. If the DLQ write
    fails, the poison/malformed job is NOT acked — it stays pending for a later retry rather than
    vanishing un-recorded."""
    class _NoDLQ(_StreamRedis):
        def xadd(self, key, fields, maxlen=None, approximate=True):
            if key == W.DEADLETTER_STREAM:
                raise RuntimeError("dlq down")
            return super().xadd(key, fields, maxlen, approximate)
        def lpush(self, k, v):
            if k == W.DEADLETTER_KEY:
                raise RuntimeError("dlq list down")
            return super().lpush(k, v)
    r = _NoDLQ()
    mid = r.xadd(W.STREAM_KEY, {"WRONG_FIELD": "x"})   # malformed → needs DLQ, which is down
    stats = W.run(r, lambda: None, once=True)
    assert stats["dead_lettered"] == 0
    assert mid in r.pending.get(W.STREAM_KEY, {})      # STILL pending — not acked, will retry
    assert mid not in r.deleted


def test_duplicate_delivery_is_idempotent_noop(stub_pj):
    """review-9-followup #5: at-least-once redelivery of an already-done job is a no-op — no
    re-processing, no double-counted metrics/trace."""
    r = _StreamRedis()
    mid = r.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    W.run(r, lambda: object(), once=True, max_jobs=1)  # processes + marks done + xdels
    assert r.kv.get(W._DONE_PREFIX + mid)              # done marker set
    # re-deliver the SAME key (simulate a redelivery of an entry already processed)
    r.deleted.discard(mid)
    r.stream.setdefault(W.STREAM_KEY, []).append((mid, {"payload": json.dumps(_JOB)}))
    stats = W.run(r, lambda: object(), once=True)
    assert stats["processed"] == 0 and stats["duplicate"] == 1   # recognized as duplicate, skipped


def test_stale_backlog_does_not_starve_new_work(stub_pj):
    """review-9-followup stream-Q1: a large pending backlog is reclaimed in BOUNDED batches while
    new entries still get read the same cycle — no starvation."""
    r = _StreamRedis()
    for i in range(W._MAX_CLAIM_PER_CYCLE * 3):        # many stale pending
        mid = r.xadd(W.STREAM_KEY, {"payload": json.dumps({**_JOB, "trace_id": f"old{i}"})})
        r.pending.setdefault(W.STREAM_KEY, {})[mid] = {"consumer": "dead", "idle": W._CLAIM_IDLE_MS + 1}
    r.xadd(W.STREAM_KEY, {"payload": json.dumps({**_JOB, "trace_id": "fresh"})})   # + one new
    stats = W.run(r, lambda: object(), once=True)
    assert stats["processed"] >= 1                     # drains without starving; terminates


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


# ── R10.4b — REAL Redis integration (skips when no redis reachable) ────────────────
# review-9-followup #3: the fakes above are simulations; these run the ACTUAL worker against a
# real Redis (XADD/XREADGROUP/XACK/XDEL/XAUTOCLAIM/INCR) on a dedicated DB. Skipped in CI / here
# when no redis is up — they run in any env that HAS one.

def _real_redis():
    import os
    try:
        import redis
    except ImportError:
        return None
    for url in (os.getenv("REDIS_TEST_URL"), os.getenv("REDIS_URL"), "redis://localhost:6379/15"):
        if not url:
            continue
        try:
            r = redis.Redis.from_url(url, socket_connect_timeout=1, decode_responses=False)
            r.ping()
            return r
        except Exception:
            continue
    return None


_REDIS = _real_redis()
_needs_redis = pytest.mark.skipif(_REDIS is None, reason="no reachable Redis (integration test)")


@pytest.fixture()
def rr():
    _REDIS.flushdb()
    yield _REDIS
    _REDIS.flushdb()


@_needs_redis
def test_real_stream_roundtrip_processed_acked_deleted(rr):
    db = _grounded_db()
    rr.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    stats = W.run(rr, lambda: db, once=True, max_jobs=1)
    assert stats["processed"] == 1
    assert rr.xlen(W.STREAM_KEY) == 0                  # XDELed after durable outcome (no MAXLEN)


@_needs_redis
def test_real_crash_recovery_via_xautoclaim(rr, monkeypatch):
    db = _grounded_db()
    monkeypatch.setattr(W, "_CLAIM_IDLE_MS", 0)        # reclaim immediately, don't wait 60s
    rr.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    W._ensure_group(rr)
    rr.xreadgroup(W.GROUP, "dead-worker", {W.STREAM_KEY: ">"}, count=1)   # delivered, not acked
    stats = W.run(rr, lambda: db, once=True, max_jobs=1, consumer="live-worker")
    assert stats["processed"] == 1 and rr.xlen(W.STREAM_KEY) == 0        # reclaimed + completed


@_needs_redis
def test_real_poison_dead_lettered(rr):
    mid = rr.xadd(W.STREAM_KEY, {"payload": json.dumps(_JOB)})
    key = mid.decode() if isinstance(mid, bytes) else mid
    rr.set(W._ATTEMPT_PREFIX + key, W._MAX_DELIVERIES)  # already at threshold → next is poison
    stats = W.run(rr, lambda: None, once=True)
    assert stats["dead_lettered"] == 1 and stats["processed"] == 0
    assert rr.xlen(W.DEADLETTER_STREAM) == 1


@_needs_redis
def test_real_malformed_dead_lettered(rr):
    rr.xadd(W.STREAM_KEY, {"NOT_payload": "x"})
    stats = W.run(rr, lambda: None, once=True)
    assert stats["dead_lettered"] == 1 and rr.xlen(W.DEADLETTER_STREAM) == 1


@_needs_redis
def test_real_two_consumers_split_work_no_double_process(rr):
    db = _grounded_db()
    for i in range(6):
        rr.xadd(W.STREAM_KEY, {"payload": json.dumps({**_JOB, "trace_id": f"t{i}"})})
    a = W.run(rr, lambda: db, once=True, consumer="worker-A")
    b = W.run(rr, lambda: db, once=True, consumer="worker-B")
    assert a["processed"] + b["processed"] == 6        # all done, none processed twice
    assert rr.xlen(W.STREAM_KEY) == 0
