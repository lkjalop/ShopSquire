"""Money-P0 M1: durable payment_attempts (association-integrity outbox)."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_payment_attempts"
down_revision = "20260714_idempotency_response"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "payment_attempts" in existing:
        return
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), server_default=sa.text("'default'")),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_payment_attempts_state", "payment_attempts", ["state"])
    op.create_index("ix_payment_attempts_order", "payment_attempts", ["order_id"])
    op.create_index("ix_payment_attempts_ref", "payment_attempts", ["provider", "provider_ref"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "payment_attempts" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("payment_attempts")
