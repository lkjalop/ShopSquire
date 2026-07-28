from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.services.business_semantics import (
    LocationATPPayload,
    convert_quantity,
    project_atp,
    validate_payload,
)
from src.app.models.db import set_engine
from src.app.services.currency_authority import (
    FxAuthority,
    convert_minor_units,
    latest_fx_authority,
    record_fx_authority,
)
from src.app.services.demand_forecast import rolling_origin_evaluation
from src.app.services.market_evidence_policy import resolve_contradictions
from src.app.services.supplier_intelligence import supplier_shadow_score
from src.app.services.product_identity import convert_uom, register_uom, register_variant


pytestmark = pytest.mark.protocol


def _migrate_semantics(engine) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260813_canonical_business_semantics.py"
    spec = importlib.util.spec_from_file_location("canonical_semantics_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original


def test_fx_requires_dated_approved_provenance():
    quote = FxAuthority(
        base_currency="USD", quote_currency="AUD", rate=Decimal("1.5"),
        as_of="2026-07-28T00:00:00Z", source="rba", source_record_id="daily-1",
    )
    result = convert_minor_units(
        100, from_currency="USD", to_currency="AUD", authority=quote,
        at_time="2026-07-28T01:00:00Z",
    )
    assert result["amount_minor"] == 150
    with pytest.raises(ValueError, match="approved_fx_authority_required"):
        convert_minor_units(
            100, from_currency="USD", to_currency="AUD", authority=None,
            at_time="2026-07-28T01:00:00Z",
        )


def test_persisted_fx_uom_and_variant_identity_are_tenant_scoped(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'authority.sqlite'}", future=True)
    _migrate_semantics(engine)
    set_engine(engine)
    quote = FxAuthority(
        base_currency="USD", quote_currency="AUD", rate=Decimal("1.5"),
        as_of="2026-07-28T00:00:00Z", source="rba", source_record_id="daily-1",
    )
    record_fx_authority(tenant_id="tenant-a", authority=quote, approved_by="operator-1")
    stored = latest_fx_authority(
        tenant_id="tenant-a", base_currency="USD", quote_currency="AUD",
        at_time="2026-07-28T01:00:00Z",
    )
    assert stored is not None
    assert stored.rate == quote.rate
    assert stored.source_record_id == quote.source_record_id
    assert latest_fx_authority(
        tenant_id="tenant-b", base_currency="USD", quote_currency="AUD",
        at_time="2026-07-28T01:00:00Z",
    ) is None

    register_uom(
        tenant_id="tenant-a", category="count", code="EA",
        factor_to_base=Decimal("1"), is_base=True,
    )
    register_uom(
        tenant_id="tenant-a", category="count", code="CASE24",
        factor_to_base=Decimal("24"),
    )
    register_variant(
        tenant_id="tenant-a", template_id="template-1", variant_id="variant-1",
        sku="SKU-CASE", base_uom_code="EA", attributes={"pack": 24},
    )
    assert convert_uom(
        tenant_id="tenant-a", value=Decimal("2"), from_code="CASE24", to_code="EA",
    ) == Decimal("48")


def test_atp_preserves_source_and_normalized_basis_and_staleness():
    normalized = LocationATPPayload(
        variant_id="v1", location_id="l1",
        on_hand={"value": 10, "uom": "EA"},
        committed={"value": 4, "uom": "EA"},
        incoming={"value": 2, "uom": "EA"},
        source_calculated_at="2026-07-28T00:00:00Z", ttl_seconds=900,
    )
    fresh = project_atp(normalized, now=datetime(2026, 7, 28, 0, 10, tzinfo=timezone.utc))
    assert fresh["quantity"] == "8"
    assert fresh["basis"] == "normalized_projection"
    assert fresh["authorizes_execution"] is True
    stale = project_atp(normalized, now=datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc))
    assert stale["status"] == "stale"
    assert stale["authorizes_execution"] is False


def test_contracts_reject_unknown_fields_and_uom_conversion_is_explicit():
    with pytest.raises(ValueError):
        validate_payload("inventory_adjustment", {
            "variant_id": "v1", "location_id": "l1", "quantity_delta": 1,
            "uom": "EA", "reason_code": "count", "untyped": "not allowed",
        })
    assert convert_quantity(Decimal("2"), factor_to_base=Decimal("24")) == Decimal("48")


def test_rolling_origin_reports_undefined_zero_demand_and_selects_when_possible():
    zero = rolling_origin_evaluation([0.0] * 30)
    assert zero["status"] == "undefined"
    assert all(model["wape_status"] == "undefined_zero_actual" for model in zero["models"].values())
    intermittent = rolling_origin_evaluation([0, 0, 2, 0, 0, 1, 0] * 6)
    assert intermittent["status"] == "observed"
    assert intermittent["winner"] in intermittent["models"]


def test_supplier_score_stays_shadow_and_requires_minimum_outcomes():
    too_few = supplier_shadow_score(
        tenant_id="t1", supplier_id="s1",
        events=[{"tenant_id": "t1", "supplier_id": "s1", "event_type": "delivery"}],
    )
    assert too_few["status"] == "insufficient_evidence"
    events = [
        {
            "tenant_id": "t1", "supplier_id": "s1", "event_type": "delivery",
            "on_time": True, "requested_qty": 10, "filled_qty": 10,
            "received_qty": 10, "rejected_qty": 0, "lead_time_days": 4 + i,
        }
        for i in range(5)
    ]
    score = supplier_shadow_score(tenant_id="t1", supplier_id="s1", events=events)
    assert score["status"] == "shadow_observed"
    assert score["execution_allowed"] is False
    assert score["confidence_interval"]["high"] >= score["confidence_interval"]["low"]


def test_licensed_contradictions_are_contested_not_averaged():
    policy = {
        "source_system": "official", "trust_tier": "T1", "licence_id": "lic-1",
        "licence_url": "https://example.test/licence", "retrieved_at": "2026-07-28",
        "terms_hash": "abc", "allowed_uses": ["analysis"], "approved_by": "operator",
        "personal_data_allowed": False,
    }
    result = resolve_contradictions([
        {"direction": "up", "confidence": 0.8, "observed_at": "2026-07-28T00:00:00Z",
         "provenance_chain": ["official/1"], "source_policy": policy},
        {"direction": "down", "confidence": 0.9, "observed_at": "2026-07-27T00:00:00Z",
         "provenance_chain": ["official/2"], "source_policy": policy | {"trust_tier": "T2"}},
    ])
    assert result["status"] == "contested"
    assert result["winner"]["direction"] == "up"
    assert result["execution_allowed"] is False
