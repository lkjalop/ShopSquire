"""Align the RAGAS baseline table created by legacy schemas.

Revision ID: 20260832_ragas_baseline_schema_alignment
Revises: 20260831_legacy_commerce_tenant_ownership
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260832_ragas_baseline_schema_alignment"
down_revision = "20260831_legacy_commerce_tenant_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ragas_baseline" not in inspector.get_table_names():
        op.create_table(
            "ragas_baseline",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("baseline_score", sa.Float()),
            sa.Column(
                "updated_at",
                sa.Text(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        return

    columns = {column["name"] for column in inspector.get_columns("ragas_baseline")}
    if "updated_at" in columns:
        return

    column = sa.Column(
        "updated_at",
        sa.Text(),
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    if bind.dialect.name == "sqlite":
        # SQLite cannot ALTER-add a non-constant CURRENT_TIMESTAMP default.
        # Batch mode rebuilds the tiny baseline table while preserving rows.
        with op.batch_alter_table("ragas_baseline", recreate="always") as batch_op:
            batch_op.add_column(column)
    else:
        op.add_column("ragas_baseline", column)


def downgrade() -> None:
    # Baseline history remains readable across application rollback.
    pass
