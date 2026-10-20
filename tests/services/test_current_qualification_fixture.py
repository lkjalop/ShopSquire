"""New fictional evidence has explicit time, provenance and no real authority."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest

from scripts.seed_current_qualification_fixture import research_fixture
from src.app.services.requirement_contract import load_requirement_contract, assess_contract_coverage


def test_current_fixture_expires_without_refreshing_its_observations():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    fixture = research_fixture(now, "simulation:explicit-test-instance")
    original = json.dumps(fixture, sort_keys=True)
    contract = load_requirement_contract(Path("config/requirement_contracts/fictional-memory-lab.json"))
    result = assess_contract_coverage(contract, context=contract.context, claims=fixture["claims"], now=now)
    assert result["coverage_complete"] is True
    assert result["fit_authority"] == result["commerce_authority"] == "none"
    expired = assess_contract_coverage(contract, context=contract.context, claims=fixture["claims"],
                                       now=now + timedelta(hours=24))
    assert expired["coverage_complete"] is False
    assert json.dumps(fixture, sort_keys=True) == original
    assert fixture["simulation_only"] is True
    assert fixture["requires_explicit_consent"] is True
    assert fixture["tenant_ids"] == ["synthetic-electronics"]
    assert all(claim["simulation_only"] for claim in fixture["claims"])


def test_naive_fixture_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone_aware_fixture_clock_required"):
        research_fixture(datetime(2026, 10, 21), "simulation:explicit-test-instance")


def test_current_observations_preserve_fixed_replay_and_exact_configuration():
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from src.app.models.db import get_engine
    from src.app.models.orm import Product, ProductConfiguration
    from src.app.services.commerce_catalog import upsert_price
    from scripts.seed_current_qualification_fixture import seed_current_observations, TENANT

    old_clock = datetime(2026, 9, 26, tzinfo=timezone.utc)
    with Session(get_engine()) as db:
        for sku in ("LAP-FIXTURE-A", "LAP-FIXTURE-B", "HDD-3A5E65F1"):
            product = db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
            if product is None:
                product = Product(sku=sku, name="FICTIONAL " + sku, specs={"ram_gb": 32},
                                  price_cents=100000, currency="AUD", active=True)
                db.add(product)
                db.flush()
            assert upsert_price(db, tenant_id=TENANT, sku=sku, list_cents=product.price_cents,
                                source="simulation:electronics-shortfall-v1")
        old = ProductConfiguration(id="simulation:test-fixed-replay", tenant_id=TENANT,
            sku="LAP-FIXTURE-A", title="Fixed fictional replay", configuration_hash="fixed",
            price_cents=100000, currency="AUD", price_observed_at=old_clock,
            source_url="fixture://fixed-replay")
        db.add(old)
        db.flush()
        _, receipt = seed_current_observations(db, now=datetime(2026, 10, 21, tzinfo=timezone.utc))
        current = db.get(ProductConfiguration, receipt["configuration_ids"][0])
        assert current.sku == "LAP-FIXTURE-B"
        assert db.execute(select(ProductConfiguration.id).where(
            ProductConfiguration.tenant_id == TENANT, ProductConfiguration.sku == current.sku,
            ProductConfiguration.active.is_(True))).scalars().all() == [current.id]
        db.refresh(old)
        assert old.price_observed_at.date() == old_clock.date()
        assert old.source_url == "fixture://fixed-replay"
        with pytest.raises(ValueError, match="current_qualification_fixture_already_exists"):
            seed_current_observations(db, now=datetime(2026, 10, 21, tzinfo=timezone.utc))


def test_seed_refuses_non_artifact_destination_before_reading_configuration(monkeypatch, tmp_path):
    from scripts.seed_current_qualification_fixture import main

    monkeypatch.setattr("sys.argv", ["seed", "--directory", str(tmp_path)])
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
    assert list(tmp_path.iterdir()) == []
