from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.product_identity import (
    rebuild_legacy_product_aliases,
    resolve_product_alias,
)
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import route_turn


def _db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'identity.sqlite'}")
    Session = sessionmaker(bind=engine)
    db = Session()
    db.execute(text("""
        CREATE TABLE products (
            sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE product_identity_alias (
            tenant_id TEXT, normalized_alias TEXT, alias_type TEXT, sku TEXT,
            source TEXT, active INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, normalized_alias, alias_type, sku)
        )
    """))
    return db


def test_indexed_aliases_resolve_sku_mpn_model_and_title(tmp_path):
    db = _db(tmp_path)
    db.execute(text(
        "INSERT INTO products VALUES "
        "('RGAM-0007', 'HP OMEN MAX 16 2.5K 240Hz OLED', "
        "'{\"mpn\":\"B89X7PA\",\"model\":\"OMEN MAX 16-ah0007TX\"}', 1)"
    ))
    assert rebuild_legacy_product_aliases(db, tenant_id="tenant-a") == 4

    assert resolve_product_alias(db, tenant_id="tenant-a", query="quote RGAM-0007") == ('RGAM-0007', 'sku')
    assert resolve_product_alias(db, tenant_id="tenant-a", query="need B89X7PA by Friday") == ('RGAM-0007', 'manufacturer_part_number')
    assert resolve_product_alias(db, tenant_id="tenant-a", query="80 OMEN MAX 16-ah0007TX") == ('RGAM-0007', 'model')
    assert resolve_product_alias(db, tenant_id="other", query="RGAM-0007") is None


def test_ambiguous_alias_abstains(tmp_path):
    db = _db(tmp_path)
    for sku in ('A', 'B'):
        db.execute(text(
            "INSERT INTO product_identity_alias "
            "(tenant_id, normalized_alias, alias_type, sku, source, active) "
            "VALUES ('tenant-a', 'shared model', 'model', :sku, 'test', 1)"
        ), {"sku": sku})
    assert resolve_product_alias(db, tenant_id="tenant-a", query="buy shared model") is None


def test_explicit_indexed_sku_bulk_request_bypasses_model(tmp_path, monkeypatch):
    db = _db(tmp_path)
    db.execute(text("CREATE TABLE product_classification (tenant_id TEXT,sku TEXT,node_handle TEXT,status TEXT)"))
    db.execute(text("INSERT INTO products VALUES ('RGAM-0007','HP OMEN MAX 16','{}',1)"))
    db.execute(text(
        "INSERT INTO product_classification VALUES "
        "('tenant-a','RGAM-0007','el-6-11-2','approved')"
    ))
    rebuild_legacy_product_aliases(db, tenant_id="tenant-a")
    calls = {"model": 0}

    def model(_prompt, _timeout):
        calls["model"] += 1
        raise AssertionError("explicit bulk identity must not queue for model routing")

    decision = route_turn(
        db,
        TurnEnvelope(
            uid="buyer", tenant_id="tenant-a", trace_id="trace",
            query="I need 30 RGAM-0007 laptops. AUD 140000 total.",
        ),
        llm_fn=model,
    )

    assert calls["model"] == 0
    assert decision.source == "deterministic_explicit_product"
    assert decision.exact_product_sku == "RGAM-0007"
    assert decision.quantity == 30
    assert decision.total_budget_cents == 14_000_000


def test_exact_catalog_sku_survives_before_alias_index_rebuild(tmp_path):
    db = _db(tmp_path)
    db.execute(text("CREATE TABLE product_classification (tenant_id TEXT,sku TEXT,node_handle TEXT,status TEXT)"))
    db.execute(text("INSERT INTO products VALUES ('RGAM-0007','HP OMEN MAX 16','{}',1)"))
    db.execute(text(
        "INSERT INTO product_classification VALUES "
        "('tenant-a','RGAM-0007','el-6-11-2','approved')"
    ))

    decision = route_turn(
        db,
        TurnEnvelope(
            uid="buyer", tenant_id="tenant-a", trace_id="trace",
            query="We need 18 RGAM-0007 laptops for a design studio, AUD 85000 total",
        ),
        llm_fn=lambda *_args: (_ for _ in ()).throw(
            AssertionError("an exact catalog SKU must not require model routing")
        ),
    )

    assert decision.source == "deterministic_explicit_product"
    assert decision.exact_product_sku == "RGAM-0007"
    assert decision.quantity == 18
