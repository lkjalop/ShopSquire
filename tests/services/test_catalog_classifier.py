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


def test_candidates_empty_on_no_signal():
    assert candidate_nodes("") == []
    assert candidate_nodes("zzqx9 qqfw7") == []


# ── crosswalk ─────────────────────────────────────────────────────────────────

def test_existing_category_crosswalks_without_model():
    calls = []
    def spy(prompt, timeout):
        calls.append(1)
        return "{}"
    c = classify_text("whatever text", existing_category="Laptops", llm_fn=spy)
    assert c.source == "crosswalk" and c.node_handle == "el-6-6" and calls == []


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


def test_no_signal_returns_none():
    assert classify_text("zzqx9", llm_fn=_picker("el-6-6")) is None


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
