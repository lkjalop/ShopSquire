"""Tenant-scoped, sealed experiment policy.

Revision ID: 20260825_tenant_experiment_policy
Revises: 20260824_catalog_grounding_parity
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "20260825_tenant_experiment_policy"
down_revision = "20260824_catalog_grounding_parity"
branch_labels = None
depends_on = None

_LEGACY_POLICY = {
    "baseline": {"variant": "control", "legacy_unsealed": True},
    "eligibility": {"legacy_population": True},
    "min_samples": 30,
    "min_window_seconds": 86400,
    "rollback_threshold_pct": 2.0,
    "guardrails": {},
    "terminal_policy": {"allowed": ["keep", "scale", "revise", "revert"]},
}


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "tenant_id" not in _columns("experiment_run"):
        with op.batch_alter_table("experiment_run") as batch:
            batch.add_column(sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"))
            batch.add_column(sa.Column("policy_json", sa.Text(), nullable=True))
            batch.add_column(sa.Column(
                "policy_version", sa.Text(), nullable=False, server_default="experiment-policy.v1"
            ))
    bind.execute(
        sa.text("UPDATE experiment_run SET policy_json=:policy WHERE policy_json IS NULL"),
        {"policy": json.dumps(_LEGACY_POLICY, sort_keys=True, separators=(",", ":"))},
    )
    # Preserve all legacy rows while making tenant/name lookup deterministic.
    rows = bind.execute(sa.text(
        "SELECT id, tenant_id, name FROM experiment_run ORDER BY tenant_id, name, created_at, id"
    )).fetchall()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row[1]), str(row[2]))
        if key in seen:
            bind.execute(
                sa.text("UPDATE experiment_run SET name=:name WHERE id=:id"),
                {"name": f"{row[2]}__legacy__{row[0]}", "id": row[0]},
            )
        seen.add(key)
    with op.batch_alter_table("experiment_run") as batch:
        batch.alter_column("policy_json", existing_type=sa.Text(), nullable=False)

    for table in ("experiment_assignment", "experiment_result"):
        if "tenant_id" not in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"))

    op.create_index(
        "ux_experiment_tenant_name", "experiment_run", ["tenant_id", "name"], unique=True
    )
    op.create_index(
        "ix_experiment_tenant_status", "experiment_run", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_experiment_assignment_tenant", "experiment_assignment",
        ["tenant_id", "experiment_id", "assigned_at"],
    )
    op.create_index(
        "ix_experiment_result_tenant", "experiment_result",
        ["tenant_id", "experiment_id", "decided_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_result_tenant", table_name="experiment_result")
    op.drop_index("ix_experiment_assignment_tenant", table_name="experiment_assignment")
    op.drop_index("ix_experiment_tenant_status", table_name="experiment_run")
    op.drop_index("ux_experiment_tenant_name", table_name="experiment_run")
    for table in ("experiment_result", "experiment_assignment"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("tenant_id")
    with op.batch_alter_table("experiment_run") as batch:
        batch.drop_column("policy_version")
        batch.drop_column("policy_json")
        batch.drop_column("tenant_id")
