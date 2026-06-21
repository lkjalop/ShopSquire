"""Tier 2 retriever stage — mode resolution + RRF fusion (pure)."""
from __future__ import annotations

import os

from src.app.services.recommend_retriever_stage import apply_retrieval_mode, fuse, resolve_retrieval_mode


def test_resolve_mode_default_shadow_and_validation():
    os.environ.pop("RECOMMEND_RETRIEVAL_MODE", None)
    assert resolve_retrieval_mode({}) == "shadow"
    assert resolve_retrieval_mode({"RECOMMEND_RETRIEVAL_MODE": "fusion"}) == "fusion"
    assert resolve_retrieval_mode({"RECOMMEND_RETRIEVAL_MODE": "bogus"}) == "shadow"


def test_resolve_mode_env_overrides_flag():
    os.environ["RECOMMEND_RETRIEVAL_MODE"] = "primary"
    try:
        assert resolve_retrieval_mode({"RECOMMEND_RETRIEVAL_MODE": "shadow"}) == "primary"
    finally:
        os.environ.pop("RECOMMEND_RETRIEVAL_MODE", None)


def test_fuse_degenerate_cases():
    p = [{"sku": "A"}]
    assert fuse(p, []) == p          # no v2 -> primary
    assert fuse([], p) == p          # no primary -> v2
    assert fuse([], []) == []


def test_fuse_rrf_merges_and_dedups():
    primary = [{"sku": "A"}, {"sku": "B"}]
    v2 = [{"sku": "B"}, {"sku": "C"}]
    out = fuse(primary, v2)
    skus = [c["sku"] for c in out]
    assert set(skus) == {"A", "B", "C"}            # union, deduped
    assert skus[0] == "B"                            # B in both -> top RRF


def test_apply_mode_shadow_primary_fusion():
    primary = [{"sku": "A"}, {"sku": "B"}]
    v2 = [{"sku": "C"}]
    assert [c["sku"] for c in apply_retrieval_mode("shadow", primary=primary, v2=v2)] == ["A", "B"]
    assert [c["sku"] for c in apply_retrieval_mode("primary", primary=primary, v2=v2)] == ["C"]
    # primary mode falls back to monolith when v2 empty
    assert [c["sku"] for c in apply_retrieval_mode("primary", primary=primary, v2=[])] == ["A", "B"]
    assert set(c["sku"] for c in apply_retrieval_mode("fusion", primary=primary, v2=v2)) == {"A", "B", "C"}
