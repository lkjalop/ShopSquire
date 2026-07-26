"""Own NQE feedback schema through Alembic.

Revision ID: 20260727_nqe_feedback
Revises: 20260726_reco_interaction
"""
from alembic import op
import sqlalchemy as sa


revision = "20260727_nqe_feedback"
down_revision = "20260726_reco_interaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "nqe_feedback_events" not in tables:
        op.create_table(
            "nqe_feedback_events",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("trace_id", sa.String(128), nullable=False),
            sa.Column("question_id", sa.String(192), nullable=False),
            sa.Column("variant", sa.String(64), nullable=False),
            sa.Column("converted", sa.Boolean(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("answer_value", sa.String(255)),
            sa.Column("helpful", sa.Boolean()),
        )
    else:
        columns = {
            column["name"]
            for column in inspector.get_columns("nqe_feedback_events")
        }
        additions = {
            "answer_value": sa.Column("answer_value", sa.String(255)),
            "helpful": sa.Column("helpful", sa.Boolean()),
        }
        for name, column in additions.items():
            if name not in columns:
                op.add_column("nqe_feedback_events", column)

    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("nqe_feedback_events")
    }
    if "ix_nqe_feedback_tenant_created" not in indexes:
        op.create_index(
            "ix_nqe_feedback_tenant_created",
            "nqe_feedback_events",
            ["tenant_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nqe_feedback_events" not in set(inspector.get_table_names()):
        return
    indexes = {
        index["name"]
        for index in inspector.get_indexes("nqe_feedback_events")
    }
    if "ix_nqe_feedback_tenant_created" in indexes:
        op.drop_index(
            "ix_nqe_feedback_tenant_created",
            table_name="nqe_feedback_events",
        )
