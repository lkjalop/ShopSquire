"""Materialize comparable forecasts and ABC/XYZ inventory segments.

Revision ID: 20260815_forecast_intelligence
Revises: 20260814_conversation_facts
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_forecast_intelligence"
down_revision = "20260814_conversation_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "forecast_intelligence_evaluation" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "forecast_intelligence_evaluation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Text(), nullable=False),
        sa.Column("horizon_kind", sa.Text(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("history_start", sa.Text()),
        sa.Column("history_end", sa.Text()),
        sa.Column("source_watermark", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("selected_model", sa.Text()),
        sa.Column("abc_class", sa.Text()),
        sa.Column("xyz_class", sa.Text()),
        sa.Column("evaluation_json", sa.Text(), nullable=False),
        sa.Column("computation_version", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False, server_default="shadow_evaluation_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "sku",
            "as_of_date",
            "horizon_kind",
            "horizon_days",
            "source_watermark",
            "computation_version",
            name="uq_forecast_intelligence_run",
        ),
    )
    op.create_index(
        "ix_forecast_intelligence_latest",
        "forecast_intelligence_evaluation",
        ["tenant_id", "sku", "created_at"],
    )


def downgrade() -> None:
    # Forecast evidence remains available for decision replay after rollback.
    return
