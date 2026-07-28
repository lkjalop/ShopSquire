from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.services.inventory_intelligence import (
    InventoryHistory,
    calculate_inventory_intelligence,
)
from src.app.services.product_lifecycle import (
    propose_lifecycle_transition,
    resolve_lifecycle_transition,
)


def _migrate(engine) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260811_product_lifecycle.py"
    spec = importlib.util.spec_from_file_location("product_lifecycle_migration", path)
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


def test_lifecycle_is_human_gated_and_separates_sell_from_procure(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lifecycle.sqlite'}", future=True)
    _migrate(engine)
    set_engine(engine)
    proposal = propose_lifecycle_transition(
        tenant_id="tenant-a",
        sku="SKU-1",
        to_state="sell_through",
        reason="replacement model",
        evidence={"successor_sku": "SKU-2"},
        proposed_by="inventory-agent",
    )
    assert proposal["status"] == "pending"
    resolved = resolve_lifecycle_transition(
        tenant_id="tenant-a",
        transition_id=proposal["id"],
        approved=True,
        resolved_by="operator-1",
    )
    assert resolved["selling_allowed"] is True
    assert resolved["procurement_allowed"] is False


def test_inventory_metrics_and_stale_price_remain_shadow_only():
    result = calculate_inventory_intelligence(
        InventoryHistory(
            on_hand_units=100,
            units_sold=10,
            history_days=70,
            gross_margin_cents=50_000,
            average_inventory_cost_cents=100_000,
            current_price_cents=20_000,
            unit_cost_cents=12_000,
            days_since_last_sale=120,
            lead_time_days=14,
            lead_time_stddev_days=3,
        )
    )
    assert result["weekly_shelf_velocity"] == 1.0
    assert result["weeks_of_supply"] == 100.0
    assert result["gmroi_annualised"] > 2.0
    assert result["stale_price_proposal"]["execution_allowed"] is False
    assert result["stale_price_proposal"]["proposed_price_cents"] >= 13_800
