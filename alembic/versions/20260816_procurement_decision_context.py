"""Add immutable case context, replenishment proposals, and quote comparisons.

Revision ID: 20260816_procurement_context
Revises: 20260815_forecast_intelligence
"""

from alembic import op
import sqlalchemy as sa


revision = "20260816_procurement_context"
down_revision = "20260815_forecast_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "procurement_case_context_snapshot" not in tables:
        op.create_table(
            "procurement_case_context_snapshot",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("case_id", sa.Text(), nullable=False),
            sa.Column("case_version_id", sa.Text(), nullable=False),
            sa.Column("facts_json", sa.Text(), nullable=False),
            sa.Column("facts_hash", sa.String(64), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "case_id", "case_version_id", "facts_hash",
                name="uq_procurement_context_facts",
            ),
        )
        op.create_index(
            "ix_procurement_context_case",
            "procurement_case_context_snapshot",
            ["tenant_id", "case_id", "created_at"],
        )
    if "replenishment_decision_proposal" not in tables:
        op.create_table(
            "replenishment_decision_proposal",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("case_id", sa.Text(), nullable=False),
            sa.Column("context_snapshot_id", sa.String(64), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("blocked_reasons_json", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "case_id", "context_snapshot_id",
                name="uq_replenishment_context",
            ),
        )
    if "landed_cost_quote_comparison" not in tables:
        op.create_table(
            "landed_cost_quote_comparison",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("case_id", sa.Text(), nullable=False),
            sa.Column("context_snapshot_id", sa.String(64), nullable=False),
            sa.Column("target_currency", sa.Text(), nullable=False),
            sa.Column("target_uom", sa.Text(), nullable=False),
            sa.Column("comparison_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_landed_cost_comparison_case",
            "landed_cost_quote_comparison",
            ["tenant_id", "case_id", "created_at"],
        )


def downgrade() -> None:
    # These records are decision evidence and remain available for replay.
    return
