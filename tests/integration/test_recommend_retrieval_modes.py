"""Tier 2 — RECOMMEND_RETRIEVAL_MODE integration: every mode preserves the contract.

shadow (default) is the live behaviour; fusion/primary merge or swap in V2 candidates BEFORE
ranking so the existing budget/stock/security filters still apply. In the test env V2 may not be
ready, so fusion/primary degrade to primary-only — the assertion is contract-stability + the mode
label, not a specific ranking (which needs a live vector DB).
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())

_SPINE = {"results", "decision_trace_id", "constraints_used", "buyer_persona"}


def _suggest(uid):
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "gaming laptop under 1800"})
    assert r.status_code == 200
    return r.json()


def test_shadow_default_mode():
    os.environ.pop("RECOMMEND_RETRIEVAL_MODE", None)
    body = _suggest("u-rm-shadow")
    assert _SPINE <= body.keys()
    assert body.get("timing_breakdown", {}).get("retrieval_mode") in (None, "shadow")


def test_fusion_mode_preserves_contract():
    os.environ["RECOMMEND_RETRIEVAL_MODE"] = "fusion"
    try:
        body = _suggest("u-rm-fusion")
        assert _SPINE <= body.keys()
        assert body.get("timing_breakdown", {}).get("retrieval_mode") == "fusion"
    finally:
        os.environ.pop("RECOMMEND_RETRIEVAL_MODE", None)


def test_primary_mode_preserves_contract():
    os.environ["RECOMMEND_RETRIEVAL_MODE"] = "primary"
    try:
        body = _suggest("u-rm-primary")
        assert _SPINE <= body.keys()
        assert body.get("timing_breakdown", {}).get("retrieval_mode") == "primary"
    finally:
        os.environ.pop("RECOMMEND_RETRIEVAL_MODE", None)
