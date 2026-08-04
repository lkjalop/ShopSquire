"""Product_Ranking_Agent — contrastive WHY must be spec-specific, not a generic phrase.

The old behaviour gave every product the same "selected because it has better spec match" line.
Now the #1 pick says "top pick — <reason>" and every runner-up is explained by its ACTUAL spec
deltas vs the top pick ("vs the top pick — 33% cheaper; 16GB less RAM"). Deterministic, no LLM.
"""
from __future__ import annotations

from src.app.services.product_ranking_agent import _salient_deltas, listwise_rerank


def _cands():
    return [
        {"product_id": "A", "sku": "A", "name": "Alpha 32", "brand": "Acme",
         "price": 1800, "ram_gb": 32, "storage_gb": 1024, "has_dedicated_gpu": True, "gpu_vram_gb": 8,
         "cpu": "i7", "display_inches": 16, "refresh_hz": 165},
        {"product_id": "B", "sku": "B", "name": "Beta 16", "brand": "Beta",
         "price": 1200, "ram_gb": 16, "storage_gb": 512, "has_dedicated_gpu": True, "gpu_vram_gb": 6,
         "cpu": "i5", "display_inches": 15, "refresh_hz": 144},
        {"product_id": "C", "sku": "C", "name": "Gamma 32", "brand": "Gamma",
         "price": 2200, "ram_gb": 32, "storage_gb": 1024, "has_dedicated_gpu": True, "gpu_vram_gb": 8,
         "cpu": "i7", "display_inches": 16, "refresh_hz": 240},
    ]


def test_exactly_one_top_pick_and_others_contrast_vs_it():
    ranked = listwise_rerank(_cands(), required_specs={"ram_gb": 32, "gpu_vram_gb": 8},
                             budget_min=None, budget_max=2300, top_n=3)
    assert len(ranked) == 3
    # "top pick" is a substring of "vs the top pick", so match on the text AFTER the label colon.
    def _is_top(r):
        return r.contrastive_why.split(":", 1)[-1].strip().startswith("top pick")
    tops = [r for r in ranked if _is_top(r)]
    assert len(tops) == 1, [r.contrastive_why for r in ranked]
    assert tops[0].rank == 1
    for r in ranked:
        if r.rank != 1:
            assert "vs the top pick" in r.contrastive_why


def test_no_generic_phrase_and_runner_up_cites_a_real_delta():
    ranked = listwise_rerank(_cands(), required_specs={"ram_gb": 32, "gpu_vram_gb": 8},
                             budget_min=None, budget_max=2300, top_n=3)
    for r in ranked:
        assert r.contrastive_why  # never empty
        assert "selected because it has" not in r.contrastive_why  # old generic phrasing gone
    # At least one runner-up names a concrete spec delta (a digit / $ / GB / % / Hz token).
    runner_whys = " ".join(r.contrastive_why for r in ranked if r.rank != 1)
    assert any(tok in runner_whys for tok in ("$", "GB", "%", "Hz", "VRAM")), runner_whys


def test_single_product_is_top_pick():
    ranked = listwise_rerank([_cands()[0]], required_specs={"ram_gb": 32}, top_n=1)
    assert len(ranked) == 1 and "top pick" in ranked[0].contrastive_why


# ── _salient_deltas unit ──
def test_salient_deltas_skips_same_similar_and_respects_priority_and_cap():
    deltas = {
        "ram": "Same 16GB RAM",            # skipped (Same)
        "display": "Similar display (16\")",  # skipped (Similar)
        "price": "33% cheaper ($1200 vs $1800)",
        "gpu": "Higher GPU (8GB vs 6GB VRAM)",
        "storage": "Larger storage (1024GB vs 512GB)",
    }
    out = _salient_deltas(deltas, k=2)
    assert out == ["33% cheaper ($1200 vs $1800)", "Higher GPU (8GB vs 6GB VRAM)"]  # price>gpu, cap 2
    assert all("Same" not in d and "Similar" not in d for d in out)


def test_salient_deltas_empty_when_all_same():
    assert _salient_deltas({"ram": "Same 16GB RAM", "price": "Similar price ($1,800)"}) == []


# ── build_contrastive_explanations (Phase 3 extraction) ──
def test_build_contrastive_explanations_maps_by_sku():
    from src.app.services.product_ranking_agent import build_contrastive_explanations
    scored = [{"score": 1.0, "candidate": c} for c in _cands()]
    why, delta = build_contrastive_explanations(
        scored, required_specs={"ram_gb": 32, "gpu_vram_gb": 8}, budget_max=2300, top_n=3)
    assert set(why.keys()) == {"A", "B", "C"}        # one explanation per SKU
    assert all(isinstance(v, str) and v for v in why.values())
    # exactly one "top pick", others contrast vs it (delegates to the contrastive-why logic)
    tops = [k for k, v in why.items() if v.split(":", 1)[-1].strip().startswith("top pick")]
    assert len(tops) == 1
    assert isinstance(delta, dict)


def test_build_contrastive_explanations_empty_and_safe():
    from src.app.services.product_ranking_agent import build_contrastive_explanations
    assert build_contrastive_explanations([], top_n=3) == ({}, {})
