"""Project legacy rooms, incidents, and tickets onto canonical escalations.

Revision ID: 20260856_escalation_projection
Revises: 20260855_case_escalation
"""

from alembic import op
import sqlalchemy as sa


revision = "20260856_escalation_projection"
down_revision = "20260855_case_escalation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("incidents") as batch:
        batch.add_column(sa.Column("tenant_id", sa.Text()))
        batch.add_column(sa.Column("case_id", sa.Text()))
        batch.add_column(sa.Column("trace_id", sa.Text()))
    op.create_table(
        "case_escalation_projection",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "escalation_id",
            sa.Text(),
            sa.ForeignKey("case_escalation.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("projected_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_kind",
            "source_id",
            name="uq_case_escalation_projection_source",
        ),
        sa.CheckConstraint(
            "source_kind IN ('procurement_room','security_incident','ticket')",
            name="ck_case_escalation_projection_kind",
        ),
    )
    op.create_index(
        "ix_case_escalation_projection_escalation",
        "case_escalation_projection",
        ["tenant_id", "escalation_id", "projected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_case_escalation_projection_escalation",
        table_name="case_escalation_projection",
    )
    op.drop_table("case_escalation_projection")
    with op.batch_alter_table("incidents") as batch:
        batch.drop_column("trace_id")
        batch.drop_column("case_id")
        batch.drop_column("tenant_id")
