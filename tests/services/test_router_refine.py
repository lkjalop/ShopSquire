"""Phase 1d — the router emits a SOFT brand preference distinct from the HARD brand filter:
'ideally a Mac' → preferred_brand (keeps other options, lights the shelf's band 3), NOT brand_filter
(which would remove every non-Apple option)."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import route_turn


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT DEFAULT 'USD', brand TEXT, specs TEXT, "
        "product_type TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, brand, specs) VALUES "
        "('p1','MAC-1','Apple MacBook Air',129900,'Apple','{}'), "
        "('p2','DEL-1','Dell XPS 13',119900,'Dell','{}')"))
    yield s
    s.close()


def _env(q):
    return TurnEnvelope.from_suggest_params(query=q, uid="u1", tenant_id="default")


def _stub(**refine):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "use_cases": [], "requirements": {},
               "refine": refine, "compare_targets": [], "confidence": 0.9}
    return lambda p, t: json.dumps(payload)


def test_soft_preferred_brand_is_not_a_hard_filter(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    d = route_turn(db, _env("a laptop, ideally a mac"),
                   llm_fn=_stub(brand=None, prefer_brand="apple", sort=None))
    assert d.preferred_brand == "Apple"     # clamped to canonical catalog casing
    assert d.brand_filter is None           # soft preference does NOT become a hard filter


def test_brand_negation_extracted_and_clamped(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    # 'a laptop but not Apple' → exclude_brand, clamped to the catalog's canonical casing
    d = route_turn(db, _env("a laptop but not apple"),
                   llm_fn=_stub(brand=None, prefer_brand=None, exclude_brand="apple", sort=None))
    assert d.exclude_brand == "Apple"
    assert d.brand_filter is None and d.preferred_brand is None   # exclusion ≠ inclusion


def test_explicit_negation_repairs_model_positive_brand_contradiction(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    d = route_turn(
        db,
        _env("a work laptop under $1900, not Apple"),
        llm_fn=_stub(brand="apple", prefer_brand=None, exclude_brand=None, sort=None),
    )
    assert d.exclude_brand == "Apple"
    assert d.brand_filter is None


def test_hard_filter_suppresses_duplicate_soft_band(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    # 'only Apple' is a hard filter; the same brand as a soft preference is redundant → dropped
    d = route_turn(db, _env("only apple laptops"),
                   llm_fn=_stub(brand="apple", prefer_brand="apple", sort=None))
    assert d.brand_filter == "Apple" and d.preferred_brand is None


@pytest.mark.parametrize("model_lane", ["BULK", "BULK_QUOTE", "QUOTE", "RFQ"])
def test_procurement_lane_synonyms_are_clamped_to_existing_lane(db, model_lane):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    payload = {
        "lane": model_lane,
        "handle": "el-6-6",
        "use_cases": [],
        "requirements": {},
        "refine": {},
        "compare_targets": [],
        "confidence": 0.9,
    }
    decision = route_turn(
        db,
        _env("we need 25 laptops for our new office, can you do a bulk quote?"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert decision.lane == "PROCUREMENT"
    assert decision.source == "model"
