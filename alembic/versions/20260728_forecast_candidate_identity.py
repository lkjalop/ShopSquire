"""Add reproducible forecast candidate identity.

Revision ID: 20260728_forecast_identity
Revises: 20260727_nqe_feedback
"""
from alembic import op
import sqlalchemy as sa


revision = "20260728_forecast_identity"
down_revision = "20260727_nqe_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("forecast_actual_pair") as batch:
        batch.add_column(sa.Column(
            "model_id", sa.String(128), nullable=False,
            server_default="legacy_unversioned",
        ))
        batch.add_column(sa.Column(
            "model_version", sa.String(128), nullable=False,
            server_default="legacy_unversioned",
        ))
    op.create_index(
        "ix_forecast_actual_candidate",
        "forecast_actual_pair",
        ["tenant_id", "subject_id", "model_id", "model_version", "target_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_actual_candidate", table_name="forecast_actual_pair")
    with op.batch_alter_table("forecast_actual_pair") as batch:
        batch.drop_column("model_version")
        batch.drop_column("model_id")
