"""Money-P0 M3: refund_executions (idempotent retryable refund settlement)."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_refund_executions"
down_revision = "20260714_idempotency_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "refund_executions" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "refund_executions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), server_default=sa.text("'default'")),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("approval_index", sa.Integer(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("intent_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0")),
        sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_refund_exec_key", "refund_executions", ["idempotency_key"], unique=True)
    op.create_index("ix_refund_exec_state", "refund_executions", ["state"])


def downgrade() -> None:
    bind = op.get_bind()
    if "refund_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("refund_executions")
