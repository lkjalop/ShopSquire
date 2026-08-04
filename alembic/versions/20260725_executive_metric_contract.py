"""Portable executive metric snapshots and tenant-scoped supplier audits.

Revision ID: 20260725_exec_metrics
Revises: 20260724_supplier_offer
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_exec_metrics"
down_revision = "20260724_supplier_offer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "supplier_score_audits" not in tables:
        op.create_table(
            "supplier_score_audits",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("sku", sa.String(160)),
            sa.Column("supplier_id", sa.String(160), nullable=False),
            sa.Column("score", sa.Numeric(10, 6)),
            sa.Column("payload", sa.Text(), nullable=False),
        )
        op.create_index(
            "ix_supplier_score_tenant_created", "supplier_score_audits",
            ["tenant_id", "created_at"])
    elif "tenant_id" not in {c["name"] for c in inspector.get_columns("supplier_score_audits")}:
        op.add_column(
            "supplier_score_audits",
            sa.Column("tenant_id", sa.String(128), nullable=True))
        op.execute("UPDATE supplier_score_audits SET tenant_id='default' WHERE tenant_id IS NULL")

    op.create_table(
        "executive_metric_snapshot",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("metric_name", sa.String(96), nullable=False),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(192), nullable=False),
        sa.Column("value_numeric", sa.Numeric(24, 8)),
        sa.Column("value_text", sa.Text()),
        sa.Column("unit", sa.String(48)),
        sa.Column("currency", sa.String(8)),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("coverage", sa.Numeric(8, 6), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_records_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("definition_version", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "metric_name", "subject_type", "subject_id", "as_of",
            name="uq_exec_metric_identity"),
    )
    op.create_index(
        "ix_exec_metric_tenant_lookup", "executive_metric_snapshot",
        ["tenant_id", "metric_name", "subject_id", "as_of"])


def downgrade() -> None:
    op.drop_table("executive_metric_snapshot")
    # supplier_score_audits may predate this migration; preserve its operational history.
