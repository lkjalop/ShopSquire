import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.procurement_decision_context import (
    calculate_replenishment,
    compare_landed_cost_quotes,
    create_case_context_snapshot,
    create_replenishment_proposal,
    latest_case_decision_intelligence,
)


def _schema(engine):
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE fulfillment_case (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE uom_unit (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, category_id TEXT NOT NULL,
                code TEXT NOT NULL, factor_to_base NUMERIC NOT NULL, is_base INTEGER NOT NULL
            )
        """))
        db.execute(text("""
            INSERT INTO uom_unit (id, tenant_id, category_id, code, factor_to_base, is_base)
            VALUES
              ('ea', 'tenant-a', 'count', 'EA', 1, 1),
              ('case', 'tenant-a', 'count', 'CASE', 10, 0)
        """))
        db.execute(text("""
            CREATE TABLE fulfillment_case_version (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, valid_from TEXT,
                valid_to TEXT, created_at TEXT
            )
        """))
        db.execute(text("""
            CREATE TABLE procurement_case_context_snapshot (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
                case_version_id TEXT NOT NULL, facts_json TEXT NOT NULL,
                facts_hash TEXT NOT NULL, source_authority TEXT NOT NULL,
                provenance_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE (tenant_id, case_id, case_version_id, facts_hash)
            )
        """))
        db.execute(text("""
            CREATE TABLE replenishment_decision_proposal (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
                context_snapshot_id TEXT NOT NULL, result_json TEXT NOT NULL,
                status TEXT NOT NULL, blocked_reasons_json TEXT NOT NULL,
                authority TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE (tenant_id, case_id, context_snapshot_id)
            )
        """))
        db.execute(text("""
            CREATE TABLE landed_cost_quote_comparison (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
                context_snapshot_id TEXT NOT NULL, target_currency TEXT NOT NULL,
                target_uom TEXT NOT NULL, comparison_json TEXT NOT NULL,
                status TEXT NOT NULL, authority TEXT NOT NULL,
                created_by TEXT NOT NULL, created_at TEXT NOT NULL
            )
        """))
        db.execute(text("INSERT INTO fulfillment_case VALUES ('case-1', 'tenant-a')"))
        db.execute(text(
            "INSERT INTO fulfillment_case_version "
            "(id, case_id, valid_from, valid_to, created_at) "
            "VALUES ('version-1', 'case-1', '2026-07-28T00:00:00Z', NULL, '2026-07-28T00:00:00Z')"
        ))


def _facts(authority="authoritative"):
    return {
        "demand": {
            "mean_daily": 4,
            "variance_daily": 2.25,
            "distribution": "empirical",
            "forecast_evaluation_id": "forecast-1",
        },
        "supplier_lead_time": {"mean_days": 10, "variance_days2": 4},
        "service_level": 0.95,
        "inventory": {"current_atp": 20, "incoming_supply": 5},
        "commercial": {
            "moq": 25,
            "pack_size": 5,
            "price_breaks": [
                {"min_qty": 25, "discount_pct": 5},
                {"min_qty": 50, "discount_pct": 10},
            ],
        },
        "uom": {"base_uom": "EA", "order_uom": "PACK", "factor_to_base": 5},
        "source_authority": authority,
        "provenance": {
            "forecast": "forecast-1",
            "atp": "atp-1",
            "supplier_terms": "terms-1",
        },
    }


def test_replenishment_formula_uses_variance_service_atp_moq_and_pack():
    result = calculate_replenishment(_facts())
    assert result["safety_stock_units"] > 0
    assert result["reorder_point_units"] > 40
    assert result["suggested_order_units"] >= 25
    assert result["suggested_order_units"] % 5 == 0
    assert result["selected_price_break"]["min_qty"] == 25
    assert result["can_execute"] is False


def test_snapshot_is_immutable_and_simulation_cannot_authorize():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _schema(engine)
    set_engine(engine)
    snapshot = create_case_context_snapshot(
        tenant_id="tenant-a",
        case_id="case-1",
        facts=_facts("simulation"),
        created_by="operator-1",
    )
    duplicate = create_case_context_snapshot(
        tenant_id="tenant-a",
        case_id="case-1",
        facts=_facts("simulation"),
        created_by="operator-1",
    )
    assert snapshot["immutable"] is True
    assert duplicate["duplicate"] is True
    proposal = create_replenishment_proposal(
        tenant_id="tenant-a",
        case_id="case-1",
        context_snapshot_id=snapshot["snapshot_id"],
        created_by="operator-1",
    )
    assert proposal["status"] == "simulation_only"
    assert proposal["blocked_reasons"] == ["non_authoritative_inputs"]
    assert proposal["result"]["can_execute"] is False


def test_landed_cost_comparison_requires_approved_fx_and_comparable_uom():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _schema(engine)
    set_engine(engine)
    snapshot = create_case_context_snapshot(
        tenant_id="tenant-a",
        case_id="case-1",
        facts=_facts(),
        created_by="operator-1",
    )
    at_time = datetime(2026, 7, 28, 12, tzinfo=timezone.utc).isoformat()
    result = compare_landed_cost_quotes(
        tenant_id="tenant-a",
        case_id="case-1",
        context_snapshot_id=snapshot["snapshot_id"],
        target_currency="AUD",
        target_uom="EA",
        created_by="operator-1",
        at_time=at_time,
        quotes=[
            {
                "quote_id": "usd-case",
                "supplier_id": "s1",
                "purchase_unit_cost_minor": 10000,
                "freight_unit_minor": 1000,
                "currency": "USD",
                "quote_uom": "CASE",
                "quantity": 30,
                "price_breaks": [{"min_qty": 25, "discount_pct": 10}],
                "fx_authority": {
                    "base_currency": "USD",
                    "quote_currency": "AUD",
                    "rate": "1.5",
                    "as_of": "2026-07-28T10:00:00+00:00",
                    "source": "approved-treasury-feed",
                    "source_record_id": "fx-1",
                    "status": "approved",
                },
                "provenance": {"quote": "q1"},
            },
            {
                "quote_id": "missing-fx",
                "supplier_id": "s2",
                "purchase_unit_cost_minor": 1200,
                "currency": "USD",
                "quote_uom": "EA",
                "provenance": {"quote": "q2"},
            },
            {
                "quote_id": "aud-each",
                "supplier_id": "s3",
                "purchase_unit_cost_minor": 1600,
                "currency": "AUD",
                "quote_uom": "EA",
                "provenance": {"quote": "q3"},
            },
        ],
    )
    assert [row["quote_id"] for row in result["ranked"]] == ["usd-case", "aud-each"]
    assert result["ranked"][0]["comparable_landed_unit_minor"] == "1485.0000"
    assert result["excluded"] == [
        {"quote_id": "missing-fx", "reason": "approved_fx_authority_required"}
    ]
    assert result["can_authorize_purchase"] is False
    latest = latest_case_decision_intelligence(tenant_id="tenant-a", case_id="case-1")
    assert latest["context"]["facts_hash"] == snapshot["facts_hash"]
    assert latest["comparison"]["recommended"]["quote_id"] == "usd-case"
    with engine.connect() as db:
        stored = db.execute(text(
            "SELECT comparison_json FROM landed_cost_quote_comparison"
        )).scalar_one()
    assert json.loads(stored)["authority"] == "comparison_only"
