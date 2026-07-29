from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

from src.app.services import experiments


def apply_experiment_migrations(db) -> None:
    """Build experiment test schemas through the same migrations used by deployments."""
    operations = Operations(MigrationContext.configure(db.connection()))
    root = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    for filename in (
        "20260626_market_autonomy_tables.py",
        "20260825_tenant_experiment_policy.py",
    ):
        path = root / filename
        spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        original = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original
    db.commit()


def create_sealed_experiment(
    db, *, tenant_id: str = "default", name: str,
    target_metric: str = "rpv", status: str = "live",
    min_samples: int = 2, min_window_seconds: int = 60,
):
    return experiments.create_experiment(
        db, tenant_id=tenant_id, name=name, target_metric=target_metric, status=status,
        baseline={"variant": "control"}, eligibility={"all": True},
        min_samples=min_samples, min_window_seconds=min_window_seconds,
        rollback_threshold_pct=2.0, guardrails={},
        terminal_policy={"allowed": ["keep", "scale", "revise", "revert"]},
    )
