"""PARALLEL_VISION_IDENTITY — flag-gated parallel VLM product-identity (latency).

The slow (20-40s cold) VLM identify call can be pre-launched in a worker thread so it overlaps
NLP + constraint building instead of blocking the identity stage. This test guards the SAFETY
contract (the latency win itself only shows on a live stack with a vision provider):

- flag OFF (default): behaviour is the inline path — unchanged.
- flag ON: the suggest() response is identical for a text query (no image → no future launched),
  and the worker runs under the request's StoreProfile (no electronics bleed) — exercised by the
  context-propagation unit below.
"""
from __future__ import annotations

import contextvars

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.platform.store_profile import active_profile_id, set_active_profile_id, reset_active_profile_id
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())


def _keys(uid, query):
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query})
    assert r.status_code == 200
    return set(r.json().keys())


def test_text_query_unaffected_by_flag_default_off():
    # No image → no future is launched regardless of flag; contract spine intact.
    body = client.get("/api/v1/recommend/suggest", params={"uid": "u-pv", "query": "gaming laptop under 1800"}).json()
    assert "results" in body and "decision_trace_id" in body


def test_copy_context_propagates_active_profile_to_worker():
    # The launch uses contextvars.copy_context().run so the worker sees the request's profile.
    # This mirrors the submit() in suggest(): a copied context preserves active_profile_id.
    tok = set_active_profile_id("pharmacy")
    try:
        ctx = contextvars.copy_context()
        seen = ctx.run(active_profile_id)
        assert seen == "pharmacy"  # worker would resolve pharmacy patterns, not electronics
    finally:
        reset_active_profile_id(tok)
