"""M2-B3: batch get_variants kills the evidence N+1 (~3 queries × N SKUs → one per table),
retrieval pages become deterministic (ORDER BY before LIMIT), and the bundle records its own
query cost so an N+1 regression is a visible trace number, not a profiler session."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.catalog_read_model import get_variant, get_variants
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.evidence import gather_evidence


N_SKUS = 30


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://", connect_args={"check_same_thread": False}))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT, "
        "price_cents INT, currency TEXT DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT)"))
    s.execute(text(
        "CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT, stock INT, warehouse TEXT)"))
    for i in range(N_SKUS):
        s.execute(text("INSERT INTO products (id, sku, name, price_cents, specs, brand) "
                       "VALUES (:id, :sku, :name, :price, :specs, :brand)"),
                  {"id": f"p{i}", "sku": f"SKU-{i:03d}", "name": f"Unit {i}",
                   "price": 100000 + i * 1000, "specs": json.dumps({"ram_gb": 8 + i % 3 * 8}),
                   "brand": f"brand{i % 4}"})
        if i % 2 == 0:   # half have inventory rows; the other half read stock 0 via LEFT JOIN
            s.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                           "VALUES (:id, :pid, :st, 'w1')"),
                      {"id": f"i{i}", "pid": f"p{i}", "st": 5 + i})
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(s, node_handle="el-6-6")
    for i in range(N_SKUS):
        upsert_classification(s, sku=f"SKU-{i:03d}", node_handle="el-6-6",
                              source="test", status="approved")
    s.commit()
    yield s
    s.close()


def test_batch_matches_per_sku_reads(db):
    skus = [f"SKU-{i:03d}" for i in range(N_SKUS)]
    batch = get_variants(db, skus, mode="legacy")
    singles = [get_variant(db, s, mode="legacy") for s in skus]
    assert len(batch) == N_SKUS
    for b, s in zip(batch, singles):
        assert (b.sku, b.price_cents, b.stock, b.stock_source, b.brand) == \
               (s.sku, s.price_cents, s.stock, s.stock_source, s.brand)


def test_batch_preserves_caller_order_and_drops_missing(db):
    out = get_variants(db, ["SKU-005", "SKU-001", "SKU-NOPE", "SKU-003"], mode="legacy")
    assert [v.sku for v in out] == ["SKU-005", "SKU-001", "SKU-003"]   # order kept, missing absent


def test_taxonomy_evidence_is_O1_queries_not_ON(db):
    """THE B3 assertion: 30 classified SKUs retrieve in a CONSTANT number of round-trips
    (sku-page + products + stock = 3), not ~3 per SKU (~90)."""
    env = TurnEnvelope.from_suggest_params(query="laptop", uid="u1", tenant_id="default")
    bundle = gather_evidence(db, env, node_handle="el-6-6", limit=50, mode="legacy")
    assert bundle.count == N_SKUS
    assert bundle.retrieval_mode == "taxonomy:el-6-6"
    assert bundle.queries <= 4, f"N+1 regression: {bundle.queries} retrieval queries for {N_SKUS} SKUs"


def test_retrieval_page_is_deterministic(db):
    env = TurnEnvelope.from_suggest_params(query="laptop", uid="u1", tenant_id="default")
    a = gather_evidence(db, env, node_handle="el-6-6", limit=10, mode="legacy")
    b = gather_evidence(db, env, node_handle="el-6-6", limit=10, mode="legacy")
    assert [v.sku for v in a.variants] == [v.sku for v in b.variants]
    assert len(a.variants) == 10
    assert [v.sku for v in a.variants] == sorted(v.sku for v in a.variants)  # ORDER BY sku page


def test_query_count_recorded_in_trace(db):
    env = TurnEnvelope.from_suggest_params(query="laptop", uid="u1", tenant_id="default")
    bundle = gather_evidence(db, env, node_handle="el-6-6", limit=5, mode="legacy")
    assert bundle.as_trace()["queries"] == bundle.queries > 0
