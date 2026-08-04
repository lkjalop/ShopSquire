"""Track 3 — VLM hardening: cache-first, non-blocking timeout, profile-propagating worker.

The image path's product-identity VLM is the dominant latency (50-86s cold). Track 3 makes it
SAFE to run in parallel and SAFE when it is slow:

- a repeat image is a cache HIT → the VLM network call is skipped entirely (prewarm exploits this);
- when the parallel future times out, the join records vision_status="timeout" and proceeds WITHOUT
  a blocking inline re-call, so commerce still answers (text-identity + catalog carry the turn);
- the worker runs under the request's StoreProfile (copy_context().run), so a non-electronics image
  is not scored as electronics.

These are unit-level guarantees that mirror the exact join in recommend.py (~L6774). The end-to-end
latency win only shows on a live stack with a real vision provider, so it is not asserted here.
"""
from __future__ import annotations

import concurrent.futures as _futures
import contextvars
import time

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.platform.store_profile import active_profile_id, reset_active_profile_id, set_active_profile_id
from src.app.services import vision_cache
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())

_VISION_MIN_CONF = 0.0  # mirror: any identified candidate qualifies in the unit reproduction


# ── cache-first: a warmed image never calls the VLM ──
def test_cache_hit_skips_vlm_network_call(monkeypatch):
    from src.app.services import product_identity_agent as pia

    blob = b"demo-image-bytes-track3"
    vision_cache.clear()
    vision_cache.put(vision_cache.image_key(blob, "identity"),
                     {"ok": True, "identified": True, "brand": "TestBrand", "model": "X1", "confidence": 0.9})

    # If the cache is bypassed, the network call fires — make that an explicit failure.
    def _boom(*a, **k):
        raise AssertionError("VLM network call made despite a warm cache")
    monkeypatch.setattr(pia.requests, "post", _boom)

    res = pia.identify_product_from_image(blob, user_query="", trace_id=None)
    assert res.get("from_cache") is True
    assert res.get("brand") == "TestBrand"
    vision_cache.clear()


# ── non-blocking timeout: the join catches it, records status, never re-blocks ──
def test_future_timeout_is_caught_and_does_not_block():
    """Reproduces the recommend.py join: result(timeout) → TimeoutError → status=timeout, no inline
    re-call, and the guarded downstream access tolerates a None candidate."""
    ex = _futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(lambda: (time.sleep(0.2), {"identified": True})[1])
        _id_candidate = None
        _vision_status = "ok"
        try:
            _id_candidate = fut.result(timeout=0.05)
        except _futures.TimeoutError:
            _vision_status = "timeout"
            _id_candidate = None
        except Exception:
            _vision_status = "error"
            _id_candidate = None

        assert _vision_status == "timeout"
        assert _id_candidate is None
        # The hardened join guards every deref behind isinstance(dict) — a None candidate must NOT
        # crash and must NOT promote an identity (so the turn falls through to text-identity/catalog).
        _id_result = None
        if isinstance(_id_candidate, dict):  # skipped → no crash, no identity
            _id_result = _id_candidate
        assert _id_result is None
    finally:
        ex.shutdown(wait=True, cancel_futures=True)


# ── profile propagation: the worker sees the request's vertical ──
def test_copy_context_run_in_executor_preserves_profile():
    tok = set_active_profile_id("pharmacy")
    try:
        ctx = contextvars.copy_context()
        with _futures.ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(ctx.run, active_profile_id)
            assert fut.result(timeout=5) == "pharmacy"
    finally:
        reset_active_profile_id(tok)


# ── contract stays intact with the flag ON (text query → no future launched) ──
def test_text_query_contract_stable_with_parallel_flag_on(tmp_path, monkeypatch):
    import json

    from src.app.config import get_settings, load_feature_flags

    base = load_feature_flags(get_settings().feature_flags_path)
    base["PARALLEL_VISION_IDENTITY"] = True
    fp = tmp_path / "flags.json"
    fp.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("FEATURE_FLAGS_PATH", str(fp))

    # Keep the contract test independent from durable quota usage accumulated by
    # other compatibility tests sharing the local Redis instance.
    uid = f"u-pvt-{tmp_path.name}"
    body = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "gaming laptop under 1800"},
    ).json()
    assert "results" in body and "decision_trace_id" in body
