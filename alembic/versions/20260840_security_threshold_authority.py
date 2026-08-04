"""Move security threshold and analyst-correction schema under Alembic authority.

Revision ID: 20260840_security_threshold_authority
Revises: 20260839_demand_fulfillment_location
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260840_security_threshold_authority"
down_revision = "20260839_demand_fulfillment_location"
branch_labels = None
depends_on = None


_CORRECTION_COLUMNS = (
    "ground_truth",
    "analyst_verdict",
    "correction_ts",
    "correction_notes",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "security_threshold_overrides" not in tables:
        op.create_table(
            "security_threshold_overrides",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("threshold_key", sa.Text(), nullable=False),
            sa.Column("threshold_value", sa.Float(), nullable=False),
            sa.Column("source", sa.Text()),
            sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("tenant_id", "threshold_key"),
        )

    if "email_security_incidents" in tables:
        existing = _columns("email_security_incidents")
        for name in _CORRECTION_COLUMNS:
            if name not in existing:
                op.add_column("email_security_incidents", sa.Column(name, sa.Text()))


def downgrade() -> None:
    tables = _tables()
    if "email_security_incidents" in tables:
        existing = _columns("email_security_incidents")
        for name in reversed(_CORRECTION_COLUMNS):
            if name in existing:
                op.drop_column("email_security_incidents", name)
    if "security_threshold_overrides" in tables:
        op.drop_table("security_threshold_overrides")
