"""T3 classifier: deterministic candidate generation, the crosswalk, and — the part that
matters — the clamp: a model pick outside the candidate list can never become a
classification, and every failure degrades to a low-confidence lexical proposal."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.catalog_classifier import (
    candidate_nodes,
    classify_catalog,
    classify_text,
)


def _picker(handle, conf=0.9):
    """Stub llm_fn that always answers with the given handle."""
    return lambda prompt, timeout: json.dumps({"handle": handle, "confidence": conf})


# ── candidates (deterministic) ────────────────────────────────────────────────

def test_candidates_gaming_laptop_tops_gaming_laptops_node():
    # the 2026-05 release has BOTH el-6-6 (Laptops) and el-6-11-2 (Gaming Computers >
    # Gaming Laptops) — for gaming text the more specific node must win
    cands = candidate_nodes("Dell G16 7630 Gaming Laptop RTX 4070")
    assert cands[0][0].handle == "el-6-11-2"


def test_candidates_plain_laptop_finds_laptops_node():
    handles = [n.handle for n, _ in candidate_nodes("Dell 15 DC15255 15.6in FHD Laptop Ryzen 3")]
    assert "el-6-6" in handles


def test_candidates_require_leaf_name_match():
    # "laptop BACKPACK" must surface bag nodes, and Laptops (el-6-6) only via its own name
    handles = [n.handle for n, _ in candidate_nodes("Recycled Berlin Laptop Backpack")]
    assert any(h.startswith("lb-") for h in handles)


def test_candidates_empty_on_empty_text():
    assert candidate_nodes("") == []
    # NOTE: garbage text may yield SEMANTIC candidates when the embedding index is present
    # (cosine noise floors overlap real matches) — abstention is enforced in classify_text
    # (semantic-only evidence requires an affirmative model pick), not by candidate emptiness


# ── crosswalk ─────────────────────────────────────────────────────────────────

def test_crosswalk_is_fallback_when_model_fails():
    # crosswalk is a PRIOR now, not a shortcut — the model IS consulted; on failure the
    # merchant's own category stands deterministically
    c = classify_text("whatever text", existing_category="Laptops", llm_fn=lambda p, t: "{}")
    assert c.source == "crosswalk" and c.node_handle == "el-6-6"


def test_model_refines_crosswalk_within_subtree_at_normal_conf():
    # 'headset' crosswalks to el-2-2-7-2 (Headsets); the model refines to Gaming Headsets —
    # a subtree refinement accepted at the normal floor (the 6-gaming-headsets holdout class)
    c = classify_text("Logitech G325 Wireless Gaming Headset", existing_category="headset",
                      llm_fn=_picker("el-2-2-7-2-2", 0.6))
    assert c.source == "model" and c.node_handle == "el-2-2-7-2-2"


def test_specificity_earned_with_es_plurals():
    # 'Dress' must earn 'Dresses' (the +es class): the first inline plural copy missed this
    # and snapped every dress to Clothing
    c = classify_text("Linen Wrap Midi Dress", llm_fn=_picker("aa-1-4", 0.9))
    assert c.node_handle == "aa-1-4"


def test_specificity_must_be_earned():
    # the model picks 'Portable Monitors' for a NON-portable monitor: parent is a candidate,
    # 'portable' is not in the text -> snapped to Computer Monitors (the 8/10-monitors class)
    c = classify_text("LG UltraGear 27\" FHD 144Hz Gaming Monitor", existing_category="monitor",
                      llm_fn=_picker("el-17-1-1", 0.9))
    assert c.node_handle == "el-17-1"
    # but a genuinely portable monitor KEEPS the child — evidence present
    c = classify_text("AOC 16T20 15.6\" FHD USB-C Portable Monitor", existing_category="monitor",
                      llm_fn=_picker("el-17-1-1", 0.9))
    assert c.node_handle == "el-17-1-1"


def test_model_override_outside_prior_needs_strong_confidence():
    # specs said 'laptop' but the product is an iMac (the live data-bug class): a pick
    # OUTSIDE the crosswalk subtree is rejected at 0.6 (crosswalk stands) and accepted at 0.9
    text = "Apple iMac with Retina 4.5K Display 24-inch Desktop Computer"
    weak = classify_text(text, existing_category="laptop", llm_fn=_picker("el-6-3", 0.6))
    assert weak.source == "crosswalk" and weak.node_handle == "el-6-6"
    strong = classify_text(text, existing_category="laptop", llm_fn=_picker("el-6-3", 0.9))
    assert strong.source == "model" and strong.node_handle == "el-6-3"


def test_crosswalk_normalizes_singular_and_underscores():
    assert classify_text("x", existing_category="laptop", llm_fn=lambda p, t: "{}").node_handle == "el-6-6"
    c = classify_text("x", existing_category="hard_drive", llm_fn=lambda p, t: "{}")
    assert c.source == "crosswalk" and c.node_handle == "el-7-9-14-4"


def test_ambiguous_category_name_goes_to_model_not_crosswalk():
    # bare 'monitor' matches multiple node names (baby/computer/studio monitors) — must NOT
    # crosswalk; with the model unavailable it degrades to lexical fallback, never a guess
    c = classify_text("Blaupunkt 27in FHD Curved Gaming Monitor monitor",
                      existing_category="monitor", llm_fn=lambda p, t: "")
    assert c.source == "lexical_fallback"


# ── the clamp ─────────────────────────────────────────────────────────────────

def test_model_pick_from_candidates_accepted():
    c = classify_text("Dell G16 Gaming Laptop", llm_fn=_picker("el-6-11-2", 0.92))
    assert c.source == "model" and c.node_handle == "el-6-11-2" and c.confidence == 0.92


def test_model_pick_outside_candidates_clamped_to_fallback():
    # aa-1-4 (Dresses) is a REAL node but was not a candidate for a laptop — must be rejected
    c = classify_text("Dell G16 Gaming Laptop", llm_fn=_picker("aa-1-4", 0.99))
    assert c.source == "lexical_fallback" and c.node_handle != "aa-1-4"
    assert c.confidence <= 0.2


def test_garbage_model_output_falls_back():
    c = classify_text("Dell G16 Gaming Laptop", llm_fn=lambda p, t: "not json at all")
    assert c is not None and c.source == "lexical_fallback"


def test_low_confidence_model_pick_falls_back():
    c = classify_text("Dell G16 Gaming Laptop", llm_fn=_picker("el-6-6", 0.05))
    assert c.source == "lexical_fallback"


def test_garbage_with_failing_model_abstains():
    # semantic-only evidence + no affirmative model pick -> None (unclassifiable), never
    # a lexical_fallback onto the nearest semantic noise node
    assert classify_text("zzqx9 qqfw7", llm_fn=lambda p, t: "") is None
    assert classify_text("zzqx9", llm_fn=lambda p, t: "not json") is None


# ── catalog sweep writes proposals only ───────────────────────────────────────

@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, brand) VALUES "
        "('p1','LAP-1','Dell G16 Gaming Laptop',169900,'Dell'), "
        "('p2','AUD-1','Logitech Wireless Gaming Headset',19900,'Logitech')"))
    yield s
    s.close()


def test_classify_catalog_proposes_never_publishes(db):
    def route(prompt, timeout):
        return json.dumps({"handle": "el-6-11-2" if "Laptop" in prompt else "el-2-2-7-2-2",
                           "confidence": 0.9})
    report = classify_catalog(db, llm_fn=route, commit=False, mode="legacy")
    assert report["classified"] == 2 and report["by_source"].get("model") == 2
    rows = db.execute(text("SELECT sku, node_handle, status FROM product_classification ORDER BY sku")).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("AUD-1", "el-2-2-7-2-2", "proposed"), ("LAP-1", "el-6-11-2", "proposed")]
    # nothing sold until approval (T4): the sold set stays ungrounded
    from src.app.services.taxonomy_registry import sold_nodes
    assert sold_nodes(db) is None
