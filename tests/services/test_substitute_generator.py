"""Substitute generator (agnostic): same-category, in-budget alternatives ranked by profile-defined
attribute match; seed + excluded brands + over-budget removed. Profile drives which attributes count."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.substitute_generator import find_substitutes, find_substitutes_typed


# profile_fn stub: the comparable attributes are ram_gb + storage_gb (vertical-blind — supplied here)
def _profile(key, default=None):
    if key == "narration_spec_dimensions":
        return [{"label": "RAM", "variants": [{"key": "ram_gb"}]},
                {"label": "SSD", "variants": [{"key": "storage_gb"}]}]
    return default


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    s.execute(text("CREATE TABLE products (sku TEXT, name TEXT, price_cents INT, specs TEXT, "
                   "category TEXT, brand TEXT, active INT)"))
    rows = [
        ("SEED", "Seed Pick", 150000, {"ram_gb": 16, "storage_gb": 512}, "laptop", "Dell"),
        ("ALT-A", "Alt A equal", 145000, {"ram_gb": 16, "storage_gb": 512}, "laptop", "HP"),
        ("ALT-B", "Alt B better", 175000, {"ram_gb": 32, "storage_gb": 1024}, "laptop", "Lenovo"),
        ("ALT-C", "Alt C weaker", 130000, {"ram_gb": 8, "storage_gb": 256}, "laptop", "Acer"),
        ("OVER", "Over budget", 400000, {"ram_gb": 32, "storage_gb": 2048}, "laptop", "MSI"),
        ("OTHER", "Different category", 50000, {"ram_gb": 8}, "monitor", "Dell"),
    ]
    for sku, name, price, specs, cat, brand in rows:
        s.execute(text("INSERT INTO products VALUES (:k,:n,:p,:s,:c,:b,1)"),
                  {"k": sku, "n": name, "p": price, "s": json.dumps(specs), "c": cat, "b": brand})
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_finds_same_category_in_budget_ranked_by_attr_match(db):
    subs = find_substitutes(db, "SEED", budget_max=1900, profile_fn=_profile)
    skus = [x["sku"] for x in subs]
    assert "SEED" not in skus            # never returns the seed itself
    assert "OTHER" not in skus           # different category excluded
    assert "OVER" not in skus            # $4,000 > $1,900*1.1 excluded
    # ALT-B (32/1024 beats) and ALT-A (equal) both meet/beat on both specs → match 2; ALT-C weaker → lower
    assert skus[0] in ("ALT-B", "ALT-A") and "ALT-C" in skus
    top = subs[0]
    assert top["spec_match"] == 2 and top["spec_total"] == 2 and "key specs" in top["tradeoff"]


def test_excludes_brands(db):
    subs = find_substitutes(db, "SEED", budget_max=1900, exclude_brands=["HP", "Lenovo"], profile_fn=_profile)
    brands = {x["brand"] for x in subs}
    assert "HP" not in brands and "Lenovo" not in brands and "Acer" in brands


def test_price_delta_and_tradeoff_direction(db):
    subs = find_substitutes(db, "SEED", budget_max=2000, profile_fn=_profile)
    by = {x["sku"]: x for x in subs}
    assert by["ALT-B"]["price_delta_cents"] == 25000 and "more" in by["ALT-B"]["tradeoff"]
    assert by["ALT-C"]["price_delta_cents"] == -20000 and "less" in by["ALT-C"]["tradeoff"]


def test_no_catalog_row_returns_empty(db):
    assert find_substitutes(db, "NOPE", profile_fn=_profile) == []


def test_typed_missing_seed_is_not_a_source_failure(db):
    assert find_substitutes_typed(db, "NOPE", profile_fn=_profile) == {
        "status": "none_qualified",
        "items": [],
        "reason": "seed_not_found",
    }


def test_typed_schema_failure_does_not_poison_caller_transaction():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    session = sessionmaker(bind=engine, future=True)()
    try:
        result = find_substitutes_typed(session, "SEED", profile_fn=_profile)

        assert result["status"] == "schema_incompatible"
        assert result["items"] == []
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        session.close()


def test_no_profile_dims_still_returns_in_budget_same_category(db):
    subs = find_substitutes(db, "SEED", budget_max=1900, profile_fn=lambda k, default=None: default)
    assert {x["sku"] for x in subs} == {"ALT-A", "ALT-B", "ALT-C"}  # ranked on price when no attrs
    assert all(x["spec_total"] == 0 for x in subs)
